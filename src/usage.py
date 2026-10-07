"""Orçamento e contabilização de uso da sessão (V18 — Spec `usage-limits`).

Introduz `UsageBudget` (orçamento imutável definido pelo pesquisador no início
da sessão) e `UsageTracker` (acumulador de consumo: tokens de todos os
agentes, tempo de relógio, retentativas por tarefa e retentativas de conexão),
usados pelo `AutonomousLoop` (`src/autonomous_loop.py`) para transformar os
limites operacionais da Spec G5 — hoje apenas avisos — em condições de parada
reais.

Ver ``openspec/changes/v18-usage-limits/design.md`` para o desenho completo.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from src.logger import get_logger

logger = get_logger(__name__)


class StopReason(str, Enum):
    """Motivo de parada da sessão (``motivo_parada`` gravado na sessão)."""

    TOKENS = "limite_tokens"
    TIME = "limite_tempo"
    RETRIES = "limite_retentativas"
    CONNECTION = "limite_conexao"
    RUNS = "limite_execucoes"
    MODEL_VERSION = "versao_modelo"  # v18.5-model-catalog-locality (LLM_ROUTING=strict)


@dataclass(frozen=True)
class UsageBudget:
    """Orçamento de uso definido pelo pesquisador para uma sessão.

    Attributes:
        max_tokens: Limite de tokens consumidos por TODOS os agentes da
            sessão, inclusive o Curator (fechamento).
        max_minutes: Limite de tempo de relógio (wall-clock) da sessão.
        max_task_retries: Limite de retentativas da MESMA tarefa (mesmo
            ``task_name``), contado cumulativamente inclusive após
            replanejamento que mantém o nome.
        max_connection_retries: Limite de retentativas de conexão
            acumuladas na sessão (provedores LLM + sandbox Docker).
        closing_reserve_pct: Fração de ``max_tokens`` reservada para o
            fechamento (checkpoint + consolidação final) após o limite de
            exploração ser atingido.
    """

    max_tokens: int
    max_minutes: float
    max_task_retries: int
    max_connection_retries: int
    closing_reserve_pct: float

    def __post_init__(self) -> None:
        """Valida a consistência do orçamento.

        Raises:
            ValueError: Se algum valor estiver fora do intervalo válido.
        """
        if self.max_tokens <= 0:
            raise ValueError("max_tokens deve ser positivo.")
        if self.max_minutes <= 0:
            raise ValueError("max_minutes deve ser positivo.")
        if self.max_task_retries <= 0:
            raise ValueError("max_task_retries deve ser positivo.")
        if self.max_connection_retries <= 0:
            raise ValueError("max_connection_retries deve ser positivo.")
        if not (0.0 <= self.closing_reserve_pct < 1.0):
            raise ValueError("closing_reserve_pct deve estar no intervalo [0, 1).")

    @property
    def exploration_token_ceiling(self) -> int:
        """Tokens disponíveis para exploração, descontada a reserva de fechamento.

        Returns:
            ``max_tokens × (1 − closing_reserve_pct)``, truncado para inteiro.
        """
        return int(self.max_tokens * (1 - self.closing_reserve_pct))

    def to_payload(self) -> dict:
        """Serializa o orçamento para gravação em ``agent_sessions.payload['budget']``.

        Returns:
            Dicionário JSON-serializável com todos os campos do orçamento.
        """
        return {
            "max_tokens": self.max_tokens,
            "max_minutes": self.max_minutes,
            "max_task_retries": self.max_task_retries,
            "max_connection_retries": self.max_connection_retries,
            "closing_reserve_pct": self.closing_reserve_pct,
            "exploration_token_ceiling": self.exploration_token_ceiling,
        }

    @classmethod
    def from_config(
        cls,
        *,
        max_tokens: int | None = None,
        max_minutes: float | None = None,
        max_task_retries: int | None = None,
        max_connection_retries: int | None = None,
        closing_reserve_pct: float | None = None,
    ) -> "UsageBudget":
        """Constrói o orçamento a partir dos defaults de ``src/config.py``.

        Qualquer argumento explícito (tipicamente vindo de opções da CLI como
        ``--max-tokens``) sobrescreve o default correspondente.

        Args:
            max_tokens: Override para ``SESSION_MAX_TOKENS``.
            max_minutes: Override para ``SESSION_MAX_MINUTES``.
            max_task_retries: Override para ``SESSION_MAX_TASK_RETRIES``.
            max_connection_retries: Override para ``SESSION_MAX_CONNECTION_RETRIES``.
            closing_reserve_pct: Override para ``SESSION_CLOSING_RESERVE_PCT``.

        Returns:
            Um novo `UsageBudget` com os valores efetivos da sessão.
        """
        from src import config as _config

        return cls(
            max_tokens=max_tokens if max_tokens is not None else _config.SESSION_MAX_TOKENS,
            max_minutes=(
                max_minutes if max_minutes is not None else _config.SESSION_MAX_MINUTES
            ),
            max_task_retries=(
                max_task_retries
                if max_task_retries is not None
                else _config.SESSION_MAX_TASK_RETRIES
            ),
            max_connection_retries=(
                max_connection_retries
                if max_connection_retries is not None
                else _config.SESSION_MAX_CONNECTION_RETRIES
            ),
            closing_reserve_pct=(
                closing_reserve_pct
                if closing_reserve_pct is not None
                else _config.SESSION_CLOSING_RESERVE_PCT
            ),
        )


@dataclass(frozen=True)
class LimitStatus:
    """Resultado consolidado de uma verificação de limites (`UsageTracker.check`)."""

    tokens_used: int
    tokens_pct: float
    tokens_exhausted: bool
    minutes_elapsed: float
    minutes_pct: float
    time_exhausted: bool
    connection_retries: int
    connection_retries_pct: float
    connection_retries_exhausted: bool
    # Parada solicitada por outra fonte além do orçamento (ex.: versão do modelo em strict).
    pending_stop: StopReason | None = None

    @property
    def should_close(self) -> bool:
        """True se alguma condição de parada graciosa da sessão foi atingida."""
        return (
            self.tokens_exhausted
            or self.time_exhausted
            or self.connection_retries_exhausted
            or self.pending_stop is not None
        )

    @property
    def stop_reason(self) -> StopReason | None:
        """Motivo de parada correspondente.

        Segue a prioridade tokens > tempo > conexão, coerente com a ordem de
        avaliação em `UsageTracker.check`.
        """
        if self.tokens_exhausted:
            return StopReason.TOKENS
        if self.time_exhausted:
            return StopReason.TIME
        if self.connection_retries_exhausted:
            return StopReason.CONNECTION
        return self.pending_stop


def _default_token_reader(execution_id: str) -> int:
    """Lê o total de tokens consumidos pela sessão a partir da telemetria.

    Args:
        execution_id: ID da execução (mesmo usado em toda a telemetria da sessão).

    Returns:
        Soma de ``total_tokens`` de todos os agentes/provedores da sessão,
        inclusive o Curator (a telemetria não distingue papel neste totalizador).
    """
    from src.telemetry import get_telemetry

    summary = get_telemetry().get_token_summary(execution_id)
    rows = summary.get("by_provider_model", [])
    return sum(r.get("total_tokens") or 0 for r in rows)


def _default_connection_retry_reader(execution_id: str) -> int:
    """Lê o total de retentativas de conexão da sessão a partir da telemetria.

    Args:
        execution_id: ID da execução.

    Returns:
        Número de eventos ``connection_retry`` registrados para a sessão.
    """
    from src.telemetry import get_telemetry

    return get_telemetry().get_connection_retry_count(execution_id)


class UsageTracker:
    """Acumula o consumo de uma sessão e verifica os limites do `UsageBudget`.

    Uma instância por sessão mestra (execução). Tokens e retentativas de
    conexão são lidos da telemetria (fonte única de verdade, alimentada por
    todos os agentes/containers da sessão, inclusive o Curator); tempo é
    medido por relógio monotônico local ao processo do orquestrador;
    retentativas por tarefa são contadas em processo, por ``task_name``,
    cumulativamente entre ciclos de replanejamento.
    """

    def __init__(
        self,
        budget: UsageBudget,
        execution_id: str,
        *,
        token_reader: Callable[[], int] | None = None,
        connection_retry_reader: Callable[[], int] | None = None,
        clock: Callable[[], float] | None = None,
        pending_stop: Callable[[], StopReason | None] | None = None,
    ) -> None:
        """Inicializa o tracker.

        Args:
            budget: Orçamento efetivo da sessão.
            execution_id: ID da execução usado para consultar a telemetria.
            token_reader: Função sem argumentos que retorna o total de tokens
                consumidos até agora. Injetável para testes; por padrão lê a
                telemetria via `execution_id`.
            connection_retry_reader: Função sem argumentos que retorna o
                total de retentativas de conexão até agora. Injetável para
                testes; por padrão lê a telemetria via `execution_id`.
            clock: Função sem argumentos que retorna um timestamp monotônico
                em segundos. Injetável para testes de limite de tempo.
            pending_stop: Função sem argumentos que devolve um motivo de parada pedido por outra fonte (versão do
                modelo em ``strict``), verificada nos mesmos pontos que os limites; ``None`` = nenhuma.
        """
        self.budget = budget
        self.execution_id = execution_id
        self._clock = clock or time.monotonic
        self._started_monotonic = self._clock()
        self._token_reader = token_reader or (lambda: _default_token_reader(execution_id))
        self._connection_retry_reader = connection_retry_reader or (
            lambda: _default_connection_retry_reader(execution_id)
        )
        self._pending_stop = pending_stop
        self._task_retry_counts: dict[str, int] = {}
        self._abandoned_tasks: set[str] = set()

    def elapsed_minutes(self) -> float:
        """Minutos de relógio decorridos desde a criação do tracker.

        Returns:
            Minutos decorridos (float).
        """
        return (self._clock() - self._started_monotonic) / 60.0

    def record_task_attempt(self, task_name: str) -> int:
        """Registra uma nova tentativa de execução da tarefa `task_name`.

        Conta cumulativamente entre ciclos de replanejamento (mesmo
        ``task_name`` reaparecendo em planos incrementais), conforme
        design §2 — Retentativas por tarefa.

        Args:
            task_name: Nome da subtarefa no DAG.

        Returns:
            O número total de tentativas já registradas para essa tarefa
            (inclusive esta).
        """
        count = self._task_retry_counts.get(task_name, 0) + 1
        self._task_retry_counts[task_name] = count
        return count

    def task_attempts(self, task_name: str) -> int:
        """Número de tentativas já registradas para `task_name`."""
        return self._task_retry_counts.get(task_name, 0)

    def task_retries_exhausted(self, task_name: str) -> bool:
        """True se `task_name` atingiu `max_task_retries`.

        Args:
            task_name: Nome da subtarefa no DAG.
        """
        return self._task_retry_counts.get(task_name, 0) >= self.budget.max_task_retries

    def mark_task_abandoned(self, task_name: str) -> None:
        """Marca a tarefa como abandonada por esgotamento de retentativas.

        Args:
            task_name: Nome da subtarefa no DAG.
        """
        self._abandoned_tasks.add(task_name)
        logger.warning(
            "Tarefa abandonada por esgotamento de retentativas",
            extra={
                "task_name": task_name,
                "attempts": self._task_retry_counts.get(task_name, 0),
                "max_task_retries": self.budget.max_task_retries,
            },
        )

    def is_task_abandoned(self, task_name: str) -> bool:
        """True se `task_name` já foi marcada como abandonada."""
        return task_name in self._abandoned_tasks

    @property
    def abandoned_tasks(self) -> frozenset[str]:
        """Conjunto imutável das tarefas abandonadas até o momento."""
        return frozenset(self._abandoned_tasks)

    def all_pending_abandoned(self, pending_task_names: list[str]) -> bool:
        """True se TODAS as tarefas em `pending_task_names` foram abandonadas.

        Usado para decidir se a sessão inteira deve fechar com
        ``motivo_parada="limite_retentativas"`` (design §3).

        Args:
            pending_task_names: Nomes das tarefas ainda pendentes/falhas no
                ciclo atual.

        Returns:
            False se a lista estiver vazia (nada pendente não é "tudo
            abandonado" — não há razão para fechar por este motivo).
        """
        if not pending_task_names:
            return False
        return all(t in self._abandoned_tasks for t in pending_task_names)

    def check(self) -> LimitStatus:
        """Avalia todos os limites do orçamento e retorna o status consolidado.

        Returns:
            `LimitStatus` com o percentual consumido e o estado de cada limite.
        """
        tokens_used = self._token_reader()
        tokens_pct = (tokens_used / self.budget.max_tokens) if self.budget.max_tokens else 0.0
        tokens_exhausted = tokens_used >= self.budget.exploration_token_ceiling

        minutes_elapsed = self.elapsed_minutes()
        minutes_pct = (
            (minutes_elapsed / self.budget.max_minutes) if self.budget.max_minutes else 0.0
        )
        time_exhausted = minutes_elapsed >= self.budget.max_minutes

        connection_retries = self._connection_retry_reader()
        connection_pct = (
            (connection_retries / self.budget.max_connection_retries)
            if self.budget.max_connection_retries
            else 0.0
        )
        connection_exhausted = connection_retries >= self.budget.max_connection_retries

        status = LimitStatus(
            tokens_used=tokens_used,
            tokens_pct=tokens_pct,
            tokens_exhausted=tokens_exhausted,
            minutes_elapsed=minutes_elapsed,
            minutes_pct=minutes_pct,
            time_exhausted=time_exhausted,
            connection_retries=connection_retries,
            connection_retries_pct=connection_pct,
            connection_retries_exhausted=connection_exhausted,
            pending_stop=self._pending_stop() if self._pending_stop is not None else None,
        )

        if status.should_close:
            reason = status.stop_reason
            logger.warning(
                "Limite de orçamento atingido",
                extra={
                    "execution_id": self.execution_id,
                    "stop_reason": reason.value if reason else None,
                    "tokens_used": tokens_used,
                    "tokens_ceiling": self.budget.exploration_token_ceiling,
                    "minutes_elapsed": minutes_elapsed,
                    "max_minutes": self.budget.max_minutes,
                    "connection_retries": connection_retries,
                },
            )
        return status

    def tokens_hard_exhausted(self) -> bool:
        """True se o consumo já atingiu `max_tokens` (sem reserva alguma).

        Usado para decidir se ainda há orçamento para uma consolidação final
        via LLM durante o fechamento, ou se apenas o checkpoint determinístico
        (sem LLM) pode ser gravado (design §3 — reserva esgotada).
        """
        return self._token_reader() >= self.budget.max_tokens
