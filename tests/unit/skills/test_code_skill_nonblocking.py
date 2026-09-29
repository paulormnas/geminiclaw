"""A skill de código não pode congelar o event loop do processo do orquestrador.

Revisão de segurança STRIDE (v16-in-process-agents, 6.1): no runtime em processo, todos os
agentes compartilham um único event loop; uma chamada síncrona ao sandbox (que pode levar
minutos) bloquearia os demais agentes, os timeouts e o encerramento.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.skills.code.sandbox import SandboxResult
from src.skills.code.skill import CodeSkill


class _SlowSandbox:
    """Sandbox falso cuja execução bloqueia a thread por um tempo fixo."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def run(self, **kwargs) -> SandboxResult:
        time.sleep(0.5)
        return SandboxResult(stdout="ok", stderr="", exit_code=0, artifacts=[])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_loop_stays_responsive_while_sandbox_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path))
    with patch("src.skills.code.skill.PythonSandbox", _SlowSandbox):
        skill = CodeSkill()

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await skill.run(code="print('ok')", session_id="sess", task_name="tarefa")
    finally:
        task.cancel()

    assert result.success is True
    # Com o sandbox bloqueando o loop, ticks seria ~0; em thread, ~10 em 0,5 s.
    assert ticks >= 5, f"event loop ficou bloqueado durante o sandbox (ticks={ticks})"
