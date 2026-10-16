"""Utilitários de retentativa compartilhados pelos provedores LLM (Roadmap V18 /
Spec `usage-limits`).

Cada provedor (`src/llm/providers/*.py`) usa estas funções para decidir se um
erro é transitório (conexão/timeout/429/5xx — vale a pena retentar) e para
emitir o evento ``connection_retry`` na telemetria a cada retentativa, insumo
para `src.orchestration.usage.UsageTracker` aplicar `SESSION_MAX_CONNECTION_RETRIES` como
condição de parada da sessão.
"""

from __future__ import annotations

import os

from src.llm.session_context import resolve_execution_id, resolve_session_id
from src.logger import get_logger
from src.utils.agent_context import get_agent_context_optional

logger = get_logger(__name__)

# Backoff entre tentativas extras (após a primeira falha). ~3.5s de espera total
# no pior caso — evita travar o event loop do orquestrador no Pi 5 esperando um
# servidor externo indisponível.
RETRY_BACKOFFS_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0)

_RETRYABLE_STATUS_MARKERS = ("429", "500", "502", "503", "504")


def is_retryable_status(status_code: int | None) -> bool:
    """True se o código de status HTTP é transitório (429 ou 5xx).

    Args:
        status_code: Código de status HTTP, ou None se não aplicável.
    """
    if status_code is None:
        return False
    return status_code == 429 or status_code >= 500


def is_retryable_error(exc: BaseException) -> bool:
    """Heurística para decidir se uma exceção representa um erro transitório
    de conexão (vale a pena retentar) — timeout, falha de rede, ou uma
    mensagem que menciona 429/5xx.

    Args:
        exc: Exceção capturada na chamada ao provedor.

    Returns:
        True se a chamada deve ser retentada.
    """
    from src.llm.quota import ProviderQuotaExhausted

    if isinstance(exc, ProviderQuotaExhausted):  # a mensagem contém "429", mas cota esgotada não se recupera
        return False
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    message = str(exc)
    return any(marker in message for marker in _RETRYABLE_STATUS_MARKERS)


def emit_connection_retry(component: str, error_message: str) -> None:
    """Emite o evento ``connection_retry`` na telemetria da sessão corrente.

    Lê o contexto da sessão pela mesma resolução de ``src/llm/agent_loop.py``
    (``src/llm/session_context.py``): ``AgentContext`` corrente, vínculo do
    orquestrador (``bound_execution_id``) e variáveis de ambiente. Sem nenhuma
    fonte, usa ``unknown`` — o evento ainda é registrado, com contexto menos preciso.

    Nunca lança: falhas ao registrar telemetria não devem interromper a
    retentativa em curso.

    Args:
        component: Componente de origem (ex: ``"llm_provider:google"``).
        error_message: Descrição resumida do erro que motivou a retentativa.
    """
    try:
        from src.observability.telemetry import get_telemetry

        # v18.7-benchmark-fixes: o contexto vem do AgentContext (agentes em processo), do vínculo do orquestrador e só
        # então do ambiente; antes, só do ambiente, e o contador lido pelo UsageTracker ficava em zero.
        ctx = get_agent_context_optional()
        execution_id = resolve_execution_id() or "unknown"
        session_id = resolve_session_id(execution_id) or "unknown"
        agent_id = ctx.agent_id if ctx is not None else os.environ.get("AGENT_ID", "unknown")
        task_name = (ctx.task_name if ctx is not None else os.environ.get("TASK_NAME")) or None

        get_telemetry().record_connection_retry(
            execution_id=execution_id,
            session_id=session_id,
            agent_id=agent_id,
            component=component,
            error_message=error_message,
            task_name=task_name,
        )
    except Exception as e:
        logger.warning(
            "Falha ao registrar evento connection_retry na telemetria",
            extra={"component": component, "error": str(e)},
        )
