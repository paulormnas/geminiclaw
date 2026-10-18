"""Padrões das variáveis do contrato da subtarefa (v18.7-subtask-contract §1, design §9)."""

import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DEFAULTS = {
    "SUBTASK_CONTRACT_ENABLED": True,
    "CONTRACT_TASK_MAX_CHARS": 4000,
    "CONTRACT_FIELD_MAX_CHARS": 1500,
    "REVIEW_INTEGRITY_ALWAYS": True,
    "REVIEW_SCRIPT_MAX_CHARS": 6000,
    "REVIEW_OBSERVATIONS_MAX": 10,
    "PLAN_ARTIFACT_COLLISION_CHECK": True,
}


def test_padroes_do_design(monkeypatch):
    for name in DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    import src.config as config

    try:
        config = importlib.reload(config)
        for name, value in DEFAULTS.items():
            assert getattr(config, name) == value, name
    finally:
        importlib.reload(config)


def test_contrato_desligado_por_ambiente(monkeypatch):
    monkeypatch.setenv("SUBTASK_CONTRACT_ENABLED", "false")
    import src.config as config

    try:
        assert importlib.reload(config).SUBTASK_CONTRACT_ENABLED is False
    finally:
        monkeypatch.delenv("SUBTASK_CONTRACT_ENABLED")
        importlib.reload(config)


def test_env_example_documenta_as_variaveis():
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    for name, value in DEFAULTS.items():
        expected = str(value).lower() if isinstance(value, bool) else str(value)
        assert f"{name}={expected}" in text
