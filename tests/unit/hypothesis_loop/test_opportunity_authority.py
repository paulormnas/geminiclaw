"""Só a CLI do pesquisador decide oportunidades (revisão de segurança L5).

``authorize_and_decide`` registra o pedido no gate e o responde com a origem ``cli``. Qualquer outro código de
produção que o chamasse ou importasse daria a um agente ou ao orquestrador a decisão reservada ao pesquisador.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NAME = "authorize_and_decide"
DEFINITION = ROOT / "src" / "knowledge" / "opportunities.py"
ALLOWED = {ROOT / "src" / "cli_opportunities.py"}


def _uses(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == NAME:
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == NAME:
            lines.append(node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and any(a.name.split(".")[-1] == NAME for a in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value == NAME:  # getattr(module, "authorize_and_decide")
            lines.append(node.lineno)
    return lines


@pytest.mark.unit
def test_so_a_cli_de_oportunidades_chama_authorize_and_decide():
    offenders: dict[str, list[int]] = {}
    scanned = 0
    for base in ("src", "agents", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            if path == DEFINITION or path in ALLOWED:
                continue
            scanned += 1
            lines = _uses(path)
            if lines:
                offenders[str(path.relative_to(ROOT))] = lines
    assert scanned > 50, "a varredura não encontrou o código de produção"
    assert not offenders, f"{NAME} só pode ser usado por src/cli_opportunities.py: {offenders}"
    assert _uses(ALLOWED.copy().pop()), "a CLI deixou de usar authorize_and_decide: atualize este guarda"
