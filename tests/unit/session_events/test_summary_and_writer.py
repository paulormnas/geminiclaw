"""Resumo de evento, dados fechados, escritor tolerante e ouvinte da telemetria (session-continuity 1.4)."""

import logging
import re
from pathlib import Path

import pytest

import src.session.events as events
from src import config
from src.session.events import EventWriter, TelemetryTap, limpa_dados, monta_resumo, resumo_final

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]


def test_tipos_do_codigo_sao_os_do_check_da_tabela():
    sql = (ROOT / "scripts" / "migrations" / "v18_7_003_session_events.sql").read_text(encoding="utf-8")
    bloco = sql[sql.index("tipo        TEXT"):sql.index("criado_em")]
    assert tuple(re.findall(r"'([a-z_]+)'", bloco)) == events.TIPOS
    init = (ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS session_events" in init and "idx_session_events_sessao" in init


def test_metrica_validada_aparece_no_resumo():
    resumo = resumo_final("subtarefa_concluida", {"subtarefa": "treinar_rf", "metrica": "acuracia", "valor": 0.967,
                                                  "validada": True})
    assert resumo == "treinar_rf concluída (acuracia 0,967, validada)"


def test_metrica_nao_validada_nao_entra():
    assert resumo_final("subtarefa_concluida", {"subtarefa": "t", "metrica": "acuracia", "valor": 0.9}) == "t concluída"


def test_dado_sensivel_nao_aparece():
    """Scenario: o resultado bruto nunca entra, porque só os campos estruturados montam o resumo."""
    campos = {
        "subtarefa": "treinar_rf", "stdout": "/home/usuario/dados/amostra.csv\nTraceback (most recent call last)",
        "resultado": "12.537", "caminho": "/home/usuario/dados/amostra.csv",
    }
    resumo, dados = resumo_final("subtarefa_concluida", campos), limpa_dados("subtarefa_concluida", campos)
    assert resumo == "treinar_rf concluída"
    for proibido in ("/home", "Traceback", "12.537", "12,537"):
        assert proibido not in resumo and proibido not in str(dados)


def test_chave_fora_da_lista_em_dados_e_descartada():
    dados = limpa_dados("subtarefa_concluida", {"subtarefa": "t", "stdout": "x", "valor": 0.5, "lista": [1, 2]})
    assert dados == {"subtarefa": "t", "valor": 0.5}


def test_campo_de_texto_e_saneado_e_cortado():
    resumo = monta_resumo("subtarefa_iniciada", {"subtarefa": "a\x1b[2Jb" + "x" * 200})
    assert "\x1b" not in resumo and len(resumo) < 90


def test_resumo_respeita_o_teto(monkeypatch):
    monkeypatch.setattr(config, "SESSION_EVENT_SUMMARY_MAX_CHARS", 20)
    assert len(resumo_final("parada", {"motivo": "m" * 60})) <= 20
    assert len(resumo_final("parada", {"motivo": "m" * 400})) <= 20


@pytest.mark.parametrize("tipo, campos, esperado", [
    ("sessao_iniciada", {"modo": "auto", "papeis": 2}, "iniciada (modo auto, 2 papéis resolvidos)"),
    ("plano_aprovado", {"versao": 2, "subtarefas": 5, "hipoteses": 3}, "plano 2 aprovado: 5 subtarefas, 3 hipóteses"),
    ("hipotese_concluida", {"hipotese": "h3", "estado": "refutada", "veredito": -0.41}, "h3 refutada (veredito -0,41)"),
    ("objetivo_atingido", {"metrica": "acuracia", "valor": 1.0, "alvo": 0.95, "politica": "parar"},
     "objetivo atingido: acuracia 1 ≥ 0,95 (política: parar)"),
    ("decisao_pendente", {"decisao": "aprovar_hipotese", "pedido_id": 12, "referencia": "h4"},
     "aguarda você: aprovar a hipótese h4 (responda com 'decidir 12')"),
    ("comando_recebido", {"comando": "pausar"}, "pausa pedida: termina a subtarefa atual"),
    ("parada", {"motivo": "solucao_encontrada"}, "encerrada: solucao_encontrada"),
    ("suspensao", {"motivo": "suspensa_sem_pesquisador"}, "suspensa: terminal fechado; retome ao abrir a aplicação"),
    ("falha", {"apelido": "iris-01"}, "interrompida: processo parou; use 'retomar iris-01'"),
])
def test_modelos_de_resumo(tipo, campos, esperado):
    assert resumo_final(tipo, campos) == esperado


def test_tipo_desconhecido_nao_derruba_o_escritor():
    writer = EventWriter("s", connection=lambda: pytest.fail("não deveria gravar"))
    writer.emit("tipo_inventado", {})  # só registra aviso


def test_falha_de_gravacao_nao_derruba_e_registra_aviso(caplog):
    tentativas = []

    def banco_fora():
        tentativas.append(1)
        raise RuntimeError("banco indisponível")

    writer = EventWriter("s1", connection=banco_fora, retry_delay=0)
    with caplog.at_level(logging.WARNING):
        writer.emit("parada", {"motivo": "erro"}, wait=True)  # não levanta
    assert len(tentativas) == 2  # a original e uma nova tentativa
    assert any("Evento de sessão não gravado" in r.getMessage() for r in caplog.records)
    assert any(getattr(r, "extra", {}).get("tipo") == "parada" for r in caplog.records)


class _Gravador:
    def __init__(self):
        self.itens = []

    def __call__(self, session_id, tipo, campos=None, *, wait=False):
        self.itens.append((session_id, tipo, campos))


@pytest.fixture
def gravador(monkeypatch):
    g = _Gravador()
    monkeypatch.setattr(events, "emit_event", g)
    return g


def test_ouvinte_converte_eventos_da_telemetria(gravador):
    tap = TelemetryTap("s1")
    tap("subtask_start", "s1", "treinar_rf", {})
    tap("subtask_review", "s1", "treinar_rf", {"approved": False, "attempt": 0})
    tap("subtask_end", "s1", "treinar_rf", {"success": True, "metrica_validada": "acuracia", "valor_validado": 0.9})
    tap("subtask_end", "s1", "outra", {"success": False})
    tap("plan_validation", "s1", None, {"approved": True, "plan_tasks": 5, "plan_hipoteses": 3})
    tap("plan_validation", "s1", None, {"approved": False, "plan_tasks": 5})
    tap("plan_validation", "s1", None, {"approved": True, "plan_tasks": 2})
    tap("hipotese_transicao", "s1", None, {"hipotese_id": "h3", "status_novo": "refutada", "veredito_novo": -0.4})
    tap("hipotese_transicao", "s1", None, {"hipotese_id": "h4", "status_novo": "em_teste"})
    tap("objetivo_atingido", "s1", None, {"valor": 1.0, "politica": "parar", "metrica": "acuracia", "alvo": 0.95})
    tap("subtask_start", "outra-sessao", "x", {})
    tipos = [t for _, t, _ in gravador.itens]
    assert tipos == ["subtarefa_iniciada", "subtarefa_reprovada", "subtarefa_concluida", "subtarefa_reprovada",
                     "plano_aprovado", "plano_aprovado", "hipotese_concluida", "objetivo_atingido"]
    planos = [c for _, t, c in gravador.itens if t == "plano_aprovado"]
    assert [p["versao"] for p in planos] == [1, 2] and planos[0]["hipoteses"] == 3
    concluida = next(c for _, t, c in gravador.itens if t == "subtarefa_concluida")
    assert concluida["validada"] is True and concluida["metrica"] == "acuracia"


def test_telemetria_notifica_os_ouvintes_e_ouvinte_com_erro_nao_derruba(monkeypatch):
    from src.observability import telemetry

    vistos = []

    def bom(event_type, session_id, task_name, payload):
        vistos.append((event_type, session_id, task_name, payload))

    def ruim(*args):
        raise RuntimeError("falhou")

    telemetry.add_event_tap(ruim)
    telemetry.add_event_tap(bom)
    try:
        coletor = telemetry.TelemetryCollector.__new__(telemetry.TelemetryCollector)
        coletor._buffer = type("B", (), {"agent_events": []})()
        coletor._maybe_flush_sync = lambda: None
        coletor.record_agent_event("e1", "s1", "developer", "subtask_start", task_name="t", payload={"a": 1})
    finally:
        telemetry.remove_event_tap(ruim)
        telemetry.remove_event_tap(bom)
    assert vistos == [("subtask_start", "s1", "t", {"a": 1})]


def test_config_validada():
    assert config.SESSION_EVENT_SUMMARY_MAX_CHARS == 300 and config.SESSION_EVENTS_RETENTION_DAYS == 0
    assert config.TERMINAL_EVENT_DETAIL == "resumo" and config.SESSION_EVENTS_POLL_SECONDS == 2


def test_interrupcao_na_partida_sobrevive_a_limpeza_do_inicio_do_laco():
    """O 1º SIGINT entre o registro da sessão e o início do laço também é gracioso (corrida do teste de SIGINT)."""
    from src.orchestration import usage

    usage.clear_interrupt(force=True)
    usage.request_interrupt(before_start=True)
    usage.clear_interrupt()  # o que AutonomousLoop.run() faz ao começar
    assert usage.interrupt_requested() is True
    usage.clear_interrupt()  # a limpeza seguinte (próxima sessão) apaga
    assert usage.interrupt_requested() is False
    usage.request_interrupt()  # pedido comum, sem before_start: a limpeza o apaga
    usage.clear_interrupt()
    assert usage.interrupt_requested() is False
