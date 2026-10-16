"""Modo sem limite no terminal: confirmação digitada e marcação do projeto (v18.5-operation-metrics, design §2.2).

Movido de ``src/cli/main.py`` sem alterar o comportamento: a confirmação é do terminal e acontece antes do
lançamento do processo da sessão (v18.7-background-sessions, design §1.2).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.gate.persistent_gate import TerminalGate, terminal_gate
from src.gate.types import Source
from src.logger import get_logger
from src.orchestration.usage import UsageBudget

if TYPE_CHECKING:
    from src.orchestration.unlimited_mode import UnlimitedActivation

logger = get_logger(__name__)


def resolve_unlimited_budget(
    args: "argparse.Namespace",
    budget: UsageBudget,
    *,
    project_marked: Callable[[str | None], bool] | None = None,
    input_fn: Callable[[str], str] = input,
    isatty: Callable[[], bool] | None = None,
    reference: str | None = None,
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
    from src.orchestration.unlimited_mode import ORIGIN_CLI, ORIGIN_PROJECT, set_activation

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
    set_activation(confirm_unlimited(budget, origin, input_fn=input_fn, isatty=isatty, reference=reference))
    return budget


def _project_marked_unlimited(project_arg: str | None) -> bool:
    """True se o projeto da sessão (``--project`` ou o padrão) está marcado com ``modo_sem_limite``."""
    from src.knowledge import projects
    from src.knowledge.factory import open_graph_store

    projeto_id = project_arg or projects.get_default_project()
    if not projeto_id:
        return False
    return projects.is_unlimited_marked(open_graph_store(), projeto_id)


def confirm_unlimited(
    budget: UsageBudget,
    origin: str,
    *,
    input_fn: Callable[[str], str] = input,
    isatty: Callable[[], bool] | None = None,
    gate: "TerminalGate | None" = None,
    interval_minutes: float | None = None,
    token_step: int | None = None,
    now: Callable[[], datetime] | None = None,
    reference: str | None = None,
) -> "UnlimitedActivation":
    """Pede a confirmação digitada do modo sem limite.

    Args:
        budget: Orçamento já construído com ``unlimited=True``.
        origin: ``cli`` ou ``projeto``.
        input_fn: Leitura da resposta (injetável em testes).
        isatty: Indica se há terminal interativo (padrão: ``sys.stdin.isatty``).
        gate: ``TerminalGate`` das decisões reservadas (padrão: o do processo); a confirmação digitada no terminal é a
            única origem que o autoriza (v18-usage-limits X.1).
        interval_minutes: Cadência dos avisos por tempo (padrão: ``UNLIMITED_NOTICE_INTERVAL_MINUTES``).
        token_step: Cadência dos avisos por tokens (padrão: ``UNLIMITED_NOTICE_TOKEN_STEP``).
        now: Relógio (injetável em testes).
        reference: ``referencia`` do pedido no gate; o terminal passa o ``launch_id`` do lançamento, e o processo da
            sessão confere e consome o pedido (v18.7-persistent-human-gate §1.1). Padrão: a origem.

    Returns:
        A ativação confirmada.

    Raises:
        UnlimitedModeError: Se o orçamento não for sem limite, faltarem os critérios de término, não houver terminal
            interativo ou a resposta for diferente da frase de confirmação (incluindo EOF).
    """
    from src import config
    from src.orchestration.unlimited_mode import (
        CONFIRMATION_PHRASE,
        UnlimitedActivation,
        UnlimitedModeError,
        confirmation_prompt,
        stop_criteria_available,
    )

    if not budget.unlimited:
        raise UnlimitedModeError("O orçamento informado não está no modo sem limite.")
    if not stop_criteria_available():
        raise UnlimitedModeError(
            "--unlimited exige os critérios de término da V18 (solucao_encontrada e sem_caminhos_promissores), "
            "que não estão disponíveis nesta instalação; use os limites numéricos."
        )
    tty = isatty if isatty is not None else sys.stdin.isatty
    if not tty():
        raise UnlimitedModeError(
            "O modo sem limite exige confirmação interativa e não há terminal; a sessão não foi iniciada. "
            "Execute num terminal ou use os limites numéricos."
        )
    prompt = confirmation_prompt(
        budget,
        interval_minutes=interval_minutes if interval_minutes is not None else config.UNLIMITED_NOTICE_INTERVAL_MINUTES,
        token_step=token_step if token_step is not None else config.UNLIMITED_NOTICE_TOKEN_STEP,
    )
    try:
        answer = input_fn(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        raise UnlimitedModeError("Confirmação do modo sem limite não recebida; a sessão não foi iniciada.") from exc
    if answer.strip().lower() != CONFIRMATION_PHRASE:
        raise UnlimitedModeError(
            f'Confirmação diferente de "{CONFIRMATION_PHRASE}"; a sessão não foi iniciada e o modo não cai para o '
            "limitado sem o seu pedido."
        )
    # Gate de decisão reservada (X.1): a resposta de ask_researcher, do consultor ou de um agente nunca autoriza.
    active_gate = gate or terminal_gate()
    request = active_gate.resolve("ativar_modo_sem_limite", reference or origin, source=Source.TERMINAL, approved=True)
    if not active_gate.authorized(request.id):
        raise UnlimitedModeError("O gate de decisões reservadas não autorizou o modo sem limite; a sessão não iniciou.")
    stamp = (now or (lambda: datetime.now(UTC)))().isoformat()
    return UnlimitedActivation(origem=origin, confirmado_em=stamp)
