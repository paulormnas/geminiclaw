"""Estagnação, intervenção do Curator e saturação (v18.7-exploration-limits, design §7).

``StagnationPolicy`` olha o estado do objetivo ao fim de cada ciclo que executou algo (``ObjectiveState``) e decide:
nada, uma **intervenção** (o Curator sugere direções novas; a sessão nunca fecha por estagnação) ou, esgotadas as
intervenções e a paciência seguinte, a avaliação da **saturação** do tipo. A contagem de ciclos sem avanço e de
intervenções mora em ``ObjectiveMemory`` (vai no checkpoint, ``exploracao_estado``); este módulo só a lê e a atualiza.

A política não chama o Curator nem o gate: devolve um ``StallStep`` e quem a usa (``ExplorationSession``) executa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from src import config
from src.knowledge.objective import (
    SATURACAO_CONFIRMADA,
    SATURACAO_SO_AVISO,
    ObjectiveState,
)
from src.orchestration.objective_tracking import CONTINUITY_REQUESTS, ContinuityRequester, Emitter, ObjectiveTracker

STEP_INTERVENTION = "intervencao"
STEP_CLOSE = "saturacao"  # fecha a sessão (só no ``auto``, saturação confirmada)

#: Motivos de ``decidir_continuidade`` que o laço da estagnação aplica ao ser respondidos.
STAGNATION_MOTIVES = ("estagnacao", "saturacao", "intervencoes_esgotadas")

_STAGNATION_REQUESTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "estagnacao": (
        "estagnacao", ("continuar", "orientar", "parar"),
        "A exploração está sem avanço rumo ao objetivo e o Curator foi acionado para sugerir direções novas. "
        "Continuar, orientar a pesquisa ou parar?",
    ),
    "saturacao": (
        "saturacao", ("continuar", "orientar", "parar"),
        "A melhora possível ficou abaixo do erro da medida depois das intervenções. Continuar, orientar ou parar?",
    ),
    "intervencoes_esgotadas": (
        "intervencoes_esgotadas", ("continuar", "orientar", "parar"),
        "As intervenções do Curator se esgotaram sem avanço e a saturação não pôde ser confirmada. Continuar, "
        "orientar ou parar?",
    ),
}


def request_exhausted(requester: ContinuityRequester) -> None:
    """Pedido ``intervencoes_esgotadas`` (não bloqueia a sessão)."""
    motivo, options, question = _STAGNATION_REQUESTS["intervencoes_esgotadas"]
    requester(motivo, "intervencoes_esgotadas", options, question)


def patience(base: int, growth: float, interventions: int, fraction: float) -> int:
    """Paciência em ciclos: ``ceil(base × (1 + growth × intervenções) × (1 + f))`` (design §7, passo 2).

    Args:
        base: ``EXPLORATION_STALL_CYCLES``.
        growth: ``EXPLORATION_PATIENCE_GROWTH``.
        interventions: Intervenções já feitas.
        fraction: Maior fração consumida entre os limites ativos (0 no modo sem limite).
    """
    value = base * (1 + growth * interventions) * (1 + max(0.0, fraction))
    return math.ceil(round(value, 9))


@dataclass(frozen=True)
class StallStep:
    """O que o ciclo pede além de seguir.

    Attributes:
        kind: ``intervencao`` (acionar o Curator) ou ``saturacao`` (fechar a sessão).
        intervencao: Número da intervenção (1, 2, ...).
        ciclos_sem_avanco: Ciclos sem avanço que a motivaram.
        paciencia: Paciência vigente.
        detalhes: Melhor valor e hipótese (``limiar``), só números e ids.
    """

    kind: str
    intervencao: int = 0
    ciclos_sem_avanco: int = 0
    paciencia: int = 0
    detalhes: dict[str, Any] = field(default_factory=dict)


class StagnationPolicy:
    """Decide, a cada ciclo, entre seguir, intervir e avaliar a saturação."""

    def __init__(
        self,
        tracker: ObjectiveTracker,
        *,
        mode: str,
        emit: Emitter,
        requester: ContinuityRequester,
        fraction: Callable[[], float] = lambda: 0.0,
    ) -> None:
        """
        Args:
            tracker: Acompanhamento do objetivo (dono da memória, do atingimento e da política efetiva).
            mode: ``SessionMode``; o ``auto`` fecha na saturação, os demais pedem.
            emit: Telemetria ``(tipo, payload)``.
            requester: Registra um pedido ``decidir_continuidade`` ``(motivo, referencia, opcoes, pergunta)``.
            fraction: Maior fração consumida entre os limites ativos.
        """
        self._tracker = tracker
        self._mode = mode
        self._emit = emit
        self._request = requester
        self._fraction = fraction

    def enabled(self, criterion: dict[str, Any] | None) -> bool:
        """``EXPLORATION_STALL_CYCLES=0`` desliga; objetivo atingido com a política ``continuar`` também (design §7)."""
        if config.EXPLORATION_STALL_CYCLES <= 0:
            return False
        tracker = self._tracker
        return not (tracker.achievement is not None and tracker.effective_policy(criterion) == "continuar")

    def observe(self, state: ObjectiveState, criterion: dict[str, Any] | None) -> StallStep | None:
        """Aplica os passos 1 a 4 do design §7 ao fim de um ciclo que executou algo.

        Returns:
            ``None`` para seguir; um ``StallStep`` quando é hora de intervir ou de fechar por saturação. O estado de
            ``ObjectiveMemory`` já fica atualizado (intervenção feita, contagem zerada).
        """
        if not self.enabled(criterion):
            return None
        tracker = self._tracker
        memory = tracker.memory
        if state.avanco and memory.interventions:
            memory = replace(memory, interventions=0)
            tracker.memory = memory
            tracker.forget(_REPORT_PREFIX)
        needed = patience(
            config.EXPLORATION_STALL_CYCLES, config.EXPLORATION_PATIENCE_GROWTH, memory.interventions,
            self._fraction(),
        )
        if memory.cycles_without_advance < needed:
            return None
        detalhes = _best(state)
        if memory.interventions < config.EXPLORATION_MAX_INTERVENTIONS:
            tracker.memory = replace(memory, interventions=memory.interventions + 1, cycles_without_advance=0)
            return StallStep(
                STEP_INTERVENTION, memory.interventions + 1, memory.cycles_without_advance, needed, detalhes
            )
        return self._saturation(state, needed)

    def request_stagnation(self, step: StallStep) -> None:
        """No ``assisted``, o pedido ``estagnacao`` acompanha a intervenção (continuar, orientar, parar)."""
        if self._mode != "assisted":
            return
        motivo, options, question = _STAGNATION_REQUESTS["estagnacao"]
        self._request(motivo, f"estagnacao:{step.intervencao}", options, question)

    def reset(self) -> None:
        """Resposta ``continuar`` ou ``orientar``: zera intervenções e ciclos sem avanço (design §7, passo 4)."""
        tracker = self._tracker
        tracker.memory = replace(tracker.memory, interventions=0, cycles_without_advance=0)
        tracker.forget(_REPORT_PREFIX)

    # ------------------------------------------------------------------ saturação

    def _saturation(self, state: ObjectiveState, needed: int) -> StallStep | None:
        """Intervenções esgotadas e paciência seguinte esgotada: avalia a saturação do tipo (evento + desfecho)."""
        tracker = self._tracker
        if not tracker.once(f"{_REPORT_PREFIX}avaliada:{state.tipo}:{state.saturacao}"):
            return None  # já avaliada com este resultado; só uma resposta ou um avanço a reabre
        payload: dict[str, Any] = {
            "tipo": state.tipo, "resultado": state.saturacao, "paciencia": needed,
            "ciclos_sem_avanco": tracker.memory.cycles_without_advance, **_best(state),
        }
        self._emit("saturacao_avaliada", payload)
        if state.tipo == "discriminacao":
            return None  # o desfecho (várias compatíveis, experimento físico) já gerou o pedido próprio
        if state.saturacao == SATURACAO_SO_AVISO:
            motivo, options, question = CONTINUITY_REQUESTS["cobertura"]
            self._request(motivo, "cobertura", options, question)
            return None
        if state.saturacao == SATURACAO_CONFIRMADA:
            if self._mode == "auto":
                return StallStep(STEP_CLOSE, tracker.memory.interventions, tracker.memory.cycles_without_advance,
                                 needed, _best(state))
            motivo, options, question = _STAGNATION_REQUESTS["saturacao"]
            self._request(motivo, "saturacao", options, question)
            return None
        self._emit("intervencoes_esgotadas", {k: v for k, v in payload.items() if k != "resultado"})
        motivo, options, question = _STAGNATION_REQUESTS["intervencoes_esgotadas"]
        self._request(motivo, "intervencoes_esgotadas", options, question)
        return None


_REPORT_PREFIX = "estagnacao:"


def _best(state: ObjectiveState) -> dict[str, Any]:
    d = state.detalhes
    keys = ("melhor_valor", "melhor_hipotese_id", "erro_padrao", "replicas", "avanco_sem_incerteza")
    return {k: d[k] for k in keys if k in d}
