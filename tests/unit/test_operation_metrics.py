"""Métricas de operação: agregação, grupos indisponíveis, custo nulo e seção do relatório
(v18.5-operation-metrics, cenários 8.11 e 8.12; tarefas 6.x e 7.x)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from src.numeric_refs.verifier import verify_numbers
from src.report.operation_metrics import (
    BEGIN_MARK,
    END_MARK,
    GROUPS,
    CostResourcesReader,
    HumanInterventionsReader,
    MetricsUnavailable,
    PlanRejectionReader,
    aggregate_operation_metrics,
    render_chain_line,
    render_operation_metrics_section,
    unlimited_block,
)

pytestmark = pytest.mark.unit

FIXED = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


class Fake:
    def __init__(self, group: str, values: dict[str, Any] | Exception, producer: str = "fake") -> None:
        self.group = group
        self.producer = producer
        self._values = values
        self.calls = 0

    def read(self, session_id: str) -> dict[str, Any]:
        self.calls += 1
        if isinstance(self._values, Exception):
            raise self._values
        return dict(self._values)


def _all_ok() -> list[Fake]:
    return [
        Fake("egresso", {
            "bytes_total": 2048, "por_destino": [{"provedor": "google", "modelo": "gemini-4-argon",
                                                 "trust": "third_party", "localidade": "fora_do_no", "bytes": 2048,
                                                 "chamadas": 3}],
            "por_origem": {"instrucao": 100, "saida_execucao": 1948}, "intervencoes_filtro": {"saida_retida": 2},
            "consultas_busca": 4, "chamadas_visao": 1, "envios_recusados": 0, "limite_bytes": None,
        }),
        Fake("proveniencia", {"numeros_por_origem": {"res": 5, "calc": 2, "src": 1}, "numeros_nao_verificados": 0,
                              "metricas_literais": 0}),
        Fake("proveniencia", {"cadeia": {"resultado": "integra", "orfas": 0, "pendentes": 0, "ponta": "ab" * 32}}),
        Fake("verificacao", {"afirmacoes_por_status": {"suportada": 3, "parcial": 1, "refutada_deterministica": 0,
                                                       "contestada": 0, "nao_verificavel": 1, "pendente": 0},
                             "ciclos_correcao_conclusoes": [{"conclusao_id": "rel:1", "ciclos": 1, "aprovada": True}]}),
        Fake("verificacao", {"ciclos_rejeicao_plano": 2}),
        Fake("custo_recursos", {
            "tokens_total": 12345, "custo_usd_total": 0.42, "chamadas_sem_custo": 0,
            "por_tarefa": [], "por_papel": [{"agent_id": "researcher", "tokens": 12345, "custo_usd": 0.42}],
            "no": {"cpu_pct_medio": 40.5, "cpu_pct_pico": 91.0, "ram_pct_pico": 55.0, "ram_disponivel_min_mb": 3000.0,
                   "temperatura_pico_c": 71.2, "incidentes_throttling": 0},
        }),
        Fake("intervencoes_humanas", {
            "aprovacoes": None, "rejeicoes": None, "edicoes": None, "respostas_ask_researcher": 2,
            "decisoes_divergencia": None, "suspensoes": None, "interrupcoes": 1, "eventos": [],
        }),
    ]


def _aggregate(readers, **kw) -> dict[str, Any]:
    return aggregate_operation_metrics("sess", parcial=kw.pop("parcial", False), readers=readers, now=lambda: FIXED, **kw)


def test_agrega_os_cinco_grupos_e_mescla_leitores_do_mesmo_grupo() -> None:
    metrics = _aggregate(_all_ok())
    assert metrics["versao"] == 1 and metrics["parcial"] is False and metrics["gerado_em"] == FIXED.isoformat()
    assert all(metrics[g]["estado"] == "disponivel" for g in GROUPS)
    assert metrics["proveniencia"]["numeros_por_origem"]["res"] == 5 and metrics["proveniencia"]["cadeia"]["resultado"] == "integra"
    assert metrics["verificacao"]["ciclos_rejeicao_plano"] == 2 and metrics["verificacao"]["afirmacoes_por_status"]["suportada"] == 3
    assert metrics["modo_sem_limite"] == {"ativo": False, "origem": None, "confirmado_em": None, "avisos_emitidos": 0}


def test_agregacao_e_idempotente() -> None:
    readers = _all_ok()
    assert _aggregate(readers) == _aggregate(readers)


def test_produtor_ausente_vira_indisponivel_sem_numeros() -> None:
    readers = [r for r in _all_ok() if r.group != "egresso"]
    metrics = _aggregate(readers)
    assert metrics["egresso"]["estado"] == "indisponivel"
    assert "bytes_total" not in metrics["egresso"]


def test_produtor_que_declara_indisponivel_registra_o_motivo() -> None:
    readers = [r for r in _all_ok() if r.group != "egresso"]
    readers.append(Fake("egresso", MetricsUnavailable("módulo desligado", "v18.5-egress-gate")))
    egress = _aggregate(readers)["egresso"]
    assert egress["estado"] == "indisponivel" and "v18.5-egress-gate" in egress["produtor"]
    assert "desligado" in egress["motivo"]


def test_arquivo_ausente_do_produtor_e_indisponivel_nao_erro() -> None:
    readers = [r for r in _all_ok() if r.group != "verificacao"] + [Fake("verificacao", FileNotFoundError("x.json"))]
    assert _aggregate(readers)["verificacao"]["estado"] == "indisponivel"


def test_excecao_vira_erro_sem_bloquear_os_demais_e_chama_on_error() -> None:
    readers = [r for r in _all_ok() if r.group != "custo_recursos"] + [Fake("custo_recursos", RuntimeError("banco caiu"))]
    seen: list[tuple[str, str]] = []
    metrics = _aggregate(readers, on_error=lambda g, m: seen.append((g, m)))
    assert metrics["custo_recursos"]["estado"] == "erro" and "banco caiu" in metrics["custo_recursos"]["mensagem"]
    assert [metrics[g]["estado"] for g in GROUPS if g != "custo_recursos"] == ["disponivel"] * 4
    assert seen and seen[0][0] == "custo_recursos"


def test_leitor_parcial_mantem_o_grupo_disponivel_com_lacuna() -> None:
    readers = [r for r in _all_ok() if r.group != "proveniencia"] + [
        Fake("proveniencia", {"cadeia": {"resultado": "integra", "orfas": 0, "pendentes": 0, "ponta": None}}),
        Fake("proveniencia", MetricsUnavailable("sem proveniencia_numerica.json", "v18.5-numeric-references")),
    ]
    prov = _aggregate(readers)["proveniencia"]
    assert prov["estado"] == "disponivel" and prov["lacunas"][0]["produtor"] == "v18.5-numeric-references"
    assert "numeros_por_origem" not in prov


def test_parcial_e_registrado() -> None:
    assert _aggregate(_all_ok(), parcial=True)["parcial"] is True


# -- custo nunca somado como zero ----------------------------------------------------------------------------------


class FakeTelemetry:
    def __init__(self, rows, peaks=None, cpu=None, events=None) -> None:
        self.rows, self.peaks, self.cpu, self.events = rows, peaks or {}, cpu, events or {}

    def get_usage_by_task(self, execution_id):
        return self.rows

    def get_token_summary(self, execution_id):
        return {"by_provider_model": []}

    def get_hardware_peaks(self, execution_id):
        return self.peaks

    def get_average_cpu(self, execution_id):
        return self.cpu

    def get_events(self, execution_id, event_type):
        return self.events.get(event_type, [])


def _row(task, agent, tokens, cost, sem_custo=0):
    return {"task_name": task, "agent_id": agent, "tokens": tokens, "cost_usd": cost, "calls": 2,
            "calls_sem_custo": sem_custo}


def test_custo_nulo_nao_e_somado_como_zero(monkeypatch) -> None:
    rows = [_row("a", "researcher", 100, None, 2), _row("b", "developer", 50, 0.25), _row("c", "developer", 10, None, 1)]
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: FakeTelemetry(rows, cpu=None))
    out = CostResourcesReader().read("s")
    assert out["tokens_total"] == 160 and out["custo_usd_total"] == 0.25 and out["chamadas_sem_custo"] == 3
    by_task = {r["task_name"]: r["custo_usd"] for r in out["por_tarefa"]}
    assert by_task == {"a": None, "b": 0.25, "c": None}
    by_role = {r["agent_id"]: r["custo_usd"] for r in out["por_papel"]}
    assert by_role == {"researcher": None, "developer": 0.25}
    assert out["no"]["cpu_pct_medio"] is None and out["no"]["temperatura_pico_c"] is None


def test_total_de_custo_e_nulo_quando_nenhuma_chamada_informou(monkeypatch) -> None:
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: FakeTelemetry([_row("a", "researcher", 7, None, 2)]))
    assert CostResourcesReader().read("s")["custo_usd_total"] is None


def test_hardware_do_no(monkeypatch) -> None:
    peaks = {"max_temp_c": 80.5, "max_cpu_pct": 99.0, "max_mem_pct": 70.0, "min_mem_available_mb": 1200.0,
             "throttle_incidents": 3}
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: FakeTelemetry([], peaks=peaks, cpu=42.34))
    node = CostResourcesReader().read("s")["no"]
    assert node == {"cpu_pct_medio": 42.3, "cpu_pct_pico": 99.0, "ram_pct_pico": 70.0, "ram_disponivel_min_mb": 1200.0,
                    "temperatura_pico_c": 80.5, "incidentes_throttling": 3}


def test_rejeicoes_de_plano_contam_so_os_reprovados(monkeypatch) -> None:
    events = {"plan_validation": [{"payload": {"approved": False}}, {"payload": {"approved": True}},
                                   {"payload": {"approved": False}}]}
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: FakeTelemetry([], events=events))
    assert PlanRejectionReader().read("s") == {"ciclos_rejeicao_plano": 2}


def test_intervencoes_humanas_sem_inventar_zeros(monkeypatch) -> None:
    payload = {
        "researcher_interactions": [{"respondido_por": "pesquisador", "subtask_name": "t1"},
                                    {"respondido_por": "researcher", "subtask_name": "t2"}, {"subtask_name": "t3"}],
        "divergence_reports": [{"task_name": "x"}],
    }
    events = {"researcher_interruption": [{"timestamp": "2026-10-12T10:00:00+00:00", "task_name": None}]}
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: FakeTelemetry([], events=events))
    out = HumanInterventionsReader(lambda sid: payload).read("s")
    assert out["respostas_ask_researcher"] == 2  # a resposta do agente `researcher` não é do pesquisador
    assert out["interrupcoes"] == 1
    assert out["aprovacoes"] is None and out["rejeicoes"] is None and out["edicoes"] is None
    assert out["decisoes_divergencia"] is None and out["suspensoes"] is None
    assert {e["tipo"] for e in out["eventos"]} == {"resposta_ask_researcher", "interrupcao"}


def test_intervencoes_sem_payload_loader_e_indisponivel() -> None:
    with pytest.raises(MetricsUnavailable):
        HumanInterventionsReader(None).read("s")


# -- seção do relatório (8.12) -------------------------------------------------------------------------------------


def test_secao_delimitada_com_os_mesmos_numeros_do_payload() -> None:
    metrics = _aggregate(_all_ok(), unlimited=unlimited_block(
        {"unlimited": True, "unlimited_origem": "cli", "unlimited_confirmado_em": "2026-10-12T09:00:00+00:00"}, 3))
    section = render_operation_metrics_section(metrics, stop_reason="solucao_encontrada")
    assert section.startswith(BEGIN_MARK) and section.rstrip().endswith(END_MARK)
    assert "SEM LIMITE" in section and "origem: cli" in section and "avisos de consumo emitidos: 3" in section
    assert "solucao_encontrada" in section
    assert "2.048 bytes" in section and "12.345 tokens" in section and "0.42 USD" in section
    assert "res=5" in section and "suportada=3" in section and "planos reprovados: 2" in section
    assert "interrupções: 1" in section and "respostas ao ask_researcher: 2" in section
    assert render_operation_metrics_section(metrics, stop_reason="solucao_encontrada") == section  # determinístico


def test_secao_mostra_indisponivel_erro_e_parcial() -> None:
    readers = [r for r in _all_ok() if r.group not in ("egresso", "custo_recursos")]
    readers.append(Fake("custo_recursos", RuntimeError("falhou")))
    section = render_operation_metrics_section(_aggregate(readers, parcial=True))
    assert "**Egresso:** indisponível" in section
    assert "**Custo e recursos:** erro de leitura" in section
    assert "métricas parciais" in section
    assert "com limites de orçamento" in section


def test_secao_custo_nao_informado() -> None:
    readers = [r for r in _all_ok() if r.group != "custo_recursos"]
    readers.append(Fake("custo_recursos", {
        "tokens_total": 10, "custo_usd_total": None, "chamadas_sem_custo": 2, "por_tarefa": [],
        "por_papel": [{"agent_id": "researcher", "tokens": 10, "custo_usd": None}],
        "no": {"cpu_pct_medio": None, "cpu_pct_pico": None, "ram_pct_pico": None, "ram_disponivel_min_mb": None,
               "temperatura_pico_c": None, "incidentes_throttling": 0},
    }))
    section = render_operation_metrics_section(_aggregate(readers))
    assert "custo não informado" in section and "n/d" in section


def test_verificador_de_numeros_trata_a_secao_como_contagem_do_orquestrador() -> None:
    section = render_operation_metrics_section(_aggregate(_all_ok()))
    outcome = verify_numbers("# Relatório\n\nTexto sem números.\n\n" + section)
    assert outcome.nao_verificados == [] and "[não verificado]" not in outcome.texto


def test_linha_da_cadeia_de_sessoes_continuadas() -> None:
    sessions = [
        {"custo_recursos": {"tokens_total": 100, "custo_usd_total": 0.1}, "egresso": {"bytes_total": 10}},
        {"custo_recursos": {"tokens_total": 50, "custo_usd_total": None}, "egresso": {"bytes_total": 5}},
    ]
    line = render_chain_line(sessions)
    assert "2 sessões" in line and "150 tokens" in line and "0.10 USD" in line and "15 bytes" in line


def test_bloco_do_modo_sem_limite() -> None:
    assert unlimited_block(None, 0)["ativo"] is False
    block = unlimited_block({"unlimited": True, "unlimited_origem": "projeto", "unlimited_confirmado_em": "t"}, 4)
    assert block == {"ativo": True, "origem": "projeto", "confirmado_em": "t", "avisos_emitidos": 4}


def test_leitores_dos_produtores_existentes_tem_produtor_e_grupo() -> None:
    from src.claims.metrics import ClaimVerificationReader
    from src.numeric_refs.provenance_file import NumericProvenanceReader

    for reader in (ClaimVerificationReader("/tmp"), NumericProvenanceReader("/tmp")):
        assert reader.producer.startswith("v18.5-") and reader.group in GROUPS


# -- no laço: gravação no payload, anexo ao relatório e cadeia de sessões ------------------------------------------


@pytest.mark.asyncio
async def test_laco_grava_no_payload_anexa_a_secao_e_soma_a_cadeia(tmp_path, monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from src.orchestration.autonomous_loop import AutonomousLoop

    payloads = {
        "s2": {"continues_session_id": "s1", "budget": {"unlimited": False}},
        "s1": {"operation_metrics": {"custo_recursos": {"tokens_total": 100, "custo_usd_total": 0.1},
                                     "egresso": {"bytes_total": 7}}},
    }
    orchestrator = MagicMock()
    orchestrator.output_manager.base_dir = tmp_path
    orchestrator.session_manager.get.side_effect = lambda sid: SimpleNamespace_(payloads[sid])
    orchestrator.session_manager.update.side_effect = lambda sid, payload=None, **kw: payloads.__setitem__(sid, payload)
    loop = AutonomousLoop(orchestrator)
    monkeypatch.setattr("src.report.operation_metrics.default_readers", lambda *a, **k: _all_ok())
    monkeypatch.setattr("src.orchestration.autonomous_loop.get_telemetry", lambda: MagicMock(flush=AsyncMock()))

    markdown = await loop._append_operation_metrics_section("# Relatório\n", "s2", tmp_path, "solucao_encontrada")

    assert payloads["s2"]["operation_metrics"]["custo_recursos"]["tokens_total"] == 12345
    assert markdown.count(BEGIN_MARK) == 1 and "solucao_encontrada" in markdown
    assert "Cadeia de 2 sessões continuadas" in markdown and "12.445 tokens" in markdown
    assert (tmp_path / "relatorio_final.md").read_text(encoding="utf-8") == markdown


@pytest.mark.asyncio
async def test_laco_falha_de_agregacao_nao_bloqueia_o_relatorio(tmp_path, monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from src.orchestration.autonomous_loop import AutonomousLoop

    orchestrator = MagicMock()
    orchestrator.output_manager.base_dir = tmp_path
    loop = AutonomousLoop(orchestrator)

    def boom(*a, **k):
        raise RuntimeError("leitores quebraram")

    monkeypatch.setattr("src.report.operation_metrics.default_readers", boom)
    monkeypatch.setattr("src.orchestration.autonomous_loop.get_telemetry", lambda: MagicMock(flush=AsyncMock()))
    markdown = await loop._append_operation_metrics_section("# R\n", "s", tmp_path, None)
    assert "Não foi possível agregar as métricas de operação" in markdown and "# R" in markdown


class SimpleNamespace_:  # noqa: N801 - sessão mínima (payload) para o gerenciador simulado
    def __init__(self, payload) -> None:
        self.payload = payload
        self.status = "closed"
