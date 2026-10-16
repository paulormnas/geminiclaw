"""Troca do modelo de um papel dentro da sessão (v18.7-benchmark-fixes, design §1.7).

Com ``LLM_ROUTING=strict`` e ``ON_MODEL_VERSION_CHANGE=retomar``, quando um modelo deixa de informar a versão o papel
passa ao próximo modelo da lista ``preferencia`` do papel no catálogo que seja elegível: requisitos e política
(ADR 017), família do Validator diferente da do Developer (ADR 020) e localidade (ADR 019: o substituto não pode ser
menos restritivo que o modelo trocado). Papel com pin do pesquisador não é trocado: ele escolheu o modelo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.llm.availability import Availability
from src.llm.routing import RoleResolution, is_eligible
from src.logger import get_logger

if TYPE_CHECKING:
    from src.llm.session import SessionRouting

logger = get_logger(__name__)

REASON_UNKNOWN_VERSION = "versao_desconhecida"
ORIGIN_PREFERENCE = "preferencia"


def _locality_ok(current_id: str, candidate_id: str, routing: "SessionRouting") -> bool:
    """O substituto não envia dados a um lugar pior: nó local fica local e quem aceitava dados brutos continua.

    Quem aceitava dados brutos continua aceitando; o modelo local não passa a um modelo fora do nó.
    """
    current = routing.catalogo.modelos.get(current_id)
    candidate = routing.catalogo.modelos[candidate_id]
    if current is None:
        return True
    if current.localidade == "no_no" and candidate.localidade != "no_no":
        return False
    return candidate.aceita_dados_brutos or not current.aceita_dados_brutos


def find_substitute(routing: "SessionRouting", role: str) -> str | None:
    """Próximo modelo elegível da ``preferencia`` do papel depois do atual, ou ``None``."""
    current = routing.papeis.get(role)
    if current is None or current.origem != ORIGIN_PREFERENCE:
        return None
    spec = routing.catalogo.papeis[role]
    order = list(spec.preferencia)
    after = order[order.index(current.id) + 1:] if current.id in order else order
    for candidate_id in after:
        entry = routing.catalogo.modelos.get(candidate_id)
        if entry is None or not routing.disponiveis.get(candidate_id, Availability(False)).ok:
            continue
        if not is_eligible(entry, spec.requisitos, routing.politica):
            continue
        if not _locality_ok(current.id, candidate_id, routing):
            logger.info("Substituto descartado pela localidade", extra={"papel": role, "modelo": candidate_id})
            continue
        if routing.guard is not None and not routing.guard.check_fallback([role], current.id, candidate_id):
            continue
        return candidate_id
    return None


def replace_role_model(routing: "SessionRouting", role: str, new_id: str, reason: str) -> RoleResolution:
    """Passa o ``role`` ao modelo ``new_id`` no mapa da sessão (o mesmo dicionário lido pelo roteador e pelo guard)."""
    old = routing.papeis[role]
    entry = routing.catalogo.modelos[new_id]
    new = RoleResolution(
        papel=old.papel,
        id=new_id,
        trust=entry.trust,
        origem=old.origem,
        descartados=(*old.descartados, (old.id, reason)),
        desempate=old.desempate,
    )
    routing.papeis[role] = new  # type: ignore[index]  # o mapa é um dict; só muda aqui, num ponto de verificação
    return new
