"""Formato do plano com hipóteses, decisões e respostas (v18-hypothesis-loop, tarefa 1.1, cenário 6.9)."""

from __future__ import annotations

import pytest

from src.knowledge.hypotheses import PlanExtras, legacy_hypotheses, split_plan
from src.plan_normalizer import normalize_plan

pytestmark = pytest.mark.unit

TASK = {"agent_id": "developer", "task_name": "treino", "task_type": "model_impl", "prompt": "p",
        "validation_criteria": ["r2 > 0.8"], "hypothesis_ref": "h1"}


def _plan(**over):
    base = {
        "hipoteses": [{"ref": "h1", "enunciado": "GB supera a regressão linear", "justificativa": "J",
                       "custo_estimado": "baixo", "abordagem": {"nome": "gradient boosting", "tipo": "algoritmo"}}],
        "decisoes": [{"contexto": "modelo inicial", "escolhido": {"tipo": "Hipotese", "ref": "h1"},
                      "descartados": [{"tipo": "Abordagem", "nome": "rede profunda", "motivo": "dataset pequeno"}],
                      "criterio": "evidencia_previa", "justificativa": "J"}],
        "respostas_sugestoes": [{"sugestao_id": "abc123", "decisao": "aceita", "motivo": "faz sentido",
                                 "hipotese_ref": "h1"}],
        "subtarefas": [TASK],
    }
    base.update(over)
    return base


def test_formato_novo_separa_subtarefas_e_declaracoes():
    """Scenario: Plano com hipótese — o envelope é separado em subtarefas e declarações."""
    subtasks, extras = split_plan(_plan())
    assert subtasks == [TASK]
    assert extras.novo_formato and not extras.vazio
    assert extras.hipoteses[0].ref == "h1" and extras.hipoteses[0].custo == "baixo"
    assert extras.hipoteses[0].abordagem == {"nome": "gradient boosting", "tipo": "algoritmo"}
    assert extras.decisoes[0].descartados[0].nome == "rede profunda"
    assert extras.respostas[0].decisao == "aceita" and extras.respostas[0].hipotese_ref == "h1"
    assert normalize_plan(subtasks).tasks[0]["hypothesis_ref"] == "h1"  # o normalizador preserva a referência


def test_plano_no_formato_antigo_continua_funcionando():
    """Scenario: Plano no formato antigo (6.9) — lista simples e envelope antigo passam inalterados."""
    old = [dict(TASK)]
    assert split_plan(old) == (old, PlanExtras())
    envelope = {"tasks": [dict(TASK)]}
    assert split_plan(envelope) == (envelope, PlanExtras())
    assert normalize_plan(split_plan(envelope)[0]).tasks[0]["task_name"] == "treino"


def test_entradas_invalidas_sao_descartadas_sem_quebrar():
    raw = _plan(
        hipoteses=[{"ref": "../x", "enunciado": "a"}, "texto", {"ref": "ok", "enunciado": ""},
                   {"ref": "h2", "enunciado": "Válida", "custo_estimado": "enorme"}],
        decisoes=[{"contexto": "c"},
                  {"escolhido": {"tipo": "Outro", "ref": "h1"}, "contexto": "c", "justificativa": "j"}],
        respostas_sugestoes=[{"sugestao_id": "a b", "decisao": "aceita"}, {"sugestao_id": "ok", "decisao": "talvez"}],
    )
    _, extras = split_plan(raw)
    assert [h.ref for h in extras.hipoteses] == ["h2"]
    assert extras.hipoteses[0].custo == "medio"  # valor desconhecido cai no padrão
    assert extras.decisoes == () and extras.respostas == ()
    assert extras.descartados_do_plano >= 6


def test_texto_do_plano_e_limpo_e_limitado(monkeypatch):
    """Dado não confiável: controles viram espaço e o tamanho é limitado."""
    monkeypatch.setattr("src.config.HYPOTHESIS_TEXT_MAX_CHARS", 50)
    raw = _plan(hipoteses=[{"ref": "h1", "enunciado": "linha1\n\x1b[31mlinha2" + "x" * 500, "justificativa": "j"}])
    _, extras = split_plan(raw)
    text = extras.hipoteses[0].enunciado
    assert "\n" not in text and "\x1b" not in text and len(text) <= 50


def test_origem_declarada_pelo_llm_e_ignorada():
    """A origem (``pesquisador``) nunca vem do plano: o campo nem existe no modelo."""
    raw = _plan(hipoteses=[{"ref": "h1", "enunciado": "X", "justificativa": "j", "origem": "pesquisador"}])
    _, extras = split_plan(raw)
    assert not hasattr(extras.hipoteses[0], "origem")


def test_limites_por_plano(monkeypatch):
    monkeypatch.setattr("src.config.HYPOTHESES_MAX_PER_PLAN", 2)
    raw = _plan(hipoteses=[{"ref": f"h{i}", "enunciado": f"E{i}"} for i in range(10)])
    _, extras = split_plan(raw)
    assert len(extras.hipoteses) == 2


def test_formato_antigo_promove_o_texto_de_hipotese_a_hipotese_formal():
    tasks = [
        {"task_name": "a", "hypothesis": "O modelo atinge 0,85", "scientific_rationale": "porque"},
        {"task_name": "b", "hypothesis": "o modelo atinge 0,85"},
        {"task_name": "c", "hypothesis": ""},
    ]
    declared = legacy_hypotheses(tasks)
    assert len(declared) == 1 and declared[0].justificativa == "porque" and declared[0].ref.startswith("legado_")
