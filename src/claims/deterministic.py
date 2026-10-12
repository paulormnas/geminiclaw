"""Conferência determinística de frases que só comparam referências numéricas (design §4). Nenhuma chamada LLM.

Uma frase é **só de referências** quando contém exatamente um comparador da lista abaixo com uma referência de cada lado
(ou é uma atribuição "o/a <métrica> foi/é <ref>") e nenhum marcador causal ou interpretativo. O resultado é
``suportada`` ou ``refutada_deterministica``; frase fora desse molde devolve ``None`` e segue ao verificador.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from src.knowledge.normalization import normalize_metric_name

CODE_RE = re.compile(r"\[([RCS])(\d+)\]")

# Lista fechada de marcadores causais ou interpretativos: a frase que tiver qualquer um vai ao verificador.
CAUSAL_MARKERS: tuple[str, ...] = (
    "porque", "devido", "gracas", "indica", "indicam", "sugere", "sugerem", "sugerindo", "significativ", "causa",
    "causam", "causado", "explica", "explicam", "provavelmente", "possivelmente", "talvez", "atribu", "decorre",
    "resulta", "demonstra", "evidencia", "confirma", "portanto", "logo", "consequencia", "por isso", "implica",
)

# (regex sobre texto sem acentos e em minúsculas, forma)
_COMPARATORS: tuple[tuple[str, str], ...] = (
    (r"nao supera", "<="),
    (r"maior que|maior do que|superior a|acima de|supera|excede", ">"),
    (r"menor que|menor do que|inferior a|abaixo de", "<"),
    (r"igual a|equivalente a|identico a", "=="),
    (r"proximo de|proxima de|aproximadamente|cerca de", "~"),
    (r"melhor que|melhor do que|melhora", "melhor"),
    (r"pior que|pior do que|piora", "pior"),
)
_COMPARATOR_RE = re.compile(
    "|".join(f"(?P<c{i}>{pattern})" for i, (pattern, _) in enumerate(_COMPARATORS))
)
_NEGATION_RE = re.compile(r"\bnao\s+(?:\w+\s+){0,2}$")
_ATTRIBUTION_RE = re.compile(
    r"\b(?:o|a|os|as)\s+(?P<nome>[^\[\]]{2,60}?)\s+(?:foi|e|era|ficou|atingiu|chegou a|alcancou|obteve|registrou)\s+"
    r"(?:de\s+|igual a\s+)?[^\[\]]{0,40}?\[(?P<cod>[RC]\d+)\]",
    re.IGNORECASE,
)
_SHOWN_RE = re.compile(r"([-+]?\d[\d   ]*(?:,(\d+))?)(?:\s*[^\s\d\[\]]{0,12})?\s*$")


@dataclass(frozen=True)
class CodeValue:
    """Valor resolvido de um código de origem do relatório (``[R1]``…)."""

    codigo: str
    valor: float
    unidade: str | None = None
    metrica: str | None = None


@dataclass(frozen=True)
class DeterministicResult:
    status: str  # "suportada" | "refutada_deterministica"
    valores: dict[str, Any]
    justificativa: str


def fold(text: str) -> str:
    """Minúsculas e sem acentos."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def has_causal_marker(text: str) -> bool:
    folded = fold(text)
    return any(marker in folded for marker in CAUSAL_MARKERS)


def _fold_with_map(text: str) -> tuple[str, list[int]]:
    """Texto dobrado e o índice original de cada caractere dobrado (a dobra pode mudar o tamanho)."""
    out: list[str] = []
    index: list[int] = []
    for i, char in enumerate(text):
        for piece in unicodedata.normalize("NFKD", char.lower()):
            if not unicodedata.combining(piece):
                out.append(piece)
                index.append(i)
    return "".join(out), index


def shown_decimals(sentence: str, ref_start: int) -> int | None:
    """Casas decimais do número exibido imediatamente antes do código em ``ref_start`` (``None`` se não achar)."""
    match = _SHOWN_RE.search(sentence[:ref_start])
    if not match:
        return None
    return len(match.group(2)) if match.group(2) else 0


def evaluate_sentence(
    sentence: str,
    codes: dict[str, CodeValue],
    *,
    approx_rel_tol: float,
    sense_of: Callable[[str], str | None] = lambda _name: None,
    known_metrics: Callable[[], Iterable[str]] = lambda: (),
    aliases_of: Callable[[str], Iterable[str]] = lambda _name: (),
) -> DeterministicResult | None:
    """Confere ``sentence`` sem LLM, ou devolve ``None`` quando ela não é só de referências.

    Args:
        sentence: Frase do relatório renderizado (com os códigos ``[R1]``).
        codes: Valores resolvidos por código.
        approx_rel_tol: ``CLAIM_APPROX_REL_TOL`` (aproximação relativa).
        sense_of: Nome da métrica → ``maior_melhor``/``menor_melhor`` (``Metrica.sentido``) ou ``None``.
        known_metrics: Nomes das métricas conhecidas (para refutar atribuição à métrica errada).
        aliases_of: Sinônimos do vocabulário para o nome de uma métrica.
    """
    refs = [(m.group(1) + m.group(2), m.start(), m.end()) for m in CODE_RE.finditer(sentence)]
    if not refs or any(code not in codes for code, _, _ in refs):
        return None
    if has_causal_marker(sentence):
        return None
    folded, index = _fold_with_map(sentence)
    comparators = list(_COMPARATOR_RE.finditer(folded))
    if len(comparators) == 1:
        return _comparison(sentence, folded, index, comparators[0], refs, codes, approx_rel_tol, sense_of)
    if not comparators and len(refs) == 1:
        return _attribution(sentence, refs[0][0], codes, known_metrics, aliases_of)
    return None


