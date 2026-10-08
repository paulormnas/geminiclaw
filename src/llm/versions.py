"""Versão efetiva dos modelos e detecção de troca dentro da sessão (v18.5-model-catalog-locality, design §4).

``versao_efetiva`` é o que o provedor **informa** ter servido (``response.model_version`` no Google,
``model``/``system_fingerprint`` nos servidores compatíveis, ``digest`` no Ollama). Quando o provedor não informa, o
valor é o literal ``desconhecida``: nunca se inventa a versão a partir do nome pedido. A garantia é "registrado
como informado", não "imutável": a versão pode ser só um alias estável do provedor.

O :class:`VersionTracker` guarda a última versão por ``provedor/modelo`` numa sessão, acumula os eventos de troca e,
em ``LLM_ROUTING=strict``, marca ``parada_pendente`` para o ``AutonomousLoop`` fechar a sessão no próximo ponto de
verificação de limites.
"""

from __future__ import annotations

import threading
from typing import Any

from src.logger import get_logger

logger = get_logger(__name__)

UNKNOWN_VERSION = "desconhecida"
STOP_VERSION = "versao_modelo"
EVENT_VERSION_CHANGED = "versao_modelo_alterada"
_MAX_VERSION_LENGTH = 200


def normalize_version(value: Any) -> str:
    """Texto não vazio vira a versão (sem quebras de linha, truncado); qualquer outra coisa vira ``desconhecida``."""
    if not isinstance(value, str):
        return UNKNOWN_VERSION
    cleaned = " ".join(value.split())[:_MAX_VERSION_LENGTH]
    return cleaned or UNKNOWN_VERSION


def compose_compatible_version(model: Any, fingerprint: Any) -> str:
    """Versão de um servidor compatível: ``<model>@<system_fingerprint>`` ou só ``<model>``."""
    base = normalize_version(model)
    if base == UNKNOWN_VERSION:
        return UNKNOWN_VERSION
    finger = normalize_version(fingerprint)
    return base if finger == UNKNOWN_VERSION else f"{base}@{finger}"


class VersionTracker:
    """Última versão efetiva por ``provedor/modelo`` e eventos de troca de uma sessão."""

    def __init__(self, strict: bool = False) -> None:
        self.strict = strict
        self._lock = threading.Lock()
        self._versions: dict[str, str] = {}
        self._events: list[dict[str, Any]] = []
        self._pending: str | None = None
        self._on_event: Any = None
        self._on_change: Any = None

    def set_event_sink(self, sink: Any) -> None:
        """Registra ``sink(evento: dict)``, chamado a cada troca de versão (telemetria e payload da sessão)."""
        self._on_event = sink

    def set_change_sink(self, sink: Any) -> None:
        """Registra ``sink(provedor_modelo, versao)``, chamado quando a versão guardada muda (inclusive a primeira)."""
        self._on_change = sink

    @property
    def parada_pendente(self) -> str | None:
        """``"versao_modelo"`` quando, em ``strict``, a sessão deve fechar no próximo ponto de verificação."""
        return self._pending

    @property
    def eventos(self) -> list[dict[str, Any]]:
        return list(self._events)

    def current(self, model_id: str) -> str:
        """Última versão conhecida do modelo, ou ``desconhecida`` se nunca observada."""
        return self._versions.get(model_id, UNKNOWN_VERSION)

    def seed(self, model_id: str, version: Any) -> None:
        """Define a versão inicial (digest do Ollama no início da sessão), sem gerar evento."""
        with self._lock:
            self._versions[model_id] = normalize_version(version)

    def observe(self, model_id: str, version: Any, papeis: tuple[str, ...] = ()) -> dict[str, Any] | None:
        """Registra a versão observada numa chamada; devolve o evento se uma versão conhecida mudou.

        ``desconhecida`` após uma versão conhecida conta como troca. Em ``strict``, versão ``desconhecida``
        ou alterada marca ``parada_pendente``.
        """
        new = normalize_version(version)
        event: dict[str, Any] | None = None
        with self._lock:
            previous = self._versions.get(model_id)
            self._versions[model_id] = new
            if previous is not None and previous != UNKNOWN_VERSION and previous != new:
                event = {
                    "tipo": EVENT_VERSION_CHANGED,
                    "papeis": list(papeis),
                    "provedor_modelo": model_id,
                    "anterior": previous,
                    "nova": new,
                }
                self._events.append(event)
            if self.strict and (event is not None or new == UNKNOWN_VERSION):
                self._pending = STOP_VERSION
            changed = previous != new
        if changed and self._on_change is not None:
            try:
                self._on_change(model_id, new)
            except Exception:  # noqa: BLE001 — telemetria nunca derruba a chamada de LLM
                logger.exception("Falha ao atualizar a versão efetiva no perfil de alocação")
        if event is not None:
            logger.warning(
                "Versão efetiva do modelo mudou dentro da sessão",
                extra={"provedor_modelo": model_id, "anterior": event["anterior"], "nova": new},
            )
            if self._on_event is not None:
                try:
                    self._on_event(event)
                except Exception:  # noqa: BLE001 — telemetria nunca derruba a chamada de LLM
                    logger.exception("Falha ao registrar o evento de versão do modelo")
        elif self.strict and new == UNKNOWN_VERSION:
            logger.warning(
                "Versão efetiva desconhecida em LLM_ROUTING=strict: a sessão fechará no próximo ponto de verificação",
                extra={"provedor_modelo": model_id},
            )
        return event
