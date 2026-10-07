"""Preparação da retomada de uma sessão a partir do checkpoint (v18-research-continuity).

``prepare_resume`` valida tudo o que a retomada lê de fontes não confiáveis (arquivos da sessão, payload,
grafo) e devolve um ``ResumeState`` pronto para o orquestrador. Nunca confirma o ``Problema`` nem aprova
decisão reservada: sem Problema confirmado a retomada é recusada e o pesquisador é orientado a confirmá-lo
pelo fluxo normal (``geminiclaw --project <id> "<prompt>"``).

Regras de segurança:

- ``session_id`` e ``project_id`` validados por expressão fechada; diretórios resolvidos sem link simbólico e
  confinados ao diretório de outputs;
- a cadeia de sessões continuadas só inclui sessões do **mesmo projeto**, conferidas no banco de sessões e no
  grafo (uma sessão não "continua" a de outro projeto); profundidade limitada e sem ciclos;
- idempotência: uma sessão que já foi continuada não é continuada de novo (sem bifurcar a pesquisa);
- sessão ainda ativa (batimento recente) nunca é retomada.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src import config
from src.continuity import (
    RESUME_CONFIRM,
    RESUME_REFUSE,
    CheckpointError,
    ResumeState,
    evaluate_resumability,
    read_checkpoint,
    resolve_session_dir,
    validate_session_id,
)
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore
from src.logger import get_logger

logger = get_logger(__name__)

MAX_PROMPT_CHARS = 20_000


class ResumeError(RuntimeError):
    """A retomada não pode prosseguir (mensagem acionável, sem eco de conteúdo não confiável)."""


@dataclass(frozen=True)
class ResumePreparation:
    """Resultado de ``prepare_resume``."""

    state: ResumeState
    prompt: str
    mode: str
    project_context: str


def _verify_in_graph(store: GraphStore | None, session_id: str, project_id: str) -> bool:
    """Confere no grafo que a ``Sessao`` pertence ao projeto. ``False`` se o grafo não pôde ser consultado."""
    if store is None:
        return False
    try:
        for node in store.find_nodes("Sessao", {"sessao_id": session_id}, limit=5):
            if node.properties.get("projeto_id") != project_id:
                raise ResumeError(f"a sessão '{session_id}' pertence a outro projeto no grafo; retomada recusada.")
    except ResumeError:
        raise
    except Exception as exc:  # noqa: BLE001 - grafo fora do ar: vale o banco de sessões
        logger.warning("Vínculo da sessão não conferido no grafo", extra={"extra": {"erro": type(exc).__name__}})
        return False
    return True


def build_chain(
    session_manager: Any, base_dir: Path | str, source_id: str, project_id: str | None, store: GraphStore | None
) -> tuple[Path, ...]:
    """Diretórios de outputs da sessão de origem e de seus ancestrais (mesmo projeto), origem primeiro.

    Raises:
        ResumeError: Ancestral de outro projeto, ciclo ou sessão inexistente na origem.
    """
    dirs: list[Path] = []
    seen: set[str] = set()
    current: str | None = source_id
    while current and len(dirs) < int(config.RESUME_MAX_CHAIN_DEPTH):
        if current in seen:
            raise ResumeError("ciclo na cadeia de sessões continuadas; retomada recusada.")
        seen.add(current)
        session = session_manager.get(current)
        if session is None or session.agent_id != "orchestrator":
            if current == source_id:
                raise ResumeError(f"sessão '{current}' não encontrada.")
            break
        if session.payload.get("project_id") != project_id:
            raise ResumeError(f"a sessão '{current}' da cadeia pertence a outro projeto; retomada recusada.")
        if project_id:
            _verify_in_graph(store, current, project_id)
        try:
            dirs.append(resolve_session_dir(base_dir, current))
        except CheckpointError as exc:
            if current == source_id:
                raise ResumeError(str(exc)) from exc
            logger.warning("Ancestral sem diretório de outputs; cadeia truncada", extra={"extra": {"session_id": current}})
            break
        nxt = session.payload.get("continues_session_id")
        try:
            current = validate_session_id(nxt) if nxt else None
        except CheckpointError:
            current = None
    return tuple(dirs)


def pending_flags(session_dir: Path) -> list[dict[str, str]]:
    """Sinalizações ao Curator ainda pendentes na sessão (tipo e texto)."""
    try:
        from src.knowledge.curator_flags import FlagStore

        return [{"tipo": f.tipo, "texto": f.texto} for f in FlagStore(session_dir).pending(limit=10)]
    except Exception:  # noqa: BLE001
        return []


def select_session_for_project(session_manager: Any, project_id: str) -> str:
    """Sessão mais recente do projeto (a ponta da cadeia).

    Raises:
        ResumeError: Projeto sem sessões.
    """
    sessions = session_manager.list_by_project(project_id, limit=1)
    if not sessions:
        raise ResumeError(f"o projeto {project_id} não tem sessões para continuar.")
    return sessions[0].id


async def prepare_resume(
    *,
    session_manager: Any,
    base_dir: Path | str,
    session_id: str,
    project_arg: str | None = None,
    mode: str | None = None,
    store: GraphStore | None = None,
    index: Any = None,
    confirm: Callable[[str], bool] | None = None,
) -> ResumePreparation:
    """Valida e prepara a retomada de ``session_id``.

    Args:
        session_manager: Gerenciador de sessões.
        base_dir: Diretório base de outputs.
        session_id: Sessão a continuar.
        project_arg: Projeto informado pelo pesquisador (precisa coincidir com o da sessão).
        mode: Modo da nova sessão (padrão: o da sessão de origem).
        store: Grafo (``None``: retomada sem grafo, só se a sessão original não tinha projeto ou o grafo caiu).
        index: Índice semântico para a experiência relacionada.
        confirm: Pergunta sim/não ao pesquisador (``None``: não interativo).

    Raises:
        ResumeError: Qualquer condição que impeça a retomada.
    """
    from src.knowledge import projects
    from src.knowledge.resume_context import build_resume_context

    try:
        sid = validate_session_id(session_id)
    except CheckpointError as exc:
        raise ResumeError(str(exc)) from exc
    session = session_manager.get(sid)
    if session is None or session.agent_id != "orchestrator":
        raise ResumeError(f"sessão '{sid}' não encontrada.")
    project_id = session.payload.get("project_id")
    if project_id is not None:
        try:
            project_id = projects.validate_project_id(project_id)
        except GraphStoreError as exc:
            raise ResumeError("a sessão tem um project_id inválido; retomada recusada.") from exc
    if project_arg:
        try:
            if projects.validate_project_id(project_arg) != project_id:
                raise ResumeError("a sessão pertence a outro projeto; retomada recusada.")
        except GraphStoreError as exc:
            raise ResumeError(str(exc)) from exc

    follow = session_manager.find_continuation(sid)
    if follow is not None:
        raise ResumeError(
            f"a sessão '{sid}' já foi continuada por '{follow.id}'; use `geminiclaw resume --session {follow.id}` "
            "ou `geminiclaw continue --project <id>`."
        )

    try:
        source_dir = resolve_session_dir(base_dir, sid)
        checkpoint, origin = read_checkpoint(source_dir)
    except CheckpointError as exc:
        raise ResumeError(f"não é possível retomar '{sid}': {exc}") from exc
    if origin == "backup":
        logger.warning("Retomada a partir do checkpoint de backup", extra={"extra": {"session_id": sid}})
    if checkpoint.project_id != project_id:
        raise ResumeError("o project_id do checkpoint diverge do da sessão; retomada recusada.")

    verdict = evaluate_resumability(session.status, checkpoint)
    if verdict.decision == RESUME_REFUSE:
        raise ResumeError(f"sessão '{sid}' não retomável: {verdict.message}")
    if verdict.decision == RESUME_CONFIRM and not (confirm is not None and confirm(verdict.message)):
        raise ResumeError("retomada não confirmada pelo pesquisador.")

    prompt = session.payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        prompt = checkpoint.prompt_original
    if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise ResumeError("a sessão não tem um prompt original válido registrado; retomada recusada.")

    problem_id: str | None = None
    project_block = ""
    graph_ok = store is not None
    if project_id:
        if store is None:
            raise ResumeError("o grafo de conhecimento está indisponível; suba os serviços e tente novamente.")
        try:
            detail = await asyncio.to_thread(projects.get_project, store, project_id)
        except GraphStoreError as exc:
            raise ResumeError(f"projeto da sessão indisponível: {exc}") from exc
        if detail.problema is None:
            raise ResumeError(
                f"o projeto {project_id} não tem Problema confirmado; a retomada não confirma o Problema. "
                f'Confirme-o antes: `geminiclaw --project {project_id} "<prompt>"`.'
            )
        problem_id = detail.problema.id
        project_block = projects.format_project_context(detail)

    chain = await asyncio.to_thread(build_chain, session_manager, base_dir, sid, project_id, store)
    block, graph_ok = await asyncio.to_thread(
        build_resume_context, checkpoint, store=store, index=index, problem_id=problem_id,
        pending_flags=pending_flags(source_dir),
    )
    state = ResumeState(
        source_session_id=sid,
        project_id=project_id,
        checkpoint=checkpoint,
        readable_dirs=chain,
        context_block=block,
        curator_pending=checkpoint.curator_pendente,
        graph_available=graph_ok,
    )
    return ResumePreparation(
        state=state,
        prompt=prompt,
        mode=mode or checkpoint.modo or session.payload.get("mode") or config.SESSION_DEFAULT_MODE,
        project_context=project_block,
    )

