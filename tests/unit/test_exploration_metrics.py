"""``v18.7-exploration-metrics``: grupo ``exploracao``, evento por tentativa e divergência de hash do contrato.

Telemetria e grafo simulados (nenhuma chamada paga). Um teste por cenário da spec ``operation-metrics``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator.agent import ReviewResult
from src.llm.context_compression import estimate_tokens
from src.observability.telemetry import TelemetryCollector
from src.report.operation_metrics import (
    GROUPS,
    VERSION,
    ContractReader,
    ExplorationLinkingReader,
    ExplorationStopReader,
    aggregate_operation_metrics,
    render_operation_metrics_section,
)
from src.utils.egress_fragments import plain_text
from tests.support.exploration_world import hyp, plan, task
from tests.unit.subtask_contract.test_contract_dispatch import ContractHarness, _one_task

pytestmark = pytest.mark.unit


def _node(label: str, node_id: str, **props: Any) -> SimpleNamespace:
    return SimpleNamespace(label=label, id=node_id, properties=props)


class FakeStore:
    """Só ``find_nodes`` e ``neighbors``: o que o leitor de ligação usa."""

    def __init__(self, experiments: list[tuple[dict, str | None]]) -> None:
        self.session = _node("Sessao", "ses", sessao_id="s")
        self.experiments = [(_node("Experimento", f"e{i}", **props), origin) for i, (props, origin) in enumerate(experiments)]

    def find_nodes(self, label, props, limit=2):
        return [self.session] if label == "Sessao" else []

    def neighbors(self, node_id, rels, direction="out", depth=1):
        if node_id == "ses":
            return SimpleNamespace(nodes=[e for e, _ in self.experiments])
        for exp, origin in self.experiments:
            if exp.id == node_id and origin:
                return SimpleNamespace(nodes=[_node("Hipotese", "h-" + exp.id, origem=origin)])
        return SimpleNamespace(nodes=[])


def _telemetry(events: dict[str, list[dict]], usage: list[dict] | None = None) -> MagicMock:
    telemetry = MagicMock()
    telemetry.get_events.side_effect = lambda sid, kind: [{"payload": p} for p in events.get(kind, [])]
    telemetry.get_usage_by_role.return_value = usage or []
    return telemetry


def _read(reader, events, usage=None):
    with patch("src.observability.telemetry.get_telemetry", return_value=_telemetry(events, usage)):
        return reader.read("s")


# --- Ligação ----------------------------------------------------------------------------------------------------


def test_contagem_por_papel_e_origem():
    """Scenario: Contagem por papel e origem."""
    store = FakeStore(
        [({"papel": "teste"}, "sistema"), ({"papel": "teste"}, "sistema"), ({"papel": "teste"}, "researcher"),
         ({"papel": "preparacao"}, None), ({"papel": "preparacao"}, None), ({"papel": "referencia"}, None),
         ({}, "curator")]  # nó antigo, sem papel: conta como teste
    )
    out = _read(ExplorationLinkingReader(lambda: store), {})["ligacao"]
    assert out["experimentos_por_papel"] == {"teste": 4, "preparacao": 2, "referencia": 1}
    assert out["testes_por_origem"]["sistema"] == 2 and out["testes_por_origem"]["curator"] == 1
    assert out["proporcao_testes_sistema"] == 0.5 and out["estado"] == "disponivel"


def test_soma_dos_ciclos():
    """Scenario: Soma dos ciclos."""
    cycles = [
        {"ligacoes_prepara": 3, "hipoteses_sistema_abandonadas": 0, "removidas_pelo_replanejamento": ["a"]},
        {"ligacoes_prepara": 2, "hipoteses_sistema_abandonadas": 1, "hipoteses_sistema_criadas": 2},
    ]
    out = _read(ExplorationLinkingReader(lambda: FakeStore([({"papel": "teste"}, "sistema")])),
                {"hypothesis_cycle": cycles})["ligacao"]
    assert out["ligacoes_prepara_derivadas"] == 5 and out["hipoteses_sistema_abandonadas"] == 1
    assert out["hipoteses_sistema_criadas"] == 2 and out["removidas_pelo_replanejamento"] == 1


def test_produtor_ausente():
    """Scenario: Produtor ausente."""
    out = _read(ExplorationLinkingReader(lambda: FakeStore([({}, None)])), {"hypothesis_cycle": [{"ciclo": 1}]})
    block = out["ligacao"]
    assert block["estado"] == "indisponivel" and block["produtor"] == "v18.7-hypothesis-linking"
    assert "experimentos_por_papel" not in block


def test_sem_testes_a_proporcao_e_nula():
    """Scenario: Sem testes."""
    out = _read(ExplorationLinkingReader(lambda: FakeStore([({"papel": "preparacao"}, None)])), {})["ligacao"]
    assert out["proporcao_testes_sistema"] is None and out["experimentos_por_papel"]["teste"] == 0


def test_falha_de_leitura_de_um_bloco_nao_derruba_os_outros():
    def boom():
        raise RuntimeError("grafo fora")

    out = _read(ExplorationLinkingReader(boom), {})["ligacao"]
    assert out["estado"] == "erro" and "grafo fora" in out["mensagem"]


# --- Parada -----------------------------------------------------------------------------------------------------


def test_retiradas_por_similaridade_listadas():
    """Scenario: Retiradas por similaridade listadas."""
    events = {"restricao_retirada": [
        {"criterio": "similaridade", "hipotese_id": f"h{i}", "restricao_id": "r1", "similaridade": 0.8 + i / 100}
        for i in range(3)
    ] + [{"criterio": "abordagem", "hipotese_id": "h9", "restricao_id": "r2"}]}
    with patch("src.config.OPERATION_METRICS_LIST_MAX_ITEMS", 2):
        out = _read(ExplorationStopReader(), events)["parada"]
    assert out["retiradas_restricao"] == {"abordagem": 1, "similaridade": 3}
    assert len(out["retiradas_restricao_similaridade"]) == 2
    assert out["retiradas_restricao_similaridade_omitidas"] == 1


def test_contadores_da_parada():
    events = {
        "hypothesis_cycle": [{}, {}, {}], "estagnacao_intervencao": [{}], "saturacao_avaliada": [{}],
        "objetivo_atingido": [{"tipo": "limiar"}], "objetivo_desfecho": [{"desfecho": "todas_contrariadas"}],
    }
    out = _read(ExplorationStopReader(), events)["parada"]
    assert (out["ciclos"], out["intervencoes_estagnacao"], out["saturacao_avaliada"]) == (3, 1, True)
    assert out["objetivo_atingido"] is True and out["desfecho_objetivo"] == "todas_contrariadas"


def test_parada_sem_eventos_do_produtor():
    out = _read(ExplorationStopReader(), {})["parada"]
    assert out["estado"] == "indisponivel" and out["produtor"] == "v18.7-exploration-limits"


# --- Contrato ---------------------------------------------------------------------------------------------------


def test_fracao_da_entrada():
    """Scenario: Fração da entrada."""
    attempts = [{"contrato_sha256": "a" * 64, "contrato_tokens_estimados": 1650} for _ in range(14)]
    usage = [{"agent_id": "developer", "prompt_tokens": 200_000}, {"agent_id": "validator", "prompt_tokens": 125_000},
             {"agent_id": "researcher", "prompt_tokens": 999_999}]
    out = _read(ContractReader(), {"subtask_attempt": attempts}, usage)["contrato"]
    assert out["tokens_estimados_total"] == 23100 and out["tokens_estimados_medio"] == 1650
    assert out["fracao_entrada"] == 0.071 and out["tentativas"] == 14


def test_subtarefa_sem_contrato_conta_sem_hash():
    """Scenario: Subtarefa sem contrato."""
    attempts = [{"contrato_sha256": None, "contrato_tokens_estimados": None, "tarefa_original_truncada": False},
                {"contrato_sha256": "b" * 64, "contrato_tokens_estimados": 100, "tarefa_original_truncada": True}]
    out = _read(ContractReader(), {"subtask_attempt": attempts, "contrato_divergente": [{}]})["contrato"]
    assert out["tentativas_sem_hash"] == 1 and out["tarefa_original_truncada"] == 1 and out["divergencias"] == 1
    assert out["fracao_entrada"] is None


def test_contrato_sem_eventos_fica_indisponivel():
    out = _read(ContractReader(), {})["contrato"]
    assert out["estado"] == "indisponivel" and out["produtor"] == "v18.7-subtask-contract"


# --- Agregação, versão e relatório ------------------------------------------------------------------------------


class _Group:
    def __init__(self, group, values):
        self.group, self.values, self.producer = group, values, "x"

    def read(self, session_id):
        return self.values


def test_agregacao_grava_versao_2_e_o_grupo():
    """Scenario: Fechamento grava as métricas."""
    readers = [_Group(g, {"k": 1}) for g in GROUPS if g != "exploracao"]
    readers += [_Group("exploracao", {"ligacao": {"estado": "disponivel"}, "parada": {"estado": "indisponivel",
                "produtor": "p"}})]
    out = aggregate_operation_metrics("s", parcial=False, readers=readers)
    assert out["versao"] == VERSION == 2 and set(GROUPS) <= set(out)
    assert out["exploracao"]["estado"] == "disponivel"


def test_grupo_exploracao_indisponivel_quando_nenhum_bloco_le():
    readers = [_Group("exploracao", {"ligacao": {"estado": "indisponivel", "produtor": "a"},
                                     "contrato": {"estado": "indisponivel", "produtor": "b"}})]
    out = aggregate_operation_metrics("s", parcial=False, readers=readers)["exploracao"]
    assert out["estado"] == "indisponivel" and out["produtor"] == "a, b"


def _metrics(exploration):
    ok = {"estado": "disponivel"}
    base = {
        "versao": 2, "gerado_em": "t", "parcial": False, "modo_sem_limite": {},
        "egresso": {"estado": "indisponivel", "produtor": "p"}, "proveniencia": {"estado": "indisponivel", "produtor": "p"},
        "verificacao": {**ok, "ciclos_rejeicao_plano": 0}, "custo_recursos": {"estado": "indisponivel", "produtor": "p"},
        "intervencoes_humanas": {"estado": "indisponivel", "produtor": "p"},
    }
    if exploration is not None:
        base["exploracao"] = exploration
    return base


def test_payload_antigo_mostra_nd():
    """Scenario: Payload antigo."""
    text = render_operation_metrics_section({**_metrics(None), "versao": 1})
    assert "**Exploração:** n/d" in text


def test_secao_lista_as_retiradas_por_similaridade():
    """Scenario: Seção lista as retiradas."""
    exploration = {"estado": "disponivel", "parada": {
        "estado": "disponivel", "ciclos": 4, "intervencoes_estagnacao": 0, "saturacao_avaliada": False,
        "objetivo_atingido": False, "desfecho_objetivo": None, "retiradas_restricao": {"similaridade": 1},
        "retiradas_restricao_similaridade": [{"hipotese_id": "hip-1", "restricao_id": "res-1", "similaridade": 0.86}],
        "retiradas_restricao_similaridade_omitidas": 0,
    }, "ligacao": {"estado": "indisponivel", "produtor": "v18.7-hypothesis-linking"}}
    text = render_operation_metrics_section(_metrics(exploration))
    assert "restrição res-1, hipótese hip-1, similaridade 0.86" in text
    assert "ligação: indisponível (v18.7-hypothesis-linking)" in text


def test_secao_do_motivo_hipoteses_nao_testadas_sem_sem_hipotese():
    """Scenario: Seção do relatório."""
    text = render_operation_metrics_section(_metrics(None), stop_reason="hipoteses_nao_testadas")
    assert "hipóteses em teste sem nenhuma tentativa" in text and "sem_hipotese" not in text


def test_verificacao_nao_traz_reprovacoes_sem_hipotese():
    """Scenario: Contadores."""
    from src.report.operation_metrics import HypothesisClosureReader

    events = {"exploration_stop": [{"motivo_parada": "hipoteses_nao_testadas"}],
              "hipoteses_sem_tentativa": [{"hipoteses": ["h1", "h2"]}]}
    out = _read(HypothesisClosureReader(), events)
    assert out["fechada_por_hipoteses_nao_testadas"] is True
    assert out["hipoteses_sem_tentativa_no_fechamento"] == 2 and "reprovacoes_sem_hipotese" not in out


# --- Evento por tentativa e divergência (laço) -----------------------------------------------------------------


def _capture(h):
    seen: list[dict] = []
    h.extra_patches.append(patch.object(
        TelemetryCollector, "record_agent_event", autospec=True, side_effect=lambda self, **kw: seen.append(kw)))
    return seen


@pytest.mark.asyncio
async def test_tentativas_com_o_mesmo_contrato_nao_divergem(tmp_path):
    """Scenarios: Tentativas com o mesmo contrato, Evento sem texto e Laço de ferramentas não repete o evento."""
    h = ContractHarness(tmp_path, plans=[_one_task()], fail_first=True)

    async def review(**kwargs):
        c = kwargs["contract"]
        return ReviewResult(is_approved=True, status="pass", feedback="ok", contract_sha256=c.sha256())

    h.orch.validator.review_result = AsyncMock(side_effect=review)
    seen = _capture(h)
    h.extra_patches += [patch("src.config.REVIEW_ENABLED", True), patch("src.config.REVIEW_MODE", "per_subtask")]
    await h.run()
    attempts = [e for e in seen if e.get("event_type") == "subtask_attempt" and e["agent_id"] == "developer"]
    assert [a["payload"]["attempt"] for a in attempts] == [1, 2]  # uma por tentativa, nunca por volta do laço
    expected = {"task_name", "attempt", "contrato_sha256", "contrato_chars", "contrato_tokens_estimados",
                "tarefa_original_truncada", "recorte_sha256", "limiar_mascarado"}
    assert all(set(a["payload"]) == expected for a in attempts)
    contract = h.contracts[0]
    text = plain_text(contract.fragments())
    first = attempts[0]["payload"]
    assert first["contrato_chars"] == len(text) and first["contrato_tokens_estimados"] == estimate_tokens(text)
    assert not [e for e in seen if e.get("event_type") == "contrato_divergente"]
    assert text not in str(first)  # nenhum texto do contrato no evento


@pytest.mark.asyncio
async def test_hash_divergente_gera_evento_e_nao_reprova(tmp_path):
    """Scenario: Hash divergente."""
    h = ContractHarness(tmp_path, plans=[plan([task("treinar_modelo_a", validation_criteria=["relatório"])],
                                              [hyp("h1")])])
    h.orch.validator.review_result = AsyncMock(
        return_value=ReviewResult(is_approved=True, status="pass", feedback="ok", contract_sha256="b" * 64))
    seen = _capture(h)
    h.extra_patches += [patch("src.config.REVIEW_ENABLED", True), patch("src.config.REVIEW_MODE", "per_subtask")]
    await h.run()
    diverged = [e["payload"] for e in seen if e.get("event_type") == "contrato_divergente"]
    attempt = next(e["payload"] for e in seen if e.get("event_type") == "subtask_attempt" and e["agent_id"] == "developer")
    assert diverged[0]["hash_revisao"] == "b" * 64 and diverged[0]["hash_tentativa"] == attempt["contrato_sha256"]
    assert diverged[0]["attempt"] == 1
    reviews = [e["payload"] for e in seen if e.get("event_type") == "subtask_review"]
    assert reviews and reviews[0]["approved"] is True  # a subtarefa continua aprovada


@pytest.mark.asyncio
async def test_subtarefa_sem_contrato_registra_hash_nulo(tmp_path):
    h = ContractHarness(tmp_path, plans=[_one_task()])
    seen = _capture(h)
    h.extra_patches.append(patch("src.config.SUBTASK_CONTRACT_ENABLED", False))
    await h.run()
    attempt = next(e["payload"] for e in seen if e.get("event_type") == "subtask_attempt" and e["agent_id"] == "developer")
    assert attempt["contrato_sha256"] is None and attempt["contrato_chars"] is None
    assert attempt["recorte_sha256"] is None


def test_hash_do_recorte_vem_da_tarefa():
    """Scenario: Hash do recorte na tentativa."""
    from src.agent_runtime.types import AgentTask
    from src.orchestration.autonomous_loop import AutonomousLoop

    seen: list[dict] = []
    loop = AutonomousLoop.__new__(AutonomousLoop)
    loop._attempt_hashes = {}
    telemetry = SimpleNamespace(record_agent_event=lambda **kw: seen.append(kw))
    with patch("src.orchestration.autonomous_loop.get_telemetry", return_value=telemetry):
        loop._record_attempt_event(AgentTask(agent_id="developer", prompt="x", task_name="t", recorte_sha256="c" * 64),
                                   None, 1, "s")
        loop._record_attempt_event(AgentTask(agent_id="developer", prompt="x", task_name="t"), None, 2, "s")
    assert seen[0]["payload"]["recorte_sha256"] == "c" * 64 and seen[1]["payload"]["recorte_sha256"] is None
