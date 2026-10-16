"""Mudança de versão do modelo dentro da sessão: política ``ON_MODEL_VERSION_CHANGE``
(v18.7-benchmark-fixes, design §1.7; requisito "Mudança de versão dentro da sessão" de ``llm-providers``)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src import config
from src.llm.allocation import record_call_version
from src.llm.availability import Availability
from src.llm.session import _resolve, bind_session_routing
from src.llm.versions import UNKNOWN_VERSION, VersionTracker
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.usage import StopReason
from tests.support.catalog_fixtures import base_document, load, model
from tests.support.env_override import env_override

pytestmark = pytest.mark.unit

CLAUDE = "anthropic/claude-sonnet-5-5"


@pytest.fixture(autouse=True)
def unbind_session_routing(monkeypatch):
    from src.llm import session

    monkeypatch.setattr(config, "LLM_JUDGE_INDEPENDENCE", "off")
    yield
    session._current.set(None)


def _doc(prefs: dict[str, list[str]] | None = None, models: list[dict] | None = None) -> dict:
    doc = base_document()
    if models is not None:
        doc["modelos"] = models
    for role, order in (prefs or {}).items():
        doc["papeis"][role]["preferencia"] = order
    return doc


def _routing(tmp_path, doc: dict | None = None, *, policy: str = "retomar", unavailable=(), pins=None):
    catalog = load(tmp_path, doc)
    available = {i: Availability(i not in unavailable) for i in catalog.modelos}
    routing = _resolve(catalog, pins or {}, "third_party_allowed", "strict", available)
    object.__setattr__(routing, "versions", VersionTracker(strict=True, policy=policy))
    return routing


def _loop(routing, sink=None):
    session = MagicMock(payload={"eventos_versao_modelo": []})
    orchestrator = MagicMock()
    orchestrator.session_manager.get.return_value = session
    loop = AutonomousLoop(orchestrator=orchestrator)
    recorder = MagicMock()
    loop._recorder = lambda _sid: recorder  # type: ignore[method-assign]
    events: list[dict] = []
    routing.versions.set_event_sink(events.append)
    return loop, orchestrator, recorder, events


def _bind(routing):
    bind_session_routing(routing)
    return routing


# --- configuração ------------------------------------------------------------------------------------------------


def test_valor_invalido_de_on_model_version_change():
    """Scenario: Valor inválido de ON_MODEL_VERSION_CHANGE."""
    from src.utils.configuration_error import ConfigurationError

    with env_override({"ON_MODEL_VERSION_CHANGE": "talvez"}) as load_config:
        with pytest.raises(ConfigurationError) as error:
            load_config()
    assert "ON_MODEL_VERSION_CHANGE" in str(error.value)
    assert "retomar" in str(error.value) and "parar" in str(error.value)


def test_padrao_e_valores_validos():
    with env_override({}) as load_config:
        assert load_config().ON_MODEL_VERSION_CHANGE == "retomar"
    with env_override({"ON_MODEL_VERSION_CHANGE": " PARAR "}) as load_config:
        assert load_config().ON_MODEL_VERSION_CHANGE == "parar"


# --- modo flexível -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("policy", ["retomar", "parar"])
def test_troca_de_versao_em_modo_flexivel(policy):
    """Scenario: Troca de versão em modo flexível (o evento é gravado e a sessão continua, qualquer que seja a política)."""
    tracker = VersionTracker(strict=False, policy=policy)
    events: list[dict] = []
    tracker.set_event_sink(events.append)
    tracker.observe(CLAUDE, "v1", ("researcher",))
    tracker.observe(CLAUDE, "v2", ("researcher",))
    assert [e["tipo"] for e in events] == ["versao_modelo_alterada"] and events[0]["anterior"] == "v1"
    assert tracker.parada_pendente is None and tracker.drain_actions() == []


# --- retomar -------------------------------------------------------------------------------------------------------


def test_versao_nova_informada_com_retomar(tmp_path):
    """Scenario: Versão nova informada com a política retomar (checkpoint, evento e a sessão continua)."""
    routing = _bind(_routing(tmp_path))
    loop, orchestrator, recorder, events = _loop(routing)
    before = {role: res.id for role, res in routing.papeis.items()}
    record_call_version("anthropic", "claude-sonnet-5-5", "v1")
    record_call_version("anthropic", "claude-sonnet-5-5", "v2")

    stop = loop._pending_stop("sessao")

    assert stop is None
    assert [(e["tipo"], e["anterior"], e["nova"]) for e in events] == [("versao_modelo_alterada", "v1", "v2")]
    recorder.set_usage.assert_called_once()  # o checkpoint é gravado
    assert {role: res.id for role, res in routing.papeis.items()} == before  # o mesmo modelo
    assert routing.versions.current(CLAUDE) == "v2"  # as chamadas seguintes ficam registradas com a versão nova
    assert routing.versions.drain_actions() == []


def test_versao_desconhecida_com_substituicao_de_modelo(tmp_path):
    """Scenario: Versão desconhecida com substituição de modelo."""
    doc = _doc({"researcher": [CLAUDE, "google/gemini-4-argon", "ollama/qwen3:8b"]})
    routing = _bind(_routing(tmp_path, doc))
    loop, orchestrator, recorder, events = _loop(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)

    stop = loop._pending_stop("sessao")

    assert stop is None
    assert routing.resolution("researcher").id == "google/gemini-4-argon"
    replaced = [e for e in events if e["tipo"] == "modelo_substituido"]
    researcher = [e for e in replaced if e["papel"] == "researcher"]
    assert researcher == [{"tipo": "modelo_substituido", "papel": "researcher", "anterior": CLAUDE,
                           "novo": "google/gemini-4-argon", "motivo": "versao_desconhecida"}]
    payload = orchestrator.session_manager.update.call_args.kwargs["payload"]
    assert payload["allocation_profile"]["papeis"]["researcher"]["provedor_modelo"] == "google/gemini-4-argon"
    assert payload["llm_routing"]["papeis"]["researcher"]["id"] == "google/gemini-4-argon"
    from src.egress.routing import ModelRouter

    assert ModelRouter.get_provider("researcher").model_name == "gemini-4-argon"  # o roteador usa o modelo novo


def test_substituicao_respeita_a_familia_do_validator(tmp_path, monkeypatch):
    """Scenario: Substituição respeita a família do Validator (ADR 020)."""
    monkeypatch.setattr(config, "LLM_JUDGE_INDEPENDENCE", "required")
    models = [
        model("google/dev", "third_party", familia="dev-fam"),
        model("google/juiz-1", "third_party", familia="juiz-fam"),
        model("google/mesma-familia", "third_party", familia="dev-fam"),
        model("google/juiz-3", "third_party", familia="outra-fam"),
    ]
    prefs = {role: ["google/dev"] for role in ("researcher", "developer", "summarizer", "curator", "base")}
    prefs["validator"] = ["google/juiz-1", "google/mesma-familia", "google/juiz-3"]
    routing = _bind(_routing(tmp_path, _doc(prefs, models)))
    assert routing.resolution("validator").id == "google/juiz-1"
    loop, _, _, events = _loop(routing)
    record_call_version("google", "juiz-1", UNKNOWN_VERSION)

    loop._pending_stop("sessao")

    assert routing.resolution("validator").id == "google/juiz-3"
    assert [e["novo"] for e in events if e["tipo"] == "modelo_substituido"] == ["google/juiz-3"]


def test_substituicao_respeita_a_localidade(tmp_path):
    """Scenario: Substituição respeita a localidade (nó local não passa a modelo fora do nó)."""
    models = [
        model("ollama/local-a", "self_hosted", localidade="no_no"),
        model("anthropic/nuvem", "third_party"),
        model("ollama/local-b", "self_hosted", localidade="no_no"),
    ]
    prefs = {role: ["ollama/local-a", "anthropic/nuvem", "ollama/local-b"] for role in
             ("researcher", "developer", "summarizer", "validator", "curator", "base")}
    routing = _bind(_routing(tmp_path, _doc(prefs, models)))
    loop, _, _, events = _loop(routing)
    record_call_version("ollama", "local-a", UNKNOWN_VERSION)

    loop._pending_stop("sessao")

    assert routing.resolution("researcher").id == "ollama/local-b"
    assert not any(e.get("novo") == "anthropic/nuvem" for e in events)


def test_sem_modelo_elegivel_fecha_com_versao_modelo(tmp_path):
    """Scenario: Sem modelo elegível (fecha com ``versao_modelo``; nenhum ``modelo_substituido``)."""
    doc = _doc({role: [CLAUDE, "google/gemini-4-argon"] for role in base_document()["papeis"]})
    routing = _bind(_routing(tmp_path, doc, unavailable=("google/gemini-4-argon",)))
    loop, _, recorder, events = _loop(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)

    stop = loop._pending_stop("sessao")

    assert stop == StopReason.MODEL_VERSION
    assert not [e for e in events if e["tipo"] == "modelo_substituido"]
    assert routing.resolution("researcher").id == CLAUDE


def test_papel_com_pin_do_pesquisador_nao_e_trocado(tmp_path):
    from src.llm.routing import Pin

    routing = _bind(_routing(tmp_path, pins={"researcher": Pin(id=CLAUDE)}))
    loop, _, _, events = _loop(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)

    assert loop._pending_stop("sessao") == StopReason.MODEL_VERSION
    assert routing.resolution("researcher").id == CLAUDE


# --- parar ---------------------------------------------------------------------------------------------------------


def test_politica_parar_mantem_o_comportamento_anterior(tmp_path):
    """Scenario: Troca de versão em modo strict com a política parar."""
    routing = _bind(_routing(tmp_path, policy="parar"))
    loop, _, _, events = _loop(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", "v1")
    record_call_version("anthropic", "claude-sonnet-5-5", "v2")
    assert loop._pending_stop("sessao") == StopReason.MODEL_VERSION
    assert routing.versions.drain_actions() == []


def test_versao_desconhecida_com_a_politica_parar(tmp_path):
    """Scenario: Versão desconhecida em modo strict com a política parar."""
    routing = _bind(_routing(tmp_path, policy="parar"))
    loop, _, _, _ = _loop(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)
    assert loop._pending_stop("sessao") == StopReason.MODEL_VERSION


# --- benchmark ----------------------------------------------------------------------------------------------------


def test_bateria_usa_a_politica_parar():
    """Scenario: Bateria usa a política parar para a versão do modelo (o ambiente base não é alterado)."""
    from scripts.benchmark.run_benchmark import build_env

    base = {"ON_MODEL_VERSION_CHANGE": "retomar"}
    env = build_env(base, {"*": "google/gemini-4-argon"})
    assert env["ON_MODEL_VERSION_CHANGE"] == "parar" and base == {"ON_MODEL_VERSION_CHANGE": "retomar"}


def test_versao_modelo_e_limite_e_anomalia():
    """Scenarios: Classificação e Versão do modelo é anomalia."""
    from scripts.benchmark.run_benchmark import anomalies, stop_class
    from tests.unit.benchmark.test_footprint_and_seed import _ok_result

    assert stop_class("versao_modelo") == "limite"
    problems = anomalies(_ok_result(stop_reason="versao_modelo", status="exit 3"))
    assert any("versao_modelo" in p for p in problems)
