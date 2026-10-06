"""Achados da revisão de segurança do PR #105 (``v17-structural-fact-ingestion``).

Cada teste reproduz um achado do parecer (numeração do parecer no docstring). Sem rede, sem LLM,
sem Docker e sem AGE.
"""

from __future__ import annotations

import json
import os
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import config
from src.agents.validator_agent import ValidatorAgent
from src.knowledge import ingestion
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion import (
    FactIngestor,
    SessionContext,
    SubtaskInput,
    ingest_inputs,
    ingest_session_start,
    ingest_subtask,
    replay_event,
    sync_pending,
    sync_session,
)
from src.knowledge.ingestion_queue import DEAD_FILENAME, PendingQueue
from src.knowledge.projects import create_project
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.output_manager import OutputManager
from src.session import Session

SESSION = "sessao-rev"


def _nodes(store, label):
    return store.find_nodes(label, {}, limit=10_000)


def _rels(store, rel):
    return [e for e in store._edges if e.rel_type == rel]  # noqa: SLF001


@pytest.fixture
def store():
    return InMemoryGraphStore()


@pytest.fixture
def project_id(store):
    return create_project(store, "P", "O", [])


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / SESSION
    d.mkdir()
    return d


@pytest.fixture
def ctx(project_id):
    return SessionContext(project_id=project_id, session_id=SESSION, modo="auto", inicio="x", no_execucao="n")


def _task(session_dir, name="treinar", metrics=None, datasets=None):
    folder = session_dir / name
    folder.mkdir(exist_ok=True)
    params = {"seed": 1, "parameters": {"a": 1}}
    if datasets is not None:
        params["datasets"] = datasets
    (folder / "params.json").write_text(json.dumps(params), encoding="utf-8")
    (folder / "metrics.json").write_text(json.dumps({"metrics": metrics or {"r2": 0.8}}), encoding="utf-8")


def _sub(**kw):
    base = {"task_name": "treinar", "subtask_id": "s1", "agent_id": "developer", "review_status": "pass",
            "review_verified": True, "validation_criteria": ["r2 >= 0.5"]}
    base.update(kw)
    return SubtaskInput(**base)


class _Down:
    """Fábrica do grafo que levanta erro de conexão."""

    def __call__(self):
        raise ConnectionError("fora")


# --- Achado 1 (bloqueante): Validator degradado -------------------------------


class _BrokenProvider:
    async def generate(self, **kwargs):
        raise RuntimeError("provedor fora do ar")


class _GarbageProvider:
    async def generate(self, **kwargs):
        return MagicMock(text="texto solto sem JSON", usage=None)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [_BrokenProvider(), _GarbageProvider()])
async def test_validator_degradado_nao_e_verificado(provider, tmp_path):
    """Achado 1: exceção do LLM ou resposta ilegível devolve pass, mas ``verified=False``."""
    task = AgentTask(agent_id="developer", prompt="p", task_name="t", validation_criteria=["gera um gráfico claro"])
    review = await ValidatorAgent(provider=provider).review_result(
        task=task, response_text="ok", artifacts_on_disk=[], output_dir=tmp_path
    )
    assert review.status == "pass" and review.verified is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_validator_por_criterio_quantitativo_e_verificado(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "metrics.json").write_text(json.dumps({"metrics": {"r2": 0.9}}), encoding="utf-8")
    task = AgentTask(agent_id="developer", prompt="p", task_name="t", validation_criteria=["r2 >= 0.5"])
    review = await ValidatorAgent(provider=_BrokenProvider()).review_result(
        task=task, response_text="", artifacts_on_disk=[], output_dir=tmp_path
    )
    assert review.status == "pass" and review.verified is True


@pytest.mark.unit
def test_ingestao_grava_nao_validado_quando_revisao_nao_verificada(store, ctx, session_dir):
    """Achado 1: pass não verificado nunca vira ``validado``; verificado continua validado."""
    _task(session_dir)
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub(review_verified=False))
    assert _nodes(store, "Resultado")[0].properties["status_validacao"] == "nao_validado"
    # lado verificado (outra subtarefa)
    _task(session_dir, "outra")
    ingest_subtask(store, ctx, session_dir, _sub(task_name="outra", subtask_id="s2"))
    by_exp = {n.properties["status_validacao"] for n in _nodes(store, "Resultado")}
    assert by_exp == {"nao_validado", "validado"}


