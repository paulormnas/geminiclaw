"""Independência do julgamento: modo, roteador, pins, despacho, registro e retomada (v18.6-validator-independence).

Cada teste cita o Scenario da spec ``openspec/specs/llm-providers/spec.md``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.availability import Availability
from src.llm.catalog import load_catalog
from src.llm.independence import (
    JudgeIndependenceGuard,
    judged_families_from_session,
)
from src.llm.routing import (
    NoEligibleModelError,
    Pin,
    PinError,
    RoutingError,
    effective_judge_mode,
    resolve_session,
)
from src.llm.session import SessionRouting
from tests.support.catalog_fixtures import REGISTERED, all_available, base_document, load, model

pytestmark = pytest.mark.unit

CLAUDE = "anthropic/claude-sonnet-5-5"
HAIKU = "anthropic/claude-haiku-5-5"
GEMINI = "google/gemini-4-argon"
GPT = "openai/gpt-6-luna"
QWEN = "ollama/qwen3:8b"
THIRD = "third_party_allowed"
SELF = "self_hosted_only"


def doc(prefs: dict[str, list[str]] | None = None, models: list[dict] | None = None) -> dict:
    """Catálogo de teste com famílias claude, gemini, gpt e qwen; ``prefs`` troca a preferência de papéis."""
    document = base_document()
    document["modelos"] = models or [
        model(CLAUDE, "third_party", familia="claude"),
        model(HAIKU, "third_party", familia="claude"),
        model(GEMINI, "third_party", familia="gemini"),
        model(GPT, "third_party", familia="gpt"),
        model(QWEN, "self_hosted", familia="qwen"),
    ]
    for role, pref in (prefs or {}).items():
        document["papeis"][role]["preferencia"] = pref
    return document


def make_routing(
    tmp_path: Path,
    document: dict,
    *,
    politica: str = THIRD,
    modo: str = "required",
    origem: str = "variavel",
    pins: dict[str, str] | None = None,
    routing: str = "flexible",
    disponiveis: dict[str, Availability] | None = None,
) -> SessionRouting:
    catalog = load(tmp_path, document)
    avail = disponiveis or all_available(catalog)
    pin_map = {role: Pin(pid) for role, pid in (pins or {}).items()}
    papeis = resolve_session(catalog, avail, politica, pin_map, routing, modo)
    guard = JudgeIndependenceGuard(catalog, papeis, avail, politica, modo, origem, routing)
    return SessionRouting(politica, routing, catalog, papeis, avail, guard=guard)


# --- Modo de independência -------------------------------------------------------------------------------------


def test_padrao_em_politica_de_terceiros():
    """Scenario: Padrão em política de terceiros."""
    assert effective_judge_mode(None, THIRD) == ("required", "padrao_politica")
    assert effective_judge_mode("", THIRD) == ("required", "padrao_politica")


def test_padrao_so_local():
    """Scenario: Padrão só local."""
    assert effective_judge_mode(None, SELF) == ("preferred", "padrao_politica")


def test_valor_explicito_vence_o_padrao():
    assert effective_judge_mode("OFF", THIRD) == ("off", "variavel")


def test_valor_invalido():
    """Scenario: Valor inválido (a inicialização falha listando os valores aceitos)."""
    with pytest.raises(RoutingError) as exc:
        effective_judge_mode("sim", THIRD)
    for value in ("required", "preferred", "off"):
        assert value in str(exc.value)


def test_valor_invalido_impede_a_sessao(monkeypatch):
    from src.llm.session import build_offline_routing

    monkeypatch.setattr("src.config.LLM_JUDGE_INDEPENDENCE", "sim")
    with pytest.raises(RoutingError, match="required"):
        build_offline_routing()


def test_sessao_sem_variavel_usa_o_padrao_da_politica(monkeypatch):
    """Scenario: Padrão só local (pela sessão): origem do modo registrada."""
    from src.llm.session import build_offline_routing

    monkeypatch.setattr("src.config.LLM_JUDGE_INDEPENDENCE", "")
    routing = build_offline_routing()
    assert routing.guard.modo == "preferred" and routing.guard.origem_modo == "padrao_politica"
    assert routing.independence_payload()["origem_modo"] == "padrao_politica"


# --- Família do Validator --------------------------------------------------------------------------------------


def test_preferido_da_mesma_familia(tmp_path):
    """Scenario: Preferido da mesma família."""
    document = doc({"developer": [CLAUDE], "validator": [CLAUDE, GEMINI]})
    routing = make_routing(tmp_path, document)
    assert routing.resolution("developer").id == CLAUDE
    validator = routing.resolution("validator")
    assert validator.id == GEMINI
    assert (CLAUDE, "mesma_familia_julgamento") in validator.descartados
    assert routing.guard.atendida


def test_independencia_vence_a_posicao_na_preferencia(tmp_path):
    """Um modelo de grupo inferior é usado se o preferido é da mesma família (ADR 020 §3)."""
    document = doc({"developer": [CLAUDE], "validator": [CLAUDE, HAIKU, QWEN, GPT]})
    routing = make_routing(tmp_path, document)
    assert routing.resolution("validator").id == QWEN


def test_sem_elegivel_em_required(tmp_path):
    """Scenario: Sem modelo elegível em `required`."""
    document = doc(
        {"developer": [CLAUDE], "validator": [CLAUDE, HAIKU]},
    )
    with pytest.raises(NoEligibleModelError) as exc:
        make_routing(tmp_path, document)
    assert exc.value.papel == "validator"
    assert "LLM_JUDGE_INDEPENDENCE=preferred" in str(exc.value)
    assert "mesma_familia_julgamento" in str(exc.value)


def test_sem_elegivel_em_preferred(tmp_path):
    """Scenario: Sem modelo elegível em `preferred`."""
    qwen2 = "ollama/qwen3.5:4b"
    models = [model(QWEN, "self_hosted", familia="qwen"), model(qwen2, "self_hosted", familia="qwen")]
    document = doc(
        {role: [QWEN, qwen2] for role in base_document()["papeis"]}, models=models
    )
    routing = make_routing(tmp_path, document, politica=SELF, modo="preferred", origem="padrao_politica")
    assert routing.resolution("validator").id == QWEN  # o preferido do catálogo
    assert routing.resolution("validator").conflito_independencia
    assert not routing.guard.atendida
    assert routing.independence_payload()["atendida"] is False
    banner = "\n".join(routing.banner_lines())
    assert "NÃO atendida" in banner


def test_modo_off(tmp_path):
    """Scenario: Modo `off`."""
    document = doc({"developer": [CLAUDE], "validator": [CLAUDE, GEMINI]})
    routing = make_routing(tmp_path, document, modo="off")
    assert routing.resolution("developer").id == CLAUDE and routing.resolution("validator").id == CLAUDE
    assert routing.guard.eventos == []


# --- Pins ------------------------------------------------------------------------------------------------------


def test_so_o_juiz_com_pin(tmp_path):
    """Scenario: Só o juiz com pin."""
    document = doc({"developer": [CLAUDE, GEMINI], "validator": [GEMINI]})
    routing = make_routing(tmp_path, document, pins={"validator": CLAUDE})
    assert routing.resolution("validator").id == CLAUDE
    assert routing.resolution("developer").id == GEMINI


def test_dois_pins_em_conflito_strict(tmp_path):
    """Scenario: Dois pins em conflito, `strict`."""
    with pytest.raises(PinError):
        make_routing(
            tmp_path, doc(), pins={"validator": CLAUDE, "developer": HAIKU}, routing="strict"
        )


def test_dois_pins_em_conflito_flexible(tmp_path, caplog):
    """Scenario: Dois pins em conflito, `flexible`."""
    document = doc({"validator": [CLAUDE, GEMINI]})
    routing = make_routing(tmp_path, document, pins={"validator": CLAUDE, "developer": HAIKU})
    assert routing.resolution("developer").id == HAIKU
    validator = routing.resolution("validator")
    assert validator.id == GEMINI and validator.origem == "preferencia"
    assert (CLAUDE, "mesma_familia_julgamento") in validator.descartados


def test_dois_pins_em_conflito_strict_preferred_mantem_o_pin(tmp_path):
    routing = make_routing(
        tmp_path, doc(), modo="preferred", pins={"validator": CLAUDE, "developer": HAIKU}, routing="strict"
    )
    assert routing.resolution("validator").id == CLAUDE and not routing.guard.atendida


# --- Conferência no despacho -----------------------------------------------------------------------------------


def test_dica_do_developer_na_familia_do_juiz(tmp_path):
    """Scenario: Dica do Developer na família do juiz."""
    document = doc({"developer": [GEMINI], "validator": [CLAUDE]})
    routing = make_routing(tmp_path, document)
    model_id = routing.apply_hint("developer", CLAUDE, subtarefa="eda")
    assert model_id == GEMINI
    event = routing.guard.eventos[-1]
    assert event["decisao"] == "rejeitado" and event["motivo"] == "mesma_familia_julgamento"
    assert event["subtarefa"] == "eda" and event["papel"] == "developer" and event["familia"] == "claude"


def test_dica_de_outra_familia_e_aceita_e_registrada(tmp_path):
    document = doc({"developer": [GEMINI], "validator": [CLAUDE]})
    routing = make_routing(tmp_path, document)
    assert routing.apply_hint("developer", GPT, subtarefa="x") == GPT
    assert routing.guard.eventos[-1]["decisao"] == "aceito"
    assert routing.apply_hint("developer", GPT) == GPT  # segunda chamada: sem novo evento
    assert len(routing.guard.eventos) == 1


def _fallback_catalog() -> dict:
    prefs = {role: [QWEN] for role in base_document()["papeis"]}
    prefs.update({"developer": ["google/gemini-dev"], "validator": ["google/gemini-val"]})
    return doc(
        prefs,
        models=[
            model("google/gemini-dev", "third_party", familia="gdev"),
            model("google/gemini-val", "third_party", familia="gemini"),
            model("google/gemini-fb", "third_party", familia="gemini"),
            model(QWEN, "self_hosted", familia="qwen"),
        ],
    )


def test_modo_off_nao_confere_a_reserva(tmp_path, monkeypatch):
    """Scenario: Modo `off` não confere a reserva."""
    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", "gemini-fb")
    routing = make_routing(tmp_path, _fallback_catalog(), modo="off")
    assert routing.fallback_for("google/gemini-dev") == "gemini-fb"
    assert routing.guard.eventos == []


def test_reserva_do_429_na_familia_do_juiz_em_required(tmp_path, monkeypatch):
    """Scenario: Reserva do 429 na família do juiz em `required`."""
    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", "gemini-fb")
    routing = make_routing(tmp_path, _fallback_catalog())
    assert routing.fallback_for("google/gemini-dev") is None
    event = routing.guard.eventos[-1]
    assert event["decisao"] == "rejeitado" and event["modelo"] == "google/gemini-fb"


def test_reserva_do_429_em_preferred_e_usada_com_aviso(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", "gemini-fb")
    routing = make_routing(tmp_path, _fallback_catalog(), modo="preferred")
    assert routing.fallback_for("google/gemini-dev") == "gemini-fb"
    assert routing.guard.eventos[-1]["decisao"] == "aceito_preferred"
    assert not routing.guard.atendida


def test_base_nao_e_julgado_depois_da_v18_6(tmp_path):
    """O `base` (papel interno) não entra na conferência: sem ponto de despacho e sem família proibida."""
    document = doc({"developer": [CLAUDE], "validator": [GEMINI], "base": [GEMINI, HAIKU]})
    routing = make_routing(tmp_path, document)
    assert routing.resolution("base").id == GEMINI
    assert not hasattr(routing, "dispatch_model")
    assert not hasattr(routing.guard, "check_dispatch")
    assert routing.guard.eventos == []


@pytest.mark.asyncio
async def test_orchestrator_aplica_a_dica_sem_despacho_de_base(tmp_path):
    """O orquestrador resolve o modelo da subtarefa por `apply_hint` (sem a conferência de `base`/`reviewer`)."""
    from src.llm.session import bind_session_routing
    from src.orchestrator import AgentTask, Orchestrator

    document = doc({"developer": [CLAUDE], "validator": [GEMINI]})
    routing = make_routing(tmp_path, document)
    bind_session_routing(routing)
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.rate_limiter = MagicMock(acquire=AsyncMock())
    orchestrator._session_planning_run_counts = {}
    orchestrator._session_agent_run_counts = {}
    orchestrator.session_manager = MagicMock()
    orchestrator.session_manager.create.return_value = MagicMock(id="agent-session")
    orchestrator.output_manager = MagicMock(base_dir=tmp_path)
    orchestrator.agent_runtime = MagicMock(run=AsyncMock(side_effect=RuntimeError("parou aqui")))
    orchestrator._resumes = {}
    task = AgentTask(agent_id="developer", prompt="x", task_name="s1", preferred_model=GEMINI)
    with patch("src.orchestrator.get_telemetry", return_value=MagicMock()):
        try:
            await orchestrator._execute_agent(task, None)
        except Exception:  # noqa: BLE001 — o que importa é a decisão registrada antes da execução
            pass
    assert routing.guard.eventos[-1]["decisao"] == "rejeitado" and routing.guard.eventos[-1]["papel"] == "developer"


# --- Registro --------------------------------------------------------------------------------------------------


def test_registro_na_inicializacao(tmp_path):
    """Scenario: Registro na inicialização."""
    document = doc({"developer": [CLAUDE], "validator": [GEMINI]})
    routing = make_routing(tmp_path, document, origem="padrao_politica")
    record = routing.independence_payload()
    assert record["atendida"] is True
    assert record["modo"] == "required" and record["origem_modo"] == "padrao_politica"
    assert record["validator"] == {"modelo": GEMINI, "familia": "gemini", "origem_familia": "versionado"}
    assert record["developer"]["familia"] == "claude"
    banner = "\n".join(routing.banner_lines())
    assert "gemini (validator)" in banner and "claude (developer)" in banner


def test_origem_da_familia_local(tmp_path):
    document = doc({"developer": [CLAUDE], "validator": ["ollama/local-x"]})
    local = {"modelos": [model("ollama/local-x", "self_hosted", familia="outra")]}
    catalog = load(tmp_path, document, local=local)
    avail = all_available(catalog)
    papeis = resolve_session(catalog, avail, THIRD, {}, "flexible", "required")
    guard = JudgeIndependenceGuard(catalog, papeis, avail, THIRD, "required", "variavel")
    assert guard.registro()["validator"]["origem_familia"] == "local"


def test_eventos_vao_ao_sink(tmp_path):
    routing = make_routing(tmp_path, doc({"developer": [GEMINI], "validator": [CLAUDE]}))
    received: list[dict] = []
    routing.guard.set_event_sink(received.append)
    routing.apply_hint("developer", CLAUDE, subtarefa="eda")
    assert received and received[0]["tipo"] == "independencia_julgamento"


# --- Retomada --------------------------------------------------------------------------------------------------


def test_catalogo_mudou_entre_as_execucoes(tmp_path):
    """Scenario: Catálogo mudou entre as execuções."""
    document = doc({"developer": [GEMINI], "validator": [CLAUDE]})
    routing = make_routing(tmp_path, document)
    original = {"independencia_julgamento": {"developer": {"familia": "claude"}}}
    with pytest.raises(NoEligibleModelError):
        routing.guard.verificar_retomada(judged_families_from_session(original))


def test_retomada_em_preferred_segue_com_atendida_false(tmp_path):
    routing = make_routing(tmp_path, doc({"developer": [GEMINI], "validator": [CLAUDE]}), modo="preferred")
    routing.guard.verificar_retomada({"claude"})
    assert not routing.guard.atendida and routing.guard.eventos[-1]["decisao"] == "aceito_preferred"


def test_retomada_sem_conflito_passa(tmp_path):
    routing = make_routing(tmp_path, doc({"developer": [GEMINI], "validator": [CLAUDE]}))
    routing.guard.verificar_retomada({"gemini"})
    assert routing.guard.atendida


def test_familias_julgadas_do_payload_incluem_eventos():
    payload = {
        "independencia_julgamento": {"developer": {"familia": "gemini"}},
        "eventos_independencia_julgamento": [
            {"papel": "developer", "decisao": "aceito", "familia": "claude"},
            {"papel": "base", "decisao": "aceito", "familia": "llama"},
            {"papel": "developer", "decisao": "rejeitado", "familia": "gpt"},
            {"papel": "reviewer", "decisao": "aceito", "familia": "qwen"},
        ],
    }
    assert judged_families_from_session(payload) == {"gemini", "claude"}


@pytest.mark.asyncio
async def test_orchestrator_confere_a_retomada_antes_de_criar_a_sessao(tmp_path):
    """Scenario: Catálogo mudou entre as execuções (pelo orquestrador: falha antes de criar a sessão)."""
    from src.orchestrator import Orchestrator

    routing = make_routing(tmp_path, doc({"developer": [GEMINI], "validator": [CLAUDE]}))
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.session_manager = MagicMock()
    orchestrator.session_manager.get.return_value = MagicMock(
        payload={"independencia_julgamento": {"developer": {"familia": "claude"}}}
    )
    resume = MagicMock(source_session_id="src", project_id="11111111-1111-1111-1111-111111111111")
    with pytest.raises(NoEligibleModelError):
        await orchestrator.handle_request(
            "x", llm_routing=routing, resume=resume, project_id="11111111-1111-1111-1111-111111111111"
        )
    orchestrator.session_manager.create.assert_not_called()


# --- Catálogo --------------------------------------------------------------------------------------------------


def test_catalogo_versionado_tem_uma_familia_de_cada_antes_do_local():
    """Scenario: Teste do catálogo."""
    catalog = load_catalog(registered_providers=REGISTERED, base_urls={}, local_path=Path("/nonexistent.yaml"))
    families = [catalog.modelos[m].familia_modelo for m in catalog.papeis["validator"].preferencia]
    first_local = families.index("qwen")
    assert {"claude", "gemini", "gpt"} <= set(families[:first_local])


# --- Telemetria da revisão -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telemetria_da_revisao(tmp_path):
    """Scenario: Telemetria da revisão."""
    from src.agents.validator_agent import ValidatorAgent
    from src.llm.base import LLMResponse
    from src.orchestrator import AgentTask

    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(
        return_value=LLMResponse(text='{"status": "pass", "feedback": "ok", "issues": []}')
    )
    agent = ValidatorAgent(provider=provider)
    task = AgentTask(agent_id="developer", prompt="x", task_name="eda", validation_criteria=["texto claro"])
    with patch("src.agents.validator_agent.record_llm_call") as record:
        await agent.review_result(task=task, response_text="ok", output_dir=tmp_path)
    assert record.call_args.args[3] == "validator"
    assert record.call_args.kwargs["funcao"] == "revisao_subtarefa"


# --- Payload, telemetria e métricas ----------------------------------------------------------------------------


def test_orchestrator_grava_evento_e_atualiza_o_payload(tmp_path):
    """Cada conferência vai à telemetria e ao payload da sessão (ADR 020 §6)."""
    from src.orchestrator import Orchestrator

    routing = make_routing(tmp_path, doc({"developer": [GEMINI], "validator": [CLAUDE]}))
    orchestrator = Orchestrator.__new__(Orchestrator)
    stored = {"payload": {}}
    orchestrator.session_manager = MagicMock()
    orchestrator.session_manager.get.side_effect = lambda sid: MagicMock(payload=dict(stored["payload"]))
    orchestrator.session_manager.update.side_effect = lambda sid, payload: stored.update(payload=payload)
    telemetry = MagicMock()
    with patch("src.orchestrator.get_telemetry", return_value=telemetry):
        orchestrator._wire_independence_events(routing, "sessao")
        routing.apply_hint("developer", CLAUDE, subtarefa="eda")
    assert telemetry.record_agent_event.call_args.kwargs["event_type"] == "independencia_julgamento"
    assert stored["payload"]["eventos_independencia_julgamento"][0]["decisao"] == "rejeitado"
    assert stored["payload"]["independencia_julgamento"]["atendida"] is True


def test_metricas_de_operacao_leem_o_registro():
    from src.operation_metrics import JudgeIndependenceReader, MetricsUnavailable

    payload = {
        "independencia_julgamento": {
            "modo": "required", "atendida": True,
            "validator": {"familia": "gemini"}, "developer": {"familia": "claude"},
        },
        "eventos_independencia_julgamento": [{"decisao": "rejeitado"}, {"decisao": "aceito"}],
    }
    values = JudgeIndependenceReader(lambda sid: payload).read("s")
    assert values["independencia_julgamento_atendida"] is True
    assert values["independencia_julgamento_rejeicoes"] == 1
    with pytest.raises(MetricsUnavailable):
        JudgeIndependenceReader(lambda sid: {}).read("s")


def test_secao_de_metricas_mostra_a_linha_de_julgamento():
    from src.operation_metrics import STATE_OK, render_operation_metrics_section

    group = {"estado": STATE_OK}
    metrics = {
        "versao": 1, "gerado_em": "t", "parcial": False,
        "egresso": {"estado": "indisponivel"}, "proveniencia": {"estado": "indisponivel"},
        "verificacao": {
            "estado": STATE_OK, "independencia_julgamento_modo": "required",
            "independencia_julgamento_atendida": True, "independencia_julgamento_rejeicoes": 2,
            "independencia_julgamento_familias": {"validator": "gemini", "developer": "claude"},
        },
        "custo_recursos": {"estado": "indisponivel"}, "intervencoes_humanas": group | {"estado": "indisponivel"},
    }
    text = render_operation_metrics_section(metrics)
    assert "Independência do julgamento" in text and "gemini (validator)" in text


def test_avaliacao_de_comunicacao_usa_o_validator_para_o_modelo_da_revisao():
    from scripts.benchmark.communication import evaluate_events

    result = evaluate_events([], {}, None, {"validator": "google/x", "reviewer": "old/y"})
    assert result["revisao_subtarefa"]["model"] == "google/x"
