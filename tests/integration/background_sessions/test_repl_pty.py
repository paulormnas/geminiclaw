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


def test_evento_de_progresso_e_impresso_sem_apagar_a_entrada():
    """Scenario: Linha intercalada (session-events-terminal)."""
    child = spawn(GC_EVENT_AFTER="1.0")
    child.expect(PROMPT)
    child.send("pesq")  # o pesquisador está digitando quando o evento chega
    child.expect(r"\[iris-01\] plano 2 aprovado: 5 subtarefas, 3 hipóteses")
    child.expect(PROMPT + r".*pesq")  # o prompt é redesenhado com o texto parcial (há cores no meio)
    child.sendline("uisas")  # completa a digitação: a entrada final é ``pesquisas``
    child.expect("Pesquisas:")
    child.expect("iris-01")
    child.sendline("sair")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0


def test_evento_com_sequencia_de_controle_chega_saneado_ao_terminal():
    child = spawn(GC_EVENT_AFTER="0.5", GC_EVENT_SUMMARY="ok \x1b]0;titulo\x07 \x1b[2J fim ‮")
    child.expect(PROMPT)
    child.expect(r"\[iris-01\] ok .*fim")
    linha = child.after
    assert "\x1b" not in linha and "\x07" not in linha and "‮" not in linha
    child.sendline("sair")
    child.expect(pexpect.EOF)
    child.close()


def test_nivel_silencioso_so_mostra_decisao_pendente():
    child = spawn(GC_EVENT_AFTER="0.5", GC_EVENT_TYPE="subtarefa_concluida", GC_EVENT_SUMMARY="t1 concluída",
                  TERMINAL_EVENT_DETAIL="silencioso")
    child.expect(PROMPT)
    child.expect(pexpect.TIMEOUT, timeout=2)  # nada é impresso
    assert "t1 concluída" not in (child.before or "")
    child.sendline("sair")
    child.expect(pexpect.EOF)
    child.close()
