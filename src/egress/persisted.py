"""Marca de contaminação persistida com o texto (v18.5-egress-gate, design §7).

Todo texto produzido por modelo que o orquestrador guarda para uso futuro em prompt leva a marca junto: o resumo de
subtarefa no checkpoint (``resultado_marca``), o resultado em ``SubtaskOutput.tainted`` e as memórias de longo prazo
(tag ``egress:tainted``). Na leitura o trecho é reconstruído com a marca gravada; na **retomada com outro catálogo** a
marca não é recalculada: vale a declarada na produção, e o filtro é aplicado conforme o destino novo.

Texto sem marca (legado) recebe ``tainted=True`` se o ``allocation_profile`` da sessão que o produziu tem algum papel
com ``aceita_dados_brutos``; sem perfil, ``False`` (textos anteriores à V18.5 não são reclassificados).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from src.egress.fragments import ORIGIN_INSTRUCAO_VALUE, mark_tainted

TAINT_TAG = "egress:tainted"
MARK_ORIGIN_MAX = 32
MARK_PRODUCER_MAX = 64


def resumo_marca(tainted: bool, produced_by: str | None, origem: str = ORIGIN_INSTRUCAO_VALUE) -> dict[str, Any]:
    """Marca gravada junto ao texto: ``{"origem", "tainted", "produzido_por"}``."""
    return {"origem": origem, "tainted": bool(tainted), "produzido_por": (produced_by or "")[:MARK_PRODUCER_MAX]}


def read_mark(data: object) -> bool | None:
    """``tainted`` de uma marca gravada; ``None`` se não há marca. Marca malformada é um erro (não é adivinhada).

    Raises:
        ValueError: Marca presente mas fora do formato.
    """
    if data is None:
        return None
    if not isinstance(data, Mapping):
        raise ValueError("marca de contaminação inválida: esperado um objeto.")
    tainted = data.get("tainted")
    origem = data.get("origem", ORIGIN_INSTRUCAO_VALUE)
    produced_by = data.get("produzido_por", "")
    if (
        not isinstance(tainted, bool)
        or not isinstance(origem, str)
        or len(origem) > MARK_ORIGIN_MAX
        or not isinstance(produced_by, str)
        or len(produced_by) > MARK_PRODUCER_MAX
    ):
        raise ValueError("marca de contaminação inválida: campos 'origem', 'tainted' e 'produzido_por'.")
    return tainted


def legacy_tainted(profile: object) -> bool:
    """Regra de texto sem marca: contaminado se o perfil de alocação da sessão produtora tem papel com dados brutos."""
    if not isinstance(profile, Mapping):
        return False
    roles = profile.get("papeis")
    if not isinstance(roles, Mapping):
        return False
    return any(isinstance(e, Mapping) and e.get("aceita_dados_brutos") is True for e in roles.values())


def resumed_text_tainted(state: Any, source_session_id: str, session_manager: Any) -> bool:
    """Marca do resumo de uma subtarefa retomada: a gravada no checkpoint, senão a regra de texto legado.

    A marca gravada vale mesmo que o catálogo da sessão nova seja outro (design §7).
    """
    try:
        recorded = read_mark(getattr(state, "resultado_marca", None))
    except ValueError:
        recorded = True  # marca ilegível: o lado seguro
    if recorded is not None:
        return recorded
    try:
        session = session_manager.get(source_session_id)
        profile = session.payload.get("allocation_profile") if session is not None else None
    except Exception:  # noqa: BLE001 — sem a sessão produtora, não há perfil: regra do texto sem perfil
        profile = None
    return legacy_tainted(profile)


def tag_text(text: str, tainted: bool | None) -> str:
    """Texto com a marca em linha quando contaminado; ``None`` (sem marca) segue a regra legado do perfil corrente."""
    if tainted is None:
        from src.egress.gate import any_role_raw

        tainted = any_role_raw()
    return mark_tainted(text) if tainted else text


def with_taint_tag(tags: Iterable[str] | None, tainted: bool) -> list[str]:
    """Tags da memória de longo prazo com ``egress:tainted`` (acrescentada quando contaminada, removida senão)."""
    cleaned = [t for t in (tags or []) if t != TAINT_TAG]
    return [*cleaned, TAINT_TAG] if tainted else cleaned


def tags_tainted(tags: Iterable[str] | None) -> bool:
    """True se as tags da memória carregam a marca de contaminação."""
    return TAINT_TAG in (tags or [])