@pytest.mark.unit
def test_evento_antigo_sem_review_verified_e_nao_verificado():
    assert SubtaskInput.from_dict({"task_name": "t", "review_status": "pass"}).review_verified is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_laco_repassa_verified_e_evento_de_revisao(tmp_path):
    from unittest.mock import patch

    from src.autonomous_loop import AutonomousLoop

    orch = MagicMock()
    orch.output_manager.base_dir = tmp_path
    orch.output_manager.list_artifacts.return_value = []
    orch.validator = ValidatorAgent(provider=_BrokenProvider())
    loop = AutonomousLoop(orch)
    task = AgentTask(agent_id="developer", prompt="p", task_name="t", validation_criteria=["gera um gráfico claro"])
    events = []
    with patch("src.telemetry.get_telemetry") as tel:
        tel.return_value.record_agent_event.side_effect = lambda **kw: events.append(kw)
        review = await loop._review_subtask(
            task, AgentResult(agent_id="d", session_id="s", status="success", response={"text": "x"}), "sess"
        )
    assert review["verified"] is False
    assert events and events[0]["payload"]["verified"] is False


# --- Achado 2: fila confia em project_id / pasta da sessão --------------------


def _forge(session_dir, project_id, **data):
    event = {"v": 1, "kind": "subtask", "ctx": {"project_id": project_id, "modo": "auto", "inicio": "x",
                                                 "no_execucao": "n"},
             "data": _sub(review_status="pass").to_dict() | data}
    PendingQueue(session_dir).append(event)


@pytest.mark.unit
def test_replay_recusa_project_id_divergente_do_grafo(store, ctx, session_dir):
    """Achado 2: a Sessao do grafo manda; evento com outro project_id vai para a fila morta."""
    other = create_project(store, "Outro", "O2", [])
    _task(session_dir)
    ingest_session_start(store, ctx)
    _forge(session_dir, other)
    report = sync_pending(store, session_dir.parent, SESSION)
    assert (report.applied, report.dead) == (0, 1)
    assert _nodes(store, "Experimento") == []
    assert (session_dir / DEAD_FILENAME).exists()


@pytest.mark.unit
def test_replay_aceita_project_id_igual_ao_do_grafo(store, ctx, session_dir):
    _task(session_dir)
    ingest_session_start(store, ctx)
    _forge(session_dir, ctx.project_id)
    assert sync_pending(store, session_dir.parent, SESSION).applied == 1


@pytest.mark.unit
def test_sync_pede_confirmacao_e_mostra_projeto_e_sessao(store, ctx, session_dir):
    """Achado 2: nada é escrito sem confirmação; o plano traz sessão, projeto e contagem."""
    _task(session_dir)
    ingest_session_start(store, ctx)
    _forge(session_dir, ctx.project_id)
    seen = []

    def deny(plan):
        seen.extend(plan)
        return False

    report = sync_pending(store, session_dir.parent, confirm=deny)
    assert report.applied == 0 and report.cancelled is True
    assert seen[0].session_id == SESSION and seen[0].project_id == ctx.project_id and seen[0].events == 1
    assert _nodes(store, "Experimento") == []
    assert sync_pending(store, session_dir.parent, confirm=lambda plan: True).applied == 1


@pytest.mark.unit
def test_cli_sync_sem_yes_e_sem_terminal_recusa(store, ctx, session_dir, monkeypatch, capsys):
    from unittest.mock import patch

    from src.knowledge.semantic_runtime import run_knowledge_command

    _task(session_dir)
    ingest_session_start(store, ctx)
    _forge(session_dir, ctx.project_id)
    runtime = MagicMock(store=store)
    monkeypatch.setattr(config, "OUTPUT_BASE_DIR", str(session_dir.parent))
    with patch("sys.stdin.isatty", return_value=False):
        assert run_knowledge_command(["sync"], runtime=runtime) == 1
    assert "--yes" in capsys.readouterr().out
    assert _nodes(store, "Experimento") == []
    assert run_knowledge_command(["sync", "--yes"], runtime=runtime) == 0
    assert len(_nodes(store, "Experimento")) == 1


@pytest.mark.unit
def test_pasta_da_sessao_e_privada(tmp_path):
    """Achado 2: a pasta da sessão não é legível/gravável por terceiros (0700)."""
    path = OutputManager(str(tmp_path / "o"), str(tmp_path / "l")).init_session("s1")
    assert (path.stat().st_mode & 0o777) == 0o700


