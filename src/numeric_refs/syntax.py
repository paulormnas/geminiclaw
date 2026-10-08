"""Sintaxe das referências numéricas (design §1): ``{{res:...}}``, ``{{calc:...}}`` e ``{{src:...}}``.

Um único parser, usado pelo relatório, pelas ferramentas do Curator e (por acordo) pelo ``EgressGate`` para reconhecer
números com origem. Qualquer ``{{`` seguido de ``res:``, ``calc:`` ou ``src:`` que não case com a forma completa é
**referência malformada** (erro de sintaxe com posição).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

EXEC_ID_PATTERN = r"exec_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
METRIC_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_.\-]*"
METRIC_NAME_RE = re.compile(rf"^{METRIC_NAME_PATTERN}$")

RES_RE = re.compile(r"\{\{res:(" + EXEC_ID_PATTERN + r")/(" + METRIC_NAME_PATTERN + r")\}\}")
CALC_RE = re.compile(r"\{\{calc:(.+?)\}\}", re.DOTALL)
SRC_RE = re.compile(r"\{\{src:([^#{}\s]+)#(.+?)\}\}", re.DOTALL)
_OPEN_RE = re.compile(r"\{\{(?:res|calc|src):")

# Operandos dentro de uma expressão ``calc``: ``res:<exec_id>/<nome>`` e ``src:<id>#"<trecho>"``.
OPERAND_RES_RE = re.compile(r"res:(" + EXEC_ID_PATTERN + r")/(" + METRIC_NAME_PATTERN + r")")
OPERAND_SRC_RE = re.compile(r'src:([^#{}\s"]+)#"((?:[^"\\]|\\.)*)"')

PARAM_PREFIX = "param."


@dataclass(frozen=True)
class ResTarget:
    exec_id: str
    nome: str

    @property
    def is_param(self) -> bool:
        return self.nome.startswith(PARAM_PREFIX)


@dataclass(frozen=True)
class CalcExpr:
    expressao: str


@dataclass(frozen=True)
class SrcTarget:
    fonte: str  # id de Insumo ou URL
    trecho: str

    @property
    def is_url(self) -> bool:
        return self.fonte.startswith(("http://", "https://"))


@dataclass(frozen=True)
class NumericRef:
    kind: Literal["res", "calc", "src"]
    raw: str
    span: tuple[int, int]
    payload: ResTarget | CalcExpr | SrcTarget

    @property
    def key(self) -> tuple:
        """Chave de identidade: a mesma referência repetida reaproveita o código de origem."""
        p = self.payload
        if isinstance(p, ResTarget):
            return ("res", p.exec_id, p.nome)
        if isinstance(p, CalcExpr):
            return ("calc", " ".join(p.expressao.split()))
        return ("src", p.fonte, " ".join(p.trecho.split()))


@dataclass(frozen=True)
class SyntaxIssue:
    posicao: int
    trecho: str
    motivo: str


def find_references(text: str) -> list[NumericRef]:
    """Referências bem formadas do texto, em ordem de posição."""
    refs: list[NumericRef] = []
    for match in RES_RE.finditer(text):
        refs.append(NumericRef("res", match.group(0), match.span(), ResTarget(match.group(1), match.group(2))))
    for match in CALC_RE.finditer(text):
        refs.append(NumericRef("calc", match.group(0), match.span(), CalcExpr(match.group(1).strip())))
    for match in SRC_RE.finditer(text):
        refs.append(NumericRef("src", match.group(0), match.span(), SrcTarget(match.group(1), match.group(2).strip())))
    refs.sort(key=lambda r: r.span[0])
    return refs


def find_malformed(text: str) -> list[SyntaxIssue]:
    """Ocorrências de ``{{res:``, ``{{calc:`` ou ``{{src:`` que não casam com a forma completa."""
    covered = [r.span for r in find_references(text)]
    issues: list[SyntaxIssue] = []
    for match in _OPEN_RE.finditer(text):
        start = match.start()
        if any(lo <= start < hi for lo, hi in covered):
            continue
        end = text.find("}}", start)
        snippet = text[start : (end + 2 if end != -1 else start + 80)][:120]
        kind = match.group(0)[2:-1]
        issues.append(SyntaxIssue(start, snippet, _reason(kind, snippet)))
    return issues


def _reason(kind: str, snippet: str) -> str:
    if "}}" not in snippet:
        return "referência não fechada com '}}'"
    if kind == "res":
        return (
            "esperado {{res:exec_<uuid4>/<nome_metrica>}} "
            "(exec_id no formato exec_<uuid4> e nome [A-Za-z_][A-Za-z0-9_.-]*)"
        )
    if kind == "src":
        return "esperado {{src:<id_insumo_ou_url>#<trecho>}} (sem espaços na fonte e com um trecho)"
    return "esperado {{calc:<expressão>}} com ao menos um operando"
