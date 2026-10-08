"""Descrição de imagens por modelo de visão (v18.5-research-data-ingestion, design §5).

Toda imagem enviada a um modelo passa por ``EgressGate.authorize_vision`` (registro em ``egress_log`` com
``canal=visao``) antes de qualquer chamada de rede. O modelo vem de ``VISION_MODEL`` (entrada do catálogo de modelos).
Provedores com suporte: ``google`` (Gemini) e ``ollama`` (campo ``images`` de ``/api/chat``, visão ``no_no``).
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from src.egress.gate import Destination
from src.logger import get_logger

logger = get_logger(__name__)

VISION_CHANNEL = "visao"
VISION_ROLE = "ingestao"
OBSOLETE_ALIAS_MODEL = "google/gemini-3.8-flash"
DEFAULT_VISION_PROMPT = (
    "Descreva o conteúdo desta imagem em detalhes (gráficos, tabelas, texto visível, "
    "estruturas de microscopia, etc.) para uso como contexto científico."
)
SUPPORTED_PROVIDERS = frozenset({"google", "ollama"})
_OLLAMA_TIMEOUT_SECONDS = 600.0


class VisionConfigError(ValueError):
    """``VISION_MODEL`` inválido: a sessão não inicia, com a causa e o que fazer."""


class VisionUnsupported(RuntimeError):
    """O provedor do modelo de visão não suporta imagens."""


@dataclass(frozen=True)
class VisionTarget:
    """Modelo de visão resolvido do catálogo."""

    model_id: str
    destination: Destination


def configured_model_id(environ: dict[str, str] | None = None) -> str | None:
    """``provedor/modelo`` da visão, ou ``None`` (sem visão).

    ``VISION_MODEL`` vence; ``OCR_PROVIDER=gemini`` sem ``VISION_MODEL`` é alias obsoleto de
    ``google/gemini-3.8-flash`` e emite ``WARNING``. Lê o ambiente no momento da chamada (testes e sobrescrita).
    """
    env = environ if environ is not None else os.environ
    from src import config

    vision = (env.get("VISION_MODEL", config.VISION_MODEL) or "").strip()
    if vision:
        return vision
    if (env.get("OCR_PROVIDER", config.OCR_PROVIDER) or "").strip().lower() == "gemini":
        logger.warning(
            f"OCR_PROVIDER=gemini é obsoleto; usando VISION_MODEL={OBSOLETE_ALIAS_MODEL}. Defina VISION_MODEL no .env."
        )
        return OBSOLETE_ALIAS_MODEL
    return None


def resolve_target(model_id: str) -> VisionTarget:
    """Destino de ``model_id`` a partir do catálogo.

    Raises:
        VisionConfigError: Modelo fora do catálogo ou de provedor sem suporte a visão.
    """
    from src.llm.session import get_catalog

    catalog = get_catalog()
    entry = catalog.modelos.get(model_id)
    if entry is None:
        known = ", ".join(sorted(catalog.modelos))
        raise VisionConfigError(
            f"VISION_MODEL='{model_id}' não está no catálogo de modelos. Use uma entrada existente "
            f"({known}) ou deixe vazio para usar só o OCR local."
        )
    if entry.provedor not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise VisionConfigError(
            f"VISION_MODEL='{model_id}': provedor sem suporte a visão (suportados: {supported})."
        )
    destination = Destination(
        canal=VISION_CHANNEL,  # type: ignore[arg-type]
        provedor=entry.provedor,
        modelo=entry.modelo,
        trust=entry.trust,
        localidade=entry.localidade,
        aceita_dados_brutos=entry.aceita_dados_brutos,
        papel=VISION_ROLE,
    )
    return VisionTarget(model_id, destination)


def mime_type_for(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
    }.get(path.suffix.lower(), "application/octet-stream")


def describe_image(path: Path, target: VisionTarget, prompt: str = DEFAULT_VISION_PROMPT) -> str:
    """Descrição de ``path`` pelo modelo de ``target``. Chamada síncrona (a ingestão roda antes do laço de agentes).

    O chamador DEVE ter autorizado o envio (``EgressGate.authorize_vision``) antes.

    Raises:
        VisionUnsupported: Provedor sem suporte a visão.
    """
    provider = target.destination.provedor
    if provider == "google":
        return _describe_google(path, target.destination.modelo or "", prompt)
    if provider == "ollama":
        return _describe_ollama(path, target.destination.modelo or "", prompt)
    raise VisionUnsupported(f"provedor '{provider}' sem suporte a visão")


def _describe_google(path: Path, model: str, prompt: str) -> str:
    from google import genai

    from src.config import GEMINI_API_KEY

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model,
        contents=[prompt, genai.types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type_for(path))],
    )
    return (response.text or "").strip()


def _describe_ollama(path: Path, model: str, prompt: str) -> str:
    import httpx

    from src.llm import registry

    base_url = registry.resolve_base_url("ollama")
    if not base_url:
        raise VisionConfigError("provedor ollama sem endpoint configurado (OLLAMA_BASE_URL) para a visão.")
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "user", "content": prompt, "images": [base64.b64encode(path.read_bytes()).decode("ascii")]}
        ],
    }
    response = httpx.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=_OLLAMA_TIMEOUT_SECONDS)
    response.raise_for_status()
    return str((response.json().get("message") or {}).get("content") or "").strip()
