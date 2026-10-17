"""Banner de início da sessão no terminal.

Movido de ``src/cli/main.py`` sem alterar o comportamento (v18.7-background-sessions, tarefa 0.9; ADR 024 §5).
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.session import SessionRouting

from src.config import (
    APP_NAME,
    SessionMode,
)
from src.host.health import thermal_protection_warning
from src.logger import get_logger
from src.orchestration.usage import UsageBudget
from src.research_data.context_loader import ContextBundle
from src.utils.terminal import BOLD, DIM, RESET, YELLOW

logger = get_logger(__name__)


def data_banner_lines(bundle: ContextBundle | None) -> list[str]:
    """Linhas do banner sobre os dados de entrada: contagens por classe e arquivos compartilháveis com o motivo."""
    if bundle is None or not bundle.markings:
        return []
    counts = bundle.marking_counts()
    lines = [
        f"Dados: {counts['pesquisa']} de pesquisa · {counts['compartilhaveis']} compartilháveis · "
        f"{counts['documentos']} documentos"
    ]
    for marking in bundle.shareable_markings():
        lines.append(f"  compartilhável: {marking.caminho} — {marking.motivo}")
    return lines


def print_session_banner(
    mode: str,
    context_dir: str = "input_context",
    budget: UsageBudget | None = None,
    llm_routing: "SessionRouting | None" = None,
    context_bundle: ContextBundle | None = None,
) -> None:
    """Exibe o banner de inicialização de sessão (Roadmap V15.6 / Spec G10).

    Não bloqueia: apenas informa o pesquisador do estado atual antes de iniciar.

    Args:
        mode: Modo de operação ativo da sessão (SessionMode).
        context_dir: Diretório de contexto de entrada a inspecionar.
        budget: Orçamento de uso efetivo da sessão (Roadmap V18 / Spec
            `usage-limits`). Se omitido, usa os defaults de `src/config.py`
            apenas para exibição (não altera o orçamento real da sessão).
        llm_routing: Mapa resolvido de modelos por papel (ADR 017). Quando informado, o
            banner traz uma linha por papel (``<papel>  <provedor/modelo>  (<trust>)``), a
            política, o modo de roteamento e a versão/hash do catálogo — nunca segredos.
    """
    mode_label = {
        SessionMode.ASSISTED.value: "assistido",
        SessionMode.SEMI.value: "semi-autônomo",
        SessionMode.AUTO.value: "autônomo",
    }.get(mode, mode)

    context_path = Path(context_dir)
    file_count = 0
    file_names: list[str] = []
    if context_path.is_dir():
        file_names = sorted(p.name for p in context_path.iterdir() if p.is_file())
        file_count = len(file_names)

    if file_count == 0:
        context_desc = f"{YELLOW}⚠ Nenhum contexto detectado{RESET}"
    elif file_count <= 3:
        context_desc = f"{file_count} arquivo(s): {', '.join(file_names)}"
    else:
        context_desc = f"{file_count} arquivos"

    print(
        f"\n{DIM}┌──────────────────────────────────────────────────────────────┐{RESET}\n"
        f"{DIM}│{RESET}  {APP_NAME}  │  Modo: {BOLD}{mode_label}{RESET}  │  Contexto: {context_desc}\n"
        f"{DIM}│{RESET}  Pressione Ctrl+C para suspender │  -h para ajuda\n"
        f"{DIM}└──────────────────────────────────────────────────────────────┘{RESET}"
    )

    for line in data_banner_lines(context_bundle):
        print(f"  {DIM}{line}{RESET}")

    # Roadmap V18 / Spec usage-limits — orçamento efetivo exibido no início da sessão.
    effective_budget = budget or UsageBudget.from_config()
    if effective_budget.unlimited:
        from src import config as _cfg
        from src.orchestration.unlimited_mode import banner_line, get_activation

        print(
            f"  {DIM}Orçamento: {RESET}{YELLOW}{BOLD}"
            + banner_line(
                effective_budget,
                (get_activation().origem if get_activation() else "cli"),
                interval_minutes=_cfg.UNLIMITED_NOTICE_INTERVAL_MINUTES,
                token_step=_cfg.UNLIMITED_NOTICE_TOKEN_STEP,
            )
            + RESET
        )
    else:
        print(
            f"  {DIM}Orçamento: {RESET}{effective_budget.max_tokens:,} tokens "
            f"({effective_budget.closing_reserve_pct*100:.0f}% reservados p/ fechamento) │ "
            f"{effective_budget.max_minutes:.0f}min │ "
            f"US$ {effective_budget.max_cost_usd:.2f} │ "
            f"{effective_budget.max_task_retries} retentativas/tarefa │ "
            f"{effective_budget.max_connection_retries} retentativas de conexão"
        )

    thermal_warning = thermal_protection_warning()
    if thermal_warning:
        print(f"  {YELLOW}⚠ {thermal_warning}{RESET}")

    if llm_routing is not None:
        header, *role_lines = llm_routing.banner_lines()
        print(f"  {DIM}{header}{RESET}")
        for line in role_lines:
            print(f"    {line}")
        # v18.5-model-catalog-locality — bloco "Alocação": trust, localidade e dados brutos por papel.
        from src.llm.allocation import allocation_banner_lines, allocation_catalog_line, mixed_profile_warning

        print(f"  {DIM}Alocação{RESET}")
        print(f"    {allocation_catalog_line(llm_routing)}")
        for line in allocation_banner_lines(llm_routing):
            print(f"    {line}")
        # v18.5-egress-gate — perfil que mistura papéis com e sem dados brutos: a filtragem entre papéis é frequente.
        mixed = mixed_profile_warning(llm_routing)
        if mixed:
            print(f"    {YELLOW}{mixed}{RESET}")

    if mode == SessionMode.AUTO.value:
        print(f"  {YELLOW}⚠ Modo autônomo ativo — sem consulta ao pesquisador{RESET}")
    print()
