"""Ajudas dos testes de estrutura do código (ADR 024, ``v18.7-source-layout``)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

_LINT = "import sys; from importlinter.cli import lint_imports_command; sys.exit(lint_imports_command())"


def run_lint_imports(config: Path, *, cwd: Path = ROOT, pythonpath: list[Path] | None = None) -> subprocess.CompletedProcess:
    """Executa a verificação de contratos de importação em subprocesso com o contrato de ``config``."""
    env = dict(os.environ)
    paths = [str(p) for p in (pythonpath or [ROOT])]
    env["PYTHONPATH"] = os.pathsep.join(paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    return subprocess.run(
        [sys.executable, "-c", _LINT, "--config", str(config)],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=300,
    )


def importlinter_section() -> str:
    """Texto da seção ``[tool.importlinter]`` (e contratos) de ``pyproject.toml``."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    start = text.index("[tool.importlinter]")
    rest = text[start:]
    end = re.search(r"\n\[(?!\[?tool\.importlinter)", rest)
    return rest[: end.start()] if end else rest