# --- Achado 3: sync perdia eventos anexados durante o processamento ----------


@pytest.mark.unit
def test_sync_nao_perde_evento_anexado_durante_o_processamento(store, ctx, session_dir):
    """Achado 3: evento acrescentado pela sessão viva enquanto o sync roda continua na fila."""
    _task(session_dir)
    ingest_session_start(store, ctx)
    _forge(session_dir, ctx.project_id)
    late = {"v": 1, "kind": "session_end", "ctx": {"project_id": ctx.project_id, "modo": "auto", "inicio": "x",
                                                    "no_execucao": "n"},
            "data": {"fim": "f", "motivo_parada": "erro", "consumo": {}}}

    class _Racing(InMemoryGraphStore):
        appended = False

        def find_nodes(self, *a, **k):
            if not self.appended:
                _Racing.appended = True
                PendingQueue(session_dir).append(late)  # a sessão viva anexa no meio do replay
            return store.find_nodes(*a, **k)

    racing = _Racing()
    racing._nodes, racing._edges = store._nodes, store._edges  # noqa: SLF001 - mesmo grafo
    report = sync_session(racing, session_dir)
    assert report.applied == 1
    events, _ = PendingQueue(session_dir).read()
    assert [e["kind"] for e in events] == ["session_end"]


@pytest.mark.unit
def test_fila_concorrente_mantem_todos_os_eventos(session_dir):
    queue = PendingQueue(session_dir)
    threads = [threading.Thread(target=lambda i=i: queue.append({"kind": "inputs", "n": i})) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    events, _ = queue.read()
    assert len(events) == 20 and len({e["event_id"] for e in events}) == 20


# --- Achado 4: fila inutilizável não derruba a sessão ------------------------


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["dir", "symlink", "noperm"])
def test_trava_da_fila_inutilizavel_nao_levanta(ctx, session_dir, tmp_path, kind):
    """Achado 4: trava como diretório, link ou sem permissão não derruba o ingestor."""
    lock = session_dir / ".knowledge_pending.lock"
    if kind == "dir":
        lock.mkdir()
    elif kind == "symlink":
        os.symlink(tmp_path / "alvo", lock)
    else:
        lock.write_text("")
        lock.chmod(0)
    ing = FactIngestor(_Down(), ctx, session_dir)
    assert ing.session_start() is False
    assert ing.subtask(_sub()) is False
    assert ing.session_end(fim="f", motivo_parada="erro") is False
    lock.chmod(0o600) if kind == "noperm" else None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_request_sobrevive_a_fila_inutilizavel(tmp_path):
    sm = MagicMock()
    sess = Session(id="s1", agent_id="orchestrator", status="active", created_at="2025-01-01T00:00:00+00:00",
                   updated_at="2025-01-01T00:00:00+00:00", payload={})
    sm.create.return_value = sess
    sm.get.return_value = sess
    runtime = MagicMock()
    runtime.run = AsyncMock(return_value=AgentResult(agent_id="a", session_id="s1", status="success", response={}))
    om = OutputManager(str(tmp_path / "o"), str(tmp_path / "l"))
    (om.base_dir / "s1").mkdir(parents=True)
    (om.base_dir / "s1" / ".knowledge_pending.lock").mkdir()
    orch = Orchestrator(session_manager=sm, output_manager=om, agent_runtime=runtime,
                        knowledge_store_factory=_Down())
    result = await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")],
                                       project_id="01890000-0000-7000-8000-000000000001")
    assert result.succeeded == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fim_de_sessao_pelo_orquestrador_grava_motivo_parada(tmp_path, store):
    """Sugestão 7: caminho completo orquestrador -> motivo_parada=limite_tokens."""
    pid = create_project(store, "P", "O", [])
    sm = MagicMock()
    sm.create.return_value = Session(id="s1", agent_id="o", status="active", created_at="2025-01-01T00:00:00+00:00",
                                     updated_at="2025-01-01T00:00:00+00:00", payload={})
    sm.get.return_value = Session(id="s1", agent_id="o", status="active", created_at="2025-01-01T00:00:00+00:00",
                                  updated_at="2025-01-01T00:00:00+00:00", payload={"motivo_parada": "limite_tokens"})
    runtime = MagicMock()
    runtime.run = AsyncMock(return_value=AgentResult(agent_id="a", session_id="s1", status="success", response={}))
    om = OutputManager(str(tmp_path / "o"), str(tmp_path / "l"))
    orch = Orchestrator(session_manager=sm, output_manager=om, agent_runtime=runtime,
                        knowledge_store_factory=lambda: store)
    await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")], project_id=pid)
    assert _nodes(store, "Sessao")[0].properties["motivo_parada"] == "limite_tokens"


