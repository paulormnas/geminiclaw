"""``v18.6-hypothesis-closure``: resultado negativo como progresso, veredito, fechamento e evidência das afirmações.

Um teste por ``#### Scenario`` da spec ``hypothesis-loop`` (nome do cenário no docstring). Sem rede, LLM real, Docker
ou banco: grafo em memória, provedor LLM e orquestrador simulados.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator.agent import ReviewResult, ValidatorAgent
from src.artifacts.subtask_output import negative_result_feedback
from src.claims.decompose import Sentence
from src.claims.evidence import report_evidence_builder, session_results_item
from src.claims.model import Conclusao
from src.knowledge import vocabulary
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion import SessionContext, SubtaskInput, ingest_session_start, ingest_subtask
from src.knowledge.projects import ProblemDraft, confirm_problem, create_project
from src.knowledge.provenance import Actor
from src.knowledge.service import KnowledgeService
from src.knowledge.verdict import VerdictParams
from src.knowledge.vocabulary import seed_vocabulary
from src.llm.base import LLMResponse
from src.orchestration.autonomous_loop import AutonomousLoop, CycleProgress, succeeded_task_names
from src.orchestration.orchestrator import AgentResult, AgentTask
from src.report.claims_report import ensure_claims_file
from src.report.operation_metrics import HypothesisClosureReader
from tests.support.curator_graph import ORQ, RESEARCHER
from tests.support.exploration_world import LoopHarness, hyp, plan, task

pytestmark = pytest.mark.unit

FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "cnpq_areas_fixture.csv"
REAL_METRICS = vocabulary.DEFAULT_VOCABULARY_DIR / vocabulary.METRICS_FILENAME


# --- Revisão: resultado negativo ----------------------------------------------------------------------------------


def _write(root: Path, rel: str, content) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _agent(reply: str = '{"status": "pass", "feedback": "ok", "issues": []}'):
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text=reply))
    return ValidatorAgent(provider=provider), provider


async def _review(agent, root, criteria, *, hypothesis_id="hyp-1", expected=None):
    t = AgentTask(agent_id="developer", prompt="x", task_name="treinar_rl", validation_criteria=criteria,
                  expected_artifacts=expected or [], hypothesis_id=hypothesis_id)
    with patch("src.agents.validator.agent.record_llm_call"):
        return await agent.review_result(task=t, response_text="ok", output_dir=root)


CRITERION = "acurácia no teste >= 0.95"


@pytest.mark.asyncio
async def test_acuracia_abaixo_do_alvo_numa_subtarefa_com_hipotese(tmp_path):
    """Scenario: Acurácia abaixo do alvo numa subtarefa com hipótese."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    _write(tmp_path, "treinar_rl/modelo.txt", "modelo")
    agent, _ = _agent()
    review = await _review(agent, tmp_path, [CRITERION], expected=["modelo.txt"])
    assert review.status == "fail" and review.outcome == "resultado_negativo"
    assert review.negative_findings == [
        {"metric": "accuracy", "value": 0.933, "operator": ">=", "threshold": 0.95}
    ]


@pytest.mark.asyncio
async def test_subtask_review_registra_o_outcome(tmp_path):
    """Scenario: Acurácia abaixo do alvo (evento `subtask_review` com `outcome`)."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    agent, _ = _agent()
    orchestrator = MagicMock()
    orchestrator.validator = agent
    orchestrator.output_manager.list_artifacts.return_value = []
    orchestrator.output_manager.base_dir = tmp_path.parent
    telemetry = MagicMock()
    loop = AutonomousLoop(orchestrator)
    t = AgentTask(agent_id="developer", prompt="x", task_name="treinar_rl", validation_criteria=[CRITERION],
                  hypothesis_id="hyp-1")
    result = AgentResult(agent_id="developer", session_id="s", status="success", response={"text": "ok"})
    with patch("src.observability.telemetry.get_telemetry", return_value=telemetry), \
            patch("src.agents.validator.agent.record_llm_call"):
        review = await loop._review_subtask(t, result, tmp_path.name)
    assert review["outcome"] == "resultado_negativo" and review["negative_findings"]
    payload = telemetry.record_agent_event.call_args.kwargs["payload"]
    assert payload["outcome"] == "resultado_negativo"


@pytest.mark.asyncio
async def test_metrica_ausente_nao_e_resultado_negativo(tmp_path):
    """Scenario: Métrica ausente não é resultado negativo."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"f1": 0.9}})
    review = await _review(_agent()[0], tmp_path, [CRITERION])
    assert review.status == "fail" and review.outcome == "reprovado" and review.negative_findings == []


