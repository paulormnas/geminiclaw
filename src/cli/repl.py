"""Execução de um prompt e laço do REPL.

Movido de ``src/cli/main.py`` sem alterar o comportamento (v18.7-background-sessions, tarefa 0.9; ADR 024 §5).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.cli.project_session import ProjectBinder
    from src.llm.session import SessionRouting

from src.cli.banner import print_session_banner
from src.cli.context_commands import clear_context, print_context_lifecycle_message
from src.cli.reports import format_result
from src.cli.resume import resume_session
from src.cli.sandboxes import show_sandboxes, stop_sandboxes
from src.config import (
    SESSION_DEFAULT_MODE,
)
from src.logger import get_logger
from src.orchestration.orchestrator import Orchestrator
from src.orchestration.usage import UsageBudget
from src.research_data.context_loader import ContextBundle
from src.utils.terminal import BANNER, DIM, MAGENTA, RED, RESET, STATUS_ICONS, YELLOW

logger = get_logger(__name__)

EXIT_COMMANDS = {"exit", "quit", "sair"}


async def execute_prompt(
    orchestrator: Orchestrator,
    prompt: str,
    mode: str | None = None,
    context_bundle: ContextBundle | None = None,
    budget: UsageBudget | None = None,
    llm_routing: "SessionRouting | None" = None,
    project_binder: "ProjectBinder | None" = None,
) -> bool:
    """Executa um prompt no orquestrador e exibe o resultado.

    Args:
        orchestrator: Instância do orquestrador.
        prompt: Prompt do usuário.
        mode: Nível de autonomia da sessão (SessionMode). Se omitido, usa o padrão.
        context_bundle: Contexto pré-carregado de `input_context/` (Spec G9).
        budget: Orçamento de uso da sessão (Roadmap V18 / Spec `usage-limits`).
            Se omitido, usa os defaults de `src/config.py`.
        llm_routing: Mapa resolvido de modelos por papel (ADR 017); se omitido, o
            orquestrador o resolve antes de qualquer chamada de LLM.
        project_binder: Resolve o projeto da sessão e garante o Problema confirmado pelo
            pesquisador antes de qualquer planejamento (v17-research-project).

    Returns:
        False se a sessão foi recusada antes de começar (projeto/problema); True caso contrário.
    """
    project_kwargs: dict[str, Any] = {}
    if project_binder is not None:
        from src.cli.project_session import ProjectFlowError
        from src.llm.session import bind_session_routing

        try:
            if llm_routing is not None:
                bind_session_routing(llm_routing)  # o rascunho do Problema usa o modelo do papel researcher
            binding = await project_binder.bind(prompt, context_bundle)
        except ProjectFlowError as e:
            print(f"\n  {STATUS_ICONS['error']} {RED}{e}{RESET}\n")
            return False
        if binding.mode == "sem_grafo":
            print(f"\n  {YELLOW}SEM GRAFO: projeto e Problema não aplicados nesta sessão.{RESET}")
            project_kwargs = {"project_mode": "sem_grafo"}
        else:
            project_kwargs = {"project_id": binding.project_id, "project_context": binding.context_block}

    print(f"\n  {STATUS_ICONS['running']} {DIM}Processando...{RESET}\n")

    try:
        result = await orchestrator.handle_request(
            prompt, mode=mode, context_bundle=context_bundle, budget=budget, llm_routing=llm_routing,
            **project_kwargs,
        )
        print(format_result(result))
        if context_bundle and result.session_id:
            print_context_lifecycle_message(result.session_id, context_bundle)
    except Exception as e:
        logger.error("Erro ao processar prompt", extra={"error": str(e)}, exc_info=True)
        print(f"\n  {STATUS_ICONS['error']} {RED}Erro: {e}{RESET}\n")
    return True


async def interactive_mode(
    orchestrator: Orchestrator,
    mode: str | None = None,
    explicit_mode: str | None = None,
    context_bundle: ContextBundle | None = None,
    budget: UsageBudget | None = None,
    llm_routing: "SessionRouting | None" = None,
    project_binder: "ProjectBinder | None" = None,
) -> None:
    """Executa a CLI em modo interativo (REPL).

    Args:
        orchestrator: Instância do orquestrador.
        mode: Nível de autonomia da sessão (SessionMode). Se omitido, usa o padrão.
        context_bundle: Contexto pré-carregado de `input_context/` (Spec G9), reutilizado
            em todas as interações do REPL.
        budget: Orçamento de uso da sessão (Roadmap V18 / Spec `usage-limits`),
            reutilizado em todas as interações do REPL. Se omitido, usa os
            defaults de `src/config.py`.
        llm_routing: Mapa resolvido de modelos por papel (ADR 017), resolvido uma vez para
            todo o REPL.
        project_binder: Vínculo de projeto, resolvido no primeiro prompt e reutilizado.
    """
    print(BANNER)
    print(f"  {DIM}Modo interativo. Digite 'sair' para encerrar.{RESET}\n")
    print_session_banner(
        mode or SESSION_DEFAULT_MODE, budget=budget, llm_routing=llm_routing, context_bundle=context_bundle
    )

    while True:
        try:
            prompt = input(f"  {MAGENTA}🔮 >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {DIM}Encerrando...{RESET}")
            break

        if not prompt:
            continue

        if prompt.lower() in EXIT_COMMANDS:
            print(f"\n  {DIM}Até logo! 👋{RESET}\n")
            break

        if prompt.lower() == "sandboxes":
            show_sandboxes()
            continue

        if prompt.lower() == "parar-sandboxes" or prompt.lower().startswith("parar-sandboxes "):
            parts = prompt.split()
            s_id = parts[1] if len(parts) > 1 else None
            stop_sandboxes(session_id=s_id)
            continue

        if prompt.lower() == "clear-context":
            clear_context()
            continue

        if prompt.lower() == "resume" or prompt.lower().startswith("resume "):
            parts = prompt.split()
            s_id = parts[1] if len(parts) > 1 else None
            if not s_id:
                print(f"\n  {RED}❌ Use: resume <session_id>{RESET}\n")
            else:
                await resume_session(orchestrator, s_id, mode=explicit_mode, budget=budget)
            continue

        await execute_prompt(
            orchestrator, prompt, mode=mode, context_bundle=context_bundle, budget=budget,
            llm_routing=llm_routing, project_binder=project_binder,
        )