@pytest.mark.unit
def test_fim_por_excecao_so_enfileira_sem_tocar_no_grafo(ctx, session_dir):
    """Sugestão 11: no caminho de exceção o grafo não é acessado (sem I/O que trave o Ctrl+C)."""
    calls = []
    ing = FactIngestor(lambda: calls.append(1), ctx, session_dir)
    ing.session_end(fim="f", motivo_parada="interrompida", offline=True)
    assert calls == []
    events, _ = PendingQueue(session_dir).read()
    assert [e["kind"] for e in events] == ["session_end"]


# --- Achado 5: indisponibilidade x dado inválido -----------------------------


class _Broken(InMemoryGraphStore):
    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    def find_nodes(self, *a, **k):
        raise self._exc


@pytest.mark.unit
def test_indisponibilidade_nao_incrementa_attempts(ctx, session_dir):
    """Achado 5: banco fora do ar nunca mata evento válido, por mais syncs que rodem."""
    FactIngestor(_Down(), ctx, session_dir).session_start()
    for _ in range(8):
        report = sync_session(_Broken(ConnectionError("fora")), session_dir)
    assert (report.pending, report.dead) == (1, 0)
    (event,), _ = PendingQueue(session_dir).read()
    assert event["attempts"] == 0
    assert not (session_dir / DEAD_FILENAME).exists()


@pytest.mark.unit
def test_dado_invalido_incrementa_e_vai_para_a_fila_morta(ctx, session_dir):
    FactIngestor(_Down(), ctx, session_dir).session_start()
    reports = [sync_session(_Broken(GraphStoreError("rejeitado")), session_dir) for _ in range(5)]
    assert reports[0].pending == 1 and reports[-1].dead == 1
    assert (session_dir / DEAD_FILENAME).exists()


@pytest.mark.unit
def test_down_so_para_erro_de_conexao(ctx, session_dir, store):
    """Achado 5: GraphStoreError de um evento não derruba os eventos seguintes da sessão."""
    class _Reject(InMemoryGraphStore):
        def create_node(self, label, props, *, actor):
            if label == "Sessao":
                raise GraphStoreError("rejeitado")
            return super().create_node(label, props, actor=actor)

    ing = FactIngestor(lambda: _Reject(), ctx, session_dir)
    ing.session_start()
    assert ing._down is False  # noqa: SLF001
    # erro de conexão marca down
    ing2 = FactIngestor(_Down(), ctx, session_dir)
    ing2.session_start()
    assert ing2._down is True  # noqa: SLF001


@pytest.mark.unit
def test_falha_ao_gravar_fila_morta_nao_perde_evento(ctx, session_dir, tmp_path):
    FactIngestor(_Down(), ctx, session_dir).session_start()
    os.symlink(tmp_path / "alvo", session_dir / DEAD_FILENAME)  # fila morta inutilizável
    for _ in range(5):
        sync_session(_Broken(GraphStoreError("rejeitado")), session_dir)
    events, _ = PendingQueue(session_dir).read()
    assert len(events) == 1


@pytest.mark.unit
def test_retry_dead_recoloca_na_fila(store, ctx, session_dir):
    FactIngestor(_Down(), ctx, session_dir).session_start()
    for _ in range(5):
        sync_session(_Broken(GraphStoreError("rejeitado")), session_dir)
    assert (session_dir / DEAD_FILENAME).exists()
    report = sync_pending(store, session_dir.parent, SESSION, retry_dead=True)
    assert report.applied == 1 and report.dead == 0
    assert len(_nodes(store, "Sessao")) == 1
    assert not (session_dir / DEAD_FILENAME).exists()


@pytest.mark.unit
def test_fila_morta_tem_teto(session_dir):
    dead = PendingQueue(session_dir, filename=DEAD_FILENAME, max_events=3)
    assert [dead.append({"kind": "x", "n": i}) for i in range(5)] == [True, True, True, False, False]


# --- Achado 6: hash sem cache e sem dedupe de nomes --------------------------


def _snapshot(session_dir, name="dados.csv", size=100):
    snap = session_dir / "input_snapshot"
    snap.mkdir(exist_ok=True)
    (snap / name).write_bytes(b"x" * size)


