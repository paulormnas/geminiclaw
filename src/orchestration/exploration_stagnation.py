"""Estagnação e saturação na ``ExplorationSession`` (v18.7-exploration-limits, design §7).

``StagnationMixin`` liga ``StagnationPolicy`` à sessão: aplica as respostas do pesquisador aos pedidos de
estagnação/saturação, decide ao fim de cada ciclo, aciona o Curator em modo intervenção e devolve o motivo de parada
quando a sessão deve fechar (``saturacao`` no ``auto``; ``encerrada_pesquisador`` na resposta ``parar``).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Callable

from src.knowledge.suggestions import StallContext
from src.logger import get_logger
from src.orchestration.stagnation import STAGNATION_MOTIVES, STEP_CLOSE, STEP_INTERVENTION, StagnationPolicy

logger = get_logger(__name__)

STOP_SATURATION = "saturacao"
STOP_RESEARCHER = "encerrada_pesquisador"


class StagnationMixin:
    """Parte da ``ExplorationSession`` que cuida da estagnação (usa ``objective``, ``suggest`` e ``_emit``)."""

    _stagnation: StagnationPolicy | None = None
    _usage_fraction: Callable[[], float] | None = None

    def set_usage_fraction(self, fraction: Callable[[], float] | None) -> None:
        """Fração consumida do limite mais usado (tokens, tempo, custo); ``None`` vale 0 (modo sem limite)."""
        self._usage_fraction = fraction

    def _fraction(self) -> float:
        try:
            return float(self._usage_fraction()) if self._usage_fraction is not None else 0.0
        except Exception as exc:  # noqa: BLE001 - sem a leitura a paciência não cresce, nunca derruba a sessão
            logger.warning("Fração de uso indisponível", extra={"extra": {"erro": type(exc).__name__}})
            return 0.0

    @property
    def stagnation(self) -> StagnationPolicy:
        if self._stagnation is None:
            self._stagnation = StagnationPolicy(
                self.objective, mode=self.mode, emit=self._emit, requester=self._request_continuity,  # type: ignore[attr-defined]
                fraction=self._fraction,
            )
        return self._stagnation

    def session_progress(self) -> tuple[int, int]:
        """``(experimentos, resultados)`` da sessão no grafo, para o disjuntor (design §9.1; síncrono)."""
        store = self.store  # type: ignore[attr-defined]
        sessions = store.find_nodes("Sessao", {"sessao_id": self.ctx.session_id}, limit=2)  # type: ignore[attr-defined]
        experiments = results = 0
        for session in sessions:
            for exp in store.neighbors(session.id, ["EXECUTADO_EM"], direction="in", depth=1).nodes:
                if exp.label != "Experimento":
                    continue
                experiments += 1
                produced = store.neighbors(exp.id, ["PRODUZIU"], direction="out", depth=1)
                results += sum(1 for n in produced.nodes if n.label == "Resultado")
        return experiments, results

    def apply_stagnation_answers(self) -> str | None:
        """Aplica as respostas aos pedidos de estagnação, saturação e intervenções esgotadas (síncrono).

        ``continuar`` e ``orientar`` zeram as contagens (o texto de ``orientar`` já foi à caixa de entrada pelo
        terminal); ``parar`` devolve ``encerrada_pesquisador``. Cada pedido é consumido uma vez.
        """
        try:
            from src.gate.persistent_gate import session_gate

            gate = session_gate()
            answered = gate.answered_unconsumed(self._chain())  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - sem o gate a pesquisa segue
            logger.warning("Respostas de estagnação indisponíveis", extra={"extra": {"erro": type(exc).__name__}})
            return None
        stop: str | None = None
        for request in answered:
            if request.decisao != "decidir_continuidade" or request.motivo not in STAGNATION_MOTIVES:
                continue
            action = (request.resposta or {}).get("acao")
            if action in ("continuar", "orientar"):
                self.stagnation.reset()
            elif action == "parar":
                stop = STOP_RESEARCHER
            else:
                continue
            gate.mark_consumed(request.id)
        return stop

    async def manage_stagnation(self, state: Any) -> str | None:
        """Fim de ciclo que executou algo: aplica respostas, conta a estagnação e intervém ou satura.

        Args:
            state: ``ObjectiveState`` do ciclo (``None`` quando o ``Problema`` não tem objetivo avaliável).

        Returns:
            ``saturacao`` ou ``encerrada_pesquisador`` quando a sessão deve fechar; ``None`` para seguir.

        Raises:
            SuggestionError: O Curator falhou na intervenção (o laço fecha com ``erro``).
        """
        if state is None:
            return None
        answered_stop = await asyncio.to_thread(self.apply_stagnation_answers)
        if answered_stop is not None:
            return answered_stop
        step = await asyncio.to_thread(self.stagnation.observe, state, self.objective.criterion)  # type: ignore[attr-defined]
        if step is None:
            return None
        if step.kind == STEP_CLOSE:
            return STOP_SATURATION
        if step.kind == STEP_INTERVENTION:
            context = StallContext(
                step.intervencao, step.ciclos_sem_avanco, step.detalhes.get("melhor_valor"),
                step.detalhes.get("melhor_hipotese_id"),
            )
            fresh = await self.suggest(intervencao=context)  # type: ignore[attr-defined]
            self._emit(  # type: ignore[attr-defined]
                "estagnacao_intervencao",
                {
                    "intervencao": step.intervencao, "ciclos_sem_avanco": step.ciclos_sem_avanco,
                    "paciencia": step.paciencia, "sugestoes": fresh,
                },
            )
            await asyncio.to_thread(self.stagnation.request_stagnation, step)
        return None

    # ------------------------------------------------------------------ planos rejeitados (design §9.3)

    async def intervene_on_plan_rejections(self, issues: list[str], rejected: int) -> bool:
        """``ON_PLAN_REJECTIONS=explorar``: planos rejeitados em sequência são estagnação, não parada.

        Com intervenções disponíveis aciona o Curator com as últimas ``issues`` (evento ``estagnacao_intervencao``,
        ``origem = planos_rejeitados``); esgotadas, avalia como o passo 4 do design §7 (evento e pedido
        ``intervencoes_esgotadas``, sem bloquear). Com a estagnação desligada só devolve ``False``.

        Returns:
            ``True`` se o Curator foi acionado (o laço pede abordagem diferente ao Researcher).

        Raises:
            SuggestionError: O Curator falhou (o laço fecha com ``erro``).
        """
        from src import config

        if config.EXPLORATION_STALL_CYCLES <= 0:
            return False
        tracker = self.objective  # type: ignore[attr-defined]
        memory = tracker.memory
        details = dict(tracker.last_state.detalhes) if tracker.last_state is not None else {}
        if memory.interventions >= config.EXPLORATION_MAX_INTERVENTIONS:
            payload = {"origem": "planos_rejeitados", "planos_rejeitados": rejected}
            self._emit("saturacao_avaliada", {**payload, "resultado": "nao_avaliavel"})  # type: ignore[attr-defined]
            self._emit("intervencoes_esgotadas", payload)  # type: ignore[attr-defined]
            from src.orchestration.stagnation import request_exhausted

            await asyncio.to_thread(request_exhausted, self._request_continuity)  # type: ignore[attr-defined]
            return False
        number = memory.interventions + 1
        tracker.memory = replace(memory, interventions=number, cycles_without_advance=0)
        context = StallContext(
            number, memory.cycles_without_advance, details.get("melhor_valor"), details.get("melhor_hipotese_id"),
            tuple(issues),
        )
        fresh = await self.suggest(intervencao=context)  # type: ignore[attr-defined]
        self._emit(  # type: ignore[attr-defined]
            "estagnacao_intervencao",
            {"intervencao": number, "origem": "planos_rejeitados", "planos_rejeitados": rejected, "sugestoes": fresh},
        )
        return True

    def request_plan_rejections(self, issues: list[str], rejected: int) -> None:
        """``ON_PLAN_REJECTIONS=parar`` no ``assisted``/``semi``: pedido ``planos_rejeitados`` com as últimas issues."""
        from src.utils.display_text import sanitize_line

        shown = "; ".join(sanitize_line(i, 160) for i in issues[:3]) or "sem detalhe"
        self._request_continuity(  # type: ignore[attr-defined]
            "planos_rejeitados", "planos_rejeitados", ("continuar", "orientar", "parar"),
            f"O Validator rejeitou {rejected} planos seguidos ({shown}). Continuar, orientar ou parar?",
        )

    def plan_rejection_answer(self) -> str | None:
        """Resposta ao pedido ``planos_rejeitados``: ``continuar`` (também ``orientar``), ``parar`` ou ``None``."""
        try:
            from src.gate.persistent_gate import session_gate

            gate = session_gate()
            answered = gate.answered_unconsumed(self._chain())  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Respostas indisponíveis", extra={"extra": {"erro": type(exc).__name__}})
            return None
        for request in answered:
            if request.decisao != "decidir_continuidade" or request.motivo != "planos_rejeitados":
                continue
            action = (request.resposta or {}).get("acao")
            if action in ("continuar", "orientar", "parar"):
                gate.mark_consumed(request.id)
                return "parar" if action == "parar" else "continuar"
        return None
