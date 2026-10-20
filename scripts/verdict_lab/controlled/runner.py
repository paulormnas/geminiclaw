"""Execução real das explorações: processo da sessão, reset isolado, semeadura e arquivamento (design §4.4 e §4.5).

A política de parada fica em :mod:`scripts.verdict_lab.controlled.explorer`; aqui estão os efeitos: criar o processo
``main.py --mode auto`` (e ``... --session <id> resume``), ler o motivo de parada e o custo de cada sessão, contar os
experimentos do projeto e arquivar. Reaproveita do runner de benchmark as guardas do reset, ``build_env``, o
encerramento do grupo de processos, a leitura de custo e o arquivamento.

Nada aqui roda sem ``--executar`` (:mod:`scripts.verdict_lab.controlled.__main__`); os efeitos externos (processo,
banco, grafo) entram por parâmetros para que os testes os simulem sem LLM.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.benchmark import archive as bench_archive
from scripts.benchmark import footprint, model_versions, reset_stores
from scripts.benchmark import run_benchmark as rb
from scripts.verdict_lab.controlled import regimes
from scripts.verdict_lab.controlled.explorer import Segmento, Teto, explorar

Executor = Callable[[Sequence[str], dict[str, str], float], "ResultadoProcesso"]


@dataclass(frozen=True)
class ResultadoProcesso:
    """Saída de um subprocesso da sessão."""

    codigo: int | None
    log: str
    prazo_estourado: bool = False


def executar_processo(cmd: Sequence[str], env: dict[str, str], timeout: float) -> ResultadoProcesso:
    """Roda ``cmd`` em primeiro plano e em grupo próprio; no prazo o grupo inteiro é encerrado (como o runner)."""
    proc = subprocess.Popen(
        list(cmd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
    )
    try:
        log, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        rb.terminate_group(proc, rb.KILL_GRACE_SECONDS)
        log, _ = proc.communicate()
        return ResultadoProcesso(proc.returncode, log or "", prazo_estourado=True)
    rb.reap_group(proc)
    return ResultadoProcesso(proc.returncode, log or "")


def uso_da_sessao(session_id: str) -> dict[str, Any]:
    """Custo, tokens, chamadas e uso por agente da sessão (``token_usage``)."""
    resumo = rb.sum_tokens(rb.db_token_usage(session_id))
    por_agente: dict[str, dict[str, float]] = {}
    try:
        from src.db import get_connection

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT agent_id, COUNT(*) AS chamadas, SUM(total_tokens) AS tokens, "
                "SUM(estimated_cost_usd) AS custo FROM token_usage WHERE execution_id = %s GROUP BY agent_id",
                (session_id,),
            ).fetchall()
        for row in rows:
            por_agente[str(row["agent_id"])] = {
                "chamadas": float(row["chamadas"] or 0),
                "tokens": float(row["tokens"] or 0),
                "custo_usd": float(row["custo"] or 0),
            }
    except Exception:  # noqa: BLE001 - o uso por agente é complementar; o total já veio de db_token_usage
        pass
    return {**resumo, "por_agente": por_agente}


CHAVES_DO_ALVO = ("DATABASE_URL", "QDRANT_URL", "KNOWLEDGE_READER_DATABASE_URL")


class AlvoNaoAplicado(RuntimeError):
    """O processo ainda aponta para o banco de desenvolvimento; nada foi escrito."""


def aplicar_alvo_ao_processo(env_base: dict[str, str]) -> None:
    """Aponta o próprio processo (ambiente e ``src.config``) para os bancos de benchmark.

    ``src.config`` lê o ambiente na importação, e o orquestrador importa módulos de ``src`` antes de conhecer o alvo;
    sem este ajuste a semeadura e a leitura do grafo usariam o banco de desenvolvimento (``DATABASE_URL`` do ``.env``).
    """
    from src import config

    for chave in CHAVES_DO_ALVO:
        valor = env_base.get(chave)
        if not valor:
            continue
        os.environ[chave] = valor
        setattr(config, chave, valor)
    for modulo, atributo in (("src.memory.qdrant", "QDRANT_URL"), ("src.cli.infrastructure", "DATABASE_URL"),
                             ("src.cli.infrastructure", "QDRANT_URL")):
        if modulo in sys.modules and env_base.get(atributo):
            setattr(sys.modules[modulo], atributo, env_base[atributo])


def conferir_alvo_do_processo(target: reset_stores.BenchmarkTarget) -> None:
    """Recusa seguir se ``src.config`` ainda aponta para outro banco que o de benchmark (fail-fast).

    Raises:
        AlvoNaoAplicado: ``DATABASE_URL`` do processo não é o banco do alvo.
    """
    from urllib.parse import urlsplit

    from src import config

    banco = urlsplit(config.DATABASE_URL or "").path.lstrip("/")
    if banco != target.database:
        raise AlvoNaoAplicado(
            f"O processo aponta para o banco '{banco}' e o alvo é '{target.database}': a semeadura escreveria no banco "
            "errado. Chame aplicar_alvo_ao_processo antes de executar as explorações."
        )


def semear_producao(nome: str, draft: Any) -> str:
    """Cria o projeto com o ``Problema`` do regime no grafo de produção (o de benchmark, no ambiente da rodada)."""
    from scripts.benchmark.seed_project import seed_project

    return seed_project(nome, draft=draft)


def contagens_do_projeto(project_id: str) -> dict[str, int]:
    """Experimentos, resultados e hipóteses do projeto no grafo."""
    nos = footprint.project_graph(project_id).get("nos_por_rotulo", {})
    return {
        "experimentos": int(nos.get("Experimento", 0)),
        "resultados": int(nos.get("Resultado", 0)),
        "hipoteses": int(nos.get("Hipotese", 0)),
    }


@dataclass
class ProcessBackend:
    """Backend real: uma sessão por ``iniciar``/``retomar``.

    Attributes:
        env: Ambiente completo do subprocesso (``build_env`` + ``INPUT_CONTEXT_DIR``); não contém a verdade.
        output_dir: ``OUTPUT_BASE_DIR`` onde as sessões gravam a pasta de saída.
        executor, uso, contagens, parada, ultima_sessao: pontos de substituição para os testes.
    """

    task: str
    project_id: str
    env: dict[str, str]
    output_dir: Path
    timeout: float
    python: str = sys.executable
    executor: Executor = executar_processo
    uso: Callable[[str], dict[str, Any]] = uso_da_sessao
    contagens: Callable[[str], dict[str, int]] = contagens_do_projeto
    parada: Callable[[Path], str | None] = rb._stop_reason
    ultima_sessao: Callable[[Path, float], Path | None] = rb.newest_session
    logs: list[str] = field(default_factory=list)
    sessoes: list[str] = field(default_factory=list)

    def comando_iniciar(self) -> list[str]:
        return [self.python, "main.py", "--mode", "auto", "--project", self.project_id, self.task]

    def comando_retomar(self, session_id: str) -> list[str]:
        return [self.python, "main.py", "--mode", "auto", "--session", session_id, "resume"]

    def _segmento(self, cmd: Sequence[str]) -> Segmento:
        inicio = time.time()
        executado = self.executor(cmd, self.env, self.timeout)
        minutos = (time.time() - inicio) / 60.0
        self.logs.append(executado.log)
        pasta = self.ultima_sessao(self.output_dir, inicio - 1)
        session_id = pasta.name if pasta is not None else ""
        motivo = self.parada(pasta) if pasta is not None else None
        contagem = self.contagens(self.project_id)
        if session_id:
            self.sessoes.append(session_id)
            uso = self.uso(session_id)
        else:
            uso = {}
        return Segmento(
            session_id=session_id,
            motivo_parada=motivo,
            minutos=minutos,
            prazo_estourado=executado.prazo_estourado,
            custo_usd=float(uso.get("cost_usd") or 0.0),
            tokens=int(uso.get("total_tokens") or 0),
            chamadas=int(uso.get("calls") or 0),
            custo_por_provedor=dict(uso.get("cost_by_provider") or {}),
            uso_por_agente=dict(uso.get("por_agente") or {}),
            experimentos_total=contagem["experimentos"],
        )

    def iniciar(self) -> Segmento:
        return self._segmento(self.comando_iniciar())

    def retomar(self, session_id: str) -> Segmento:
        return self._segmento(self.comando_retomar(session_id))

    def estado(self) -> dict[str, Any]:
        return self.contagens(self.project_id)


@dataclass(frozen=True)
class Item:
    """Uma exploração do plano: (repetição, regime, combinação) e a semente do dado."""

    repeticao: int
    regime: str
    combo: dict[str, Any]
    teto: Teto
    semente: int

    @property
    def nome(self) -> str:
        return f"{self.combo['name']}/{self.regime}/r{self.repeticao}"


def itens_do_plano(plano: dict[str, Any], combos: dict[str, dict[str, Any]], sementes: list[int]) -> list[Item]:
    """Explorações na ordem repetição → regime → combinação (rodadas parciais ficam equilibradas)."""
    from scripts.verdict_lab.controlled.budget import teto_da

    itens: list[Item] = []
    maximo = max(plano["repeticoes"].values(), default=0)
    for r in range(1, maximo + 1):
        for regime, n in plano["repeticoes"].items():
            if r > n:
                continue
            for combo_plano in plano["combinacoes"]:
                nome = combo_plano["nome"]
                if nome not in combos:
                    raise rb.CombinationRefused(f"combinação '{nome}' do plano não existe na matriz.")
                itens.append(Item(r, regime, combos[nome], teto_da(combo_plano), sementes[r - 1]))
    return itens


def diretorio_da(saida: Path, item: Item) -> Path:
    return saida / item.combo["name"] / item.regime / f"r{item.repeticao}"


def ambiente_da_exploracao(
    item: Item, env_base: dict[str, str], matriz_env: dict[str, str] | None, input_dir: Path
) -> dict[str, str]:
    """Ambiente do subprocesso: papéis da combinação, extras da matriz e ``INPUT_CONTEXT_DIR``; sem a verdade."""
    controle = rb.is_control(item.combo)
    juiz = {"LLM_JUDGE_INDEPENDENCE": "off"} if controle else {}
    env = rb.build_env(env_base, item.combo["roles"], {**(matriz_env or {}), **item.combo.get("env", {}), **juiz})
    env["INPUT_CONTEXT_DIR"] = str(input_dir)
    return env


def executar_item(
    item: Item,
    *,
    saida: Path,
    env_base: dict[str, str],
    matriz: dict[str, Any],
    output_dir: Path,
    target: reset_stores.BenchmarkTarget | None,
    reset: bool,
    dump: bool,
    semear: Callable[[str, Any], str] | None = None,
    reiniciar: Callable[..., Any] = reset_stores.reset_stores,
    backend_factory: Callable[..., Any] = ProcessBackend,
) -> dict[str, Any]:
    """Prepara e executa uma exploração e arquiva o resultado em ``<saida>/<combinação>/<regime>/r<r>/``.

    Raises:
        scripts.benchmark.reset_stores.ResetError: O reset ou a conferência falhou (nada roda).
    """
    pasta = diretorio_da(saida, item)
    pasta.mkdir(parents=True, exist_ok=True)
    if reset and target is not None:
        rb._close_local_pools()
        reiniciar(target, archive_dir=pasta, dump=dump, base_env=env_base)
    if target is not None:
        conferir_alvo_do_processo(target)
    regimes.preparar_entrada(item.regime, item.semente, pasta / "input_context", pasta / "verdade")
    semear = semear or semear_producao
    project_id = semear(f"{item.combo['name']}-{item.regime}-r{item.repeticao}", regimes.problem_draft(item.regime))
    env = ambiente_da_exploracao(item, env_base, matriz.get("env"), pasta / "input_context")
    backend = backend_factory(
        task=regimes.tarefa(item.regime), project_id=project_id, env=env, output_dir=output_dir,
        timeout=float(matriz.get("timeout_seconds", 12000)),
    )
    identidade = {
        "combinacao": item.combo["name"], "regime": item.regime, "repeticao": item.repeticao,
        "semente_dado": item.semente, "project_id": project_id, "papeis": item.combo["roles"],
    }
    resultado = explorar(backend, item.teto, identidade=identidade)
    ultima = backend.sessoes[-1] if backend.sessoes else None
    if ultima:
        try:
            resultado.update(model_versions.execution_record(model_versions.db_allocation_profile(ultima)))
        except Exception as exc:  # noqa: BLE001 - versão de modelo ausente é registrada, não derruba a rodada
            resultado["modelos_erro"] = f"{type(exc).__name__}: {exc}"
    eventos: list[dict[str, Any]] = []
    for sid in backend.sessoes:
        eventos.extend(bench_archive.fetch_events(sid) or [])
    bench_archive.archive_repetition(
        pasta,
        session_dir=(output_dir / ultima) if ultima else None,
        log="\n".join(backend.logs),
        events=eventos or None,
        project_graph=footprint.project_graph_full(project_id),
    )
    (pasta / "exploracao.json").write_text(
        json.dumps(resultado, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    return resultado