def _comparison(
    sentence: str,
    folded: str,
    index: list[int],
    match: re.Match,
    refs: list[tuple[str, int, int]],
    codes: dict[str, CodeValue],
    approx_rel_tol: float,
    sense_of: Callable[[str], str | None],
) -> DeterministicResult | None:
    kind = next(_COMPARATORS[i][1] for i in range(len(_COMPARATORS)) if match.group(f"c{i}"))
    cut = index[match.start()] if match.start() < len(index) else len(sentence)
    left = [r for r in refs if r[2] <= cut]
    right = [r for r in refs if r[1] >= cut]
    if len(left) != 1 or len(right) != 1:
        return None
    (code_a, start_a, _), (code_b, start_b, _) = left[0], right[0]
    a, b = codes[code_a], codes[code_b]
    if a.unidade and b.unidade and a.unidade != b.unidade:
        return None
    negated = bool(_NEGATION_RE.search(folded[: match.start()])) and kind != "<="
    values = {
        code_a: {"valor": a.valor, "unidade": a.unidade, "metrica": a.metrica},
        code_b: {"valor": b.valor, "unidade": b.unidade, "metrica": b.metrica},
    }
    if kind in ("melhor", "pior"):
        if not a.metrica or not b.metrica or normalize_metric_name(a.metrica) != normalize_metric_name(b.metrica):
            return None  # métricas diferentes (ADR 015 §7): vai ao verificador
        sentido = sense_of(a.metrica)
        if sentido not in ("maior_melhor", "menor_melhor"):
            return None
        values["sentido"] = sentido
        higher_is_better = sentido == "maior_melhor"
        a_better = a.valor > b.valor if higher_is_better else a.valor < b.valor
        holds = a_better if kind == "melhor" else (b.valor > a.valor if higher_is_better else b.valor < a.valor)
    elif kind in (">", "<", "<="):
        holds = {">": a.valor > b.valor, "<": a.valor < b.valor, "<=": a.valor <= b.valor}[kind]
    elif kind == "==":
        decimals = [d for d in (shown_decimals(sentence, start_a), shown_decimals(sentence, start_b)) if d is not None]
        tolerance = 0.5 * 10 ** (-min(decimals)) if decimals else 1e-9 * max(abs(a.valor), abs(b.valor), 1.0)
        values["tolerancia"] = tolerance
        holds = abs(a.valor - b.valor) <= tolerance
    else:  # "~"
        values["tolerancia_relativa"] = approx_rel_tol
        holds = abs(a.valor - b.valor) <= approx_rel_tol * abs(b.valor)
    if negated:
        holds = not holds
    status = "suportada" if holds else "refutada_deterministica"
    comparator = match.group(0)
    sinal = "não " if negated else ""
    note = f"{code_a}={a.valor:g} {sinal}{comparator} {code_b}={b.valor:g}: {'confere' if holds else 'não confere'}"
    return DeterministicResult(status, values, note)


def _attribution(
    sentence: str,
    code: str,
    codes: dict[str, CodeValue],
    known_metrics: Callable[[], Iterable[str]],
    aliases_of: Callable[[str], Iterable[str]],
) -> DeterministicResult | None:
    folded = fold(sentence)
    match = _ATTRIBUTION_RE.search(folded)
    value = codes[code]
    if not match or match.group("cod").upper() != code or not value.metrica:
        return None
    named = normalize_metric_name(match.group("nome"))
    actual = normalize_metric_name(value.metrica)
    if not named or not actual:
        return None
    names = {actual, *(normalize_metric_name(a) for a in aliases_of(value.metrica))}
    values = {code: {"valor": value.valor, "unidade": value.unidade, "metrica": value.metrica}}
    if any(n and len(n) >= 2 and (n == named or n in named or named in n) for n in names):
        return DeterministicResult("suportada", values, f"{code} é o valor de '{value.metrica}'")
    others = {normalize_metric_name(m) for m in known_metrics()} - names
    if any(o and len(o) >= 2 and (o == named or o in named) for o in others):
        values["nome_citado"] = match.group("nome").strip()
        cited = values["nome_citado"]
        return DeterministicResult(
            "refutada_deterministica", values, f"{code} é o valor de '{value.metrica}', não de '{cited}'"
        )
    return None
