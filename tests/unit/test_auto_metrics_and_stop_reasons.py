"""``v18.6-auto-metrics-and-stop-reasons``: métricas definidas pelo agente, ``hipoteses_nao_testadas`` e ``sem_hipotese``.

Um teste por ``#### Scenario`` dos deltas da mudança (nome do cenário no docstring). Sem rede, LLM real, Docker ou
banco: grafo em memória, provedor LLM e orquestrador simulados.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator.agent import ReviewResult, ValidationResult, ValidatorAgent
from src.knowledge import schema
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.hypotheses import split_plan
from src.knowledge.ingestion import MOTIVOS_PARADA
from src.knowledge.metric_definition import (
    APLICADA,
    DESCARTADA,
    PRECEDENCIA_PESQUISADOR,
    REJEITADA_PELO_PESQUISADOR,
    SENTIDO_DIVERGENTE,
    MetricDecl,
    apply_validated_metrics,
    parse_metrics,
)
from src.knowledge.provenance import Actor
from src.knowledge.vocabulary import reject_term
from src.llm.base import LLMResponse
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.orchestrator import AgentResult, AgentTask
from src.report.operation_metrics import HypothesisClosureReader, describe_stop_reason, render_operation_metrics_section
from src.session.continuity import RESUME_REFUSE, Checkpoint, evaluate_resumability
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.hypothesis_world import HypothesisWorld

pytestmark = pytest.mark.unit

ORQ = Actor(kind="orquestrador")
METRICA = {"nome": "R2", "sentido": "maior_melhor", "limiar": 0.9, "justificativa": "Regressão com alvo contínuo."}
APPROVED_METRICS = ValidationResult(is_valid=True, status="approved", reason="ok", metrics_approved=True)


@pytest.fixture
def _no_curator():
    with patch("src.config.CURATOR_ENABLED", False):
        yield


def _events(telemetry: MagicMock, kind: str) -> list[dict]:
    return [c.kwargs["payload"] for c in telemetry.record_agent_event.call_args_list
            if c.kwargs.get("event_type") == kind]


def _harness(tmp_path: Path, plans: list, *, validator=None, alvo: float | None = 0.8, mode: str = "auto"):
    telemetry = MagicMock()
    h = LoopHarness(tmp_path, mode=mode, plans=plans, validator=validator,
                    world_kw={"approve_metric": False, "alvo": alvo, "objetivo_do_pesquisador": False})
    h.extra_patches.append(patch("src.orchestration.autonomous_loop.get_telemetry", return_value=telemetry))
    return h, telemetry


def _metric(world: HypothesisWorld, nome: str = "R2"):
    (node,) = [n for n in world.raw.find_nodes("Metrica", {}, limit=50) if n.properties["nome"] == nome]
    return node


# --- hypothesis-loop: conferência do veredito e definição de métricas (modo auto) ------------------------------------


@pytest.mark.asyncio
async def test_modo_auto_sem_metrica_aprovada_segue_e_exige_metricas_no_plano(tmp_path, _no_curator):
    """Scenario: Modo auto sem métrica aprovada."""
    h, telemetry = _harness(tmp_path, [plan([task("t1")], [hyp("h1")])])
    await h.run()
    assert h.plan_calls >= 1 and h.stop_reason != "erro"
    assert "DEFINIÇÃO DE MÉTRICAS" in h.planner_prompts[0] and '"metricas"' in h.planner_prompts[0]
    (event,) = _events(telemetry, "veredito_indisponivel")
    assert event["modo"] == "auto"


@pytest.mark.asyncio
async def test_definicao_validada_grava_metrica_e_criterio(tmp_path, _no_curator):
    """Scenario: Definição validada."""
    first = plan([task("t1")], [hyp("h1")], metricas=[METRICA])
    validator = AsyncMock(return_value=APPROVED_METRICS)
    h, _ = _harness(tmp_path, [first, first], validator=validator, alvo=None)
    emitted: list[tuple[str, dict]] = []
    original = h.orch._start_exploration

    def spy(session_id, ingestor, mode):
        original(session_id, ingestor, mode)
        exploration = h.orch._explorations[session_id]
        inner = exploration._telemetry
        exploration._telemetry = lambda kind, payload: (emitted.append((kind, payload)), inner(kind, payload))[1]

    h.orch._start_exploration = spy
    await h.run()
    node = _metric(h.w)
    assert node.properties["status"] == "aprovado"
    assert node.properties["origem_definicao"] == "agente" and node.properties["aprovada_por"] == "validator"
    assert "Regressão" in node.properties["justificativa_definicao"]
    criterio = h.w.raw.get_node(h.w.problem.id).properties["criterio_sucesso"]
    assert criterio["alvo"] == 0.9 and criterio["metrica_id"] == node.id and criterio["definido_por"] == "agente"
    assert any(kind == "metricas_definidas" for kind, _ in emitted)
    # a exigência desligou: o segundo ciclo de planejamento não repete a instrução
    assert "DEFINIÇÃO DE MÉTRICAS" in h.planner_prompts[0]
    assert all("DEFINIÇÃO DE MÉTRICAS" not in p for p in h.planner_prompts[1:])
    kwargs = [c.kwargs for c in validator.await_args_list]
    assert kwargs[0]["metric_definition"]["metricas"][0]["nome"] == "R2"
    assert all("metric_definition" not in k for k in kwargs[1:])


@pytest.mark.asyncio
async def test_validator_reprova_a_definicao_e_o_plano_volta_ao_researcher(tmp_path, _no_curator):
    """Scenario: Validator reprova a definição."""
    rejected = ValidationResult(
        is_valid=False, status="revision_needed", reason="métrica", issues=["Métricas: limiar implausível"],
        signature="sig-1",
    )
    validator = AsyncMock(side_effect=[rejected, APPROVED_METRICS, APPROVED_METRICS, APPROVED_METRICS])
    first = plan([task("t1")], [hyp("h1")], metricas=[METRICA])
    h, _ = _harness(tmp_path, [first, first, first], validator=validator)
    await h.run()
    assert "Métricas: limiar implausível" in h.planner_prompts[1]  # o Researcher recebeu as issues
    assert _metric(h.w).properties["status"] == "aprovado"  # só depois da aprovação do 2º parecer


@pytest.mark.asyncio
async def test_reprovacao_repetida_nao_aprova_por_cansaco(tmp_path, _no_curator):
    """Scenario: Reprovação repetida não aprova por cansaço."""
    rejected = ValidationResult(
        is_valid=False, status="revision_needed", reason="métrica", issues=["Métricas: vaidade"], signature="s",
        metrics_approved=False,
    )
    h, _ = _harness(tmp_path, [plan([task("t1")], [hyp("h1")], metricas=[METRICA])],
                    validator=AsyncMock(return_value=rejected))
    with patch("src.config.ON_PLAN_REJECTIONS", "parar"):
        await h.run()
    assert _metric(h.w).properties["status"] == "candidato"
    assert h.ran == [] and h.stop_reason in ("planos_rejeitados", "limite_execucoes")  # o plano nunca é aprovado


@pytest.mark.asyncio
async def test_plano_sem_metricas_no_modo_auto_e_reprovado_sem_chamar_o_llm():
    """Scenario: Plano sem métricas no modo auto."""
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text='{"status": "approved"}'))
    agent = ValidatorAgent(provider=provider)
    steps = [{"agent_id": "developer", "task_name": "t", "prompt": "p", "validation_criteria": ["r2 >= 0.8"]}]
    result = await agent.validate_plan(steps, "tarefa", metric_definition={"problema": {}, "metricas": []})
    assert not result.is_valid and result.deterministic and not result.metrics_approved
    assert "metricas" in result.issues[0]
    provider.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_validator_llm_aprova_ou_reprova_as_metricas():
    """Scenario: Definição validada / Validator reprova a definição (parecer do LLM)."""
    steps = [{"agent_id": "developer", "task_name": "t", "prompt": "p", "validation_criteria": ["r2 >= 0.8"]}]
    definition = {"problema": {"titulo": "T"}, "metricas": [METRICA]}

    async def run(reply: str) -> ValidationResult:
        provider = MagicMock()
        provider.model_name = "m"
        provider.generate = AsyncMock(return_value=LLMResponse(text=reply))
        with patch("src.agents.validator.agent.record_llm_call"):
            return await ValidatorAgent(provider=provider).validate_plan(steps, "t", metric_definition=definition)

    ok = await run('{"status": "approved", "reason": "ok", "issues": [], "metricas_status": "approved"}')
    assert ok.is_valid and ok.metrics_approved
    bad = await run('{"status": "approved", "reason": "ok", "issues": [], "metricas_status": "revision_needed", '
                    '"metricas_issues": ["limiar 0.99 implausível"]}')
    assert not bad.is_valid and not bad.metrics_approved and "Métricas: limiar 0.99 implausível" in bad.issues
    silent = await run('{"status": "approved", "reason": "ok", "issues": []}')
    assert not silent.is_valid and not silent.metrics_approved  # sem parecer sobre as métricas: reprova


# --- governança da gravação -----------------------------------------------------------------------------------------


def test_precedencia_do_pesquisador():
    """Scenario: Precedência do pesquisador."""
    w = HypothesisWorld(alvo=0.9)  # a métrica R2 do Problema aprovada pelo pesquisador (approve_metric=True)
    before_node = _metric(w).properties.copy()
    before = w.raw.get_node(w.problem.id).properties["criterio_sucesso"].copy()
    applied = apply_validated_metrics(
        w.raw, w.pid, w.sid, [MetricDecl("R2", "maior_melhor", 0.99, "Quero mais.")]
    )
    assert applied.outcomes[0].estado == PRECEDENCIA_PESQUISADOR
    assert _metric(w).properties == before_node
    assert w.raw.get_node(w.problem.id).properties["criterio_sucesso"] == before


def test_metrica_rejeitada_pelo_pesquisador_nao_e_aprovada():
    """Scenario: Métrica rejeitada pelo pesquisador."""
    w = HypothesisWorld(approve_metric=False)
    reject_term(w.raw, _metric(w, "R2").id, motivo="não serve")
    applied = apply_validated_metrics(w.raw, w.pid, w.sid, [MetricDecl("R2", "maior_melhor", 0.9, "J")])
    assert applied.outcomes[0].estado == DESCARTADA and applied.outcomes[0].motivo == REJEITADA_PELO_PESQUISADOR
    assert _metric(w).properties["status"] == "rejeitado"
    assert [n for n in w.raw.find_nodes("Metrica", {}, limit=50) if n.properties["status"] == "aprovado"] == []


def test_sentido_divergente_descarta_a_definicao():
    """Scenario: Sentido divergente."""
    w = HypothesisWorld(approve_metric=False)
    applied = apply_validated_metrics(w.raw, w.pid, w.sid, [MetricDecl("R2", "menor_melhor", 0.1, "J")])
    assert applied.outcomes[0].motivo == SENTIDO_DIVERGENTE
    assert _metric(w).properties["status"] == "candidato"


def test_gravacao_com_origem_do_agente_e_ator_orquestrador():
    """Scenario: Gravação com origem do agente."""
    w = HypothesisWorld(approve_metric=False, objetivo_do_pesquisador=False)
    applied = apply_validated_metrics(
        w.raw, w.pid, w.sid,
        [MetricDecl("R2", "maior_melhor", 0.85, "J principal"), MetricDecl("MAE", "menor_melhor", 0.2, "J extra")],
    )
    assert [o.estado for o in applied.outcomes] == [APLICADA, APLICADA]
    props = _metric(w).properties
    assert (props["status"], props["origem_definicao"], props["aprovada_por"]) == ("aprovado", "agente", "validator")
    assert w.raw.audit_log[-1]["actor"] == "orquestrador"
    criterio = w.raw.get_node(w.problem.id).properties["criterio_sucesso"]
    assert criterio["alvo"] == 0.8  # mesmo R2 e alvo do pesquisador no Problema: prevalece
    assert [m["nome"] for m in criterio["metricas_adicionais"]] == ["MAE"]


def test_nenhum_agente_aprova_metrica():
    """Scenario: Gravação com origem do agente (a barreira de `AGENT_ALLOWED_VALUES` segue valendo)."""
    w = HypothesisWorld(approve_metric=False)
    validator = Actor(kind="agente", role="validator")
    with pytest.raises(Exception, match="(?i)human|pesquisador|reserv|confirma"):
        w.raw.update_node(_metric(w).id, {"status": "aprovado"}, actor=validator)


def test_no_antigo_sem_as_propriedades_continua_valido():
    """Scenario: Nó antigo sem as propriedades."""
    store = InMemoryGraphStore()
    node_id = store.create_node(
        "Metrica", {"nome": "acuracia", "sentido": "maior_melhor", "status": "aprovado", "projeto_id": "global",
                    "sessao_id": "seed"}, actor=ORQ,
    )
    props = store.get_node(node_id).properties
    assert "origem_definicao" not in props and "aprovada_por" not in props
    props_schema = schema.NODE_SCHEMAS["Metrica"].properties
    assert props_schema["origem_definicao"].enum == ("pesquisador", "agente")
    assert props_schema["aprovada_por"].enum == ("pesquisador", "validator")
    assert not props_schema["origem_definicao"].required and not props_schema["aprovada_por"].required


def test_parse_de_metricas_descarta_o_invalido():
    raw = {
        "subtarefas": [{"task_name": "t"}],
        "metricas": [
            METRICA,
            {"nome": "r2", "sentido": "maior_melhor", "limiar": 1, "justificativa": "repetida"},
            {"nome": "x", "sentido": "tanto_faz", "limiar": 1, "justificativa": "J"},
            {"nome": "y", "sentido": "maior_melhor", "limiar": "nan", "justificativa": "J"},
            {"nome": "z", "sentido": "maior_melhor", "limiar": 1, "justificativa": ""},
            "texto",
        ],
    }
    _, extras = split_plan(raw)
    assert [m.nome for m in extras.metricas] == ["R2"] and extras.descartados_do_plano == 5
    decls, dropped = parse_metrics([dict(METRICA, nome=f"m{i}") for i in range(5)])
    assert len(decls) == 3 and dropped == 2  # METRICS_MAX_PER_PLAN


# --- hypothesis-loop: hipoteses_nao_testadas -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ciclos_ociosos_esgotados_fecham_com_o_motivo_proprio(tmp_path, _no_curator):
    """Scenario: Ciclos ociosos esgotados."""
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first], record_attempts=False)
    telemetry = MagicMock()
    h.extra_patches.append(patch("src.orchestration.autonomous_loop.get_telemetry", return_value=telemetry))
    result = await h.run()
    (node,) = h.hypotheses()
    assert h.stop_reason == "hipoteses_nao_testadas" == h.checkpoint().motivo_parada
    (event,) = _events(telemetry, "hipoteses_sem_tentativa")
    assert event["motivo_parada"] == "hipoteses_nao_testadas" and event["hipoteses"] == [node.id]
    assert all(r.status != "error" for r in result.results)
    assert "hipoteses_nao_testadas" in MOTIVOS_PARADA


def test_retomada_de_hipoteses_nao_testadas_e_recusada():
    """Scenario: Retomada recusada."""
    checkpoint = Checkpoint.__new__(Checkpoint)
    checkpoint.motivo_parada = "hipoteses_nao_testadas"
    verdict = evaluate_resumability("closed", checkpoint)
    assert verdict.decision == RESUME_REFUSE and "hipoteses_nao_testadas" in verdict.message


# --- hypothesis-loop: motivos da revisão -----------------------------------------------------------------------------------


def _write(root: Path, rel: str, content) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _agent():
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text='{"status": "pass", "feedback": "ok", "issues": []}'))
    return ValidatorAgent(provider=provider)


async def _review(root: Path, criteria: list[str], hypothesis_id: str) -> ReviewResult:
    t = AgentTask(agent_id="developer", prompt="x", task_name="treinar_rl", validation_criteria=criteria,
                  hypothesis_id=hypothesis_id)
    with patch("src.agents.validator.agent.record_llm_call"):
        return await _agent().review_result(task=t, response_text="ok", output_dir=root)


@pytest.mark.asyncio
async def test_subtarefa_sem_hipotese_nao_registra_sem_hipotese(tmp_path):
    """v18.7-hypothesis-linking: o motivo ``sem_hipotese`` deixou de existir; a reprovação segue sem motivo."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.95"], hypothesis_id="")
    assert review.status == "fail" and review.outcome == "reprovado" and review.motivos == []


