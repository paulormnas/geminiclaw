"""Resolução das dependências a montar no sandbox (v18.7-dependency-artifacts §2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agent_runtime.types import AgentResult, AgentTask
from src.orchestration.dependency_artifacts import dependency_names, resolve_dependency_mounts
from src.utils.agent_context import AgentContext, DependencyMount
from tests.support.exploration_world import hyp, plan, task
from tests.unit.subtask_contract.test_contract_dispatch import ContractHarness

pytestmark = pytest.mark.unit

CHAIN = {"avaliar": ["treinar"], "treinar": ["dividir_dados"], "dividir_dados": []}


def _folders(root: Path, session: str, names):
    for n in names:
        (root / session / n).mkdir(parents=True)
        (root / session / n / "x.csv").write_text("1", encoding="utf-8")


def test_dependencia_direta_e_transitiva(tmp_path):
    _folders(tmp_path, "s1", ["treinar", "dividir_dados"])
    concluded = {"treinar": "s1", "dividir_dados": "s1"}
    mounts = resolve_dependency_mounts("avaliar", CHAIN, concluded, tmp_path, "transitivas")
    assert [m.task_name for m in mounts] == ["treinar", "dividir_dados"]
    assert mounts[0] == DependencyMount("treinar", tmp_path / "s1" / "treinar", "s1")


def test_escopo_direto(tmp_path):
    _folders(tmp_path, "s1", ["treinar", "dividir_dados"])
    mounts = resolve_dependency_mounts("avaliar", CHAIN, {"treinar": "s1", "dividir_dados": "s1"}, tmp_path, "diretas")
    assert [m.task_name for m in mounts] == ["treinar"]


def test_dependencia_da_sessao_anterior(tmp_path):
    _folders(tmp_path, "s1", ["dividir_dados"])
    _folders(tmp_path, "s2", ["treinar"])
    mounts = resolve_dependency_mounts(
        "avaliar", CHAIN, {"treinar": "s2", "dividir_dados": "s1"}, tmp_path, "transitivas"
    )
    assert {(m.task_name, m.session_id) for m in mounts} == {("treinar", "s2"), ("dividir_dados", "s1")}


def test_dependencia_sem_pasta_ou_nao_concluida_nao_e_montada(tmp_path):
    (tmp_path / "s1" / "treinar").mkdir(parents=True)  # concluída; dividir_dados nunca gravou pasta
    mounts = resolve_dependency_mounts("avaliar", CHAIN, {"treinar": "s1", "dividir_dados": "s1"}, tmp_path)
    assert [m.task_name for m in mounts] == ["treinar"]
    assert resolve_dependency_mounts("avaliar", CHAIN, {}, tmp_path) == ()


def test_teto_nao_trunca_a_lista(tmp_path):
    names = [f"d{i}" for i in range(17)]
    _folders(tmp_path, "s1", names)
    depends = {"consumidora": names, **{n: [] for n in names}}
    mounts = resolve_dependency_mounts("consumidora", depends, {n: "s1" for n in names}, tmp_path)
    assert len(mounts) == 17  # a recusa por DEPENDENCY_ARTIFACTS_MAX_MOUNTS é do sandbox (seção 3)


def test_ciclo_e_autodependencia_nao_geram_montagem_da_propria_subtarefa(tmp_path):
    _folders(tmp_path, "s1", ["a", "b"])
    depends = {"a": ["b"], "b": ["a"]}
    mounts = resolve_dependency_mounts("a", depends, {"a": "s1", "b": "s1"}, tmp_path)
    assert [m.task_name for m in mounts] == ["b"]
    assert dependency_names("a", {"a": ["a"]}, "diretas") == []


def test_desligado_nao_monta(tmp_path):
    _folders(tmp_path, "s1", ["treinar"])
    with patch("src.config.DEPENDENCY_ARTIFACTS_ENABLED", False):
        assert resolve_dependency_mounts("avaliar", CHAIN, {"treinar": "s1"}, tmp_path) == ()


def test_contexto_do_agente_guarda_as_montagens():
    ctx = AgentContext(session_id="s", agent_session_id="a", agent_id="developer", mode="auto", output_dir=Path("/x"),
                       model="m", dependency_dirs=(DependencyMount("t", Path("/x/s/t"), "s"),))
    assert ctx.dependency_dirs[0].task_name == "t"
    assert AgentContext(session_id="s", agent_session_id="a", agent_id="d", mode="m", output_dir=Path("/x"),
                        model="m").dependency_dirs == ()


class MountHarness(ContractHarness):
    """Guarda as montagens que chegam ao runtime em cada execução do Developer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mounts: dict[str, tuple] = {}

    async def _run(self, task_, ctx) -> AgentResult:
        if task_.agent_id == "developer":
            self.mounts[task_.task_name] = tuple(task_.dependency_mounts)
        return await super()._run(task_, ctx)


@pytest.mark.asyncio
async def test_laco_entrega_as_dependencias_ao_runtime(tmp_path):
    p = plan(
        [task("dividir_dados"), task("treinar", depends_on=["dividir_dados"]),
         task("avaliar", depends_on=["treinar"])],
        [hyp("h1")],
    )
    h = MountHarness(tmp_path, plans=[p])
    await h.run()
    assert h.mounts["dividir_dados"] == ()
    assert [m.task_name for m in h.mounts["treinar"]] == ["dividir_dados"]
    assert [m.task_name for m in h.mounts["avaliar"]] == ["treinar", "dividir_dados"]
    assert all(m.source.is_dir() and m.session_id == h.w.sid for m in h.mounts["avaliar"])


@pytest.mark.asyncio
async def test_laco_com_montagem_desligada(tmp_path):
    p = plan([task("a"), task("b", depends_on=["a"])], [hyp("h1")])
    h = MountHarness(tmp_path, plans=[p])
    with patch("src.config.DEPENDENCY_ARTIFACTS_ENABLED", False):
        await h.run()
    assert h.mounts["b"] == ()


def test_agent_task_tem_o_campo_das_montagens():
    t = AgentTask(agent_id="developer", prompt="x")
    assert t.dependency_mounts == () and SimpleNamespace  # campo presente e vazio por padrão
