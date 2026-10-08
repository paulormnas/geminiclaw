"""Integração da skill de código com o registro de execuções (spec execution-provenance; design §4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent_runtime.context import AgentContext, bind_agent_context, current_context
from src.provenance.ledger import ExecutionLedger, get_ledger, set_ledger
from src.provenance.records import status_of
from src.provenance.store import TIPO_INICIO, TIPO_TERMINO, MemoryStore
from src.skills.code.assets import AssetRecord
from src.skills.code.sandbox import ImageInfo, PhaseTiming, SandboxResult
from src.skills.code.skill import PROVENANCE_BEGIN_ERROR, CodeSkill

pytestmark = pytest.mark.unit


class FakeSandbox:
    """Dublê do sandbox: grava arquivos na pasta da tarefa e devolve um ``SandboxResult`` configurável."""

    image = "geminiclaw-sandbox"

    def __init__(self, result: SandboxResult | None = None, files: dict[str, str] | None = None, boom=None, **_kw):
        self.result = result or _ok_result()
        self.files = files or {}
        self.boom = boom
        self.calls = 0

    def run(self, *, output_dir, session_id, task_name, **_kwargs):
        self.calls += 1
        if self.boom is not None:
            raise self.boom
        task_dir = Path(output_dir) / session_id / task_name
        task_dir.mkdir(parents=True, exist_ok=True)
        for name, content in self.files.items():
            (task_dir / name).write_text(content, encoding="utf-8")
        return self.result


def _ok_result(**over) -> SandboxResult:
    base = dict(
        stdout="ok", stderr="", exit_code=0, artifacts=[], image="geminiclaw-sandbox",
        imagem=ImageInfo("geminiclaw-sandbox", "sha256:abc", ["repo@sha256:def"]),
        python_version="3.11.9", pacotes={"numpy": "1.26.4"},
        ativos=[AssetRecord("https://x/y.bin", "a" * 64, "y.bin", 10, True, "download")],
        fases=[PhaseTiming("execute", "2026-10-08T10:00:00+00:00", "2026-10-08T10:00:05+00:00", 0)],
    )
    base.update(over)
    return SandboxResult(**base)


@pytest.fixture
def skill(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr("src.config.PROVENANCE_HASH_CACHE_PATH", str(tmp_path / "cache.db"))
    set_ledger(ExecutionLedger(MemoryStore(), tmp_path / "outputs"))
    with patch("src.skills.code.skill.PythonSandbox", FakeSandbox):
        instance = CodeSkill()
    instance.sandbox = FakeSandbox()
    return instance


@pytest.fixture
def agent_context(tmp_path):
    ctx = AgentContext(
        session_id="s1", agent_session_id="a1", agent_id="developer", mode="auto",
        output_dir=tmp_path / "outputs" / "s1", model="m", task_name="treinar", project_id="proj", subtask_id="sub-1",
    )
    token = bind_agent_context(ctx)
    yield ctx
    current_context.reset(token)


METRICS = json.dumps({"seed": 7, "metrics": {"r2": 0.8, "n": 3, "rotulo": "x"}})
PARAMS = json.dumps({"parameters": {"k": 3}, "seed": 7})


@pytest.mark.asyncio
async def test_execucao_bem_sucedida_registra_inicio_e_termino(skill, agent_context):
    """Scenario: Execução bem-sucedida."""
    skill.sandbox = FakeSandbox(files={"metrics.json": METRICS, "params.json": PARAMS, "grafico.txt": "g"})
    result = await skill.run(code="print(1)", session_id="s1", task_name="treinar")
    assert result.success and result.metadata["provenance_pending"] is False
    ledger = get_ledger()
    start = ledger.store.get(result.metadata["exec_id"], TIPO_INICIO)
    end = ledger.store.get(result.metadata["exec_id"], TIPO_TERMINO)
    assert start is not None and end is not None and end.prev_hash == start.record_hash
    assert result.metadata["record_hash"] == end.record_hash
    body = end.corpo
    assert body["status"] == "sucesso" and body["exit_code"] == 0 and body["seed"] == 7
    assert body["hash_params"] and len(body["hash_codigo"]) == 64
    assert body["metricas"] == {"n": "3", "r2": "0.8"}  # métricas numéricas, como texto
    assert body["imagem"]["id"] == "sha256:abc" and body["pacotes"] == {"numpy": "1.26.4"}
    assert body["ativos"][0]["sha256"] == "a" * 64 and body["ativos"][0]["origem"] == "download"
    assert body["inicio_execucao"] == "2026-10-08T10:00:00+00:00" and body["fim_execucao"].endswith("05+00:00")
    caminhos = {s["caminho"] for s in body["saidas"]}
    assert caminhos == {"s1/treinar/metrics.json", "s1/treinar/params.json", "s1/treinar/grafico.txt"}
    assert body["hash_metrics"] and start.subtask_id == "sub-1" and start.project_id == "proj"
    manifest = json.loads((Path(skill.output_dir) / "s1" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["steps"][0]["exec_id"] == result.metadata["exec_id"]


@pytest.mark.parametrize(
    "sandbox_result, expected",
    [
        (_ok_result(exit_code=1, stderr="Traceback"), ("falha_execucao", None)),
        (_ok_result(exit_code=-1, timed_out=True), ("timeout", None)),
        (_ok_result(exit_code=-1, install_failed=True, fase_falha="install"), ("falha_install", "install")),
        (_ok_result(exit_code=-1, fase_falha="fetch_assets"), ("falha_fetch_assets", "fetch_assets")),
        (_ok_result(exit_code=-1, fase_falha="infra", infra_error="daemon"), ("erro_sandbox", "infra")),
    ],
)
@pytest.mark.asyncio
async def test_termino_em_qualquer_desfecho(skill, agent_context, sandbox_result, expected):
    """Scenarios: Timeout e Falha de instalação."""
    skill.sandbox = FakeSandbox(sandbox_result)
    result = await skill.run(code="print(1)", session_id="s1", task_name="treinar")
    assert not result.success
    end = get_ledger().store.get(result.metadata["exec_id"], TIPO_TERMINO)
    assert (end.corpo["status"], end.corpo["fase_falha"]) == expected


@pytest.mark.asyncio
async def test_excecao_inesperada_gera_termino_erro_orquestrador(skill, agent_context):
    skill.sandbox = FakeSandbox(boom=RuntimeError("daemon caiu"))
    result = await skill.run(code="print(1)", session_id="s1", task_name="treinar")
    assert not result.success and "daemon caiu" in result.error
    end = get_ledger().store.get(result.metadata["exec_id"], TIPO_TERMINO)
    assert end.corpo["status"] == "erro_orquestrador" and end.corpo["erro_tipo"] == "RuntimeError"
    assert end.corpo["imagem"] is None


@pytest.mark.asyncio
async def test_codigo_recusado_pela_validacao_nao_registra(skill, agent_context):
    """Scenario: Código recusado pela validação."""
    result = await skill.run(code="import subprocess\nsubprocess.run(['ls'])", session_id="s1", task_name="treinar")
    assert not result.success and skill.sandbox.calls == 0
    assert get_ledger().store.records("proj") == []


@pytest.mark.asyncio
async def test_sem_registro_de_inicio_nenhum_container_e_criado(skill, agent_context):
    """Scenario: Banco indisponível no início."""
    get_ledger().store.unavailable = True
    result = await skill.run(code="print(1)", session_id="s1", task_name="treinar")
    assert not result.success and skill.sandbox.calls == 0
    assert PROVENANCE_BEGIN_ERROR in result.error and result.metadata["fase_falha"] == "infra"


@pytest.mark.asyncio
async def test_termino_pendente_quando_o_banco_cai_durante_a_execucao(skill, agent_context):
    """Scenario: Banco cai durante a execução — e entra na cadeia na chamada seguinte."""
    store = get_ledger().store

    class DropsAfterRun(FakeSandbox):
        def run(self, **kwargs):
            out = super().run(**kwargs)
            store.unavailable = True
            return out

    skill.sandbox = DropsAfterRun()
    first = await skill.run(code="print(1)", session_id="s1", task_name="treinar")
    assert first.success and first.metadata["provenance_pending"] is True and "record_hash" not in first.metadata
    store.unavailable = False
    skill.sandbox = FakeSandbox()
    second = await skill.run(code="print(2)", session_id="s1", task_name="treinar")
    records = store.records("proj")
    assert [r.tipo for r in records] == [TIPO_INICIO, TIPO_TERMINO, TIPO_INICIO, TIPO_TERMINO]
    assert records[1].exec_id == first.metadata["exec_id"] and records[2].exec_id == second.metadata["exec_id"]
    assert get_ledger().pending_exec_ids("s1", skill.output_dir) == []


@pytest.mark.asyncio
async def test_sem_banco_e_sem_disco_a_skill_falha(skill, agent_context, tmp_path):
    """Scenario: Sem banco e sem disco."""
    store = get_ledger().store

    class DropsAndBlocks(FakeSandbox):
        def run(self, **kwargs):
            out = super().run(**kwargs)
            store.unavailable = True
            (Path(skill.output_dir) / "s1" / "provenance_pending.jsonl").mkdir()  # diretório no lugar do arquivo
            return out

    skill.sandbox = DropsAndBlocks()
    result = await skill.run(code="print(1)", session_id="s1", task_name="treinar")
    assert not result.success and "término não registrado nem guardado localmente" in result.error


@pytest.mark.asyncio
async def test_sem_projeto_a_cadeia_e_da_sessao(skill):
    result = await skill.run(code="print(1)", session_id="solta", task_name="t")
    assert result.success
    assert get_ledger().store.projects_of_session("solta") == ["sem_projeto:solta"]


@pytest.mark.asyncio
async def test_entradas_do_snapshot_entram_no_inicio_com_hash(skill, agent_context):
    snapshot = Path(skill.output_dir) / "s1" / "input_snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "dados.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    result = await skill.run(code="print(1)", session_id="s1", task_name="treinar")
    start = get_ledger().store.get(result.metadata["exec_id"], TIPO_INICIO)
    (entry,) = start.corpo["entradas"]
    assert entry["caminho"] == "s1/input_snapshot/dados.csv" and len(entry["sha256"]) == 64 and entry["tamanho"] == 8


def test_status_de_cada_desfecho():
    assert status_of(_ok_result()) == "sucesso"
    assert status_of(None) == "erro_orquestrador"
    assert status_of(_ok_result(), RuntimeError("x")) == "erro_orquestrador"
    assert status_of(SandboxResult(stdout="", stderr="Pacotes inválidos", exit_code=-1)) == "erro_sandbox"