@pytest.mark.asyncio
async def test_evento_da_revisao_leva_os_motivos(tmp_path):
    """Scenario: Evento da revisão."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    orchestrator = MagicMock()
    orchestrator.validator = _agent()
    orchestrator.output_manager.list_artifacts.return_value = []
    orchestrator.output_manager.base_dir = tmp_path.parent
    telemetry = MagicMock()
    t = AgentTask(agent_id="developer", prompt="x", task_name="treinar_rl",
                  validation_criteria=["acurácia no teste >= 0.95"], hypothesis_origin="sistema")
    result = AgentResult(agent_id="developer", session_id="s", status="success", response={"text": "ok"})
    with patch("src.observability.telemetry.get_telemetry", return_value=telemetry), \
            patch("src.agents.validator.agent.record_llm_call"):
        review = await AutonomousLoop(orchestrator)._review_subtask(t, result, tmp_path.name)
    assert telemetry.record_agent_event.call_args.kwargs["payload"]["motivos"] == ["hipotese_do_sistema"]
    assert review["motivos"] == ["hipotese_do_sistema"] and review["outcome"] == "reprovado"


@pytest.mark.asyncio
async def test_reprovacao_com_hipotese_nao_leva_o_motivo(tmp_path):
    """Scenario: Reprovação com hipótese não leva o motivo."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"accuracy": 0.933}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.95"], hypothesis_id="hyp-1")
    assert review.outcome == "resultado_negativo" and review.motivos == []
    with patch("src.config.NEGATIVE_RESULT_AS_PROGRESS", False):
        review = await _review(tmp_path, ["acurácia no teste >= 0.95"], hypothesis_id="hyp-1")
    assert review.outcome == "reprovado" and review.motivos == []


