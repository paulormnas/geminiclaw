"""Esgotamento de cota ou de teto de gasto do provedor, distinto de limite de taxa (v18.7-benchmark-fixes, design §1).

Um 429 transitório (limite por minuto) é retentado; o esgotamento da cota ou do gasto mensal não se recupera na sessão
e retentar só gasta tempo. Cada provedor de nuvem classifica o erro pelos marcadores de ``config`` e levanta
:class:`ProviderQuotaExhausted`; o registro por sessão faz o laço autônomo fechar com ``limite_cota_provedor``
(``src/orchestration/usage.py``).
"""

from __future__ import annotations

import re
import threading

from src import config
from src.llm.session_context import resolve_execution_id, resolve_session_id
from src.logger import get_logger
from src.utils.agent_context import get_agent_context_optional

logger = get_logger(__name__)

DETAIL_MAX_CHARS = 300
QUOTA_STATUS_CODES = frozenset({400, 402, 403, 429})
EVENT_TYPE = "cota_provedor_esgotada"

_SECRET_RE = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,})")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")

_lock = threading.Lock()
_recorded: dict[str, "ProviderQuotaExhausted"] = {}


class ProviderQuotaExhausted(RuntimeError):
    """O provedor recusou a chamada por cota ou teto de gasto esgotado (não recuperável na sessão)."""

    def __init__(self, provider: str, model: str, status_code: int | None, detail: str) -> None:
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.detail = clean_detail(detail)
        super().__init__(f"cota ou teto de gasto esgotado no provedor {provider} (modelo {model}): {self.detail}")


def clean_detail(detail: object) -> str:
    """Mensagem do provedor em uma linha, sem chaves de API, truncada em 300 caracteres (nunca cabeçalhos)."""
    text = _CONTROL_RE.sub(" ", str(detail))
    text = _SECRET_RE.sub("[segredo omitido]", " ".join(text.split()))
    return text[:DETAIL_MAX_CHARS]


def markers_for(provider: str) -> tuple[str, ...]:
    """Marcadores de esgotamento do provedor (``LLM_QUOTA_MARKERS_<PROVEDOR>``), em minúsculas."""
    return tuple(config.QUOTA_MARKERS.get(provider, ()))


def is_quota_exhausted(provider: str, status_code: int | None, message: str) -> bool:
    """True se o status é 429/400/402/403 e a mensagem contém um marcador do provedor (sem diferenciar caixa)."""
    if status_code not in QUOTA_STATUS_CODES:
        return False
    lowered = str(message).lower()
    return any(marker in lowered for marker in markers_for(provider))


def raise_if_quota_exhausted(provider: str, model: str, status_code: int | None, message: str) -> None:
    """Classifica o erro e, se for esgotamento de cota/gasto, registra para a sessão e levanta a exceção.

    Raises:
        ProviderQuotaExhausted: O erro é cota ou gasto esgotado.
    """
    if not is_quota_exhausted(provider, status_code, message):
        return
    exc = ProviderQuotaExhausted(provider, model, status_code, message)
    logger.error(
        "Cota ou teto de gasto esgotado no provedor",
        extra={"provider": provider, "model": model, "status": status_code, "detail": exc.detail},
    )
    record_quota_exhausted(exc)
    raise exc


def record_quota_exhausted(exc: ProviderQuotaExhausted) -> bool:
    """Guarda o esgotamento para a sessão corrente e grava o evento ``cota_provedor_esgotada`` (só o primeiro).

    Returns:
        True se este foi o primeiro registro da sessão. Nunca levanta.
    """
    execution_id = resolve_execution_id() or "unknown"
    with _lock:
        if execution_id in _recorded:
            return False
        _recorded[execution_id] = exc
    try:
        from src.observability.telemetry import get_telemetry

        ctx = get_agent_context_optional()
        payload = {"provedor": exc.provider, "modelo": exc.model, "status": exc.status_code, "detalhe": exc.detail}
        if ctx is not None:
            payload["papel"] = ctx.agent_id
        get_telemetry().record_agent_event(
            execution_id=execution_id,
            session_id=resolve_session_id(execution_id) or execution_id,
            agent_id=f"llm_provider:{exc.provider}",
            event_type=EVENT_TYPE,
            payload=payload,
        )
    except Exception as err:  # noqa: BLE001 - o registro do evento nunca interrompe a parada
        logger.warning("Falha ao registrar o evento cota_provedor_esgotada", extra={"error": str(err)})
    return True


def quota_stop_for(execution_id: str) -> ProviderQuotaExhausted | None:
    """O esgotamento registrado para a sessão, ou ``None``."""
    with _lock:
        return _recorded.get(execution_id)


def clear_quota_stop(execution_id: str) -> None:
    """Esquece o registro da sessão (início de uma nova sessão no mesmo processo)."""
    with _lock:
        _recorded.pop(execution_id, None)
