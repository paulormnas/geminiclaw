"""Retomada de sessões e projetos pelo terminal (v18-research-continuity).

Movido de ``src/cli/main.py`` sem alterar o comportamento (v18.7-background-sessions, tarefa 0.9; ADR 024 §5).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from src.cli.banner import print_session_banner
from src.cli.reports import format_result
from src.logger import get_logger
from src.orchestration.orchestrator import Orchestrator
from src.orchestration.usage import UsageBudget
from src.research_data.context_loader import ContextBundle
from src.utils.terminal import DIM, RED, RESET, STATUS_ICONS, YELLOW

logger = get_logger(__name__)


def _ask_yes_no(question: str) -> bool:
    """Pergunta sim/não no terminal; sem TTY a resposta é "não" (nada é confirmado por omissão)."""
    from src.cli.project_session import is_interactive

    if not is_interactive():
        return False
    try:
        return input(f"  {question} [s/N] ").strip().lower() in ("s", "sim", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


async def _run_resume(
    orchestrator: Orchestrator,
    session_id: str,
    *,
    project_arg: str | None = None,
    mode: str | None = None,
    budget: UsageBudget | None = None,
    model_pin: str | None = None,
) -> bool:
    """Retoma ``session_id`` a partir do checkpoint, em uma NOVA sessão ligada à anterior (v18-research-continuity).

    Orçamento novo por sessão retomada. Nunca confirma o Problema nem aprova decisão reservada.

    Returns:
        ``True`` se a nova sessão foi executada; ``False`` se a retomada foi recusada.
    """
    from src.llm.catalog import CatalogError
    from src.llm.routing import RoutingError
    from src.llm.session import bind_session_routing, build_session_routing
    from src.session.resume import ResumeError, prepare_resume

    try:
        await orchestrator.recover_interrupted_sessions()
    except Exception as e:  # noqa: BLE001 - a detecção de paradas nunca impede a retomada
        logger.warning("Detecção de sessões interrompidas falhou", extra={"error": type(e).__name__})

    store = index = None
    try:
        from src.knowledge.factory import open_graph_store, open_knowledge_runtime

        runtime = open_knowledge_runtime()
        store = runtime.store if runtime is not None else open_graph_store()
        index = runtime.index if runtime is not None else None
    except Exception as e:  # noqa: BLE001 - sem grafo, a preparação recusa se a sessão tinha projeto
        logger.warning("Grafo indisponível para a retomada", extra={"error": type(e).__name__})

    try:
        prep = await prepare_resume(
            session_manager=orchestrator.session_manager,
            base_dir=orchestrator.output_manager.base_dir,
            session_id=session_id,
            project_arg=project_arg,
            mode=mode,
            store=store,
            index=index,
            confirm=_ask_yes_no,
        )
    except ResumeError as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}{e}{RESET}\n")
        return False

    try:
        routing = await build_session_routing(cli_pins={"researcher": model_pin} if model_pin else None)
    except (RoutingError, CatalogError) as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}Falha na resolução de modelos: {e}{RESET}\n")
        return False
    bind_session_routing(routing)

    print_session_banner(prep.mode, budget=budget, llm_routing=routing)
    if prep.accumulated.get("tokens") or prep.accumulated.get("minutos"):
        print(
            f"  {DIM}Consumo acumulado da cadeia: {prep.accumulated['tokens']:.0f} tokens, "
            f"{prep.accumulated['minutos']:.1f} min (esta sessão tem orçamento novo).{RESET}"
        )
    divergence = orchestrator.resume_provenance_divergence(prep.state.source_session_id)
    if divergence is not None:
        print(f"  {YELLOW}⚠ Proveniência: {divergence[0]}{RESET}")
    print(
        f"\n  {DIM}Retomando a sessão {prep.state.source_session_id} a partir do checkpoint "
        f"({len(prep.state.completed)} subtarefa(s) concluída(s) não serão reexecutadas); "
        f"orçamento novo (modo: {prep.mode}).{RESET}\n"
    )
    try:
        result = await orchestrator.handle_request(
            prep.prompt,
            mode=prep.mode,
            context_bundle=ContextBundle(),
            budget=budget,
            llm_routing=routing,
            project_id=prep.state.project_id,
            project_context=prep.project_context,
            project_mode=None if prep.state.project_id else "sem_grafo",
            resume=prep.state,
        )
        print(format_result(result))
    except Exception as e:  # noqa: BLE001 - ResumeConflictError inclusive: o código de saída reflete a falha
        logger.error("Erro ao retomar a sessão", extra={"error": str(e)})
        print(f"\n  {STATUS_ICONS['error']} {RED}Erro: {e}{RESET}\n")
        return False
    return True


async def resume_session(orchestrator: Orchestrator, session_id: str, **kwargs: Any) -> bool:
    """``geminiclaw resume --session <id>``: retoma a sessão a partir do checkpoint (sem reiniciar do prompt)."""
    return await _run_resume(orchestrator, session_id, **kwargs)


async def continue_project(orchestrator: Orchestrator, project_id: str, **kwargs: Any) -> bool:
    """``geminiclaw continue --project <id>``: retoma a sessão mais recente do projeto."""
    from src.knowledge.errors import GraphStoreError
    from src.knowledge.projects import validate_project_id
    from src.session.resume import ResumeError, select_session_for_project

    try:
        await orchestrator.recover_interrupted_sessions()
        pid = validate_project_id(project_id)
        session_id = select_session_for_project(orchestrator.session_manager, pid)
    except (GraphStoreError, ResumeError) as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}{e}{RESET}\n")
        return False
    return await _run_resume(orchestrator, session_id, project_arg=pid, **kwargs)
