"""Guarda de consulta: verifica o texto que sai do nó em direção a buscadores públicos.

V18 — Spec `researcher-consult`, design §4 (ADR 010 item 9, ADR 019 §3). A guarda é
deliberadamente conservadora e **não prova ausência de dados**: ela bloqueia a forma mais comum
de vazamento (valores e nomes de arquivo copiados para a busca), não a paráfrase.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

DEFAULT_QUERY_MAX_CHARS = 120
MAX_LINES = 3
# Stems menores que isso não são tratados como nome protegido (casariam com palavras comuns).
MIN_PROTECTED_STEM_LEN = 3

# Separadores decimais: ponto, vírgula, vírgula decimal árabe e pontos médios (NFKC já converte
# o ponto de largura total).
_DECIMAL = re.compile("\\d[.,\u066b\u00b7\u22c5]\\d")
_DIGIT_RUN = re.compile(r"\d{4,}")
# Grupos de dígitos separados por espaço, hífen, ponto ou vírgula ("0 9 5 3", "12-34-56-78").
_SEPARATED_DIGITS = re.compile(r"\d+(?:[\s\-.,]+\d+)+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_NAME_SEPARATORS = re.compile(r"[\s_\-.]+")
MAX_DECODE_ROUNDS = 5
# Nomes normalizados com pelo menos este tamanho casam por substring (pega sufixos como
# `medicoes_lote7s`); os menores exigem palavra inteira, para não casar com `database`.
SUBSTRING_MIN_LEN = 6


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


def _normalize_name(texto: str) -> str:
    return _NAME_SEPARATORS.sub(" ", texto.lower()).strip()


def _name_variants(name: str) -> set[str]:
    variants = {_normalize_name(name)}
    stem = Path(name).stem
    if len(stem) >= MIN_PROTECTED_STEM_LEN:
        variants.add(_normalize_name(stem))
    return {v for v in variants if len(v.replace(" ", "")) >= MIN_PROTECTED_STEM_LEN}


def _decode(texto: str) -> str | None:
    """Percent-decode repetido até estabilizar, NFKC e remoção de caracteres invisíveis.

    Returns:
        O texto normalizado, ou ``None`` se a codificação não estabiliza em
        ``MAX_DECODE_ROUNDS`` rodadas (tratada como recusa).
    """
    for _ in range(MAX_DECODE_ROUNDS):
        decoded = unquote(texto)
        if decoded == texto:
            break
        texto = decoded
    else:
        if unquote(texto) != texto:
            return None
    texto = unicodedata.normalize("NFKC", texto)
    return "".join(c for c in texto if unicodedata.category(c) not in ("Cf", "Cc") or c in "\n\t")


def check_query(
    texto: str,
    nomes_protegidos: Iterable[str] = (),
    max_chars: int = DEFAULT_QUERY_MAX_CHARS,
) -> Ok | Recusa:
    """Verifica se ``texto`` pode ser enviado a um buscador público.

    Função pura. O texto é decodificado (percent-encoding repetido), normalizado (NFKC) e
    limpo de caracteres invisíveis antes das regras. Regras, na ordem: ``formato`` (mais de 3
    linhas ou caracteres de controle, no texto original), ``consulta_longa``, ``codificacao``
    (não estabiliza), ``numero_decimal``, ``numero_longo`` (4 ou mais dígitos, também quando
    separados por espaço, hífen ou ponto, que não sejam um ano entre 1900 e 2100) e
    ``nome_de_arquivo`` (nome de arquivo da sessão, com ou sem extensão, ignorando maiúsculas e
    tratando ``_``, ``-``, ``.`` e espaço como equivalentes).

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
    normalizado = _decode(texto)
    if normalizado is None:
        return Recusa("codificacao", "codificação percentual não estabiliza")
    if _DECIMAL.search(normalizado):
        return Recusa("numero_decimal", "número com separador decimal")
    for run in _DIGIT_RUN.findall(normalizado):
        if not (len(run) == 4 and 1900 <= int(run) <= 2100):
            return Recusa("numero_longo", "sequência de 4 ou mais dígitos que não é ano")
    for seq in _SEPARATED_DIGITS.findall(normalizado):
        groups = re.findall(r"\d+", seq)
        if sum(len(g) for g in groups) < 4:
            continue
        if all(len(g) == 4 and 1900 <= int(g) <= 2100 for g in groups):
            continue
        return Recusa("numero_longo", "dígitos separados somam 4 ou mais")
    flat = _normalize_name(normalizado)
    for name in nomes_protegidos:
        for variant in _name_variants(name):
            if len(variant.replace(" ", "")) >= SUBSTRING_MIN_LEN:
                hit = variant in flat
            else:
                hit = re.search(rf"(?<!\w){re.escape(variant)}(?!\w)", flat) is not None
            if hit:
                return Recusa("nome_de_arquivo", "nome de arquivo da sessão")
    return Ok()