@pytest.mark.asyncio
async def test_artefato_ausente_nao_e_resultado_negativo(tmp_path):
    """Scenario: Artefato ausente não é resultado negativo."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    review = await _review(_agent()[0], tmp_path, [CRITERION], expected=["modelo_que_nao_existe.pkl"])
    assert review.status == "fail" and review.outcome == "reprovado"


@pytest.mark.asyncio
async def test_subtarefa_sem_hipotese(tmp_path):
    """Scenario: Subtarefa sem hipótese."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    review = await _review(_agent()[0], tmp_path, [CRITERION], hypothesis_id="")
    assert review.status == "fail" and review.outcome == "reprovado"


@pytest.mark.asyncio
async def test_recurso_desligado(tmp_path, monkeypatch):
    """Scenario: Recurso desligado."""
    monkeypatch.setattr("src.config.NEGATIVE_RESULT_AS_PROGRESS", False)
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    review = await _review(_agent()[0], tmp_path, [CRITERION])
    assert review.status == "fail" and review.outcome == "reprovado"


@pytest.mark.asyncio
async def test_criterio_restante_reprovado_pelo_revisor_continua_reprovado(tmp_path):
    """Condição 4 do design §1: critério restante reprovado pelo revisor LLM mantém `reprovado`."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    agent, _ = _agent('{"status": "fail", "feedback": "falta o gráfico", "issues": ["sem gráfico"]}')
    review = await _review(agent, tmp_path, [CRITERION, "gráfico de confusão salvo"])
    assert review.outcome == "reprovado"
    agent, _ = _agent()
    review = await _review(agent, tmp_path, [CRITERION, "gráfico de confusão salvo"])
    assert review.outcome == "resultado_negativo"


# --- Laço: concluded_negative ---------------------------------------------------------------------------------


NEGATIVE_REVIEW = {
    "status": "fail", "outcome": "resultado_negativo", "issues": ["acuracia"], "feedback": "", "verified": True,
    "negative_findings": [{"metric": "acuracia", "value": 0.933, "operator": ">=", "threshold": 0.95}],
    "resolved_artifacts": {},
}


def _loop_with(execute, planning):
    orchestrator = MagicMock()
    orchestrator._execute_agent = execute
    orchestrator._run_planning_loop = planning
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    return AutonomousLoop(orchestrator)


@pytest.mark.asyncio
async def test_dependente_roda_e_a_subtarefa_negativa_nao_repete():
    """Scenario: Dependente roda."""
    ran: list[str] = []

    async def execute(t, master_session_id=None):
        ran.append(t.task_name)
        return AgentResult(agent_id=t.agent_id, session_id="s1", status="success", response={"text": "ok"})

    tasks = [
        AgentTask(agent_id="base", prompt="treinar", task_name="treinar_rl", validation_criteria=["acuracia >= 0.95"],
                  hypothesis_id="h2"),
        AgentTask(agent_id="base", prompt="comparar", task_name="comparar", depends_on=["treinar_rl"]),
    ]
    loop = _loop_with(execute, AsyncMock(return_value=tasks))

    async def review(t, result, sid, attempt=1):
        return dict(NEGATIVE_REVIEW)

    with patch("src.orchestration.autonomous_loop.get_telemetry", return_value=MagicMock()), \
            patch("src.config.REVIEW_ENABLED", True), patch("src.config.REVIEW_MODE", "per_subtask"), \
            patch.object(loop, "_review_subtask", side_effect=review), \
            patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
        result = await loop.run("tarefa", "exec_neg")
    assert ran.count("treinar_rl") == 1 and ran.count("comparar") == 1
    assert ran.index("treinar_rl") < ran.index("comparar")
    assert result.succeeded >= 2


def test_disjuntor_nao_dispara_com_resultados_negativos_novos():
    """Scenario: Disjuntor não dispara."""
    cycle1 = {"a": {"status": "concluded_negative"}, "x": {"status": "failed"}}
    cycle2 = {"b": {"status": "concluded_negative"}, "x": {"status": "failed"}}
    p1 = CycleProgress(frozenset(succeeded_task_names(cycle1)), frozenset({"x:agent:1"}))
    p2 = CycleProgress(frozenset(succeeded_task_names(cycle2)), frozenset({"x:agent:1"}))
    assert succeeded_task_names(cycle1) == ["a"]
    assert p2.advanced_from(p1)  # só há progresso novo (resultado negativo), com a mesma assinatura de erro


@pytest.mark.asyncio
async def test_feedback_ao_researcher_cita_hipotese_valor_e_limiar():
    """Scenario: Feedback ao Researcher."""
    feedbacks: list[str | None] = []

    async def planning(*args, **kwargs):
        feedbacks.append(kwargs.get("execution_feedback"))
        if len(feedbacks) == 1:
            return [
                AgentTask(agent_id="base", prompt="a", task_name="treinar_rl", validation_criteria=["acuracia >= 0.95"],
                          hypothesis_id="h2", hypothesis_ref="h2"),
                AgentTask(agent_id="base", prompt="b", task_name="quebra"),
                AgentTask(agent_id="base", prompt="c", task_name="depende", depends_on=["quebra"]),
            ]
        return [AgentTask(agent_id="base", prompt="d", task_name="outra_abordagem")]

    async def execute(t, master_session_id=None):
        status = "error" if t.task_name == "quebra" else "success"
        return AgentResult(agent_id=t.agent_id, session_id="s1", status=status, response={"text": "ok"},
                           error="falhou" if status == "error" else None)

    loop = _loop_with(execute, AsyncMock(side_effect=planning))

    async def review(t, result, sid, attempt=1):
        return dict(NEGATIVE_REVIEW)

    from src.orchestration.usage import UsageBudget

    budget = UsageBudget(max_tokens=500_000, max_minutes=120, max_task_retries=1, max_connection_retries=20,
                         closing_reserve_pct=0.05)
    with patch("src.orchestration.autonomous_loop.get_telemetry", return_value=MagicMock()), \
            patch("src.config.REVIEW_ENABLED", True), patch("src.config.REVIEW_MODE", "per_subtask"), \
            patch.object(loop, "_review_subtask", side_effect=review), \
            patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
        await loop.run("tarefa", "exec_fb", budget=budget)
    assert len(feedbacks) >= 2
    feedback = feedbacks[1] or ""
    assert "h2" in feedback and "0.933" in feedback and "0.95" in feedback and "outra abordagem" in feedback


def test_negative_result_feedback_texto():
    text = negative_result_feedback({"t": {"hypothesis": "h2", "findings": NEGATIVE_REVIEW["negative_findings"]}})
    assert "Resultado negativo: h2 (subtarefa t): acuracia = 0.933 < 0.95" in text


# --- Ingestão ------------------------------------------------------------------------------------------------------


SESSION = "sessao-teste"


def _seeded_store(tmp_path_factory) -> InMemoryGraphStore:
    vocab_dir = tmp_path_factory.mktemp("vocab")
    shutil.copy(FIXTURE_CSV, vocab_dir / vocabulary.CNPQ_FILENAME)
    shutil.copy(REAL_METRICS, vocab_dir / vocabulary.METRICS_FILENAME)
    store = InMemoryGraphStore()
    seed_vocabulary(store, vocabulary_dir=vocab_dir)
    return store


def _world(store: InMemoryGraphStore, metric: str):
    pid = create_project(store, "Projeto de teste", "Objetivo", [])
    draft = ProblemDraft(titulo="T", resumo="R", metrica=metric, alvo=0.95, delta_min=0.01)
    problem_id = confirm_problem(store, pid, draft, sentido_metrica="maior_melhor")
    ctx = SessionContext(project_id=pid, session_id=SESSION, modo="auto", inicio="2026-10-13T10:00:00+00:00",
                         no_execucao="no-1")
    ingest_session_start(store, ctx)
    hid = store.create_node(
        "Hipotese",
        {"projeto_id": pid, "sessao_id": SESSION, "enunciado": "RL atinge 0,95", "justificativa": "J",
         "status": "em_teste", "origem": "researcher", "justificativa_criacao": "plano", "nos_consultados": []},
        actor=RESEARCHER,
    )
    store.create_edge(hid, "SOBRE", problem_id, {}, actor=ORQ)
    return ctx, hid


def _metrics(session_dir: Path, task_name: str, metrics: dict) -> None:
    folder = session_dir / task_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "params.json").write_text(json.dumps({"task_name": task_name, "seed": 7, "parameters": {"C": 1}}))
    (folder / "metrics.json").write_text(
        json.dumps({"task_name": task_name, "seed": 7, "parameters": {"C": 1}, "metrics": metrics})
    )


def _negative_sub(**over) -> SubtaskInput:
    base = dict(
        task_name="treinar_rl", subtask_id="sub-1", agent_id="developer", review_status="fail",
        review_verified=True, review_outcome="resultado_negativo", validation_criteria=["acurácia no teste >= 0.95"],
    )
    base.update(over)
    return SubtaskInput(**base)


def test_veredito_recebe_a_tentativa_do_resultado_negativo(tmp_path_factory, tmp_path):
    """Scenario: Veredito recebe a tentativa."""
    store = _seeded_store(tmp_path_factory)
    ctx, hid = _world(store, "accuracy")
    session_dir = tmp_path / SESSION
    _metrics(session_dir, "treinar_rl", {"test_accuracy": 0.933})
    exp_id = ingest_subtask(store, ctx, session_dir, _negative_sub(hypothesis_id=hid))

    exp = store.get_node(exp_id)
    assert exp.properties["status"] == "sucesso" and exp.properties["criterio_plano_atendido"] is False
    (resultado,) = store.find_nodes("Resultado", {"nome_original": "test_accuracy"}, limit=2)
    assert resultado.properties["status_validacao"] == "validado"

    verdict = KnowledgeService(store, VerdictParams()).recompute_hypothesis(hid)
    assert store.get_node(hid).properties["n_tentativas"] == 1 and verdict.n_tentativas == 1
    refuta = [e for e in store._edges if e.rel_type == "REFUTA" and e.dst_id == hid]  # noqa: SLF001
    assert [e.src_id for e in refuta] == [resultado.id]


def test_recurso_desligado_grava_falha_na_ingestao(tmp_path_factory, tmp_path, monkeypatch):
    """Scenario: Recurso desligado (ingestão volta ao tratamento anterior: reprovação é `falha`)."""
    monkeypatch.setattr("src.config.NEGATIVE_RESULT_AS_PROGRESS", False)
    store = _seeded_store(tmp_path_factory)
    ctx, hid = _world(store, "accuracy")
    session_dir = tmp_path / SESSION
    _metrics(session_dir, "treinar_rl", {"test_accuracy": 0.933})
    exp_id = ingest_subtask(store, ctx, session_dir, _negative_sub(hypothesis_id=hid))
    assert store.get_node(exp_id).properties["status"] == "falha"


def test_metrica_candidata_registra_resultado_sem_mede(tmp_path, tmp_path_factory):
    """Scenario: Métrica candidata."""
    store = InMemoryGraphStore()  # vocabulário não semeado: a Metrica do Problema nasce `candidato`
    ctx, hid = _world(store, "acuracia")
    (metric,) = store.find_nodes("Metrica", {}, limit=5)
    assert metric.properties["status"] == "candidato"
    session_dir = tmp_path / SESSION
    _metrics(session_dir, "treinar_rl", {"accuracy": 0.933})
    telemetry = MagicMock()
    with patch("src.observability.telemetry.get_telemetry", return_value=telemetry):
        ingest_subtask(store, ctx, session_dir, _negative_sub(hypothesis_id=hid))
    events = [c.kwargs for c in telemetry.record_agent_event.call_args_list]
    sem_mede = [e for e in events if e["event_type"] == "resultado_sem_mede"]
    assert len(sem_mede) == 1 and sem_mede[0]["payload"]["motivo"] == "metrica_nao_aprovada"
    assert not [e for e in store._edges if e.rel_type == "MEDE"]  # noqa: SLF001


# --- Conferência do veredito no início da sessão -----------------------------------------------------------------


@pytest.fixture(autouse=False)
def _no_curator():
    with patch("src.config.CURATOR_ENABLED", False):
        yield


@pytest.mark.asyncio
async def test_modo_assistido_sem_metrica_aprovada_avisa_e_segue(tmp_path, capsys, _no_curator):
    """Scenario: Modo assistido sem métrica aprovada."""
    p = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, mode="assisted", plans=[p, p], world_kw={"approve_metric": False},
                    approver=lambda items: {i.id: __import__("src.knowledge.hypothesis_cycle", fromlist=["x"])
                                            .ApprovalDecision("aprovar") for i in items})
    await h.run()
    assert "Veredito indisponível" in capsys.readouterr().out
    assert h.plan_calls >= 1 and h.ran == ["t1"]
    assert "DEFINIÇÃO DE MÉTRICAS" not in h.planner_prompts[0]  # v18.6-auto-metrics-and-stop-reasons: só no auto


# --- Fechamento por falta de caminhos -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hipotese_no_plano_sem_tentativa_nao_fecha_e_o_feedback_cita(tmp_path, _no_curator):
    """Scenario: Hipótese no plano sem tentativa."""
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first], record_attempts=False)
    await h.run()
    (node,) = h.hypotheses()
    assert h.plan_calls >= 3  # o 1º ciclo ocioso não fechou a sessão
    assert node.id in h.planner_prompts[2] and "sem nenhuma tentativa" in h.planner_prompts[2]


@pytest.mark.asyncio
async def test_ciclos_ociosos_esgotados_fecham_com_hipoteses_nao_testadas(tmp_path, _no_curator):
    """Scenario: Ciclos ociosos esgotados."""
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first], record_attempts=False)
    result = await h.run()
    (node,) = h.hypotheses()
    assert h.stop_reason == "hipoteses_nao_testadas"  # v18.6-auto-metrics-and-stop-reasons: não é mais `erro`
    assert all(r.status != "error" for r in result.results)


@pytest.mark.asyncio
async def test_todas_as_hipoteses_testadas_fecham_por_sem_caminhos(tmp_path, _no_curator):
    """Scenario: Todas as hipóteses testadas."""
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first])  # o Developer deixa metrics.json: a ingestão grava a tentativa
    await h.run()
    (node,) = h.hypotheses()
    assert node.properties["n_tentativas"] == 1
    assert h.stop_reason == "sem_caminhos_promissores"


# --- Afirmações do relatório ---------------------------------------------------------------------------------------


def _results_graph() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    exp = store.create_node(
        "Experimento",
        {"subtarefa_id": "s:random_forest", "status": "sucesso", "caminho_artefatos": "/x", "no_execucao": "n",
         "projeto_id": "p", "sessao_id": "sess"},
        actor=ORQ,
    )
    for nome, valor, status in (("random_forest.accuracy", 0.9667, "validado"), ("lixo", 0.1, "nao_validado")):
        res = store.create_node(
            "Resultado",
            {"nome_original": nome, "valor": valor, "status_validacao": status, "caminho_metrics": "/m",
             "projeto_id": "p", "sessao_id": "sess", "exec_id": "exec_9"},
            actor=ORQ,
        )
        store.create_edge(exp, "PRODUZIU", res, {}, actor=ORQ)
    return store


def test_frase_sem_codigo_recebe_a_tabela_de_resultados():
    """Scenario: Frase sem código recebe a tabela."""
    graph = _results_graph()
    build = report_evidence_builder([], None, session_results=lambda: session_results_item(graph, "sess"))
    sentence = Sentence(1, "O Random Forest atingiu acurácia de 0,97 no teste", (0, 50))
    items = build(Conclusao("rel:resultados:1", "relatorio", sentence.texto, "summarizer"), [sentence])
    assert len(items) == 1 and items[0].frases == frozenset({1})
    assert "random_forest.accuracy" in items[0].texto and "0.9667" in items[0].texto
    assert "lixo" not in items[0].texto  # só `validado` e `divergente_documentado`


def test_relatorio_sem_afirmacoes_grava_afirmacoes_json_com_motivo(tmp_path):
    """Scenario: Relatório sem afirmações."""
    state = SimpleNamespace(session_dir=tmp_path, session_id="sess", extras={"claims": {"conclusoes": []}})
    with patch("src.config.CLAIM_VERIFY_ENABLED", True):
        ensure_claims_file(state)
    data = json.loads((tmp_path / "afirmacoes.json").read_text(encoding="utf-8"))
    assert data["afirmacoes"] == [] and data["motivo_vazio"] == "sem_conclusoes"
    with patch("src.config.CLAIM_VERIFY_ENABLED", False):
        (tmp_path / "afirmacoes.json").unlink()
        ensure_claims_file(state)
    assert json.loads((tmp_path / "afirmacoes.json").read_text(encoding="utf-8"))["motivo_vazio"] == (
        "verificacao_desligada"
    )


# --- Métricas de operação -------------------------------------------------------------------------------------------


def test_contadores_de_operacao():
    events = {
        "resultado_sem_mede": [{"payload": {"motivo": "metrica_nao_aprovada"}}] * 2,
        "subtask_review": [
            {"task_name": "a", "payload": {"outcome": "resultado_negativo"}},
            {"task_name": "a", "payload": {"outcome": "resultado_negativo"}},
            {"task_name": "b", "payload": {"outcome": "reprovado"}},
        ],
        "hipoteses_sem_tentativa": [{"payload": {"hipoteses": ["h1", "h2"]}}],
    }
    telemetry = MagicMock()
    telemetry.get_events.side_effect = lambda sid, kind: events.get(kind, [])
    with patch("src.observability.telemetry.get_telemetry", return_value=telemetry):
        out = HypothesisClosureReader().read("s")
    assert out == {
        "resultados_sem_mede": 2, "subtarefas_resultado_negativo": 1, "hipoteses_sem_tentativa_no_fechamento": 2,
        "fechada_por_hipoteses_nao_testadas": False, "reprovacoes_sem_hipotese": 0,
    }


def test_review_result_default_outcome():
    assert ReviewResult(is_approved=True, status="pass", feedback="").outcome == "aprovado"
    assert ReviewResult(is_approved=False, status="fail", feedback="").outcome == "reprovado"
    assert Actor  # import usado por fixtures de grafo


def test_sessao_simulada_fecha_hipoteses_pelo_veredito_calculado(tmp_path):
    """Cenário de integração (8.2) sobre o grafo em memória: uma hipótese refutada e outra validada."""
    from tests.support.hypothesis_closure_scenario import run_closure_scenario

    store = InMemoryGraphStore()
    out = run_closure_scenario(store, tmp_path, "mem")
    assert store.get_node(out["experiment"]).properties["status"] == "sucesso"
    assert out["changed"][out["refuted"]] == "refutada" and out["changed"][out["validated"]] == "validada"
    assert out["verdicts"][out["refuted"]].veredito < 0 < out["verdicts"][out["validated"]].veredito
