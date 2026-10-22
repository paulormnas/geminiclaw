"""Consulta só leitura ao Researcher pelo terminal (v18.7-session-events-terminal, ADR 023 §3 e §7).

Duas metades:

- **Terminal** (``run_consult_process``): cria um processo filho como o da sessão (``stdin`` fechado, ambiente filtrado
  sem as credenciais do terminal e ``PGOPTIONS`` com ``default_transaction_read_only = on``), passa a pergunta por um
  arquivo ``0600`` e recebe só o JSON da resposta, que valida como dado não confiável. O processo do terminal, que tem
  a credencial de escrita dos comandos, nunca executa o modelo nem as ferramentas web.
- **Filho** (``python -m src.cli.terminal_consult --request ARQUIVO``): monta o contexto da pesquisa pelo grafo
  somente leitura, chama o Researcher (``ask``) e imprime ``{"resposta", "orientacao_sugerida"}`` ou ``{"erro"}``.

O contexto é montado de forma determinística e delimitado como dado; o consumo é registrado em ``token_usage`` com o
``execution_id`` da sessão consultada (conta no orçamento dela) e a origem ``consulta_terminal``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import config
from src.logger import get_logger
from src.utils.display_text import sanitize_line

logger = get_logger(__name__)

CONSULT_MODULE = "src.cli.terminal_consult"
EXIT_REFUSED = 3  # consulta recusada (política de dados ou falha da consulta); o JSON traz o motivo
_TIMEOUT_SECONDS = 180.0
_MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class ConsultOutcome:
    """Resultado visto pelo terminal: a resposta e a orientação (saneadas) ou o motivo da recusa."""

    resposta: str = ""
    orientacao_sugerida: str | None = None
    erro: str = ""

    @property
    def ok(self) -> bool:
        return not self.erro


# --- terminal ----------------------------------------------------------------------------------------------------


#: Credenciais do terminal que o processo filho (que executa modelo e ferramentas web) nunca recebe.
TERMINAL_CREDENTIAL_NAMES = (
    "TERMINAL_DATABASE_URL_FILE", "TERMINAL_DATABASE_URL", "PGPASSWORD", "PGPASSFILE", "PGSERVICEFILE",
)


def consult_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Ambiente do processo filho: o da sessão (``filtered_env``) sem as credenciais do terminal, mais o banco
    relacional somente leitura (``PGOPTIONS``)."""
    from src.session.launcher import filtered_env

    env = filtered_env(environ, denylist=TERMINAL_CREDENTIAL_NAMES)
    options = env.get("PGOPTIONS", "")
    env["PGOPTIONS"] = (options + " " if options else "") + "-c default_transaction_read_only=on"
    return env


def parse_outcome(raw: str) -> ConsultOutcome:
    """Valida a saída do filho como dado não confiável: só os campos esperados, saneados e com teto."""
    try:
        data = json.loads(raw.strip().splitlines()[-1]) if raw.strip() else None
    except (ValueError, IndexError):
        data = None
    if not isinstance(data, dict):
        return ConsultOutcome(erro="a consulta não devolveu uma resposta legível")
    if isinstance(data.get("erro"), str) and data["erro"].strip():
        return ConsultOutcome(erro=sanitize_line(data["erro"], _MAX_ERROR_CHARS))
    resposta = data.get("resposta")
    if not isinstance(resposta, str) or not resposta.strip():
        return ConsultOutcome(erro="a consulta não devolveu uma resposta legível")
    orientacao = data.get("orientacao_sugerida")
    return ConsultOutcome(
        resposta=sanitize_line(resposta, int(config.SESSION_EVENT_SUMMARY_MAX_CHARS) * 8),
        orientacao_sugerida=sanitize_line(orientacao, int(config.SESSION_INBOX_MAX_CHARS))
        if isinstance(orientacao, str) and orientacao.strip() else None,
    )


