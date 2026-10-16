"""Garantias do gate escritas e conferidas (persistent-human-gate 1.8 e 5.2, na camada da aplicação).

A versão de desenvolvimento não tem papel de banco separado (decisão do pesquisador, 2026-10-16); o que se garante é que o
código da sessão e os agentes não têm caminho para resolver pedidos, gravar mensagem ou presença.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
# Só o terminal (CLI) e o próprio pacote do gate podem usar o gate que responde.
ALLOWED_TERMINAL_GATE = ("src/cli/", "src/gate/")
FORBIDDEN_SQL = (
    "SET ROLE",
    "SET SESSION AUTHORIZATION",
    "session_replication_role",
    "DISABLE TRIGGER",
    "DROP TRIGGER",
    "ALTER ROLE",
)


def _python_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_terminal_gate_so_existe_no_terminal():
    """Scenario: a sessão e os agentes nunca instanciam o gate que responde."""
    offenders = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(ALLOWED_TERMINAL_GATE):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "TerminalGate":
                offenders.append(rel)
            if isinstance(node, ast.alias) and node.name == "TerminalGate":
                offenders.append(rel)
    assert not offenders, f"TerminalGate fora do terminal: {sorted(set(offenders))}"


def test_gate_da_sessao_nao_tem_answer():
    from src.gate.persistent_gate import PersistentGate, TerminalGate

    assert not hasattr(PersistentGate, "answer") and hasattr(TerminalGate, "answer")


def test_nenhum_contorno_de_papel_ou_gatilho_em_src():
    """Scenario: teste estático dos contornos (a lista completa do requisito)."""
    hits = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN_SQL:
            if needle.lower() in text.lower():
                hits.append((path.relative_to(ROOT).as_posix(), needle))
    assert not hits, hits


def _run_config(**env: str) -> subprocess.CompletedProcess[str]:
    import os

    full = {**os.environ, "GENAI_API_KEY": "x", "GEMINI_API_KEY": "x", "DATABASE_URL": "postgresql://u:p@h/d", **env}
    return subprocess.run(
        [sys.executable, "-c", "import src.config"], cwd=ROOT, env=full, capture_output=True, text=True, timeout=60
    )


def test_espera_de_ask_researcher_precisa_ser_menor_que_o_tempo_do_agente():
    bad = _run_config(AGENT_TIMEOUT_SECONDS="100", GATE_ASK_WAIT_SECONDS="120")
    assert bad.returncode != 0 and "GATE_ASK_WAIT_SECONDS" in bad.stderr
    assert _run_config(AGENT_TIMEOUT_SECONDS="0", GATE_ASK_WAIT_SECONDS="120").returncode == 0
    assert _run_config(AGENT_TIMEOUT_SECONDS="300", GATE_ASK_WAIT_SECONDS="120").returncode == 0


def test_mensagem_da_caixa_nao_pode_passar_do_limite_da_tabela():
    bad = _run_config(SESSION_INBOX_MAX_CHARS="2001")
    assert bad.returncode != 0 and "SESSION_INBOX_MAX_CHARS" in bad.stderr
