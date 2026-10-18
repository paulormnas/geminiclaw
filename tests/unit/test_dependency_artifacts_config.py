"""Variáveis de ``v18.7-dependency-artifacts`` (§1, design §8)."""

import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DEFAULTS = {
    "DEPENDENCY_ARTIFACTS_ENABLED": True,
    "DEPENDENCY_ARTIFACTS_SCOPE": "transitivas",
    "DEPENDENCY_ARTIFACTS_MAX_MOUNTS": 16,
    "DEPENDENCY_ARTIFACTS_LIST_MAX": 20,
}


def _reload():
    import src.config as config

    return importlib.reload(config)


def test_padroes_do_design(monkeypatch):
    for name in DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    try:
        config = _reload()
        for name, value in DEFAULTS.items():
            assert getattr(config, name) == value, name
    finally:
        _reload()


@pytest.mark.parametrize(
    "name,value",
    [("DEPENDENCY_ARTIFACTS_SCOPE", "todas"), ("DEPENDENCY_ARTIFACTS_MAX_MOUNTS", "0"),
     ("DEPENDENCY_ARTIFACTS_LIST_MAX", "0")],
)
def test_valor_invalido_falha_na_inicializacao(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    try:
        with pytest.raises(ValueError):
            _reload()
    finally:
        monkeypatch.delenv(name)
        _reload()


def test_escopo_direto_e_aceito(monkeypatch):
    monkeypatch.setenv("DEPENDENCY_ARTIFACTS_SCOPE", "DIRETAS")
    try:
        assert _reload().DEPENDENCY_ARTIFACTS_SCOPE == "diretas"
    finally:
        monkeypatch.delenv("DEPENDENCY_ARTIFACTS_SCOPE")
        _reload()


def test_env_example_documenta_as_variaveis():
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    for name, value in DEFAULTS.items():
        expected = str(value).lower() if isinstance(value, bool) else str(value)
        assert f"{name}={expected}" in text
