"""Fontes da busca técnica e texto de insumos para conferir ``{{src}}`` (design §2.2 e §2.4).

Só o texto que o sistema de fato recebeu conta como fonte: cada resultado devolvido ao Researcher é gravado em
``outputs/<sessão>/fontes_busca.jsonl`` (o cache em memória continua como está).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.logger import get_logger

logger = get_logger(__name__)

SOURCES_FILE = "fontes_busca.jsonl"
MAX_SNIPPET_CHARS = 4000
_TEXT_SUFFIXES = {".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".jsonl"}
_EXTRACTED_SUFFIXES = {".pdf", ".docx", ".pptx"}
_text_cache: dict[str, str] = {}


def record_search_sources(session_dir: Path | str, query: str, results: list[dict]) -> int:
    """Acrescenta os resultados da busca a ``fontes_busca.jsonl`` da sessão; devolve quantos foram gravados.

    Nunca levanta: a falha de gravação só gera aviso (a busca continua).
    """
    target = Path(session_dir) / SOURCES_FILE
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    for item in results:
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        snippet = str(item.get("snippet") or item.get("description") or "")[:MAX_SNIPPET_CHARS]
        title = str(item.get("title") or "")[:300]
        lines.append(
            json.dumps(
                {
                    "url": url, "titulo": title, "trecho": snippet, "consulta": query[:300], "obtido_em": now,
                    "sha256_trecho": hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
                },
                ensure_ascii=False,
            )
        )
    if not lines:
        return 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        logger.warning("fontes_busca.jsonl não gravado", extra={"error": type(exc).__name__})
        return 0
    return len(lines)


def read_search_sources(output_dir: Path | str, session_ids: Iterable[str]) -> list[dict]:
    """Entradas de ``fontes_busca.jsonl`` das sessões dadas (linhas inválidas são ignoradas)."""
    entries: list[dict] = []
    for session_id in session_ids:
        path = Path(output_dir) / session_id / SOURCES_FILE
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in raw:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                entries.append(item)
    return entries


def normalize_for_match(text: str) -> str:
    """NFC, hifenização de fim de linha desfeita, espaços colapsados e minúsculas (casamento de trechos)."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return " ".join(text.split()).lower()


def extract_text(path: Path, digest: str | None = None) -> str:
    """Texto do arquivo de insumo (local; nunca vai a prompt). PDF/DOCX/PPTX usam o extrator do ``ContextLoader``.

    Raises:
        ValueError: Formato sem extrator.
    """
    if digest and digest in _text_cache:
        return _text_cache[digest]
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
    elif suffix in _EXTRACTED_SUFFIXES:
        from src.skills.document_processor.extractors.registry import ExtractorRegistry

        text = ExtractorRegistry().extract(str(path)).text_content
    else:
        raise ValueError(f"formato sem extrator de texto: {suffix or 'sem extensão'}")
    if digest:
        _text_cache[digest] = text
    return text
