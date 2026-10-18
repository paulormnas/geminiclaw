"""Eventos de progresso da sessão (v18.7-session-events-terminal, ADR 023 §2 e §7).

O processo da sessão grava cada evento na tabela ``session_events`` assim que ele ocorre (transação própria, fora da
telemetria em lote); o terminal os lê por consulta periódica. O resumo é montado de campos estruturados e saneados,
nunca de saída de execução, trecho de dado, caminho absoluto ou mensagem de exceção. ``dados`` aceita, por ``tipo``,
só uma lista fechada de chaves com valores escalares curtos.

``EventWriter`` nunca levanta: uma falha de gravação tem uma nova tentativa depois de ``RETRY_DELAY_SECONDS`` e, se
repetir, vira ``WARNING`` no log e a sessão segue (o pedido ao pesquisador é persistente no gate).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from src import config
from src.db import get_connection
from src.logger import get_logger
from src.utils.display_text import sanitize_line

logger = get_logger(__name__)

TIPOS: tuple[str, ...] = (
    "sessao_iniciada", "plano_aprovado", "subtarefa_iniciada", "subtarefa_concluida", "subtarefa_reprovada",
    "hipotese_criada", "hipotese_concluida", "objetivo_atingido", "decisao_pendente", "comando_recebido", "parada",
    "suspensao", "falha",
)
#: Eventos que o nível ``silencioso`` do terminal ainda mostra.
TIPOS_SILENCIOSO = frozenset({"decisao_pendente", "parada", "suspensao", "falha"})
#: Eventos do nível ``resumo`` (padrão): os do silencioso mais os que marcam avanço da pesquisa.
TIPOS_RESUMO = TIPOS_SILENCIOSO | {"plano_aprovado", "hipotese_concluida", "objetivo_atingido", "comando_recebido"}

#: Chaves de ``dados`` aceitas por ``tipo`` (ids, contagens, códigos). Qualquer outra chave é descartada na escrita.
DADOS_PERMITIDOS: dict[str, frozenset[str]] = {
    "sessao_iniciada": frozenset({"modo", "papeis"}),
    "plano_aprovado": frozenset({"versao", "subtarefas", "hipoteses"}),
    "subtarefa_iniciada": frozenset({"subtarefa"}),
    "subtarefa_concluida": frozenset({"subtarefa", "metrica", "valor", "validada"}),
    "subtarefa_reprovada": frozenset({"subtarefa", "tentativa", "esgotada"}),
    "hipotese_criada": frozenset({"hipotese"}),
    "hipotese_concluida": frozenset({"hipotese", "estado", "veredito"}),
    "objetivo_atingido": frozenset({"metrica", "valor", "alvo", "politica"}),
    "decisao_pendente": frozenset({"decisao", "pedido_id", "referencia"}),
    "comando_recebido": frozenset({"comando", "subtarefa", "aceito"}),
    "parada": frozenset({"motivo"}),
    "suspensao": frozenset({"motivo"}),
    "falha": frozenset({"motivo", "apelido"}),
}

RETRY_DELAY_SECONDS = 1.0
_FIELD_MAX = 64


@dataclass(frozen=True)
class Event:
    """Linha de ``session_events``."""

    id: int
    session_id: str
    seq: int
    tipo: str
    criado_em: str
    resumo: str
    dados: dict[str, Any]


# --- resumo ------------------------------------------------------------------------------------------------------


def _text(value: Any) -> str:
    return sanitize_line(value, _FIELD_MAX)


def _num(value: Any) -> str:
    """Número em pt-BR, com vírgula e no máximo 4 casas (``0,967``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _text(value)
    texto = f"{value:.4f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return texto.replace(".", ",")


def _plural(n: Any, singular: str, plural: str) -> str:
    return f"{_num(n)} {singular if n == 1 else plural}"


_MOTIVOS_SUSPENSAO = {
    "aguarda_pesquisador": "só restam pedidos a você; responda e retome",
    "suspensa_sem_pesquisador": "terminal fechado; retome ao abrir a aplicação",
    "pausada_pesquisador": "pausada por você; use 'retomar' para continuar",
}
_DECISOES = {
    "aprovar_oportunidade": "aprovar a oportunidade {ref}",
    "confirmar_problema": "confirmar o problema",
    "aprovar_termo_vocabulario": "aprovar o termo {ref}",
    "autorizar_escrita_instrumento": "autorizar a escrita no instrumento",
    "ativar_modo_sem_limite": "ativar o modo sem limite",
    "aprovar_hipotese": "aprovar a hipótese {ref}",
    "decidir_objetivo_atingido": "decidir o que fazer ao atingir o objetivo",
    "responder_pergunta_agente": "responder a uma pergunta de um agente",
    "decidir_continuidade": "decidir a continuidade da pesquisa",
    "restringir_direcao": "decidir sobre uma direção restrita",
    "ativar_adendo_regimento": "ativar o adendo do regimento",
}
_COMANDOS = {
    "pausar": "pausa pedida: termina a subtarefa atual",
    "parar": "parada pedida: fecha com checkpoint",
    "cancelar": "cancelamento pedido",
    "replanejar": "replanejamento pedido: depois das subtarefas em curso",
}


def monta_resumo(tipo: str, campos: dict[str, Any]) -> str:
    """Resumo curto do evento, montado só de ``campos`` estruturados (cada texto saneado)."""
    c = campos
    if tipo == "sessao_iniciada":
        papeis = _plural(c.get("papeis", 0), "papel resolvido", "papéis resolvidos")
        return f"iniciada (modo {_text(c.get('modo', '?'))}, {papeis})"
    if tipo == "plano_aprovado":
        partes = [_plural(c.get("subtarefas", 0), "subtarefa", "subtarefas")]
        if c.get("hipoteses") is not None:
            partes.append(_plural(c["hipoteses"], "hipótese", "hipóteses"))
        return f"plano {_num(c.get('versao', 1))} aprovado: {', '.join(partes)}"
    if tipo == "subtarefa_iniciada":
        return f"{_text(c.get('subtarefa', '?'))} iniciada"
    if tipo == "subtarefa_concluida":
        base = f"{_text(c.get('subtarefa', '?'))} concluída"
        if c.get("metrica") and c.get("valor") is not None and c.get("validada"):
            return f"{base} ({_text(c['metrica'])} {_num(c['valor'])}, validada)"
        return base
    if tipo == "subtarefa_reprovada":
        nome = _text(c.get("subtarefa", "?"))
        if c.get("esgotada"):
            return f"{nome} reprovada: tentativas esgotadas"
        return f"{nome} reprovada na revisão (tentativa {_num(c.get('tentativa', 1))})"
    if tipo == "hipotese_criada":
        return f"{_text(c.get('hipotese', '?'))} criada"
    if tipo == "hipotese_concluida":
        veredito = f" (veredito {_num(c['veredito'])})" if c.get("veredito") is not None else ""
        return f"{_text(c.get('hipotese', '?'))} {_text(c.get('estado', 'concluída'))}{veredito}"
    if tipo == "objetivo_atingido":
        corpo = "objetivo atingido"
        if c.get("metrica") and c.get("valor") is not None:
            corpo += f": {_text(c['metrica'])} {_num(c['valor'])}"
            if c.get("alvo") is not None:
                corpo += f" ≥ {_num(c['alvo'])}"
        if c.get("politica"):
            corpo += f" (política: {_text(c['politica'])})"
        return corpo
    if tipo == "decisao_pendente":
        pedido = f" (responda com 'decidir {_num(c['pedido_id'])}')" if c.get("pedido_id") is not None else ""
        codigo = _text(c.get("decisao", ""))
        modelo = _DECISOES.get(codigo)
        ref = _text(c.get("referencia", ""))
        descricao = modelo.format(ref=ref) if modelo and "{ref}" in modelo and ref else (
            modelo.replace(" {ref}", "") if modelo else (codigo or "uma decisão")
        )
        return f"aguarda você: {descricao}{pedido}"
    if tipo == "comando_recebido":
        comando = _text(c.get("comando", "?"))
        texto = _COMANDOS.get(comando, f"comando {comando} recebido")
        if comando == "cancelar" and c.get("subtarefa"):
            texto = f"cancelamento pedido: {_text(c['subtarefa'])}"
        if c.get("aceito") is False:
            texto += " (recusado)"
        return texto
    if tipo == "parada":
        return f"encerrada: {_text(c.get('motivo', '?'))}"
    if tipo == "suspensao":
        motivo = _text(c.get("motivo", ""))
        return f"suspensa: {_MOTIVOS_SUSPENSAO.get(motivo, motivo or 'aguarda você')}"
    if tipo == "falha":
        apelido = _text(c.get("apelido", ""))
        dica = f"; use 'retomar {apelido}'" if apelido else ""
        return f"interrompida: processo parou{dica}"
    raise ValueError(f"tipo de evento desconhecido: {tipo!r}")


def limpa_dados(tipo: str, campos: dict[str, Any]) -> dict[str, Any]:
    """Só as chaves permitidas do ``tipo`` e só valores escalares curtos (texto saneado)."""
    permitidas = DADOS_PERMITIDOS.get(tipo, frozenset())
    out: dict[str, Any] = {}
    for chave, valor in campos.items():
        if chave not in permitidas:
            continue
        if isinstance(valor, bool) or valor is None or isinstance(valor, (int, float)):
            out[chave] = valor
        elif isinstance(valor, str):
            out[chave] = _text(valor)
    return out


def resumo_final(tipo: str, campos: dict[str, Any]) -> str:
    """Resumo com o teto de ``SESSION_EVENT_SUMMARY_MAX_CHARS`` (nunca passa de 300)."""
    return sanitize_line(monta_resumo(tipo, campos), min(config.SESSION_EVENT_SUMMARY_MAX_CHARS, 300))


# --- gravação ---------------------------------------------------------------------------------------------------


_INSERT = (
    "INSERT INTO session_events (session_id, seq, tipo, resumo, dados, criado_em) "
    "SELECT %s, COALESCE(MAX(seq), 0) + 1, %s, %s, %s::jsonb, COALESCE(%s::timestamptz, now()) "
    "FROM session_events WHERE session_id = %s"
)


def insert_event(conn: Any, session_id: str, tipo: str, campos: dict[str, Any] | None = None,
                 criado_em: str | None = None) -> None:
    """Insere o evento na conexão dada, dentro de um savepoint: uma falha do evento nunca desfaz a transação de quem
    chamou (usado para gravar o evento final na mesma transação do status da sessão)."""
    try:
        resumo, dados = resumo_final(tipo, campos or {}), limpa_dados(tipo, campos or {})
        with conn.transaction():
            conn.execute(_INSERT, (session_id, tipo, resumo, json.dumps(dados), criado_em, session_id))
    except Exception as exc:  # noqa: BLE001 - evento é informativo
        logger.warning(
            "Evento de sessão não gravado",
            extra={"extra": {"tipo": tipo, "session_id": session_id, "erro": type(exc).__name__}},
        )


class EventWriter:
    """Grava os eventos de uma sessão, em ordem, sem derrubá-la.

    ``emit`` monta o resumo e grava numa fila de um só trabalhador (a ordem é a da emissão); ``wait=True`` grava na
    hora, na thread de quem chamou (eventos finais, que precisam estar no banco antes do status final). ``seq`` é
    atribuído pelo banco (``max(seq)+1`` da sessão), então sobrevive à retomada e a escritores concorrentes (o
    terminal grava ``falha``); um conflito de ``seq`` é tentado de novo.
    """

    def __init__(self, session_id: str, *, connection: Callable[[], Any] = get_connection,
                 retry_delay: float | None = None) -> None:
        self.session_id = session_id
        self._connection = connection
        self._retry_delay = RETRY_DELAY_SECONDS if retry_delay is None else retry_delay
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def emit(self, tipo: str, campos: dict[str, Any] | None = None, *, wait: bool = False) -> None:
        """Monta e grava o evento; nunca levanta."""
        try:
            dados = limpa_dados(tipo, campos or {})
            resumo = resumo_final(tipo, campos or {})
        except Exception:  # noqa: BLE001 - evento é informativo
            logger.warning("Evento de sessão não montado", extra={"extra": {"tipo": tipo}}, exc_info=True)
            return
        if wait:
            self._write(tipo, resumo, dados)
            return
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-events")
            self._executor.submit(self._write, tipo, resumo, dados)

    def flush(self) -> None:
        """Espera as gravações pendentes."""
        with self._lock:
            executor = self._executor
        if executor is not None:
            executor.submit(lambda: None).result()

    def close(self) -> None:
        """Espera e encerra o trabalhador."""
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True)

    def _write(self, tipo: str, resumo: str, dados: dict[str, Any]) -> None:
        for tentativa in (1, 2):
            try:
                with self._connection() as conn:
                    conn.execute(_INSERT, (self.session_id, tipo, resumo, json.dumps(dados), None, self.session_id))
                return
            except Exception as exc:  # noqa: BLE001 - nunca derruba a sessão
                if tentativa == 1:
                    time.sleep(self._retry_delay)
                    continue
                logger.warning(
                    "Evento de sessão não gravado",
                    extra={"extra": {"tipo": tipo, "session_id": self.session_id, "erro": type(exc).__name__}},
                )


