"""Modo sem limite: confirmação, origem e avisos periódicos (v18.5-operation-metrics, design §2).

O modo só é ativado por ação explícita do pesquisador: a opção ``--unlimited`` da CLI ou a marcação
``modo_sem_limite`` do nó ``Projeto`` (``geminiclaw project unlimited``). Nunca por variável de ambiente,
plano, resposta de agente ou mensagem IPC. Em ambos os casos exige a confirmação digitada no início de CADA
execução; sem terminal interativo a sessão não inicia.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.logger import get_logger
from src.orchestration.exploration import ExplorationStop
from src.orchestration.usage import UsageBudget

logger = get_logger(__name__)

CONFIRMATION_PHRASE = "sem limite"
ORIGIN_CLI = "cli"
ORIGIN_PROJECT = "projeto"


_ACTIVATION: "UnlimitedActivation | None" = None


class UnlimitedModeError(RuntimeError):
    """O modo sem limite não pode ser iniciado (mensagem acionável para o pesquisador)."""


def stop_criteria_available() -> bool:
    """True se os critérios de término por resultado da V18 existem (solução encontrada, sem caminhos promissores)."""
    names = {member.value for member in ExplorationStop}
    return {"solucao_encontrada", "sem_caminhos_promissores"} <= names


def confirmation_prompt(budget: UsageBudget, *, interval_minutes: float, token_step: int) -> str:
    """Texto da confirmação (design §2.2)."""
    return (
        "⚠ MODO SEM LIMITE: tokens, tempo, custo e volume de egresso não interrompem a sessão.\n"
        f"  Retentativas por tarefa ({budget.max_task_retries}) e de conexão ({budget.max_connection_retries}) "
        "continuam limitadas.\n"
        "  As regras de localidade dos dados continuam valendo.\n"
        f"  Avisos de consumo a cada {interval_minutes:g} min ou {token_step:,} tokens.\n"
        f'  Digite "{CONFIRMATION_PHRASE}" para confirmar: '
    )


@dataclass(frozen=True)
class UnlimitedActivation:
    """Registro da ativação confirmada, gravado em ``payload["budget"]``."""

    origem: str
    confirmado_em: str

    def to_payload(self) -> dict[str, str | bool]:
        return {
            "unlimited": True,
            "unlimited_origem": self.origem,
            "unlimited_confirmado_em": self.confirmado_em,
        }


def banner_line(budget: UsageBudget, origin: str, *, interval_minutes: float, token_step: int) -> str:
    """Linha de orçamento do banner no modo sem limite (design §2.7)."""
    origem = "marcação do projeto" if origin == ORIGIN_PROJECT else "opção --unlimited"
    return (
        f"SEM LIMITE de tokens, tempo, custo e egresso ({origem}) │ {budget.max_task_retries} retentativas/tarefa │ "
        f"{budget.max_connection_retries} retentativas de conexão │ avisos a cada {interval_minutes:g} min / "
        f"{token_step:,} tokens"
    )


class NoticeSchedule:
    """Decide quando emitir o aviso periódico: o que ocorrer primeiro entre tempo e tokens; ambos reiniciam."""

    def __init__(self, interval_minutes: float, token_step: int, *, started_minutes: float = 0.0) -> None:
        if interval_minutes <= 0 or token_step <= 0:
            raise ValueError("A cadência dos avisos do modo sem limite deve ser positiva.")
        self.interval_minutes = interval_minutes
        self.token_step = token_step
        self._last_minutes = started_minutes
        self._last_tokens = 0

    def due(self, minutes_elapsed: float, tokens_used: int) -> bool:
        """True se o aviso é devido agora (e reinicia a cadência)."""
        by_time = minutes_elapsed - self._last_minutes >= self.interval_minutes
        by_tokens = tokens_used - self._last_tokens >= self.token_step
        if by_time or by_tokens:
            self._last_minutes = minutes_elapsed
            self._last_tokens = tokens_used
            return True
        return False


def set_activation(activation: "UnlimitedActivation | None") -> None:
    """Guarda a ativação confirmada nesta execução da CLI (lida pelo banner e pelo orquestrador)."""
    global _ACTIVATION
    _ACTIVATION = activation


def get_activation() -> "UnlimitedActivation | None":
    """Ativação confirmada nesta execução, ou ``None`` (modo limitado)."""
    return _ACTIVATION


def budget_payload(budget: UsageBudget) -> dict:
    """``budget.to_payload()`` com origem e instante da confirmação quando o modo sem limite está ativo."""
    payload = budget.to_payload()
    if budget.unlimited and _ACTIVATION is not None:
        payload.update(_ACTIVATION.to_payload())
    return payload


def record_confirmation_event(session_id: str) -> None:
    """Evento de telemetria ``unlimited_mode_confirmed`` (no-op no modo limitado). Nunca levanta."""
    if _ACTIVATION is None:
        return
    try:
        from src.observability.telemetry import get_telemetry

        get_telemetry().record_agent_event(
            execution_id=session_id,
            session_id=session_id,
            agent_id="orchestrator",
            event_type="unlimited_mode_confirmed",
            payload=_ACTIVATION.to_payload(),
        )
    except Exception:  # noqa: BLE001 - telemetria nunca impede a sessão
        logger.warning("Evento unlimited_mode_confirmed não registrado", exc_info=True)
