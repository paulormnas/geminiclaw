"""Normalizador determinístico de plano (v16-pipeline-robustness, requisito "Normalização determinística")."""

import pytest

from src.plan_normalizer import normalize_plan

pytestmark = pytest.mark.unit


def _task(**kw):
    base = {"agent_id": "developer", "task_name": "t", "prompt": "p", "validation_criteria": ["c"]}
    base.update(kw)
    return base


def kinds(result):
    return [r.kind for r in result.repairs]


def test_envelope_de_lista():
    """Scenario: Envelope de lista."""
    result = normalize_plan({"tasks": [_task(task_name="a"), _task(task_name="b")]})
    assert [t["task_name"] for t in result.tasks] == ["a", "b"]
    assert "unwrap_envelope" in kinds(result)


def test_dependencia_como_texto():
    """Scenario: Dependência como texto."""
    plan = [_task(task_name="carregar_dados"), _task(task_name="limpar_dados"),
            _task(task_name="modelo", depends_on="carregar_dados, limpar_dados")]
    result = normalize_plan(plan)
    assert result.tasks[2]["depends_on"] == ["carregar_dados", "limpar_dados"]
    assert "coerce_list" in kinds(result)


def test_nome_fora_do_padrao_atualiza_as_dependencias():
    """Scenario: Nome fora do padrão atualiza as dependências."""
    plan = [_task(task_name="Carregar Dados"), _task(task_name="treinar", depends_on=["Carregar Dados"])]
    result = normalize_plan(plan)
    assert result.tasks[0]["task_name"] == "carregar_dados"
    assert result.tasks[1]["depends_on"] == ["carregar_dados"]
    assert "snake_case_name" in kinds(result)


def test_nomes_repetidos():
    """Scenario: Nomes repetidos."""
    result = normalize_plan([_task(task_name="treinar"), _task(task_name="treinar")])
    assert [t["task_name"] for t in result.tasks] == ["treinar", "treinar_2"]
    assert "dedupe_name" in kinds(result)


def test_conteudo_nao_e_inventado():
    """Scenario: Conteúdo não é inventado."""
    plan = [
        _task(task_name="a", task_type="validation", validation_criteria=["modelos comparados"]),
        {"agent_id": "developer", "task_name": "b", "prompt": "p"},
    ]
    result = normalize_plan(plan)
    assert result.tasks[0]["validation_criteria"] == ["modelos comparados"]
    assert "validation_criteria" not in result.tasks[1]


def test_task_name_ausente_e_derivado():
    result = normalize_plan([{"agent_id": "developer", "prompt": "p", "validation_criteria": ["c"]}])
    assert result.tasks[0]["task_name"] == "developer_1"
    assert "derive_task_name" in kinds(result)


def test_sinonimos_de_tipo_e_agente():
    result = normalize_plan([_task(agent_id="Desenvolvedor", task_type="Model Implementation")])
    assert result.tasks[0]["agent_id"] == "developer"
    assert result.tasks[0]["task_type"] == "model_impl"


def test_task_type_sem_equivalente_e_removido_e_registrado():
    result = normalize_plan([_task(task_type="magia")])
    assert "task_type" not in result.tasks[0]
    assert "normalize_task_type" in kinds(result)


def test_dependencia_com_grafia_diferente_e_corrigida():
    plan = [_task(task_name="carregar_dados"), _task(task_name="m", depends_on=["Carregar-Dados"])]
    result = normalize_plan(plan)
    assert result.tasks[1]["depends_on"] == ["carregar_dados"]
    assert not result.unrecoverable


def test_dependencia_inexistente_nao_e_reparada():
    result = normalize_plan([_task(task_name="m", depends_on=["fantasma"])])
    assert any("fantasma" in u for u in result.unrecoverable)


def test_autodependencia_removida():
    result = normalize_plan([_task(task_name="m", depends_on=["m"])])
    assert result.tasks[0]["depends_on"] == []
    assert "break_self_dependency" in kinds(result)


def test_ciclo_entre_subtarefas_nao_e_reparado():
    plan = [_task(task_name="a", depends_on=["b"]), _task(task_name="b", depends_on=["a"])]
    result = normalize_plan(plan)
    assert any("circular" in u for u in result.unrecoverable)


def test_plano_vazio_ou_invalido():
    assert normalize_plan([]).unrecoverable
    assert normalize_plan("texto").unrecoverable


def test_normalizar_duas_vezes_nao_gera_novos_reparos():
    plan = {"plan": [_task(task_name="Carregar Dados", depends_on="x")]}
    first = normalize_plan(plan)
    second = normalize_plan(first.tasks)
    assert second.repairs == []
