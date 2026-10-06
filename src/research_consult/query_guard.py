"""Guarda de consulta: verifica o texto que sai do nó em direção a buscadores públicos.

V18 — Spec `researcher-consult`, design §4 (ADR 010 item 9, ADR 019 §3). A guarda é
deliberadamente conservadora e **não prova ausência de dados**: ela bloqueia a forma mais comum
de vazamento (valores e nomes de arquivo copiados para a busca), não a paráfrase.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_QUERY_MAX_CHARS = 120
MAX_LINES = 3
# Stems menores que isso não são tratados como nome protegido (casariam com palavras comuns).
MIN_PROTECTED_STEM_LEN = 3

_DECIMAL = re.compile(r"\d[.,]\d")
_DIGIT_RUN = re.compile(r"\d{4,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class Ok:
    """Consulta liberada."""


@dataclass(frozen=True)
class Recusa:
    """Consulta recusada, com o motivo (``numero_decimal``, ``numero_longo``, ...)."""

    motivo: str
    detalhe: str = ""


def protected_file_names(session_dir: Path) -> list[str]:
    """Nomes de arquivo de ``input_snapshot/`` e ``artifacts/`` da sessão.

    Args:
        session_dir: Diretório de outputs da sessão (``outputs/<session_id>``).

    Returns:
        Nomes (com extensão) dos arquivos encontrados; lista vazia se as pastas não existem.
    """
    names: list[str] = []
    for sub in ("input_snapshot", "artifacts"):
        base = session_dir / sub
        if not base.is_dir():
            continue
        names.extend(p.name for p in base.rglob("*") if p.is_file())
    return sorted(set(names))


def _name_variants(name: str) -> set[str]:
    variants = {name.lower()}
    stem = Path(name).stem.lower()
    if len(stem) >= MIN_PROTECTED_STEM_LEN:
        variants.add(stem)
    return {v for v in variants if len(v) >= MIN_PROTECTED_STEM_LEN}


def check_query(
    texto: str,
    nomes_protegidos: Iterable[str] = (),
    max_chars: int = DEFAULT_QUERY_MAX_CHARS,
) -> Ok | Recusa:
    """Verifica se ``texto`` pode ser enviado a um buscador público.

    Função pura. Regras, na ordem: ``formato`` (mais de 3 linhas ou caracteres de controle),
    ``consulta_longa``, ``numero_decimal``, ``numero_longo`` (4 ou mais dígitos que não sejam um
    ano entre 1900 e 2100) e ``nome_de_arquivo`` (nome de arquivo da sessão, com ou sem
    extensão, sem diferenciar maiúsculas).

    Args:
        texto: Consulta de busca ou URL completa.
        nomes_protegidos: Nomes de arquivos da sessão (ver ``protected_file_names``).
        max_chars: Tamanho máximo permitido.

    Returns:
        ``Ok`` se liberada; ``Recusa`` com o motivo caso contrário.
    """
    if len(texto.splitlines()) > MAX_LINES or _CONTROL.search(texto):
        return Recusa("formato", "mais de 3 linhas ou caracteres de controle")
    if len(texto) > max_chars:
        return Recusa("consulta_longa", f"{len(texto)} caracteres (máximo {max_chars})")
    if _DECIMAL.search(texto):
        return Recusa("numero_decimal", "número com separador decimal")
    for run in _DIGIT_RUN.findall(texto):
        if not (len(run) == 4 and 1900 <= int(run) <= 2100):
            return Recusa("numero_longo", "sequência de 4 ou mais dígitos que não é ano")
    lowered = texto.lower()
    for name in nomes_protegidos:
        for variant in _name_variants(name):
            if re.search(rf"(?<![\w]){re.escape(variant)}(?![\w])", lowered):
                return Recusa("nome_de_arquivo", "nome de arquivo da sessão")
    return Ok()
