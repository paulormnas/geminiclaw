"""REPL em pseudo-terminal com ``pexpect`` (v18.7-background-sessions, tarefa 3.4): redesenho do prompt e Ctrl+C."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pexpect
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.timeout(30)]

ROOT = Path(__file__).resolve().parents[3]
PROMPT = "🔮 >"


def spawn(**env: str) -> pexpect.spawn:
    return pexpect.spawn(
        sys.executable, ["-m", "tests.support.repl_pty"], cwd=str(ROOT), encoding="utf-8", timeout=15,
        env={**os.environ, "PYTHONPATH": str(ROOT), "TERM": "dumb", **env},
    )


def test_prompt_comando_desconhecido_e_sair():
    child = spawn()
    child.expect(PROMPT)
    child.sendline("estude a base iris")
    child.expect("nova-pesquisa <tarefa>")
    child.expect(PROMPT)
    child.sendline("sair")
    child.expect("Até logo")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0


def test_notificacao_assincrona_redesenha_o_prompt_com_o_texto_parcial():
    child = spawn(GC_NOTIFY_AFTER="1.0")
    child.expect(PROMPT)
    child.send("texto parcial")  # o pesquisador está digitando quando o aviso chega
    child.expect("AVISO-ASSINCRONO")
    child.expect(PROMPT)  # o prompt é redesenhado depois do aviso
    child.sendline("")
    child.sendline("sair")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0


def test_ctrl_c_no_prompt_encerra_o_repl_sem_traceback():
    child = spawn()
    child.expect(PROMPT)
    child.sendintr()
    child.expect("Encerrando")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0
    assert "Traceback" not in (child.before or "")
