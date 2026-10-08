"""Avaliador determinístico de expressões ``{{calc:...}}`` (design §3).

**Nunca** usa ``eval``, ``exec`` nem ``compile`` de código executável: ``ast.parse(..., mode="eval")`` só produz a
árvore, que um visitante com **lista de permissão** percorre e avalia, em ``float`` (IEEE 754), com unidades.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Union

from src.numeric_refs import syntax
from src.numeric_refs.units import (
    Unit,
    unit_div,
    unit_mul,
    unit_pow,
    unit_text,
)

MAX_DEPTH = 16
ALLOWED_FUNCTIONS = frozenset({"abs", "min", "max", "media", "sqrt", "round", "pct"})
_IDENT_RE = re.compile(r"^_o(\d+)$")
_USER_IDENT_RE = re.compile(r"(?<![\w])_o\d+(?![\w])")

ERR_SYNTAX = "sintaxe_invalida"
ERR_NODE = "no_nao_permitido"
ERR_NO_REF = "calculo_sem_referencia"
ERR_UNITS = "unidades_incompativeis"
ERR_MATH = "erro_matematico"
ERR_LIMIT = "limite_excedido"


class CalcError(ValueError):
    """Expressão inválida ou não calculável; ``codigo`` é o motivo exibido no apêndice."""

    def __init__(self, message: str, codigo: str = ERR_SYNTAX) -> None:
        super().__init__(message)
        self.codigo = codigo


@dataclass(frozen=True)
class OperandRef:
    ident: str
    kind: str  # "res" | "src"
    target: Union[syntax.ResTarget, syntax.SrcTarget]
    raw: str


@dataclass(frozen=True)
class Quantity:
    valor: float
    unidade: Unit
    const: bool = False
    decimais: int | None = None


@dataclass
class ParsedExpression:
    expressao: str
    normalizada: str
    tree: ast.Expression
    operandos: list[OperandRef] = field(default_factory=list)
    constantes: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class CalcValue:
    valor: float
    unidade: str | None
    decimais: int | None
    constantes: list[float]


def _limits() -> tuple[int, int, int]:
    from src import config

    return config.NUMREF_CALC_MAX_CHARS, config.NUMREF_CALC_MAX_NODES, config.NUMREF_CALC_MAX_POW


def parse_expression(expression: str) -> ParsedExpression:
    """Valida e analisa ``expression``: operandos, constantes e árvore com lista de permissão.

    Raises:
        CalcError: Tamanho excedido, operando malformado, nó fora da lista, ou sem operando de referência.
    """
    max_chars, max_nodes, _ = _limits()
    expr = expression.strip()
    if len(expr) > max_chars:
        raise CalcError(f"expressão com mais de {max_chars} caracteres", ERR_LIMIT)
    if _USER_IDENT_RE.search(expr):
        raise CalcError("identificador reservado '_o<n>' na expressão", ERR_NODE)
    operands: list[OperandRef] = []
    pieces: list[str] = []
    pos = 0
    pattern = re.compile(syntax.OPERAND_SRC_RE.pattern + "|" + syntax.OPERAND_RES_RE.pattern)
    for match in pattern.finditer(expr):
        pieces.append(expr[pos : match.start()])
        ident = f"_o{len(operands)}"
        raw = match.group(0)
        if raw.startswith("src:"):
            fonte, trecho = match.group(1), match.group(2).replace('\\"', '"')
            operands.append(OperandRef(ident, "src", syntax.SrcTarget(fonte, trecho), raw))
        else:
            operands.append(OperandRef(ident, "res", syntax.ResTarget(match.group(3), match.group(4)), raw))
        pieces.append(ident)
        pos = match.end()
    pieces.append(expr[pos:])
    normalized = "".join(pieces)
    if "res:" in normalized or "src:" in normalized:
        raise CalcError("operando 'res:' ou 'src:' malformado dentro da expressão", ERR_SYNTAX)
    if not operands:
        raise CalcError("o cálculo precisa de ao menos um operando res: ou src:", ERR_NO_REF)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"expressão inválida: {exc.msg}", ERR_SYNTAX) from exc
    count = 0
    constants: list[float] = []
    for node in ast.walk(tree):
        count += 1
        if count > max_nodes:
            raise CalcError(f"expressão com mais de {max_nodes} nós", ERR_LIMIT)
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CalcError("constante não numérica", ERR_NODE)
            constants.append(float(value))
    if _depth(tree) > MAX_DEPTH:
        raise CalcError(f"expressão com mais de {MAX_DEPTH} níveis de aninhamento", ERR_LIMIT)
    return ParsedExpression(expression.strip(), normalized, tree, operands, constants)


def _depth(node: ast.AST, level: int = 1) -> int:
    children = list(ast.iter_child_nodes(node))
    return level if not children else max(_depth(child, level + 1) for child in children)


class _Evaluator:
    def __init__(self, values: dict[str, Quantity]) -> None:
        self.values = values
        self.max_pow = _limits()[2]

    def value_of(self, node: ast.AST) -> Quantity:  # noqa: C901 - lista de permissão explícita
        if isinstance(node, ast.Expression):
            return self.value_of(node.body)
        if isinstance(node, ast.Constant):
            return Quantity(float(node.value), {}, const=True)
        if isinstance(node, ast.Name):
            if not _IDENT_RE.match(node.id) or node.id not in self.values:
                raise CalcError(f"identificador não permitido: {node.id}", ERR_NODE)
            return self.values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            inner = self.value_of(node.operand)
            sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
            return Quantity(sign * inner.valor, inner.unidade, inner.const)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        raise CalcError(f"nó não permitido: {type(node).__name__}", ERR_NODE)

    def _binop(self, node: ast.BinOp) -> Quantity:
        op = node.op
        if isinstance(op, ast.Pow):
            base = self.value_of(node.left)
            exponent = self.value_of(node.right)
            if not exponent.const or not float(exponent.valor).is_integer() or abs(exponent.valor) > self.max_pow:
                raise CalcError(f"expoente de ** deve ser constante inteira com |e| <= {self.max_pow}", ERR_LIMIT)
            e = int(exponent.valor)
            return self._finite(Quantity(self._pow(base.valor, e), unit_pow(base.unidade, Fraction(e)), base.const))
        left, right = self.value_of(node.left), self.value_of(node.right)
        if isinstance(op, (ast.Add, ast.Sub)):
            unit = self._same_unit(left, right)
            value = left.valor + right.valor if isinstance(op, ast.Add) else left.valor - right.valor
            return self._finite(Quantity(value, unit, left.const and right.const))
        if isinstance(op, ast.Mult):
            return self._finite(
                Quantity(left.valor * right.valor, unit_mul(left.unidade, right.unidade), left.const and right.const)
            )
        if isinstance(op, ast.Div):
            if right.valor == 0:
                raise CalcError("divisão por zero", ERR_MATH)
            return self._finite(
                Quantity(left.valor / right.valor, unit_div(left.unidade, right.unidade), left.const and right.const)
            )
        raise CalcError(f"operador não permitido: {type(op).__name__}", ERR_NODE)

    @staticmethod
    def _pow(base: float, exponent: int) -> float:
        if base == 0 and exponent < 0:
            raise CalcError("divisão por zero", ERR_MATH)
        try:
            return float(base) ** exponent
        except OverflowError as exc:
            raise CalcError("estouro numérico", ERR_MATH) from exc

    @staticmethod
    def _finite(q: Quantity) -> Quantity:
        if math.isnan(q.valor) or math.isinf(q.valor):
            raise CalcError("resultado não finito", ERR_MATH)
        return q

    @staticmethod
    def _same_unit(a: Quantity, b: Quantity) -> Unit:
        if a.const and b.const:
            return {}
        if a.const or b.const:
            other = b if a.const else a
            if other.unidade is None or other.unidade == {}:
                return other.unidade
            raise CalcError("constante somada a valor com unidade", ERR_UNITS)
        if a.unidade is None or b.unidade is None:
            return None
        if a.unidade != b.unidade:
            raise CalcError(f"unidades incompatíveis: {unit_text(a.unidade)} e {unit_text(b.unidade)}", ERR_UNITS)
        return a.unidade

    def _call(self, node: ast.Call) -> Quantity:
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
            name = getattr(node.func, "id", type(node.func).__name__)
            raise CalcError(f"função não permitida: {name}", ERR_NODE)
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise CalcError("argumentos nomeados ou *args não são permitidos", ERR_NODE)
        name = node.func.id
        if name == "round":
            if len(node.args) != 2:
                raise CalcError("round(x, n) exige dois argumentos", ERR_SYNTAX)
            value = self.value_of(node.args[0])
            digits_node = node.args[1]
            if not (
                isinstance(digits_node, ast.Constant)
                and isinstance(digits_node.value, int)
                and not isinstance(digits_node.value, bool)
                and 0 <= digits_node.value <= 10
            ):
                raise CalcError("round: n deve ser inteiro constante em [0, 10]", ERR_LIMIT)
            n = digits_node.value
            rounded = Decimal(repr(value.valor)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
            return Quantity(float(rounded), value.unidade, value.const, decimais=n)
        args = [self.value_of(a) for a in node.args]
        if not args:
            raise CalcError(f"{name}() sem argumentos", ERR_SYNTAX)
        if name in ("abs", "sqrt", "pct") and len(args) != 1:
            raise CalcError(f"{name}(x) exige um argumento", ERR_SYNTAX)
        if name == "abs":
            return Quantity(abs(args[0].valor), args[0].unidade, args[0].const)
        if name == "sqrt":
            if args[0].valor < 0:
                raise CalcError("raiz quadrada de valor negativo", ERR_MATH)
            return Quantity(math.sqrt(args[0].valor), unit_pow(args[0].unidade, Fraction(1, 2)), args[0].const)
        if name == "pct":
            unit = args[0].unidade
            if unit is not None and unit != {}:
                raise CalcError("pct(x) exige x adimensional", ERR_UNITS)
            return self._finite(Quantity(args[0].valor * 100.0, {"%": Fraction(1)}))
        unit = args[0].unidade
        const = args[0].const
        for other in args[1:]:
            unit = self._same_unit(Quantity(0.0, unit, const), other)
            const = const and other.const
        values = [a.valor for a in args]
        if name == "min":
            return Quantity(min(values), unit, const)
        if name == "max":
            return Quantity(max(values), unit, const)
        return self._finite(Quantity(math.fsum(values) / len(values), unit, const))  # media


def evaluate(parsed: ParsedExpression, values: dict[str, Quantity]) -> CalcValue:
    """Avalia ``parsed`` com os valores dos operandos (``_o0``, ``_o1``, ...).

    Raises:
        CalcError: Nó fora da lista, unidades incompatíveis, divisão por zero, resultado não finito, limites.
    """
    result = _Evaluator(values).value_of(parsed.tree)
    return CalcValue(result.valor, unit_text(result.unidade), result.decimais, list(parsed.constantes))
