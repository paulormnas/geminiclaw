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


def test_padroes_da_avaliacao_de_comunicacao(monkeypatch):
    for name in ("COMM_EVAL_JUDGE_PROVIDER", "COMM_EVAL_JUDGE_MODEL", "COMM_EVAL_JUDGE_CANDIDATES",
                 "COMM_EVAL_ALLOW_EXTERNAL_JUDGE", "COMM_EVAL_MAX_USD", "COMM_EVAL_JUDGE_CONTEXT_CHARS",
                 "COMM_EVAL_CALIBRATION_SIZE", "COMM_EVAL_MIN_KAPPA", "COMM_EVAL_LOOP_MIN_LENGTH"):
        monkeypatch.delenv(name, raising=False)
    import src.config as config

    try:
        config = importlib.reload(config)
        assert config.COMM_EVAL_JUDGE_PROVIDER == "" and config.COMM_EVAL_JUDGE_MODEL == ""
        assert config.COMM_EVAL_JUDGE_CANDIDATES == ""
        assert config.COMM_EVAL_ALLOW_EXTERNAL_JUDGE is False and config.COMM_EVAL_MAX_USD == 0.0
        assert config.COMM_EVAL_JUDGE_CONTEXT_CHARS == 400 and config.COMM_EVAL_CALIBRATION_SIZE == 20
        assert config.COMM_EVAL_MIN_KAPPA == 0.6 and config.COMM_EVAL_LOOP_MIN_LENGTH == 3
    finally:
        importlib.reload(config)


def test_env_example_documenta_a_avaliacao_de_comunicacao():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    for name in ("COMM_EVAL_JUDGE_CANDIDATES", "COMM_EVAL_ALLOW_EXTERNAL_JUDGE", "COMM_EVAL_MAX_USD",
                 "COMM_EVAL_JUDGE_CONTEXT_CHARS", "COMM_EVAL_CALIBRATION_SIZE", "COMM_EVAL_MIN_KAPPA",
                 "COMM_EVAL_LOOP_MIN_LENGTH"):
        assert f"{name}=" in text
