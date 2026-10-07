"""CodeSkill com as fases do sandbox (v18.5-sandbox-phases): parâmetros, erro acionável e paralelismo."""

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent_runtime.context import AgentContext, current_context
from src.skills.code.sandbox import NETWORK_UNDECLARED_MESSAGE, SandboxResult
from src.skills.code.skill import CodeSkill


class _RecordingSandbox:
    last_kwargs: dict = {}
    result = SandboxResult(stdout="ok", stderr="", exit_code=0, artifacts=[])
    delay = 0.0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def run(self, **kwargs) -> SandboxResult:
        type(self).last_kwargs = kwargs
        time.sleep(type(self).delay)
        return type(self).result


@pytest.fixture
def skill(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path))
    _RecordingSandbox.delay = 0.0
    _RecordingSandbox.result = SandboxResult(stdout="ok", stderr="", exit_code=0, artifacts=[])
    with patch("src.skills.code.skill.PythonSandbox", _RecordingSandbox):
        yield CodeSkill()


@pytest.mark.unit
def test_schema_declara_assets_e_needs_network(skill) -> None:
    props = skill.parameters_schema["properties"]
    assert props["assets"]["items"]["required"] == ["url", "destino"]
    assert props["needs_network"]["type"] == "boolean"
    assert "NÃO tem acesso à rede" in skill.description and "/assets/" in skill.description


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_repassa_assets_e_needs_network(skill) -> None:
    assets = [{"url": "https://exemplo.org/p.bin", "destino": "p.bin"}]
    await skill.run(code="print(1)", session_id="s", task_name="t", assets=assets, needs_network=True)

    assert _RecordingSandbox.last_kwargs["assets"] == assets
    assert _RecordingSandbox.last_kwargs["needs_network"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_download_dentro_do_script_devolve_mensagem_fixa(skill) -> None:
    """Cenário: Download dentro do script. A mensagem não repete a URL nem o stderr."""
    _RecordingSandbox.result = SandboxResult(
        stdout="", exit_code=1, download_nao_declarado=True, fase_falha="execute",
        stderr="urllib.error.URLError: <urlopen error> https://exemplo.org/pesos.bin",
    )
    result = await skill.run(code="print(1)", session_id="s", task_name="t")

    assert result.success is False
    assert result.error == NETWORK_UNDECLARED_MESSAGE
    assert "declare-os no parâmetro `assets`" in result.error
    assert "exemplo.org" not in result.error
    assert result.metadata["download_nao_declarado"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_falha_que_nao_e_de_rede_segue_o_fluxo_normal(skill) -> None:
    """Cenário: Falha que não é de rede."""
    _RecordingSandbox.result = SandboxResult(
        stdout="", exit_code=1, stderr="Traceback...\nValueError: x", fase_falha="execute"
    )
    result = await skill.run(code="print(1)", session_id="s", task_name="t")

    assert result.error == "Traceback...\nValueError: x"
    assert result.metadata["download_nao_declarado"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nota_de_rede_negada_acompanha_o_erro(skill) -> None:
    """Cenário: Uma entrada não compartilhável. O erro informa a condição que falhou."""
    _RecordingSandbox.result = SandboxResult(
        stdout="", exit_code=1, stderr="boom", fase_falha="execute",
        nota_rede="há entradas não compartilháveis em /inputs; a execução roda sem rede",
    )
    result = await skill.run(code="print(1)", session_id="s", task_name="t", needs_network=True)

    assert "entradas não compartilháveis" in result.error
    assert result.metadata["rede_na_execucao"] is False


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("fase", ["fetch_assets", "infra"])
async def test_falha_de_fase_preserva_a_mensagem_e_a_fase(skill, fase) -> None:
    _RecordingSandbox.result = SandboxResult(stdout="", exit_code=-1, stderr="mensagem da fase", fase_falha=fase)
    result = await skill.run(code="print(1)", session_id="s", task_name="t")

    assert result.success is False and result.error == "mensagem da fase"
    assert result.metadata["fase_falha"] == fase


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sessoes_anteriores_do_contexto_vao_ao_sandbox(skill, tmp_path) -> None:
    ctx = AgentContext(
        session_id="s", agent_session_id="a", agent_id="developer", mode="auto",
        output_dir=tmp_path, model="m", readable_dirs=(tmp_path / "antiga",),
    )
    token = current_context.set(ctx)
    try:
        await skill.run(code="print(1)", session_id="s", task_name="t")
    finally:
        current_context.reset(token)

    assert _RecordingSandbox.last_kwargs["prior_dirs"] == [tmp_path / "antiga"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duas_subtarefas_em_paralelo(skill) -> None:
    """Cenário: Duas subtarefas em paralelo. O sandbox roda em thread: o total é menor que a soma."""
    _RecordingSandbox.delay = 0.5
    started = time.monotonic()
    results = await asyncio.gather(
        skill.run(code="print(1)", session_id="s", task_name="t1"),
        skill.run(code="print(2)", session_id="s", task_name="t2"),
    )
    elapsed = time.monotonic() - started

    assert all(r.success for r in results)
    assert elapsed < 0.9


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_chama_o_sandbox_via_to_thread(skill) -> None:
    """Cenário: Duas subtarefas em paralelo (determinístico). O sandbox roda fora da thread do event loop."""
    import threading

    threads: list[int] = []
    original = _RecordingSandbox.run

    def run_recording_thread(self, **kwargs):
        threads.append(threading.get_ident())
        return original(self, **kwargs)

    with patch.object(_RecordingSandbox, "run", run_recording_thread):
        await asyncio.gather(
            skill.run(code="print(1)", session_id="s", task_name="t1"),
            skill.run(code="print(2)", session_id="s", task_name="t2"),
        )

    assert len(threads) == 2
    assert threading.get_ident() not in threads  # nenhuma execução bloqueou o event loop