@pytest.mark.asyncio
async def test_reprovacao_sem_hipotese_por_outra_causa_nao_leva_o_motivo(tmp_path):
    """Scenario: Reprovação sem hipótese por outra causa não leva o motivo."""
    _write(tmp_path, "treinar_rl/metrics.json", {"metrics": {"recall": 0.9}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.95"], hypothesis_id="")
    assert review.outcome == "reprovado" and review.motivos == []


# --- operation-metrics -----------------------------------------------------------------------------------------------


def test_contadores_de_operacao_novos():
    """Scenario: Contadores."""
    events = {
        "exploration_stop": [{"payload": {"motivo_parada": "hipoteses_nao_testadas"}}],
        "hipoteses_sem_tentativa": [{"payload": {"hipoteses": ["h1", "h2"]}}],
        "subtask_review": [
            {"task_name": "a", "payload": {"outcome": "reprovado", "motivos": ["sem_hipotese"]}},
            {"task_name": "a", "payload": {"outcome": "reprovado", "motivos": ["sem_hipotese"]}},
        ],
    }
    telemetry = MagicMock()
    telemetry.get_events.side_effect = lambda sid, kind: events.get(kind, [])
    with patch("src.observability.telemetry.get_telemetry", return_value=telemetry):
        out = HypothesisClosureReader().read("s")
    assert out["fechada_por_hipoteses_nao_testadas"] is True
    assert out["hipoteses_sem_tentativa_no_fechamento"] == 2 and out["reprovacoes_sem_hipotese"] == 1


def test_secao_do_relatorio_descreve_o_motivo():
    """Scenario: Seção do relatório."""
    verificacao = {
        "estado": "disponivel", "afirmacoes_por_status": {}, "ciclos_rejeicao_plano": 0,
        "hipoteses_sem_tentativa_no_fechamento": 2, "reprovacoes_sem_hipotese": 1,
    }
    ok = {"estado": "disponivel"}
    metrics = {
        "egresso": {**ok, "bytes_total": 0, "limite_bytes": None, "consultas_busca": 0, "chamadas_visao": 0,
                    "por_destino": [], "por_origem": {}, "intervencoes_filtro": {}},
        "proveniencia": {**ok, "numeros_por_origem": None, "cadeia": None},
        "verificacao": verificacao,
        "custo_recursos": {**ok, "tokens_total": 0, "custo_usd_total": None,
                           "no": {"cpu_pct_medio": None, "cpu_pct_pico": None, "ram_pct_pico": None,
                                  "temperatura_pico_c": None, "incidentes_throttling": 0},
                           "por_papel": []},
        "intervencoes_humanas": {**ok, "respostas_ask_researcher": 0, "decisoes_divergencia": 0, "suspensoes": 0,
                                 "interrupcoes": 0},
    }
    text = render_operation_metrics_section(metrics, stop_reason="hipoteses_nao_testadas")
    assert "hipoteses_nao_testadas (hipóteses em teste sem nenhuma tentativa" in text
    assert "hipóteses sem tentativa no fechamento: 2" in text and "sem_hipotese" in text
    assert describe_stop_reason("limite_tokens") == "limite_tokens" and describe_stop_reason(None) is None


def test_objetivo_do_pesquisador_nao_e_reescrito_pelas_metricas_do_plano():
    """O orquestrador aprova a métrica, mas o critério definido pelo pesquisador fica intacto (ADR 021 §5.2)."""
    w = HypothesisWorld(approve_metric=False)
    before = w.raw.get_node(w.problem.id).properties["criterio_sucesso"].copy()
    apply_validated_metrics(w.raw, w.pid, w.sid, [MetricDecl("R2", "maior_melhor", 0.99, "J")])
    assert w.raw.get_node(w.problem.id).properties["criterio_sucesso"] == before
