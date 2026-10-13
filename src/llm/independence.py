"""Conferência da independência do julgamento durante a sessão (ADR 020; v18.6-validator-independence).

A resolução inicial vive em ``src/llm/routing.py``. Este módulo guarda o **estado da sessão**
(:class:`JudgeIndependenceGuard`) e aplica o procedimento único de conferência do ADR 020 §3 nos pontos de
despacho: dica de plano, subtarefa de ``base``/``reviewer``, modelo de reserva do 429 e retomada.

Regra R1: nenhum juiz (``validator``, ``reviewer``) usa modelo da mesma família de um julgado (``developer``,
``base``) em uso na sessão. O juiz nunca muda de modelo no meio da sessão: uma dica que cairia na família do juiz é
descartada.

Os pontos de conferência de ``reviewer`` e ``base`` (``check_dispatch``, ``_UNUSED_UNTIL_DISPATCH``) ficam isolados
neste módulo: se o papel ``reviewer`` for removido (mudança ``v18.6-remove-unused-agents``), basta apagá-los.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Collection, Mapping

from src.llm.availability import Availability
from src.llm.catalog import Catalog
from src.llm.routing import (
    JUDGE_MODE_OFF,
    JUDGE_MODE_REQUIRED,
    JUDGE_ROLES,
    JUDGED_ROLES,
    MOTIVO_MESMA_FAMILIA,
    NoEligibleModelError,
    RoleResolution,
    RoutingError,
    _suggestion,
    find_alternative,
)
from src.logger import get_logger

logger = get_logger(__name__)

EVENT_TYPE = "independencia_julgamento"
DECISAO_ACEITO = "aceito"
DECISAO_SUBSTITUIDO = "substituido"
DECISAO_REJEITADO = "rejeitado"
DECISAO_ACEITO_PREFERRED = "aceito_preferred"

# Papéis de despacho conferidos contra os modelos em uso; fora do par validator/developer, só entram na conta
# depois de despachados (muitas sessões nunca os usam).
_UNUSED_UNTIL_DISPATCH: tuple[str, ...] = ("reviewer", "base")


class JudgeIndependenceError(RoutingError):
    """A subtarefa não pode rodar sem violar R1 em modo ``required`` (a sessão continua)."""

    def __init__(self, papel: str, modelo: str, familia: str, sugestao: str):
        self.papel = papel
        self.modelo = modelo
        self.familia = familia
        self.sugestao = sugestao
        super().__init__(
            f"O papel '{papel}' não pode usar '{modelo}' (família '{familia}'): {MOTIVO_MESMA_FAMILIA}. {sugestao}"
        )


class JudgeIndependenceGuard:
    """Estado da conferência de independência de uma sessão (mutável; seguro entre threads)."""

    def __init__(
        self,
        catalogo: Catalog,
        papeis: Mapping[str, RoleResolution],
        disponiveis: Mapping[str, Availability],
        politica: str,
        modo: str,
        origem_modo: str,
        routing_mode: str = "flexible",
    ):
        self.catalogo = catalogo
        self.papeis = papeis
        self.disponiveis = disponiveis
        self.politica = politica
        self.modo = modo
        self.origem_modo = origem_modo
        self.routing_mode = routing_mode
        self.eventos: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._sink: Callable[[dict[str, Any]], None] | None = None
        # Modelos efetivos em uso por papel: o par validator/developer desde o início.
        self._efetivos: dict[str, set[str]] = {
            role: {papeis[role].id} for role in ("validator", "developer") if role in papeis
        }
        self._aprovados: set[tuple[str, str]] = set()
        self._dicas: dict[tuple[str, str], str] = {}
        self._familias_retomada: set[str] = set()
        self._conflitos_aceitos = 0

    # ----------------------------------------------------------------- famílias

    def familia(self, model_id: str) -> str | None:
        entry = self.catalogo.modelos.get(model_id)
        return entry.familia_modelo if entry is not None else None

    def origem_familia(self, model_id: str) -> str:
        entry = self.catalogo.modelos.get(model_id)
        return entry.origem if entry is not None else "desconhecida"

    @property
    def ativo(self) -> bool:
        return self.modo != JUDGE_MODE_OFF

    def _familias_em_uso(self, papeis: Collection[str]) -> set[str]:
        out: set[str] = set()
        for role in papeis:
            for model_id in self._efetivos.get(role, ()):
                fam = self.familia(model_id)
                if fam:
                    out.add(fam)
        return out

    def _opostas(self, papel: str) -> set[str]:
        """Famílias do grupo oposto em uso (para um juiz, as dos julgados; para um julgado, as dos juízes)."""
        if papel in JUDGE_ROLES:
            return self._familias_em_uso(JUDGED_ROLES) | self._familias_retomada
        return self._familias_em_uso(JUDGE_ROLES)

    # ----------------------------------------------------------------- registro

    def set_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        self._sink = sink

    def _emitir(
        self, papel: str, model_id: str, decisao: str, motivo: str | None, subtarefa: str | None
    ) -> dict[str, Any]:
        event = {
            "tipo": EVENT_TYPE,
            "subtarefa": subtarefa,
            "papel": papel,
            "modelo": model_id,
            "familia": self.familia(model_id),
            "origem_familia": self.origem_familia(model_id),
            "decisao": decisao,
            "motivo": motivo,
        }
        with self._lock:
            self.eventos.append(event)
        if self._sink is not None:
            try:
                self._sink(event)
            except Exception as exc:  # noqa: BLE001 — registro nunca derruba a chamada
                logger.warning("Evento de independência não registrado", extra={"erro": type(exc).__name__})
        return event

    def _aceitar_conflito(self, papel: str, model_id: str, subtarefa: str | None, contexto: str) -> None:
        self._conflitos_aceitos += 1
        logger.warning(
            f"Independência do julgamento não atendida ({contexto}): modo preferred segue com o modelo em conflito",
            extra={"role": papel, "modelo": model_id, "familia": self.familia(model_id)},
        )
        self._emitir(papel, model_id, DECISAO_ACEITO_PREFERRED, MOTIVO_MESMA_FAMILIA, subtarefa)

    # ------------------------------------------------------------ inicialização

    @property
    def atendida(self) -> bool:
        """``False`` se validator e developer coincidem em família ou se o modo ``preferred`` aceitou um conflito."""
        validator, developer = self._par()
        if validator is None or developer is None:
            return True
        return self.familia(validator) != self.familia(developer) and self._conflitos_aceitos == 0

    def _par(self) -> tuple[str | None, str | None]:
        validator = self.papeis.get("validator")
        developer = self.papeis.get("developer")
        return (validator.id if validator else None, developer.id if developer else None)

    def registro(self) -> dict[str, Any]:
        """Conteúdo de ``payload["independencia_julgamento"]`` (ADR 020 §6; sem segredos)."""
        validator, developer = self._par()

        def entry(model_id: str | None) -> dict[str, Any] | None:
            if model_id is None:
                return None
            return {
                "modelo": model_id,
                "familia": self.familia(model_id),
                "origem_familia": self.origem_familia(model_id),
            }

        return {
            "modo": self.modo,
            "origem_modo": self.origem_modo,
            "validator": entry(validator),
            "developer": entry(developer),
            "atendida": self.atendida,
        }

    def summary_line(self) -> str:
        """Linha do banner, do relatório final e das métricas (ADR 020 §6)."""
        validator, developer = self._par()
        if validator is None or developer is None:
            return "Julgamento: papéis validator/developer ausentes do mapa"
        fv, fd = self.familia(validator), self.familia(developer)
        if self.modo == JUDGE_MODE_OFF:
            return f"Julgamento: conferência desligada (off): {fv} (validator), {fd} (developer)"
        if self.atendida:
            return f"Julgamento: {fv} (validator) ≠ {fd} (developer)"
        return (
            f"⚠ Julgamento: independência NÃO atendida (modo {self.modo}): "
            f"{fv} (validator), {fd} (developer)"
        )

    def metricas(self) -> dict[str, Any]:
        """Resumo para as métricas de operação."""
        rejeicoes = sum(1 for e in self.eventos if e["decisao"] == DECISAO_REJEITADO)
        return {
            "independencia_julgamento_atendida": self.atendida,
            "independencia_julgamento_rejeicoes": rejeicoes,
            "independencia_julgamento_modo": self.modo,
        }

    # ----------------------------------------------------------------- dica

    def check_hint(self, papel: str, resolved_id: str, hint_id: str, subtarefa: str | None) -> str:
        """Confere uma dica de plano já validada pelo roteador; devolve o modelo a usar.

        Em conflito a dica é rejeitada (volta ao modelo resolvido do papel) em qualquer modo, porque o juiz nunca
        troca de modelo na sessão e a alternativa (o modelo resolvido) sempre existe.
        """
        if not self.ativo or (papel not in JUDGE_ROLES and papel not in JUDGED_ROLES):
            return hint_id
        key = (papel, hint_id)
        if key in self._aprovados:
            return hint_id
        if key in self._dicas:
            return self._dicas[key]
        familia = self.familia(hint_id)
        if familia is not None and familia in self._opostas(papel):
            logger.warning(
                "Dica de modelo do plano rejeitada: mesma família do outro grupo do julgamento",
                extra={"hint": hint_id, "role": papel, "familia": familia},
            )
            self._emitir(papel, hint_id, DECISAO_REJEITADO, MOTIVO_MESMA_FAMILIA, subtarefa)
            self._dicas[key] = resolved_id
            return resolved_id
        self._emitir(papel, hint_id, DECISAO_ACEITO, None, subtarefa)
        self._efetivos.setdefault(papel, set()).add(hint_id)
        self._aprovados.add(key)
        return hint_id

    def is_approved(self, papel: str, model_id: str) -> bool:
        return (papel, model_id) in self._aprovados

    # ------------------------------------------------- despacho de reviewer/base

    def check_dispatch(
        self, papel: str, model_id: str, subtarefa: str | None, *, pin_fixo: bool = False
    ) -> str:
        """Confere o despacho de uma subtarefa para ``reviewer`` ou ``base`` (ADR 020 §4).

        Em conflito procura o próximo modelo elegível de outra família na preferência do papel (``substituido``);
        sem nenhum, ``required`` levanta :class:`JudgeIndependenceError` (só a subtarefa falha) e ``preferred``
        segue com aviso. ``pin_fixo``: pin em ``strict`` nunca é trocado.

        Raises:
            JudgeIndependenceError: Conflito sem alternativa em ``required``.
        """
        if not self.ativo or papel not in _UNUSED_UNTIL_DISPATCH:
            return model_id
        if (papel, model_id) in self._aprovados:
            return model_id
        familia = self.familia(model_id)
        opostas = self._opostas(papel)
        if familia is None or familia not in opostas:
            self._emitir(papel, model_id, DECISAO_ACEITO, None, subtarefa)
            self._efetivos.setdefault(papel, set()).add(model_id)
            self._aprovados.add((papel, model_id))
            return model_id
        alternativa = None
        if not pin_fixo:
            alternativa = find_alternative(
                papel, self.catalogo, self.disponiveis, self.politica, opostas, excluir=(model_id,)
            )
        if alternativa is not None:
            self._emitir(papel, alternativa.id, DECISAO_SUBSTITUIDO, MOTIVO_MESMA_FAMILIA, subtarefa)
            self._efetivos.setdefault(papel, set()).add(alternativa.id)
            self._aprovados.add((papel, alternativa.id))
            return alternativa.id
        if self.modo == JUDGE_MODE_REQUIRED:
            self._emitir(papel, model_id, DECISAO_REJEITADO, MOTIVO_MESMA_FAMILIA, subtarefa)
            raise JudgeIndependenceError(
                papel, model_id, familia,
                _suggestion(self.politica, ((model_id, MOTIVO_MESMA_FAMILIA),)),
            )
        self._aceitar_conflito(papel, model_id, subtarefa, "despacho")
        self._efetivos.setdefault(papel, set()).add(model_id)
        self._aprovados.add((papel, model_id))
        return model_id

    # --------------------------------------------------------- reserva do 429

    def check_fallback(self, papeis: Collection[str], primary_id: str, fallback_id: str) -> bool:
        """Confere o modelo de reserva do 429 para os papéis que usam ``primary_id``; ``True`` se pode ser usado."""
        if not self.ativo:
            return True
        for papel in papeis:
            if papel not in JUDGE_ROLES and papel not in JUDGED_ROLES:
                continue
            familia = self.familia(fallback_id)
            if familia is None or familia not in self._opostas(papel):
                continue
            if self.modo == JUDGE_MODE_REQUIRED:
                logger.warning(
                    "Reserva do 429 rejeitada: mesma família do outro grupo do julgamento",
                    extra={"fallback": fallback_id, "role": papel, "familia": familia},
                )
                self._emitir(papel, fallback_id, DECISAO_REJEITADO, MOTIVO_MESMA_FAMILIA, None)
                return False
            self._aceitar_conflito(papel, fallback_id, None, "reserva do 429")
        return True

    # ---------------------------------------------------------------- retomada

    def verificar_retomada(self, familias_julgadas: Collection[str]) -> None:
        """Confere o juiz resolvido agora contra as famílias julgadas da sessão original (ADR 020 §4).

        Raises:
            NoEligibleModelError: ``required`` e o ``validator`` resolvido coincide com uma família julgada.
        """
        if not self.ativo:
            return
        self._familias_retomada = {f for f in familias_julgadas if f}
        for papel in JUDGE_ROLES:
            res = self.papeis.get(papel)
            if res is None:
                continue
            familia = self.familia(res.id)
            if familia is None or familia not in self._familias_retomada:
                continue
            descartados = ((res.id, MOTIVO_MESMA_FAMILIA),)
            if papel == "validator" and self.modo == JUDGE_MODE_REQUIRED:
                raise NoEligibleModelError(
                    papel, self.politica, descartados, _suggestion(self.politica, descartados)
                )
            if papel == "validator":
                self._aceitar_conflito(papel, res.id, None, "retomada")
            else:
                logger.warning(
                    "Reviewer retomado na família de um modelo julgado da sessão original; conferido no despacho",
                    extra={"role": papel, "modelo": res.id},
                )


def judged_families_from_session(payload: Mapping[str, Any]) -> set[str]:
    """Famílias julgadas registradas no payload de uma sessão (registro inicial e eventos aceitos)."""
    out: set[str] = set()
    record = payload.get("independencia_julgamento")
    if isinstance(record, Mapping):
        developer = record.get("developer")
        if isinstance(developer, Mapping) and developer.get("familia"):
            out.add(str(developer["familia"]))
    for event in payload.get("eventos_independencia_julgamento") or []:
        if (
            isinstance(event, Mapping)
            and event.get("papel") in JUDGED_ROLES
            and event.get("decisao") in (DECISAO_ACEITO, DECISAO_SUBSTITUIDO, DECISAO_ACEITO_PREFERRED)
            and event.get("familia")
        ):
            out.add(str(event["familia"]))
    return out


__all__ = [
    "DECISAO_ACEITO",
    "DECISAO_ACEITO_PREFERRED",
    "DECISAO_REJEITADO",
    "DECISAO_SUBSTITUIDO",
    "EVENT_TYPE",
    "JudgeIndependenceError",
    "JudgeIndependenceGuard",
    "judged_families_from_session",
]