@pytest.mark.unit
def test_datasets_duplicados_sao_hasheados_uma_vez(store, ctx, session_dir, monkeypatch):
    """Achado 6: o mesmo nome 100 vezes em params.json custa uma leitura."""
    _snapshot(session_dir)
    _task(session_dir, datasets=["dados.csv"] * 100)
    calls = []
    real = ingestion.sha256_file
    monkeypatch.setattr(ingestion, "sha256_file", lambda *a, **k: calls.append(1) or real(*a, **k))
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub())
    assert len(calls) == 1 and len(_rels(store, "USOU")) == 1


@pytest.mark.unit
def test_cache_de_hash_entre_chamadas_da_sessao(store, ctx, session_dir, monkeypatch):
    _snapshot(session_dir)
    _task(session_dir, datasets=["dados.csv"])
    calls = []
    real = ingestion.sha256_file
    monkeypatch.setattr(ingestion, "sha256_file", lambda *a, **k: calls.append(1) or real(*a, **k))
    ing = FactIngestor(lambda: store, ctx, session_dir)
    ing.session_start()
    ing.inputs()
    ing.subtask(_sub())
    ing.subtask(_sub(subtask_id="s2"))
    assert len(calls) == 1


@pytest.mark.unit
def test_arquivo_acima_do_teto_nao_e_hasheado(store, ctx, session_dir, monkeypatch, caplog):
    monkeypatch.setattr(config, "INGESTION_MAX_FILE_BYTES", 50)
    _snapshot(session_dir, size=100)
    ingest_session_start(store, ctx)
    assert ingest_inputs(store, ctx, session_dir) == 0
    assert _nodes(store, "Insumo") == []
    assert any("grande demais" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_orcamento_de_bytes_por_chamada(store, ctx, session_dir, monkeypatch):
    monkeypatch.setattr(config, "INGESTION_MAX_HASH_BYTES_PER_CALL", 150)
    for n in ("a.csv", "b.csv", "c.csv"):
        _snapshot(session_dir, n, 100)
        (session_dir / "input_snapshot" / n).write_bytes(n[0].encode() * 100)
    ingest_session_start(store, ctx)
    assert ingest_inputs(store, ctx, session_dir) == 1  # só o primeiro cabe no orçamento


# --- Sugestões ----------------------------------------------------------------


@pytest.mark.unit
def test_hipotese_provisoria_tem_marcador_estavel(store, ctx, session_dir):
    _task(session_dir)
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub(hypothesis="H1"))
    (hip,) = _nodes(store, "Hipotese")
    assert hip.properties["justificativa_criacao"].startswith(ingestion.PROVISIONAL_MARKER)


@pytest.mark.unit
def test_usou_e_afirmado_e_executado_em_e_fato(store, ctx, session_dir):
    _snapshot(session_dir)
    _task(session_dir, datasets=["dados.csv"])
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub())
    assert _rels(store, "USOU")[0].properties["origem"] == "afirmado"
    assert _rels(store, "EXECUTADO_EM")[0].properties["origem"] == "fato"


@pytest.mark.unit
def test_abordagem_existente_e_achada_alem_de_mil_candidatas(store, ctx, session_dir):
    ingest_session_start(store, ctx)
    ator = ingestion.ACTOR_RESEARCHER
    for i in range(1100):
        store.create_node("Abordagem", {"nome": f"m{i}", "tipo": "outro", "descricao": "d",
                                        "projeto_id": ctx.project_id,
                                        "sessao_id": "x", "justificativa_criacao": "j", "nos_consultados": []},
                          actor=ator)
    _task(session_dir)
    for sid in ("a", "b"):
        ingest_subtask(store, ctx, session_dir, _sub(subtask_id=sid, approach={"nome": "m1099"}))
    assert len(_nodes(store, "Abordagem")) == 1100


@pytest.mark.unit
def test_replay_event_exige_sessao_do_mesmo_projeto(store, ctx, session_dir):
    other = create_project(store, "Outro", "O2", [])
    ingest_session_start(store, ctx)
    with pytest.raises(ingestion.IngestionDataError):
        replay_event(store, session_dir, {"kind": "session_end", "ctx": {"project_id": other, "modo": "auto",
                                                                          "inicio": "x", "no_execucao": "n"},
                                          "data": {"fim": "f"}})
