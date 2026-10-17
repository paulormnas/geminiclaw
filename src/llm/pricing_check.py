"""Verificação de preço dos modelos alcançáveis da sessão (v18.7-exploration-limits, design §3.3).

Fora do modo sem limite, o limite de custo só vale se todo modelo que o roteamento pode usar tem preço: modelo
``no_no`` (local) custa 0; modelo ``fora_do_no`` sem preço faria o custo ficar subestimado em silêncio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.llm.catalog import split_model_id
from src.llm.pricing import get_price
from src.utils.configuration_error import ConfigurationError

if TYPE_CHECKING:
    from src.llm.session import SessionRouting

LOCAL = "no_no"


def reachable_models(routing: "SessionRouting") -> list[str]:
    """Ids ``provedor/modelo`` da alocação por papel e dos modelos de reserva aceitos, sem repetição."""
    ids: list[str] = []
    for resolution in routing.papeis.values():
        ids.append(resolution.id)
        fallback = routing.fallback_for(resolution.id)
        if fallback is not None:
            ids.append(f"{split_model_id(resolution.id)[0]}/{fallback}")
    return list(dict.fromkeys(ids))


def is_local(routing: "SessionRouting", model_id: str) -> bool:
    """True se o modelo está no catálogo com localidade ``no_no`` (custo 0 por definição)."""
    entry = routing.catalogo.modelos.get(model_id)
    return entry is not None and entry.localidade == LOCAL


def unpriced_models(routing: "SessionRouting") -> list[str]:
    """Modelos alcançáveis, não locais e sem preço conhecido."""
    return [
        model_id
        for model_id in reachable_models(routing)
        if not is_local(routing, model_id) and get_price(*split_model_id(model_id)) is None
    ]


def require_priced_models(routing: "SessionRouting", *, unlimited: bool) -> None:
    """Impede o início da sessão com limite de custo quando algum modelo alcançável não tem preço.

    Raises:
        ConfigurationError: Há modelo não local sem preço; a mensagem cita cada modelo e ``LLM_PRICING_OVERRIDES``.
    """
    if unlimited:
        return
    missing = unpriced_models(routing)
    if missing:
        raise ConfigurationError(
            "A sessão não iniciou: o limite de custo exige preço de todo modelo alcançável, e estes não o têm: "
            + ", ".join(missing)
            + ". Declare o preço em LLM_PRICING_OVERRIDES (JSON provedor/modelo -> [entrada, saida, cache]), "
            "troque o modelo ou use o modo sem limite."
        )