_writers: dict[str, EventWriter] = {}
_writers_lock = threading.Lock()


def writer_for(session_id: str) -> EventWriter:
    """Escritor compartilhado da sessão (um por processo)."""
    with _writers_lock:
        writer = _writers.get(session_id)
        if writer is None:
            writer = _writers[session_id] = EventWriter(session_id)
        return writer


def emit_event(session_id: str, tipo: str, campos: dict[str, Any] | None = None, *, wait: bool = False) -> None:
    """Atalho: grava um evento da sessão pelo escritor compartilhado; nunca levanta."""
    if not session_id:
        return
    try:
        writer_for(session_id).emit(tipo, campos, wait=wait)
    except Exception:  # noqa: BLE001
        logger.warning("Evento de sessão não emitido", extra={"extra": {"tipo": tipo}}, exc_info=True)


def flush_all() -> None:
    """Espera as gravações pendentes de todos os escritores do processo."""
    with _writers_lock:
        writers = list(_writers.values())
    for writer in writers:
        writer.flush()


def reset_writers() -> None:
    """Esquece os escritores (testes)."""
    with _writers_lock:
        writers = list(_writers.values())
        _writers.clear()
    for writer in writers:
        writer.close()


# --- ouvinte da telemetria ---------------------------------------------------------------------------------------


