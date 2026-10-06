"""Testes de ``src.knowledge.ingestion`` (``openspec/changes/v17-structural-fact-ingestion``).

Usam ``InMemoryGraphStore`` e arquivos em ``tmp_path``; nenhum teste usa rede, LLM, Docker ou AGE.
Um teste por ``#### Scenario`` da spec ``knowledge-ingestion`` (nome do cenário no docstring), mais
os casos de segurança e resiliência do design.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from src.knowledge import vocabulary
from src.knowledge.errors import GraphStoreError, HumanConfirmationRequiredError
from src.knowledge.failure_cause import classify_failure
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion import (
    ACTOR_ORQUESTRADOR,
    FactIngestor,
    IngestionDataError,
    SessionContext,
    SubtaskInput,
    ingest_inputs,
    ingest_session_end,
    ingest_session_start,
    ingest_subtask,
    insumo_tipo,
    normalize_config,
    replay_event,
    sync_pending,
)
from src.knowledge.ingestion_io import collect_evidence
from src.knowledge.ingestion_queue import PENDING_FILENAME, PendingQueue
from src.knowledge.projects import create_project
from src.knowledge.provenance import Actor
from src.knowledge.vocabulary import seed_vocabulary

FIXTURE_CSV = Path(__file__).resolve().parents[2] / "fixtures" / "cnpq_areas_fixture.csv"
REAL_METRICS = vocabulary.DEFAULT_VOCABULARY_DIR / vocabulary.METRICS_FILENAME
SESSION = "sessao-teste"


@pytest.fixture
def store(tmp_path_factory) -> InMemoryGraphStore:
    vocab_dir = tmp_path_factory.mktemp("vocab")
    shutil.copy(FIXTURE_CSV, vocab_dir / vocabulary.CNPQ_FILENAME)
    shutil.copy(REAL_METRICS, vocab_dir / vocabulary.METRICS_FILENAME)
    s = InMemoryGraphStore()
    seed_vocabulary(s, vocabulary_dir=vocab_dir)
    return s


@pytest.fixture
def project_id(store) -> str:
    return create_project(store, "Projeto de teste", "Objetivo de teste", [])


@pytest.fixture
def session_dir(tmp_path) -> Path:
    d = tmp_path / SESSION
    d.mkdir()
    return d


@pytest.fixture
def ctx(project_id) -> SessionContext:
    return SessionContext(
        project_id=project_id, session_id=SESSION, modo="auto", inicio="2026-10-06T10:00:00+00:00", no_execucao="no-1"
    )


def _write_task(
    session_dir: Path,
    task: str = "treinar",
    *,
    metrics: dict | None = None,
    parameters: dict | None = None,
    datasets: list | None = None,
    baselines: dict | None = None,
    divergence_note: str | None = None,
    raw_metrics: str | None = None,
    seed: int | None = 42,
) -> Path:
    folder = session_dir / task
    folder.mkdir(exist_ok=True)
    params = {"task_name": task, "seed": seed, "parameters": parameters or {"n_estimators": 100}}
    if datasets is not None:
        params["datasets"] = datasets
    (folder / "params.json").write_text(json.dumps(params), encoding="utf-8")
    if raw_metrics is not None:
        (folder / "metrics.json").write_text(raw_metrics, encoding="utf-8")
    elif metrics is not None:
        payload = {"task_name": task, "seed": seed, "parameters": params["parameters"], "metrics": metrics,
                   "divergence_note": divergence_note}
        if datasets is not None:
            payload["datasets"] = datasets
        if baselines is not None:
            payload["baselines"] = baselines
        (folder / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    return folder


def _manifest(session_dir: Path, steps: list[dict]) -> None:
    (session_dir / "manifest.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")


def _nodes(store, label):
    return store.find_nodes(label, {}, limit=10_000)


def _rels(store, rel):
    return [e for e in store._edges if e.rel_type == rel]  # noqa: SLF001 - inspeção do dublê em memória


def _sub(**kw) -> SubtaskInput:
    base = {"task_name": "treinar", "subtask_id": "sub-1", "agent_id": "developer", "review_status": "pass",
            "review_verified": True}
    base.update(kw)
    return SubtaskInput(**base)


# --- Requirement: Fatos escritos pelo orquestrador --------------------------


@pytest.mark.unit
def test_subtarefa_com_metricas(store, ctx, session_dir):
    """Scenario: Subtarefa com métricas."""
    _write_task(session_dir, metrics={"r2": 0.8}, baselines={"r2": 0.7})
    ingest_session_start(store, ctx)
    sub = _sub(
        approach={"nome": "gradient boosting", "tipo": "algoritmo"},
        validation_criteria=["r2 >= 0.75"],
    )
    exp_id = ingest_subtask(store, ctx, session_dir, sub)

    exp = store.get_node(exp_id)
    assert exp.properties["status"] == "sucesso"
    assert exp.properties["subtarefa_id"] == "sub-1"
    (res,) = _nodes(store, "Resultado")
    assert res.properties["nome_original"] == "r2"
    assert res.properties["valor"] == 0.8
    assert res.properties["baseline"] == 0.7
    assert res.properties["status_validacao"] == "validado"
    assert [e.dst_id for e in _rels(store, "EXECUTADO_EM")] == [_nodes(store, "Sessao")[0].id]
    assert [(e.src_id, e.dst_id) for e in _rels(store, "PRODUZIU")] == [(exp_id, res.id)]
    (mede,) = _rels(store, "MEDE")
    assert store.get_node(mede.dst_id).properties["nome"] == "r2"
    (aplicou,) = _rels(store, "APLICOU")
    assert store.get_node(aplicou.dst_id).properties["nome"] == "gradient boosting"
    assert aplicou.properties["config"] == {"n_estimators": 100}
    assert aplicou.properties["hash_params"]
    assert store.get_node(aplicou.dst_id).properties["criado_por"] == "researcher"
    assert exp.properties["criado_por"] == "orquestrador"


@pytest.mark.unit
def test_insumos_do_pesquisador(store, ctx, session_dir):
    """Scenario: Insumos do pesquisador."""
    snap = session_dir / "input_snapshot"
    snap.mkdir()
    (snap / "dados.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (snap / "artigo.pdf").write_bytes(b"%PDF-1.4 conteudo")
    ingest_session_start(store, ctx)
    assert ingest_inputs(store, ctx, session_dir) == 2

    tipos = {n.properties["titulo"]: n.properties["tipo"] for n in _nodes(store, "Insumo")}
    assert tipos == {"dados.csv": "dataset", "artigo.pdf": "artigo"}
    recebeu = _rels(store, "RECEBEU")
    assert len(recebeu) == 2
    assert {store.get_node(e.src_id).label for e in recebeu} == {"Projeto"}
    assert insumo_tipo("x.bin") == "outro"
    assert all(len(n.properties["hash_conteudo"]) == 64 for n in _nodes(store, "Insumo"))


@pytest.mark.unit
def test_dataset_usado(store, ctx, session_dir):
    """Scenario: Dataset usado."""
    snap = session_dir / "input_snapshot"
    snap.mkdir()
    (snap / "dados.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    _write_task(session_dir, metrics={"r2": 0.8}, datasets=["dados.csv"])
    ingest_session_start(store, ctx)
    exp_id = ingest_subtask(store, ctx, session_dir, _sub())

    (insumo,) = _nodes(store, "Insumo")
    (usou,) = _rels(store, "USOU")
    assert (usou.src_id, usou.dst_id) == (exp_id, insumo.id)
    assert store.get_node(exp_id).properties["dataset_ids"] == [insumo.id]


@pytest.mark.unit
def test_fim_de_sessao(store, ctx):
    """Scenario: Fim de sessão."""
    ingest_session_start(store, ctx)
    ingest_session_end(
        store, ctx, fim="2026-10-06T11:00:00+00:00", motivo_parada="limite_tokens",
        consumo={"tokens": 1200, "minutos": 3.5, "retentativas_conexao": 0},
    )
    (sessao,) = _nodes(store, "Sessao")
    assert sessao.properties["fim"] == "2026-10-06T11:00:00+00:00"
    assert sessao.properties["motivo_parada"] == "limite_tokens"
    assert sessao.properties["consumo"]["tokens"] == 1200
    assert sessao.properties["modo"] == "auto"
    assert sessao.properties["no_execucao"] == "no-1"
    (pertence,) = _rels(store, "PERTENCE_A")
    assert store.get_node(pertence.dst_id).label == "Projeto"


@pytest.mark.unit
def test_sessao_continua_outra(store, project_id, ctx):
    """Design §1: ``continues_session_id`` gera ``Sessao-CONTINUA->Sessao``."""
    ingest_session_start(store, ctx)
    nxt = SessionContext(project_id=project_id, session_id="sessao-2", modo="semi", inicio="x", no_execucao="no-1",
                         continues_session_id=SESSION)
    ingest_session_start(store, nxt)
    (cont,) = _rels(store, "CONTINUA")
    assert store.get_node(cont.src_id).properties["sessao_id"] == "sessao-2"
    assert store.get_node(cont.dst_id).properties["sessao_id"] == SESSION


@pytest.mark.unit
def test_sessao_com_duas_subtarefas(store, ctx, session_dir):
    """Task 4.1: sessão com 2 subtarefas gera os nós e arestas esperados."""
    _write_task(session_dir, "preparar", metrics={"linhas": 100.0}, parameters={"limite": 5})
    _write_task(session_dir, "treinar", metrics={"r2": 0.8, "mae": 1.5}, baselines={"mae": 2.0})
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub(task_name="preparar", subtask_id="a"))
    ingest_subtask(store, ctx, session_dir, _sub(task_name="treinar", subtask_id="b",
                                                 approach={"nome": "Árvore de decisão"}, hypothesis="H1 é verdadeira"))
    ingest_session_end(store, ctx, fim="f", motivo_parada="solucao_encontrada")

    assert len(_nodes(store, "Sessao")) == 1
    assert len(_nodes(store, "Experimento")) == 2
    assert len(_nodes(store, "Resultado")) == 3
    assert len(_rels(store, "EXECUTADO_EM")) == 2
    assert len(_rels(store, "PRODUZIU")) == 3
    (abord,) = _nodes(store, "Abordagem")
    assert abord.properties["tipo"] == "outro"
    (hip,) = _nodes(store, "Hipotese")
    assert hip.properties["status"] == "em_teste" and hip.properties["origem"] == "researcher"
    (testa,) = _rels(store, "TESTA")
    assert testa.dst_id == hip.id


@pytest.mark.unit
def test_subtarefa_sem_codigo_nem_metricas_nao_gera_nos(store, ctx, session_dir):
    """Design §1: subtarefa de síntese sem ``metrics.json`` não gera nós."""
    ingest_session_start(store, ctx)
    assert ingest_subtask(store, ctx, session_dir, _sub(agent_id="summarizer", task_type="synthesis")) is None
    assert _nodes(store, "Experimento") == []


# --- Requirement: Causa da falha classificada deterministicamente -----------


def _failed(**kw):
    kw.setdefault("review_status", None)
    return _sub(agent_status="error", **kw)


@pytest.mark.unit
def test_excecao_no_codigo(store, ctx, session_dir):
    """Scenario: Exceção no código."""
    _write_task(session_dir, metrics=None)
    _manifest(session_dir, [{"task_name": "treinar", "status": "failed", "code_file": "step_01.py",
                             "run": {"exit_code": 1, "exception_type": "MemoryError", "oom_killed": False}}])
    ingest_session_start(store, ctx)
    exp = store.get_node(ingest_subtask(store, ctx, session_dir, _failed()))
    assert exp.properties["status"] == "falha"
    assert exp.properties["causa_falha"] == "abordagem"
    assert exp.properties["assinatura_falha"] == "MemoryError"


@pytest.mark.unit
def test_exit_137_e_oom(store, ctx, session_dir):
    """Task 4.3: exit 137 -> abordagem/oom."""
    _manifest(session_dir, [{"task_name": "treinar", "status": "failed", "run": {"exit_code": 137}}])
    ingest_session_start(store, ctx)
    exp = store.get_node(ingest_subtask(store, ctx, session_dir, _failed()))
    assert (exp.properties["causa_falha"], exp.properties["assinatura_falha"]) == ("abordagem", "oom")


@pytest.mark.unit
def test_timeout_de_execucao(store, ctx, session_dir):
    _manifest(session_dir, [{"task_name": "treinar", "status": "failed", "run": {"exit_code": -1, "timed_out": True}}])
    ingest_session_start(store, ctx)
    exp = store.get_node(ingest_subtask(store, ctx, session_dir, _failed()))
    assert exp.properties["assinatura_falha"] == "timeout_execucao"


@pytest.mark.unit
def test_sem_metricas(store, ctx, session_dir):
    """Scenario: Sem métricas."""
    (session_dir / "treinar").mkdir()
    _manifest(session_dir, [{"task_name": "treinar", "status": "success", "run": {"exit_code": 0}}])
    ingest_session_start(store, ctx)
    exp = store.get_node(ingest_subtask(store, ctx, session_dir, _failed(review_status="fail")))
    assert (exp.properties["causa_falha"], exp.properties["assinatura_falha"]) == ("ambigua", "sem_metricas")


@pytest.mark.unit
def test_provedor_indisponivel(store, ctx, session_dir):
    """Scenario: Provedor indisponível."""
    ingest_session_start(store, ctx)
    exp = store.get_node(ingest_subtask(store, ctx, session_dir, _failed(agent_error_category="llm_connection")))
    assert exp.properties["causa_falha"] == "infraestrutura"
    assert exp.properties["assinatura_falha"] == "llm_connection"


@pytest.mark.unit
def test_daemon_indisponivel_e_infraestrutura():
    cause = classify_failure(
        agent_error_category=None, last_run={"infra_error": "docker_unavailable", "exit_code": -1},
        metrics_status="ausente", review_status=None,
    )
    assert (cause.causa, cause.assinatura) == ("infraestrutura", "docker_unavailable")


@pytest.mark.unit
def test_metrics_ilegivel_e_validacao_indeterminada():
    cause = classify_failure(agent_error_category=None, last_run=None, metrics_status="invalido", review_status="fail")
    assert (cause.causa, cause.assinatura) == ("ambigua", "validacao_indeterminada")


@pytest.mark.unit
def test_assinatura_do_sandbox_e_sanitizada():
    cause = classify_failure(
        agent_error_category=None, last_run={"exception_type": "x\nINJECT; MATCH (n) DETACH DELETE n"},
        metrics_status="ok", review_status="fail",
    )
    assert cause.causa == "ambigua"


# --- Requirement: Configuração normalizada ----------------------------------


@pytest.mark.unit
def test_normalizacao(store, ctx, session_dir):
    """Scenario: Normalização."""
    _write_task(
        session_dir, metrics={"r2": 0.8}, seed=42,
        parameters={"n_estimators": 200, "seed": 42, "data_path": "/x", "learning_rate": 0.1,
                    "random_state": 1, "output_dir": "/o"},
    )
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub(approach={"nome": "boosting"}))
    (aplicou,) = _rels(store, "APLICOU")
    assert aplicou.properties["config"] == {"learning_rate": 0.1, "n_estimators": 200}
    assert list(aplicou.properties["config"]) == ["learning_rate", "n_estimators"]


@pytest.mark.unit
def test_normalizacao_remove_caminhos_e_valores_invalidos():
    cfg = normalize_config({"Seed": 1, "dataset": "/home/x/dados.csv", "url": "http://x", "k": float("nan"),
                            "metodo": "gini", "nested": {"depth": 3, "InputFile": "a"}, "obj": object()})
    assert cfg == {"metodo": "gini", "nested": {"depth": 3}}


# --- Requirement: Ingestão idempotente --------------------------------------


@pytest.mark.unit
def test_reingestao(store, ctx, session_dir):
    """Scenario: Reingestão."""
    snap = session_dir / "input_snapshot"
    snap.mkdir()
    (snap / "dados.csv").write_text("a\n1\n", encoding="utf-8")
    _write_task(session_dir, metrics={"r2": 0.8}, datasets=["dados.csv"])
    sub = _sub(approach={"nome": "boosting"}, hypothesis="H")
    for _ in range(2):
        ingest_session_start(store, ctx)
        ingest_inputs(store, ctx, session_dir)
        ingest_subtask(store, ctx, session_dir, sub)
        ingest_session_end(store, ctx, fim="f", motivo_parada="erro")
    labels = ("Sessao", "Insumo", "Experimento", "Resultado", "Abordagem", "Hipotese")
    counts = {lb: len(_nodes(store, lb)) for lb in labels}
    assert counts == {"Sessao": 1, "Insumo": 1, "Experimento": 1, "Resultado": 1, "Abordagem": 1, "Hipotese": 1}
    for rel in ("EXECUTADO_EM", "PRODUZIU", "MEDE", "APLICOU", "USOU", "TESTA", "RECEBEU", "PERTENCE_A"):
        assert len(_rels(store, rel)) == 1, rel


@pytest.mark.unit
def test_insumo_deduplicado_por_hash_entre_sessoes(store, project_id, ctx, session_dir, tmp_path):
    other = tmp_path / "sessao-b"
    (other / "input_snapshot").mkdir(parents=True)
    for d in (session_dir, other):
        (d / "input_snapshot").mkdir(exist_ok=True)
        (d / "input_snapshot" / "dados.csv").write_text("igual\n", encoding="utf-8")
    ctx_b = SessionContext(project_id=project_id, session_id="sessao-b", modo="auto", inicio="x", no_execucao="n")
    ingest_session_start(store, ctx)
    ingest_session_start(store, ctx_b)
    ingest_inputs(store, ctx, session_dir)
    ingest_inputs(store, ctx_b, other)
    assert len(_nodes(store, "Insumo")) == 1


@pytest.mark.unit
def test_abordagem_reaproveitada_por_nome_normalizado(store, ctx, session_dir):
    _write_task(session_dir, "a", metrics={"r2": 0.8})
    _write_task(session_dir, "b", metrics={"r2": 0.9})
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub(task_name="a", subtask_id="a", approach={"nome": "Gradient Boosting"}))
    ingest_subtask(store, ctx, session_dir, _sub(task_name="b", subtask_id="b", approach={"nome": "gradient-boosting"}))
    assert len(_nodes(store, "Abordagem")) == 1
    assert len(_rels(store, "APLICOU")) == 2


# --- Requirement: Falha do grafo não interrompe a pesquisa ------------------


class _Flaky:
    """Fábrica que falha até ser liberada (grafo fora do ar / de volta)."""

    def __init__(self, store):
        self.store = store
        self.up = False

    def __call__(self):
        if not self.up:
            raise ConnectionError("grafo fora do ar")
        return self.store


@pytest.mark.unit
def test_grafo_indisponivel(store, ctx, session_dir, caplog):
    """Scenario: Grafo indisponível."""
    _write_task(session_dir, metrics={"r2": 0.8})
    flaky = _Flaky(store)
    ingestor = FactIngestor(flaky, ctx, session_dir)

    assert ingestor.session_start() is False  # não levanta
    assert ingestor.subtask(_sub()) is False
    assert any("knowledge_pending.jsonl" in r.getMessage() for r in caplog.records)
    pending = session_dir / PENDING_FILENAME
    assert pending.exists()
    assert stat.S_IMODE(pending.stat().st_mode) == 0o600
    events = [json.loads(line) for line in pending.read_text(encoding="utf-8").splitlines()]
    assert [e["kind"] for e in events] == ["session_start", "subtask"]
    assert "0.8" not in pending.read_text(encoding="utf-8")  # valores de pesquisa não vão para a fila
    assert _nodes(store, "Experimento") == []

    flaky.up = True  # o banco voltou
    report = sync_pending(store, session_dir.parent, SESSION)
    assert (report.applied, report.pending) == (2, 0)
    assert len(_nodes(store, "Experimento")) == 1
    assert not pending.exists()
    again = sync_pending(store, session_dir.parent)
    assert again.applied == 0


@pytest.mark.unit
def test_fim_de_sessao_recupera_o_grafo_e_esvazia_a_fila(store, ctx, session_dir):
    _write_task(session_dir, metrics={"r2": 0.8})
    flaky = _Flaky(store)
    ingestor = FactIngestor(flaky, ctx, session_dir)
    ingestor.session_start()
    ingestor.subtask(_sub())
    flaky.up = True
    assert ingestor.session_end(fim="f", motivo_parada="solucao_encontrada") is True
    assert not (session_dir / PENDING_FILENAME).exists()
    assert len(_nodes(store, "Experimento")) == 1
    assert _nodes(store, "Sessao")[0].properties["motivo_parada"] == "solucao_encontrada"


@pytest.mark.unit
def test_telemetria_sem_dados_de_pesquisa(store, ctx, session_dir):
    seen = []
    _write_task(session_dir, metrics={"r2": 0.8})
    ingestor = FactIngestor(lambda: store, ctx, session_dir, telemetry=lambda k, p, ms: seen.append((k, p, ms)))
    ingestor.session_start()
    ingestor.subtask(_sub())
    assert [k for k, _, _ in seen] == ["session_start", "subtask"]
    assert all(set(p) == {"ok", "queued"} and isinstance(ms, int) for _, p, ms in seen)


@pytest.mark.unit
def test_sync_move_evento_malformado_para_fila_morta(store, ctx, session_dir):
    PendingQueue(session_dir).append({"v": 1, "kind": "subtask", "ctx": {"project_id": "nao-e-uuid"}, "data": {}})
    report = sync_pending(store, session_dir.parent, SESSION)
    assert (report.applied, report.pending, report.dead) == (0, 0, 1)
    assert (session_dir / "knowledge_pending.dead.jsonl").exists()


@pytest.mark.unit
def test_sync_atinge_limite_de_tentativas(store, ctx, session_dir):
    flaky = _Flaky(store)
    FactIngestor(flaky, ctx, session_dir).session_start()
    from src.knowledge.ingestion import sync_session

    class _Broken(InMemoryGraphStore):
        def find_nodes(self, *a, **k):
            raise GraphStoreError("rejeitado")

    reports = [sync_session(_Broken(), session_dir) for _ in range(5)]
    assert reports[0].pending == 1 and reports[-1].dead == 1


# --- Requirement: Contrato de artefatos retrocompatível ---------------------


@pytest.mark.unit
def test_artefatos_antigos(store, ctx, session_dir):
    """Scenario: Artefatos antigos."""
    folder = session_dir / "treinar"
    folder.mkdir()
    (folder / "metrics.json").write_text(
        json.dumps({"task_name": "treinar", "seed": 1, "parameters": {"a": 1}, "metrics": {"accuracy": 0.9},
                    "divergence_note": None}), encoding="utf-8")
    ingest_session_start(store, ctx)
    exp_id = ingest_subtask(store, ctx, session_dir, _sub())
    (res,) = _nodes(store, "Resultado")
    assert "baseline" not in res.properties
    assert _rels(store, "USOU") == []
    assert "dataset_ids" not in store.get_node(exp_id).properties
    assert store.get_node(exp_id).properties["seed"] == 1


# --- Segurança --------------------------------------------------------------


@pytest.mark.unit
def test_metrics_malformado_nao_derruba_a_ingestao(store, ctx, session_dir):
    for raw in ("{nao e json", "[1, 2]", '{"metrics": "texto"}', "\xff\xfe"):
        _write_task(session_dir, "t", raw_metrics=raw)
        ingest_session_start(store, ctx)
        ingest_subtask(store, ctx, session_dir, _sub(task_name="t", subtask_id=f"id-{len(raw)}", review_status="fail",
                                                     agent_status="error"))
    assert _nodes(store, "Resultado") == []
    assert _nodes(store, "Experimento")


@pytest.mark.unit
def test_metricas_nao_numericas_sao_ignoradas(store, ctx, session_dir):
    _write_task(session_dir, metrics={"ok": 1.5, "texto": "alto", "nulo": None, "flag": True, "nan": float("nan"),
                                       "lista": [1], "int": 3})
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub())
    assert {n.properties["nome_original"] for n in _nodes(store, "Resultado")} == {"ok", "int"}


@pytest.mark.unit
def test_nome_de_metrica_e_apenas_dado(store, ctx, session_dir):
    evil = "x'}) MATCH (n) DETACH DELETE n //\nCaminho: /etc/passwd"
    _write_task(session_dir, metrics={evil: 1.0})
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub())
    (res,) = _nodes(store, "Resultado")
    assert "\n" not in res.properties["nome_original"]
    assert _rels(store, "MEDE") == []  # sem canônica: nenhum candidato de vocabulário é criado
    assert not [n for n in _nodes(store, "Metrica") if n.properties["status"] == "candidato"]


@pytest.mark.unit
def test_symlink_para_fora_da_sessao_e_ignorado(store, ctx, session_dir, tmp_path):
    secret = tmp_path / "segredo.json"
    secret.write_text(json.dumps({"metrics": {"vazou": 1.0}}), encoding="utf-8")
    folder = session_dir / "treinar"
    folder.mkdir()
    os.symlink(secret, folder / "metrics.json")
    ev = collect_evidence(session_dir, "treinar")
    assert ev.metrics is None and ev.metrics_status in ("ausente", "invalido")
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub(agent_status="error", review_status=None))
    assert _nodes(store, "Resultado") == []


@pytest.mark.unit
def test_pasta_de_subtarefa_symlink_para_fora_e_ignorada(store, ctx, session_dir, tmp_path):
    outside = tmp_path / "fora"
    outside.mkdir()
    (outside / "metrics.json").write_text(json.dumps({"metrics": {"vazou": 1.0}}), encoding="utf-8")
    os.symlink(outside, session_dir / "treinar")
    ev = collect_evidence(session_dir, "treinar")
    assert ev.metrics is None


@pytest.mark.unit
def test_task_name_com_travessia_nao_le_arquivos(store, ctx, session_dir, tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"metrics": {"vazou": 1.0}}), encoding="utf-8")
    for bad in ("..", "../" + session_dir.name, "a/b", ""):
        assert collect_evidence(session_dir, bad).metrics is None


@pytest.mark.unit
def test_json_gigante_e_recusado(store, ctx, session_dir):
    folder = session_dir / "treinar"
    folder.mkdir()
    (folder / "metrics.json").write_text('{"metrics": {"a": 1}, "lixo": "' + "x" * (2 * 1024 * 1024) + '"}')
    assert collect_evidence(session_dir, "treinar").metrics_status == "invalido"


@pytest.mark.unit
def test_dataset_com_travessia_e_ignorado(store, ctx, session_dir, tmp_path):
    (tmp_path / "segredo.csv").write_text("s\n", encoding="utf-8")
    (session_dir / "input_snapshot").mkdir()
    evil = ["../../segredo.csv", "../segredo.csv", "..", 7, "ausente.csv"]
    _write_task(session_dir, metrics={"r2": 0.8}, datasets=evil)
    ingest_session_start(store, ctx)
    exp_id = ingest_subtask(store, ctx, session_dir, _sub())
    assert _rels(store, "USOU") == [] and _nodes(store, "Insumo") == []
    assert "dataset_ids" not in store.get_node(exp_id).properties


@pytest.mark.unit
def test_insumo_symlink_nao_e_ingerido(store, ctx, session_dir, tmp_path):
    secret = tmp_path / "segredo.csv"
    secret.write_text("s\n", encoding="utf-8")
    snap = session_dir / "input_snapshot"
    snap.mkdir()
    os.symlink(secret, snap / "link.csv")
    (snap / "ok.csv").write_text("a\n", encoding="utf-8")
    ingest_session_start(store, ctx)
    assert ingest_inputs(store, ctx, session_dir) == 1
    assert [n.properties["titulo"] for n in _nodes(store, "Insumo")] == ["ok.csv"]


@pytest.mark.unit
def test_nome_de_insumo_com_caracteres_de_controle_e_neutralizado(store, ctx, session_dir):
    snap = session_dir / "input_snapshot"
    snap.mkdir()
    (snap / "a\nCaminho: x.csv").write_text("a\n", encoding="utf-8")
    ingest_session_start(store, ctx)
    ingest_inputs(store, ctx, session_dir)
    assert "\n" not in _nodes(store, "Insumo")[0].properties["titulo"]


@pytest.mark.unit
def test_fila_ignora_symlink_e_arquivo_de_outro_tipo(session_dir, tmp_path):
    target = tmp_path / "alvo.jsonl"
    target.write_text('{"kind":"x"}\n', encoding="utf-8")
    os.symlink(target, session_dir / PENDING_FILENAME)
    queue = PendingQueue(session_dir)
    with pytest.raises(OSError):
        queue.read()
    assert queue.append({"kind": "session_start"}) is False  # nunca escreve através do link
    assert target.read_text(encoding="utf-8") == '{"kind":"x"}\n'


@pytest.mark.unit
def test_fila_tolera_linhas_invalidas_e_limita_evento(session_dir):
    queue = PendingQueue(session_dir)
    assert queue.append({"kind": "session_start", "data": {"x": "y" * 70_000}}) is False
    queue.path.write_text('lixo\n[1]\n{"kind": "session_start"}\n', encoding="utf-8")
    events, ignored = queue.read()
    assert [e["kind"] for e in events] == ["session_start"] and ignored == 2


@pytest.mark.unit
def test_replay_usa_o_session_id_da_pasta(store, ctx, session_dir):
    """O evento não escolhe a pasta: o ``session_id`` vem do diretório."""
    _write_task(session_dir, metrics={"r2": 0.8})
    ingest_session_start(store, ctx)
    event = {"kind": "subtask", "ctx": {"project_id": ctx.project_id, "modo": "auto", "inicio": "x",
                                         "no_execucao": "n", "session_id": "../../etc"},
             "data": _sub().to_dict()}
    replay_event(store, session_dir, event)
    assert store.get_node(_nodes(store, "Experimento")[0].id).properties["sessao_id"] == SESSION


@pytest.mark.unit
def test_replay_rejeita_tipo_desconhecido(store, session_dir):
    with pytest.raises(IngestionDataError):
        replay_event(store, session_dir, {"kind": "apagar_tudo"})


@pytest.mark.unit
def test_ingestao_nunca_cria_problema_nem_confirma(store, ctx, session_dir):
    """Gate humano: nenhum ``Problema`` é criado ou alterado pela ingestão."""
    before = len(_nodes(store, "Problema"))
    _write_task(session_dir, metrics={"r2": 0.8})
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub(approach={"nome": "x"}, hypothesis="h"))
    ingest_session_end(store, ctx, fim="f", motivo_parada="erro")
    assert len(_nodes(store, "Problema")) == before
    # e a porta única continua recusando a promoção por ator que não é o pesquisador
    draft = store.create_node(
        "Problema", {"titulo": "t", "resumo": "r", "status": "rascunho", "projeto_id": ctx.project_id,
                     "sessao_id": "s", "justificativa_criacao": "j", "nos_consultados": []},
        actor=Actor(kind="agente", role="researcher"))
    with pytest.raises(HumanConfirmationRequiredError):
        store.update_node(draft, {"status": "confirmado"}, actor=ACTOR_ORQUESTRADOR)


@pytest.mark.unit
def test_modo_invalido_e_descartado_sem_fila(store, project_id, session_dir):
    bad = SessionContext(project_id=project_id, session_id=SESSION, modo="turbo", inicio="x", no_execucao="n")
    ingestor = FactIngestor(lambda: store, bad, session_dir)
    assert ingestor.session_start() is False
    assert not (session_dir / PENDING_FILENAME).exists()


@pytest.mark.unit
def test_projeto_inexistente_vai_para_a_fila(store, session_dir):
    ghost = SessionContext(project_id="01890000-0000-7000-8000-0000000000aa", session_id=SESSION, modo="auto",
                           inicio="x", no_execucao="n")
    assert FactIngestor(lambda: store, ghost, session_dir).session_start() is False
    assert (session_dir / PENDING_FILENAME).exists()


@pytest.mark.unit
def test_hash_codigo_dos_scripts_do_manifest(store, ctx, session_dir):
    _write_task(session_dir, metrics={"r2": 0.8})
    (session_dir / "step_01.py").write_text("print(1)\n", encoding="utf-8")
    (session_dir / "step_02.py").write_text("print(2)\n", encoding="utf-8")
    _manifest(session_dir, [
        {"task_name": "treinar", "code_file": "../../etc/passwd", "run": {"exit_code": 0}},
        {"task_name": "treinar", "code_file": "step_01.py", "run": {"exit_code": 0, "imagem_sandbox": "img:1",
                                                                   "pacotes": ["numpy==2.0"]}},
        {"task_name": "outra", "code_file": "step_02.py"},
    ])
    ingest_session_start(store, ctx)
    exp = store.get_node(ingest_subtask(store, ctx, session_dir, _sub()))
    import hashlib

    assert exp.properties["hash_codigo"] == hashlib.sha256(b"print(1)\n").hexdigest()
    assert exp.properties["ambiente"] == {"imagem_sandbox": "img:1", "pacotes": ["numpy==2.0"]}


@pytest.mark.unit
def test_divergente_documentado(store, ctx, session_dir):
    _write_task(session_dir, metrics={"r2": 0.5}, divergence_note="diverge do artigo")
    ingest_session_start(store, ctx)
    exp = store.get_node(ingest_subtask(store, ctx, session_dir, _sub(review_status="divergent_but_documented")))
    assert exp.properties["status"] == "divergente_documentado"
    assert _nodes(store, "Resultado")[0].properties["status_validacao"] == "divergente_documentado"


@pytest.mark.unit
def test_graph_store_error_inesperado_vira_pendencia(session_dir, ctx):
    class _Boom(InMemoryGraphStore):
        def create_node(self, *a, **k):
            raise GraphStoreError("boom")

    assert FactIngestor(_Boom, ctx, session_dir).session_start() is False
    assert (session_dir / PENDING_FILENAME).exists()
