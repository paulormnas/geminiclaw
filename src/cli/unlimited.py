"""Modo sem limite no terminal: confirmação digitada e marcação do projeto (v18.5-operation-metrics, design §2.2).

Movido de ``src/cli/main.py`` sem alterar o comportamento: a confirmação é do terminal e acontece antes do
lançamento do processo da sessão (v18.7-background-sessions, design §1.2).
"""

import argparse
from collections.abc import Callable

from src.logger import get_logger
from src.orchestration.usage import UsageBudget

logger = get_logger(__name__)


def resolve_unlimited_budget(
    args: "argparse.Namespace",
    budget: UsageBudget,
    *,
    project_marked: Callable[[str | None], bool] | None = None,
    input_fn: Callable[[str], str] = input,
    isatty: Callable[[], bool] | None = None,
) -> UsageBudget:
    """Aplica e confirma o modo sem limite (v18.5-operation-metrics, design §2.2).

    O modo vem da opção ``--unlimited`` ou da marcação do projeto; nos dois casos a confirmação digitada é exigida a
    cada execução, e a retomada (``resume``/``continue``) não herda o modo da sessão anterior. Opções numéricas
    explícitas (``--max-tokens`` etc.) prevalecem sobre a marcação do projeto.

    Returns:
        O orçamento a usar (sem limite e confirmado, ou o recebido).

    Raises:
        UnlimitedModeError: Confirmação ausente, errada ou impossível (sem terminal).
    """
    from src.orchestration.unlimited_mode import (
        ORIGIN_CLI,
        ORIGIN_PROJECT,
        confirm_unlimited,
        set_activation,
    )

    origin: str | None = ORIGIN_CLI if budget.unlimited else None
    explicit_limits = any(
        getattr(args, name, None) is not None for name in ("max_tokens", "max_minutes", "max_egress_bytes")
    )
    if origin is None and not explicit_limits and project_marked is not None:
        try:
            if project_marked(getattr(args, "project", None)):
                origin = ORIGIN_PROJECT
                budget = UsageBudget.from_config(
                    max_task_retries=getattr(args, "max_task_retries", None),
                    max_connection_retries=getattr(args, "max_connection_retries", None),
                    unlimited=True,
                )
        except Exception as exc:  # noqa: BLE001 - sem ler a marcação, a sessão segue limitada (padrão seguro)
            logger.warning("Marcação de modo sem limite do projeto não lida", extra={"error": type(exc).__name__})
    if origin is None:
        set_activation(None)
        return budget
    set_activation(confirm_unlimited(budget, origin, input_fn=input_fn, isatty=isatty))
    return budget


def _project_marked_unlimited(project_arg: str | None) -> bool:
    """True se o projeto da sessão (``--project`` ou o padrão) está marcado com ``modo_sem_limite``."""
    from src.knowledge import projects
    from src.knowledge.factory import open_graph_store

    projeto_id = project_arg or projects.get_default_project()
    if not projeto_id:
        return False
    return projects.is_unlimited_marked(open_graph_store(), projeto_id)