class TelemetryTap:
    """Converte eventos de agente da telemetria nos eventos de progresso e os grava na hora.

    Registrado só no processo da sessão (``add_event_tap``); filtra pela sessão mestra. ``plano_aprovado`` leva a
    versão contada aqui (o n-ésimo plano aprovado da sessão).
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._plans = 0

    def __call__(self, event_type: str, session_id: str, task_name: str | None, payload: dict[str, Any]) -> None:
        if session_id != self.session_id:
            return
        if event_type == "subtask_start" and task_name:
            emit_event(session_id, "subtarefa_iniciada", {"subtarefa": task_name})
        elif event_type == "subtask_end" and task_name:
            if payload.get("success"):
                emit_event(session_id, "subtarefa_concluida", {
                    "subtarefa": task_name, "metrica": payload.get("metrica_validada"),
                    "valor": payload.get("valor_validado"), "validada": payload.get("metrica_validada") is not None,
                })
            else:
                emit_event(session_id, "subtarefa_reprovada", {"subtarefa": task_name, "esgotada": True})
        elif event_type == "subtask_review" and task_name and not payload.get("approved", True):
            emit_event(session_id, "subtarefa_reprovada", {
                "subtarefa": task_name, "tentativa": int(payload.get("attempt", 0)) + 1,
            })
        elif event_type == "plan_validation" and payload.get("approved"):
            self._plans += 1
            emit_event(session_id, "plano_aprovado", {
                "versao": self._plans, "subtarefas": payload.get("plan_tasks", 0),
                "hipoteses": payload.get("plan_hipoteses"),
            })
        elif event_type == "hipotese_transicao" and payload.get("status_novo") in ("validada", "refutada"):
            emit_event(session_id, "hipotese_concluida", {
                "hipotese": payload.get("hipotese_id"), "estado": payload.get("status_novo"),
                "veredito": payload.get("veredito_novo"),
            })
        elif event_type == "objetivo_atingido":
            emit_event(session_id, "objetivo_atingido", {
                "metrica": payload.get("metrica"), "valor": payload.get("valor"), "alvo": payload.get("alvo"),
                "politica": payload.get("politica"),
            })


def install(session_id: str) -> TelemetryTap:
    """Liga o ouvinte da telemetria à sessão deste processo."""
    from src.observability.telemetry import add_event_tap

    tap = TelemetryTap(session_id)
    add_event_tap(tap)
    return tap


# --- leitura (terminal) ------------------------------------------------------------------------------------------


def _event(row: Any) -> Event:
    dados = row["dados"]
    if isinstance(dados, str):
        dados = json.loads(dados)
    criado = row["criado_em"]
    return Event(
        id=int(row["id"]), session_id=row["session_id"], seq=int(row["seq"]), tipo=row["tipo"],
        criado_em=criado if isinstance(criado, str) else criado.isoformat(), resumo=row["resumo"],
        dados=dados or {},
    )


class EventReader:
    """Leitura de eventos pelo terminal (consulta periódica, nunca ``LISTEN/NOTIFY``)."""

    def since(self, last_id: int, *, session_ids: Iterable[str] | None = None, limit: int = 200) -> list[Event]:
        """Eventos com ``id`` maior que ``last_id``, em ordem, das sessões indicadas (todas, se omitido)."""
        ids = None if session_ids is None else list(session_ids)
        if ids is not None and not ids:
            return []
        with get_connection() as conn:
            if ids is None:
                rows = conn.execute(
                    "SELECT * FROM session_events WHERE id > %s ORDER BY id LIMIT %s", (last_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM session_events WHERE id > %s AND session_id = ANY(%s) ORDER BY id LIMIT %s",
                    (last_id, ids, limit),
                ).fetchall()
        return [_event(r) for r in rows]

    def tail(self, session_id: str, n: int) -> list[Event]:
        """Os ``n`` últimos eventos da sessão, do mais antigo ao mais novo."""
        if n <= 0:
            return []
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM session_events WHERE session_id = %s ORDER BY id DESC LIMIT %s) t "
                "ORDER BY id",
                (session_id, n),
            ).fetchall()
        return [_event(r) for r in rows]

    def last_id(self) -> int:
        """Maior ``id`` da tabela (0 se vazia): o ponto de partida do REPL, que só mostra eventos novos."""
        with get_connection() as conn:
            row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM session_events").fetchone()
        return int(row["m"])


def purge(retention_days: int) -> int:
    """Apaga os eventos de sessões terminadas há mais de ``retention_days`` dias; 0 não apaga nada.

    Só sessões em ``FINISHED_STATUSES`` (fechadas, com sucesso ou com falha); as não finalizadas nunca são tocadas.
    """
    if retention_days <= 0:
        return 0
    from src.session.states import FINISHED_STATUSES

    with get_connection() as conn:
        rows = conn.execute(
            "DELETE FROM session_events WHERE session_id IN ("
            "  SELECT id FROM agent_sessions WHERE agent_id = 'orchestrator' AND status = ANY(%s) "
            "  AND updated_at < now() - make_interval(days => %s)) RETURNING id",
            (list(FINISHED_STATUSES), retention_days),
        ).fetchall()
    return len(rows)
