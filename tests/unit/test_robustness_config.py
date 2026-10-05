"""Padrões das variáveis de robustez do pipeline (v16-pipeline-robustness §7)."""

import importlib

import pytest

pytestmark = pytest.mark.unit

ENV_VARS = (
    "PLAN_NORMALIZER_ENABLED", "PLAN_REJECTION_STALL_LIMIT", "ARTIFACT_MATCH_MODE",
    "CIRCUIT_BREAKER_STALL_CYCLES", "MAX_PLANNING_RUNS_PER_SESSION", "MAX_AGENT_RUNS_PER_SESSION",
    "MAX_CONTAINERS_PER_SESSION",
)


def test_padroes_do_design(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    import src.config as config

    try:
        config = importlib.reload(config)
        assert config.PLAN_NORMALIZER_ENABLED is True
        assert config.PLAN_REJECTION_STALL_LIMIT == 2
        assert config.ARTIFACT_MATCH_MODE == "tolerant"
        assert config.CIRCUIT_BREAKER_STALL_CYCLES == 2
        assert config.MAX_PLANNING_RUNS_PER_SESSION == 20
        assert config.MAX_AGENT_RUNS_PER_SESSION == 30
    finally:
        importlib.reload(config)


def test_env_example_documenta_as_variaveis():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    for name in ("PLAN_NORMALIZER_ENABLED", "PLAN_REJECTION_STALL_LIMIT", "ARTIFACT_MATCH_MODE",
                 "CIRCUIT_BREAKER_STALL_CYCLES", "MAX_PLANNING_RUNS_PER_SESSION"):
        assert f"{name}=" in text
