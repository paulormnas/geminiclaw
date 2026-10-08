"""Verificação estática de métricas gravadas como literais no código executado (design §6).

Análise por AST (nada é executado) sobre o código **exatamente como executado**. Padrões:

- **P1** ``save_experiment_artifacts(..., metrics={...})`` (keyword ou 3º posicional) com valor ``Constant`` numérico;
- **P2** ``metrics`` é um ``Name`` cuja última atribuição antes da chamada é um dict literal (``{k: c}``,
  ``dict(k=c)``, ``name[k] = c``, ``name.update(...)``, ou ``name[k] = var`` com ``var = c``);
- **P3** ``json.dump(obj, f)`` / ``Path(...).write_text(json.dumps(obj))`` com destino literal ``metrics.json``.

Nunca bloqueia a execução. É heurística: um literal passado por várias variáveis ou funções não é detectado.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.logger import get_logger

logger = get_logger(__name__)

LITERALS_FILE = "metricas_literais.json"
SAVE_FUNCTION = "save_experiment_artifacts"


@dataclass(frozen=True)
class LiteralFinding:
    metrica: str
    linha: int
    padrao: str

    def to_dict(self) -> dict[str, Any]:
        return {"metrica": self.metrica, "linha": self.linha, "padrao": self.padrao}


def _is_numeric_constant(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    )


def _key(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _dict_literals(node: ast.AST, constants: dict[str, bool]) -> dict[str, tuple[bool, int]] | None:
    """``{chave: (é_literal, linha)}`` de um dict literal (ou ``dict(k=v)``); ``None`` se não for um dict conhecido."""
    if isinstance(node, ast.Dict):
        out: dict[str, tuple[bool, int]] = {}
        for k, v in zip(node.keys, node.values):
            name = _key(k)
            if name is not None:
                out[name] = (_is_literal(v, constants), getattr(v, "lineno", node.lineno))
        return out
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        return {
            kw.arg: (_is_literal(kw.value, constants), getattr(kw.value, "lineno", node.lineno))
            for kw in node.keywords
            if kw.arg
        }
    return None


def _is_literal(node: ast.AST, constants: dict[str, bool]) -> bool:
    if _is_numeric_constant(node):
        return True
    return isinstance(node, ast.Name) and constants.get(node.id, False)


def _scope_statements(tree: ast.Module, call: ast.Call) -> list[ast.stmt]:
    """Instruções do escopo (módulo ou função) que contém ``call``."""
    best: list[ast.stmt] = list(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            child is call for child in ast.walk(node)
        ):
            best = list(node.body)
    return best


def _flatten(statements: list[ast.stmt]) -> list[ast.stmt]:
    out: list[ast.stmt] = []
    for stmt in statements:
        out.append(stmt)
        for field_name in ("body", "orelse", "finalbody"):
            out.extend(_flatten(getattr(stmt, field_name, []) or []))
    return out


def _resolve_name(name: str, tree: ast.Module, call: ast.Call) -> dict[str, tuple[bool, int]]:
    state: dict[str, tuple[bool, int]] = {}
    constants: dict[str, bool] = {}
    flat = [s for s in _flatten(_scope_statements(tree, call)) if getattr(s, "lineno", 0) < call.lineno]
    for stmt in sorted(flat, key=lambda s: s.lineno):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
            if isinstance(target, ast.Name):
                if target.id == name:
                    state = _dict_literals(value, constants) or {}
                else:
                    constants[target.id] = _is_numeric_constant(value)
            elif (
                isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == name
            ):
                key = _key(target.slice)
                if key is not None:
                    state[key] = (_is_literal(value, constants), stmt.lineno)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            update = stmt.value
            if (
                isinstance(update.func, ast.Attribute) and update.func.attr == "update"
                and isinstance(update.func.value, ast.Name) and update.func.value.id == name
            ):
                items: dict[str, tuple[bool, int]] = {}
                if update.args:
                    items.update(_dict_literals(update.args[0], constants) or {})
                for kw in update.keywords:
                    if kw.arg:
                        items[kw.arg] = (_is_literal(kw.value, constants), stmt.lineno)
                state.update(items)
    return state


def _metrics_from(node: ast.AST, tree: ast.Module, call: ast.Call) -> dict[str, tuple[bool, int]]:
    if isinstance(node, ast.Name):
        return _resolve_name(node.id, tree, call)
    return _dict_literals(node, {}) or {}


def _inner_metrics(info: dict[str, tuple[bool, int]], node: ast.AST) -> dict[str, tuple[bool, int]]:
    """Para ``{"metrics": {...}}`` (P3), usa o dict interno."""
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if _key(k) == "metrics" and isinstance(v, ast.Dict):
                return _dict_literals(v, {}) or {}
    return info


def _metrics_json_targets(tree: ast.Module) -> set[str]:
    """Nomes de arquivo abertos com destino literal ``...metrics.json`` (``with open(...) as f``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if (
                    isinstance(call, ast.Call) and _call_name(call) == "open" and call.args
                    and isinstance(call.args[0], ast.Constant) and str(call.args[0].value).endswith("metrics.json")
                    and isinstance(item.optional_vars, ast.Name)
                ):
                    names.add(item.optional_vars.id)
    return names


def _is_metrics_path(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value.endswith("metrics.json"):
            return True
    return False


def scan_code(code: str) -> list[LiteralFinding]:
    """Achados P1–P3 em ``code``. Código que não compila em AST devolve lista vazia (o sandbox acusa o erro)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    findings: dict[tuple[str, int, str], LiteralFinding] = {}

    def add(info: dict[str, tuple[bool, int]], pattern: str, fallback_line: int) -> None:
        for name, (is_literal, line) in info.items():
            if is_literal:
                finding = LiteralFinding(name, line or fallback_line, pattern)
                findings[(finding.metrica, finding.linha, finding.padrao)] = finding

    file_vars = _metrics_json_targets(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == SAVE_FUNCTION:
            arg = next((kw.value for kw in node.keywords if kw.arg == "metrics"), None)
            if arg is None and len(node.args) >= 3:
                arg = node.args[2]
            if arg is not None:
                info = _metrics_from(arg, tree, node)
                add(info, "P1" if isinstance(arg, ast.Dict) else "P2", node.lineno)
        elif name == "dump" and len(node.args) >= 2 and isinstance(node.args[1], ast.Name):
            if node.args[1].id in file_vars:
                obj = node.args[0]
                add(_inner_metrics(_metrics_from(obj, tree, node), obj), "P3", node.lineno)
        elif name == "write_text" and node.args and isinstance(node.func, ast.Attribute):
            inner = node.args[0]
            if _is_metrics_path(node.func.value) and isinstance(inner, ast.Call) and _call_name(inner) == "dumps":
                if inner.args:
                    obj = inner.args[0]
                    add(_inner_metrics(_metrics_from(obj, tree, node), obj), "P3", node.lineno)
    return sorted(findings.values(), key=lambda f: (f.linha, f.metrica))


def write_findings(task_dir: Path, exec_id: str, code_hash: str, findings: list[LiteralFinding]) -> Path | None:
    """Grava ``metricas_literais.json`` na pasta da subtarefa (só quando há achados). Nunca levanta."""
    if not findings:
        return None
    target = task_dir / LITERALS_FILE
    payload = {"exec_id": exec_id, "hash_codigo": code_hash, "achados": [f.to_dict() for f in findings]}
    try:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("metricas_literais.json não gravado", extra={"erro": type(exc).__name__})
        return None
    return target


def read_literal_metrics(session_dir: Path) -> set[tuple[str, str]]:
    """``{(exec_id, métrica)}`` sinalizadas nas subtarefas da sessão."""
    found: set[tuple[str, str]] = set()
    for path in session_dir.glob(f"*/{LITERALS_FILE}"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            exec_id = str(data.get("exec_id"))
            for item in data.get("achados") or []:
                found.add((exec_id, str(item.get("metrica"))))
        except (OSError, ValueError, AttributeError):
            continue
    return found
