"""Integração do registro de egresso contra um PostgreSQL real (v18.5-egress-gate, tarefas 1.3, 5.1 e 7.1).

Escritos e NÃO executados no PR da mudança (restrição de ambiente: sem containers reais). Requerem um PostgreSQL
acessível via DATABASE_URL; são pulados automaticamente sem ele.

Para rodar (em máquina com o banco do projeto no ar), selecione este arquivo com o marcador de integração.
"""

from __future__ import annotations

import gzip
import json
import os
import uuid
from pathlib import Path

import pytest

MIGRATION = Path(__file__).resolve().parents[2] / "scripts" / "migrations" / "v18_5_egress_log.sql"


def _postgres_available() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        return False
    try:
        import psycopg

        psycopg.connect(url, connect_timeout=3).close()
        return True
    except Exception:
        return False


skip_if_no_postgres = pytest.mark.skipif(
    not _postgres_available(), reason="PostgreSQL não disponível (suba o banco do projeto)."
)
pytestmark = [pytest.mark.integration, skip_if_no_postgres]


@pytest.fixture(scope="module")
def conninfo() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="module", autouse=True)
def migrated(conninfo):
    """Aplica a migração duas vezes: ela é idempotente e aditiva."""
    import psycopg

    sql = MIGRATION.read_text(encoding="utf-8")
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(sql)
        conn.execute(sql)
    yield


@pytest.fixture
def session_id(conninfo):
    sid = f"egr-int-{uuid.uuid4().hex[:8]}"
    yield sid
    import psycopg

    with psycopg.connect(conninfo, autocommit=True) as conn:  # remove só as linhas deste teste
        conn.execute("DELETE FROM egress_log WHERE session_id = %s", (sid,))


@pytest.fixture(autouse=True)
def real_pool():
    import src.db as db_module

    if db_module._pool is not None:
        db_module.close_pool()
    yield
    if db_module._pool is not None:
        db_module.close_pool()


def _dest(**kw):
    from src.egress.gate import Destination

    base = dict(canal="llm", provedor="google", modelo="gemini", trust="third_party", localidade="fora_do_no",
                aceita_dados_brutos=False, papel="researcher", versao_efetiva="desconhecida")
    base.update(kw)
    return Destination(**base)


def _rows(conninfo, sid):
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(conninfo, row_factory=dict_row) as conn:
        return conn.execute("SELECT * FROM egress_log WHERE session_id = %s ORDER BY created_at", (sid,)).fetchall()


def test_envio_gera_uma_linha_com_jsonb_e_cobre_os_campos_do_design(conninfo, session_id, tmp_path):
    from src.egress.fragments import ContentOrigin, PromptFragment, labeled
    from src.egress.gate import EgressGate

    gate = EgressGate(session_id, output_dir=tmp_path, min_group_size=10)
    mensagem = labeled("tool", PromptFragment("max: 12.537", ContentOrigin.SAIDA_EXECUCAO, source="step_01:stdout"))
    prepared = gate.prepare_llm([mensagem], "Papel.", _dest())

    (linha,) = _rows(conninfo, session_id)
    assert linha["id"] == prepared.record_id and linha["id"].startswith("egr_")
    assert (linha["canal"], linha["papel"], linha["provedor"], linha["localidade"]) == (
        "llm", "researcher", "google", "fora_do_no",
    )
    assert linha["aceita_dados_brutos"] is False and linha["recusado"] is False
    assert linha["bytes_saida_execucao_novos"] > 0 and linha["bytes_enviados"] >= linha["bytes_saida_execucao_novos"]
    saida = next(f for f in linha["fragmentos"] if f["origem"] == "saida_execucao")
    assert saida["source"] == "step_01:stdout" and len(saida["sha256"]) == 64 and saida["novo"] is True
    assert linha["intervencoes"]["extremo_em_faixa"] == 1
    # O conteúdo enviado não vai ao banco; vai à cópia local compactada, com o id da linha.
    assert "12.537" not in json.dumps(linha["fragmentos"], default=str)
    copia = tmp_path / session_id / "egress" / "envios.jsonl.gz"
    registro = json.loads(gzip.open(copia, "rt", encoding="utf-8").read().splitlines()[0])
    assert registro["id"] == prepared.record_id and "[10, 20)" in json.dumps(registro["payload"], ensure_ascii=False)


def test_volume_da_sessao_soma_so_saidas_novas_fora_do_no(conninfo, session_id, tmp_path):
    from src.egress.fragments import ContentOrigin, PromptFragment, labeled
    from src.egress.gate import EgressGate

    gate = EgressGate(session_id, output_dir=tmp_path, min_group_size=10)
    historico = [labeled("tool", PromptFragment("saida longa " * 10, ContentOrigin.SAIDA_EXECUCAO))]
    for _ in range(3):  # reenvio do mesmo histórico: conta uma vez
        gate.prepare_llm(historico, None, _dest())
    gate.prepare_llm(historico, None, _dest(localidade="no_no", aceita_dados_brutos=True, provedor="ollama"))
    assert gate.egress_bytes_for_session() == len("saida longa " * 10)
    assert gate.new_output_bytes == len("saida longa " * 10)


def test_recusa_e_registrada_sem_o_conteudo_recusado(conninfo, session_id, tmp_path):
    from src.egress.gate import EgressGate, EgressRefused

    gate = EgressGate(session_id, output_dir=tmp_path, min_group_size=10)
    with pytest.raises(EgressRefused):
        gate.check_url("https://exemplo.org/api?v=12.537", True, _dest(canal="leitura_web", provedor="exemplo.org"))
    (linha,) = _rows(conninfo, session_id)
    assert linha["recusado"] is True and linha["canal"] == "leitura_web"
    assert "12.537" not in json.dumps(linha["fragmentos"], default=str)


def test_tracker_le_o_limite_do_banco_e_fecha_com_limite_egresso(conninfo, session_id, tmp_path):
    from src.egress.fragments import ContentOrigin, PromptFragment, labeled
    from src.egress.gate import EgressGate
    from src.usage import StopReason, UsageBudget, UsageTracker

    gate = EgressGate(session_id, output_dir=tmp_path, min_group_size=10, output_max_chars=50_000)
    gate.prepare_llm([labeled("tool", PromptFragment("x" * 200, ContentOrigin.SAIDA_EXECUCAO))], None, _dest())
    budget = UsageBudget(max_tokens=10_000, max_minutes=60, max_task_retries=3, max_connection_retries=5,
                         closing_reserve_pct=0.0, max_egress_bytes=200)
    tracker = UsageTracker(budget, session_id, token_reader=lambda: 0, connection_retry_reader=lambda: 0)
    status = tracker.check()
    assert status.egress_bytes == 200 and status.stop_reason is StopReason.EGRESS


def test_falha_do_banco_impede_o_envio(session_id, tmp_path, monkeypatch):
    """Fail-fast contra o pool real: apontar a conexão para um banco inexistente barra o envio."""
    import src.db as db_module
    from src.egress.fragments import ContentOrigin, PromptFragment, labeled
    from src.egress.gate import EgressGate
    from src.egress.log import EgressLogError

    if db_module._pool is not None:
        db_module.close_pool()
    monkeypatch.setattr("src.config.DATABASE_URL", "postgresql://x:y@127.0.0.1:1/inexistente?connect_timeout=1")
    monkeypatch.setattr(db_module, "_pool", None)
    gate = EgressGate(session_id, output_dir=tmp_path, min_group_size=10)
    with pytest.raises(EgressLogError):
        gate.prepare_llm([labeled("user", PromptFragment("oi", ContentOrigin.INSTRUCAO))], None, _dest())
