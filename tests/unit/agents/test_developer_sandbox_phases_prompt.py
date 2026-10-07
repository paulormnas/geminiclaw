"""Instrução do Developer sobre as fases do sandbox (v18.5-sandbox-phases, tasks 4.4)."""

import pytest


@pytest.mark.unit
def test_instrucao_orienta_inputs_assets_e_sem_downloads() -> None:
    from agents.developer.agent import AGENT_INSTRUCTION

    assert "/inputs/" in AGENT_INSTRUCTION
    assert "`assets`" in AGENT_INSTRUCTION and "/assets/<destino>" in AGENT_INSTRUCTION
    assert "nunca baixe" in AGENT_INSTRUCTION.lower()
    assert "SEM rede" in AGENT_INSTRUCTION