def run_consult_process(
    question: str,
    session_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    module: str = CONSULT_MODULE,
    timeout: float = _TIMEOUT_SECONDS,
    extra_args: Iterable[str] = (),
) -> ConsultOutcome:
    """Pergunta ao Researcher num processo filho sem a credencial do terminal; devolve a resposta saneada."""
    fd, path = tempfile.mkstemp(prefix="geminiclaw-consulta-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:  # mkstemp cria com 0600
            json.dump({"pergunta": question, "session_id": session_id}, handle, ensure_ascii=False)
        proc = subprocess.run(  # noqa: S603 - argumentos fixos; a pergunta vai pelo arquivo, nunca pela linha de comando
            [sys.executable, "-m", module, "--request", path, *extra_args],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
            env=consult_env(os.environ if environ is None else environ),
        )
    except subprocess.TimeoutExpired:
        return ConsultOutcome(erro="a consulta passou do tempo limite")
    except OSError as exc:
        return ConsultOutcome(erro=f"não foi possível iniciar a consulta ({type(exc).__name__})")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    outcome = parse_outcome(proc.stdout)
    if not outcome.ok and proc.returncode not in (0, EXIT_REFUSED):
        logger.warning("Processo da consulta terminou com erro", extra={"codigo": proc.returncode})
    return outcome


# --- contexto (no filho) ------------------------------------------------------------------------------------------


def build_context(
    session: Any,
    store: Any,
    reader: Any,
    *,
    base_dir: Any = None,
    gate: Any = None,
    max_chars: int | None = None,
) -> str:
    """Contexto determinístico da pesquisa, delimitado como dado, até ``TERMINAL_CONSULT_CONTEXT_MAX_CHARS``.

    Projeto e Problema, hipóteses com estado e contagens de réplicas, plano do checkpoint, últimos 30 eventos e
    pedidos pendentes.
    Cada bloco é independente: o que não puder ser lido sai como indisponível, sem derrubar a consulta.
    """
    from src.knowledge.curator_tools import wrap_data

    limit = int(max_chars or config.TERMINAL_CONSULT_CONTEXT_MAX_CHARS)
    share = max(limit // 5, 600)
    payload = getattr(session, "payload", None) or {}
    blocks: list[str] = []

    def add(label: str, read: Callable[[], Any]) -> None:
        try:
            blocks.append(wrap_data(label, read(), share))
        except Exception as exc:  # noqa: BLE001 - um bloco indisponível não derruba a consulta
            blocks.append(wrap_data(label, f"indisponível ({type(exc).__name__})", share))

    project_id = payload.get("project_id")
    add("pesquisa", lambda: {
        "apelido": getattr(session, "alias", None), "estado": session.status, "modo": payload.get("mode"),
        "tarefa": sanitize_line(getattr(session, "resumo", None) or payload.get("prompt") or "", 300),
        "motivo_parada": payload.get("motivo_parada"),
    })

    def problem() -> Any:
        from src.knowledge.projects import get_active_problem

        node = get_active_problem(store, project_id) if project_id else None
        if node is None:
            return "sem Problema confirmado"
        props = node.properties
        criterio = props.get("criterio_sucesso") if isinstance(props.get("criterio_sucesso"), dict) else {}
        return {
            "titulo": sanitize_line(props.get("titulo", ""), 200),
            "resumo": sanitize_line(props.get("resumo", ""), 600),
            "objetivo": {k: criterio.get(k) for k in ("tipo", "metrica", "alvo", "sentido") if k in criterio},
        }

    add("problema", problem)

    def hypotheses() -> Any:
        found = store.find_nodes("Hipotese", {"projeto_id": project_id}, limit=60) if project_id else []
        out = []
        for node in found:
            item = {
                "id": node.id, "estado": node.properties.get("status"),
                "enunciado": sanitize_line(node.properties.get("enunciado", ""), 240),
            }
            for key in ("n_atingiu_alvo", "n_abaixo_alvo"):
                count = node.properties.get(key)
                if isinstance(count, (int, float)) and not isinstance(count, bool):
                    item[key] = int(count)
            out.append(item)
        return out

    add("hipoteses_do_projeto", hypotheses)

    def plan() -> Any:
        from src.session.continuity import read_checkpoint, resolve_session_dir

        checkpoint, _ = read_checkpoint(resolve_session_dir(base_dir or config.OUTPUT_BASE_DIR, session.id),
                                        expected_session_id=session.id)
        return [{"subtarefa": s.nome, "estado": s.status} for s in checkpoint.subtarefas][:40]

    add("plano", plan)
    add("ultimos_eventos", lambda: [sanitize_line(e.resumo, 200) for e in reader.tail(session.id, 30)])
    if gate is not None:
        add("pedidos_pendentes", lambda: [
            {"id": r.id, "decisao": r.decisao, "referencia": r.referencia}
            for r in gate.pending([session.id])
        ])
    text = "\n".join(blocks)
    return text if len(text) <= limit else text[: limit - 40] + "\n[contexto cortado no teto]"


# --- processo filho -------------------------------------------------------------------------------------------------


async def _child(question: str, session_id: str) -> tuple[dict[str, Any], int]:
    """Monta o contexto, resolve o provedor do Researcher e pergunta. Devolve ``(JSON, código de saída)``."""
    from src.agents.regimento import encerrar_sessao, iniciar_sessao
    from src.agents.researcher.consult import ConsultError
    from src.agents.researcher.terminal_consult import ask
    from src.egress.routing import ModelRouter
    from src.gate.persistent_gate import PersistentGate
    from src.knowledge.factory import open_graph_store
    from src.knowledge.read_only import ReadOnlyGraphStore
    from src.llm.metering import bind_execution
    from src.llm.session import bind_session_routing, build_session_routing
    from src.session.events import EventReader
    from src.session.manager import SessionManager

    session = SessionManager().get(session_id)
    if session is None:
        return {"erro": "pesquisa não encontrada"}, EXIT_REFUSED
    store = ReadOnlyGraphStore(open_graph_store())
    context = build_context(session, store, EventReader(), gate=PersistentGate())
    routing = await build_session_routing()
    bind_session_routing(routing)
    bind_execution(session.id, session.id)  # o consumo conta no orçamento da pesquisa consultada
    _, token = iniciar_sessao((session.payload or {}).get("mode") or config.SESSION_DEFAULT_MODE)
    try:
        provider = ModelRouter.get_provider("researcher")
        answer = await ask(provider, question, context)
    except ConsultError as exc:
        return {"erro": sanitize_line(str(exc), _MAX_ERROR_CHARS)}, EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - recusa da política de dados, provedor fora do ar etc.: vira motivo
        logger.warning("Consulta recusada ou com falha", extra={"erro": type(exc).__name__})
        motivo = sanitize_line(f"consulta recusada ({type(exc).__name__}): {exc}", _MAX_ERROR_CHARS)
        return {"erro": motivo}, EXIT_REFUSED
    finally:
        encerrar_sessao(token)
    return {"resposta": answer.resposta, "orientacao_sugerida": answer.orientacao_sugerida}, 0


def main(argv: Iterable[str] | None = None) -> int:
    """Ponto de entrada do processo filho: lê a pergunta do arquivo e imprime uma linha de JSON."""
    parser = argparse.ArgumentParser(prog=f"python -m {CONSULT_MODULE}")
    parser.add_argument("--request", required=True, help="arquivo 0600 com a pergunta e a pesquisa consultada")
    args = parser.parse_args(list(argv) if argv is not None else None)
    from src.cli.session_process import install_input_guard

    install_input_guard()
    from src.egress.routing import install_provider_resolver

    install_provider_resolver()
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        question, session_id = str(request["pergunta"]), str(request["session_id"])
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"erro": f"pedido de consulta inválido ({type(exc).__name__})"}))
        return EXIT_REFUSED
    result, code = asyncio.run(_child(question, session_id))
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
