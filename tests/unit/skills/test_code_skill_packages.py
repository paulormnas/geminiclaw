"""CodeSkill com pacotes sob demanda (v16-sandbox-slim-image): repasse ao sandbox e falha de instalação."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.skills.code.sandbox import SandboxResult
from src.skills.code.skill import CodeSkill


class _RecordingSandbox:
    last_kwargs: dict = {}
    result = SandboxResult(stdout="ok", stderr="", exit_code=0, artifacts=[])

    def __init__(self, *args, **kwargs) -> None:
        pass

    def run(self, **kwargs) -> SandboxResult:
        type(self).last_kwargs = kwargs
        return type(self).result


@pytest.fixture
def skill(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path))
    with patch("src.skills.code.skill.PythonSandbox", _RecordingSandbox):
        yield CodeSkill()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_repassa_packages_ao_sandbox(skill) -> None:
    _RecordingSandbox.result = SandboxResult(
        stdout="ok", stderr="", exit_code=0, artifacts=[], packages_installed=["tabulate==0.9.0"]
    )
    result = await skill.run(code="print(1)", session_id="s", task_name="t", packages=["tabulate"])

    assert _RecordingSandbox.last_kwargs["packages"] == ["tabulate"]
    assert "setup_commands" not in _RecordingSandbox.last_kwargs
    assert result.success is True
    assert result.metadata["packages_installed"] == ["tabulate==0.9.0"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_falha_de_instalacao_e_falha_da_execucao(skill) -> None:
    _RecordingSandbox.result = SandboxResult(
        stdout="", stderr="Falha na instalação dos pacotes: x.\nlog", exit_code=1, install_failed=True
    )
    result = await skill.run(code="print(1)", session_id="s", task_name="t", packages=["x"])

    assert result.success is False
    assert "Falha na instalação dos pacotes" in result.error
    assert result.metadata["install_failed"] is True


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("campo", ["session_id", "task_name"])
async def test_skill_recusa_nome_de_pasta_invalido(skill, campo) -> None:
    """I7: a skill valida session_id e task_name antes de criar pastas ou chamar o sandbox."""
    _RecordingSandbox.last_kwargs = {}
    ids = {"session_id": "s", "task_name": "t", campo: "../fora"}
    result = await skill.run(code="print(1)", **ids)

    assert result.success is False
    assert campo in result.error
    assert _RecordingSandbox.last_kwargs == {}
