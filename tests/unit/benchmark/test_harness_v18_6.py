"""v18.6-benchmark-harness: guardas e ordem do reset, semeadura, crescimento, placar, arquivo, repetições e custo.

Um teste (ou mais) por ``#### Scenario`` de ``openspec/specs/benchmark/spec.md``; o nome
do cenário está no nome do teste. Os cenários que exigem PostgreSQL com AGE e Qdrant reais ("Reset completo", "Dump
gravado" e "Dump falha" contra o servidor) estão em ``tests/integration/test_benchmark_reset_integration.py``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tarfile
import time
from pathlib import Path

import pytest

from scripts.benchmark import footprint, report, reset_stores, run_benchmark
from scripts.benchmark.archive import archive_dir_for, archive_repetition
from scripts.benchmark.reset_stores import BenchmarkTarget, ResetError, ResetRefused, check_guards, redact_url
from scripts.benchmark.run_benchmark import anomalies, pending_runs, run_combination
from scripts.benchmark.scoring import (
    graph_accuracy,
    score_session,
    scoreboard_anomalies,
    validated_checks,
    validated_scoreboard,
)
from scripts.benchmark.seed_project import VocabularyNotSeededError, seed_project
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.provenance import Actor
from src.knowledge.vocabulary import find_approved_metric, seed_vocabulary
from src.llm import pricing
from src.llm.providers.openai import OpenAIProvider

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
BENCH_URL = "postgresql://geminiclaw:s3gredo@db.local:5432/geminiclaw_bench"
DEV_URL = "postgresql://geminiclaw:s3gredo@db.local:5432/geminiclaw"
ORQ = Actor(kind="orquestrador")


def make_target(**over) -> BenchmarkTarget:
    values = {"database_url": BENCH_URL, "qdrant_url": "http://qdrant.local:6333", "dev_database_url": DEV_URL}
    values.update(over)
    return BenchmarkTarget(**values)


def seeded_store(tmp_path: Path) -> InMemoryGraphStore:
    shutil.copy(ROOT / "tests" / "fixtures" / "cnpq_areas_fixture.csv", tmp_path / "cnpq_areas.csv")
    shutil.copy(ROOT / "data" / "vocabulary" / "metrics.yaml", tmp_path / "metrics.yaml")
    store = InMemoryGraphStore()
    seed_vocabulary(store, vocabulary_dir=tmp_path)
    return store


# --------------------------------------------------------------------------------------------
# Reset isolado dos bancos de benchmark
# --------------------------------------------------------------------------------------------


def test_reset_sem_a_flag_recusa_e_nao_marca_isolado(monkeypatch, tmp_path) -> None:
    """Cenário "Reset sem a flag": nada é apagado, o resultado traz ``isolated: false``."""
    with pytest.raises(ResetRefused, match="--reset-stores"):
        check_guards(make_target(), reset_requested=False, confirm_target="geminiclaw_bench@db.local")
    called: list[str] = []
    monkeypatch.setattr(run_benchmark, "reset_stores", lambda *a, **k: called.append("reset"))
    result = _run_fake_combination(monkeypatch, tmp_path, reset=False)
    assert called == [] and result["isolated"] is False and result["reset"] is None


def test_reset_alvo_nao_confirmado_mostra_o_alvo_esperado_sem_senha() -> None:
    """Cenário "Alvo não confirmado"."""
    with pytest.raises(ResetRefused) as info:
        check_guards(make_target(), reset_requested=True, confirm_target="outro@host")
    message = str(info.value)
    assert "geminiclaw_bench@db.local" in message and "s3gredo" not in message and ":***@" in message


def test_reset_banco_sem_a_marca_cita_o_marcador() -> None:
    """Cenário "Banco sem a marca"."""
    target = make_target(database_url=DEV_URL, dev_database_url=None)
    with pytest.raises(ResetRefused, match="BENCHMARK_DB_MARKER"):
        check_guards(target, reset_requested=True, confirm_target=target.label)


def test_reset_banco_igual_ao_de_desenvolvimento_recusa() -> None:
    """Cenário "Banco igual ao de desenvolvimento"."""
    target = make_target(dev_database_url=BENCH_URL)
    with pytest.raises(ResetRefused, match="DATABASE_URL"):
        check_guards(target, reset_requested=True, confirm_target=target.label)


def test_guardas_satisfeitas_nao_recusam() -> None:
    target = make_target()
    check_guards(target, reset_requested=True, confirm_target=target.label)


def test_url_exibida_sem_senha_e_sem_url_do_benchmark_recusa() -> None:
    assert redact_url(BENCH_URL) == "postgresql://geminiclaw:***@db.local:5432/geminiclaw_bench"
    assert redact_url("postgresql://db.local/x") == "postgresql://db.local/x"
    with pytest.raises(ResetRefused, match="BENCHMARK_DATABASE_URL"):
        BenchmarkTarget.from_env({"DATABASE_URL": DEV_URL})


def test_ambiente_do_alvo_troca_o_banco_do_leitor_e_o_qdrant() -> None:
    reader = "postgresql://knowledge_reader:pw@db.local:5432/geminiclaw"
    env = reset_stores.target_env(make_target(), {"KNOWLEDGE_READER_DATABASE_URL": reader, "DATABASE_URL": DEV_URL})
    assert env["DATABASE_URL"] == BENCH_URL and env["QDRANT_URL"] == "http://qdrant.local:6333"
    assert env["KNOWLEDGE_READER_DATABASE_URL"].endswith("/geminiclaw_bench")


def _stub_steps(monkeypatch, calls: list[str], *, dump_error: bool = False) -> None:
    monkeypatch.setattr(reset_stores, "_database_exists", lambda t: True)

    def dump(target, dest):
        if dump_error:
            raise ResetError("pg_dump indisponível")
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "db.dump"
        path.write_bytes(b"PGDMP")
        calls.append("dump")
        return path

    def snapshots(target, dest):
        calls.append("snapshots")
        return [str(dest / "geminiclaw_knowledge-snap")]

    monkeypatch.setattr(reset_stores, "_dump_postgres", dump)
    monkeypatch.setattr(reset_stores, "_snapshot_qdrant", snapshots)
    monkeypatch.setattr(reset_stores, "_drop_qdrant", lambda t: calls.append("drop_qdrant") or ["geminiclaw_knowledge"])
    monkeypatch.setattr(reset_stores, "_recreate_database", lambda t: calls.append("recreate"))
    monkeypatch.setattr(reset_stores, "_bootstrap", lambda t, e, r: calls.append("bootstrap"))
    monkeypatch.setattr(reset_stores, "_verify", lambda t: [])


def test_dump_gravado_antes_de_apagar(monkeypatch, tmp_path) -> None:
    """Cenário "Dump gravado": o arquivo de segurança vem antes de apagar e entra no ``ResetReport``."""
    calls: list[str] = []
    _stub_steps(monkeypatch, calls)
    report_ = reset_stores.reset_stores(make_target(), archive_dir=tmp_path / "r1", base_env={})
    assert calls == ["dump", "snapshots", "drop_qdrant", "recreate", "bootstrap"]
    assert report_.dump_path and Path(report_.dump_path).parent == tmp_path / "r1" / "pre_reset"
    assert report_.qdrant_snapshots and report_.dropped_collections == ["geminiclaw_knowledge"]


def test_dump_falha_nao_apaga_nada(monkeypatch, tmp_path) -> None:
    """Cenário "Dump falha"."""
    calls: list[str] = []
    _stub_steps(monkeypatch, calls, dump_error=True)
    with pytest.raises(ResetError, match="pg_dump"):
        reset_stores.reset_stores(make_target(), archive_dir=tmp_path / "r1", base_env={})
    assert calls == []


def test_sem_dump_so_com_a_flag_e_conferencia_que_falha_levanta_erro(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    _stub_steps(monkeypatch, calls)
    monkeypatch.setattr(reset_stores, "_verify", lambda t: ["tabela ausente: egress_log"])
    with pytest.raises(ResetError, match="egress_log"):
        reset_stores.reset_stores(make_target(), archive_dir=tmp_path, dump=False, base_env={})
    assert "dump" not in calls and "recreate" in calls


# --------------------------------------------------------------------------------------------
# Projeto semeado exige métrica canônica
# --------------------------------------------------------------------------------------------


def test_vocabulario_vazio_falha_citando_o_seed_e_nao_cria_projeto() -> None:
    """Cenário "Vocabulário vazio"."""
    store = InMemoryGraphStore()
    with pytest.raises(VocabularyNotSeededError, match=r"scripts/seed_vocabulary\.py"):
        seed_project("combo", store)
    assert store.find_nodes("Projeto", {}, limit=10) == []


def test_metrica_candidata_nao_conta_como_aprovada(tmp_path) -> None:
    store = seeded_store(tmp_path)
    assert find_approved_metric(store, "accuracy") is not None  # sinônimo
    assert find_approved_metric(store, "metrica_inexistente") is None


# --------------------------------------------------------------------------------------------
# Série de crescimento das memórias
# --------------------------------------------------------------------------------------------


class FakeProc:
    pid = 2**31 - 1  # nunca é um pid real: o runner sinaliza o grupo e o teste não pode atingir ninguém
    returncode = 0

    def __init__(self, work) -> None:
        self._work = work

    def communicate(self, timeout=None):
        self._work()
        return "saída do processo\n", None

    def kill(self) -> None:  # pragma: no cover - sem timeout nos testes
        pass


class FakeResourceSampler:
    def __init__(self, *a, **k) -> None:
        pass

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def join(self, timeout=None) -> None: ...
    def summary(self) -> dict:
        return {"sys_cpu_pct": {"max": 1}}


def _run_fake_combination(monkeypatch, tmp_path, *, reset=False, work=lambda: None, nodes=None, interval=5.0,
                          session: Path | None = None, combo: dict | None = None, popen_env: dict | None = None,
                          command: list[str] | None = None, timeout: int = 60, kill_grace_seconds: float = 10.0,
                          **extra):
    """Roda ``run_combination`` sem banco ou Qdrant reais; sem ``command`` o subprocesso também é simulado."""
    nodes = nodes if nodes is not None else {"n": 0}
    def fake_popen(*a, **k):
        if popen_env is not None:
            popen_env.update(k["env"])
        return FakeProc(work)

    if command is None:
        monkeypatch.setattr(run_benchmark.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run_benchmark, "ResourceSampler", FakeResourceSampler)
    monkeypatch.setattr(footprint, "snapshot", lambda: {})
    monkeypatch.setattr(footprint, "session_operation_metrics", lambda s: None)
    monkeypatch.setattr(footprint, "embedding_events", lambda s: {})
    monkeypatch.setattr(footprint, "project_graph_full", lambda p, store=None: {"nos": [], "arestas": []})
    monkeypatch.setattr(footprint, "collect_store_sample",
                        lambda url, qdrant, graph: {"grafo": {"nos": {"Resultado": nodes["n"]}, "arestas": {}}})
    monkeypatch.setattr(run_benchmark, "newest_session", lambda out, since: session)
    monkeypatch.setattr(run_benchmark, "db_token_usage", lambda s: {})
    monkeypatch.setattr(run_benchmark, "db_metrics", lambda s: {})
    monkeypatch.setattr(run_benchmark, "db_llm_routing", lambda s: None)
    monkeypatch.setattr(run_benchmark, "fetch_events", lambda s: [{"event_type": "x", "payload": {}}])
    monkeypatch.setattr(run_benchmark, "compute_scoreboard", lambda p, s, e: {
        "accuracy_validated": None, "accuracy_source": "grafo_validado", "checks_validated": None})
    monkeypatch.setattr(run_benchmark, "_save_log", lambda name, log: str(tmp_path / f"{name}.log"))
    return run_combination(
        combo or {"name": "combo", "roles": {"*": "anthropic/claude-haiku-5-5"}, "sem_projeto": True}, "tarefa",
        {"DATABASE_URL": BENCH_URL}, timeout, tmp_path / "outputs", None,
        repeticao=1, results_path=tmp_path / "results.json", target=make_target(), reset=reset,
        store_sample_seconds=interval, kill_grace_seconds=kill_grace_seconds, command=command, **extra,
    )


def test_serie_com_inicio_e_fim(monkeypatch, tmp_path) -> None:
    """Cenário "Série com início e fim": execução simulada que grava 2 nós, amostras em intervalo curto."""
    nodes = {"n": 0}

    def work() -> None:
        time.sleep(0.5)
        nodes["n"] = 2
        time.sleep(0.5)

    result = _run_fake_combination(monkeypatch, tmp_path, work=work, nodes=nodes, interval=0.25)
    timeline = result["store_timeline"]
    assert len(timeline) >= 3
    assert timeline[0]["grafo"]["nos"]["Resultado"] == 0
    assert timeline[-1]["grafo"]["nos"]["Resultado"] - timeline[0]["grafo"]["nos"]["Resultado"] == 2
    assert footprint.growth(timeline)["nos_grafo"]["total"] == 2


def test_amostra_com_falha_tem_erro_e_o_benchmark_segue(monkeypatch) -> None:
    """Cenário "Amostra com falha": o Qdrant indisponível não derruba a coleta."""
    def broken_qdrant(url):
        raise ConnectionError("Qdrant fora do ar")

    monkeypatch.setattr(footprint, "_sample_postgres", lambda url, graph: ({"db_bytes": 1, "tabelas": {}}, {}))
    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", broken_qdrant)
    sample = footprint.collect_store_sample("postgresql://x/y", "http://q:6333", "knowledge")
    assert "Qdrant fora do ar" in sample["erro"] and sample["postgres"]["db_bytes"] == 1

    def source() -> dict:
        raise RuntimeError("fonte caiu")

    sampler = footprint.StoreSampler(source, 0.1)
    sampler.start()
    timeline = sampler.stop()
    assert len(timeline) >= 2 and all("fonte caiu" in s["erro"] for s in timeline)


def _timeline(first_nodes: int, last_nodes: int) -> list[dict]:
    def sample(t: float, nodes: int, qdrant: int, events: int) -> dict:
        return {"t": t, "postgres": {"db_bytes": 1_000_000 + events,
                                     "tabelas": {"agent_events": events, "egress_log": 0, "execution_records": 0}},
                "qdrant": {"knowledge_nodes": qdrant}, "grafo": {"nos": {"Resultado": nodes}, "arestas": {}}}

    return [sample(0.0, first_nodes, 0, 0), sample(120.0, last_nodes, 10, 240)]


def test_relatorio_de_crescimento_mostra_total_e_taxa_por_minuto() -> None:
    """Cenário "Relatório de crescimento"."""
    result = {"name": "sonnet", "repeticao": 1, "status": "exit 0", "store_timeline": _timeline(5, 25)}
    text = report.render_growth([result])
    assert "+20 (10.0/min)" in text  # nós do grafo: 20 em 2 minutos
    assert "+10 (5.0/min)" in text  # pontos do Qdrant
    assert "+240 (120.0/min)" in text  # agent_events
    assert "execution_records" in text and "egress_log" in text


# --------------------------------------------------------------------------------------------
# Placar oficial
# --------------------------------------------------------------------------------------------


def _graph_with_results(tmp_path: Path, results: list[dict], session: str = "sess-1"):
    """Projeto semeado com ``Resultado``s ``{valor, status, qualificador, mede}``; devolve (store, projeto_id)."""
    store = seeded_store(tmp_path)
    project_id = seed_project("combo", store)
    metric = find_approved_metric(store, "acuracia")
    for i, spec in enumerate(results):
        exp = store.create_node("Experimento", {
            "subtarefa_id": f"t{i}", "status": "sucesso", "caminho_artefatos": "x", "no_execucao": "n",
            "projeto_id": project_id, "sessao_id": session}, actor=ORQ)
        props = {"nome_original": "test_accuracy", "valor": spec["valor"],
                 "status_validacao": spec.get("status", "validado"), "caminho_metrics": "m.json",
                 "projeto_id": project_id, "sessao_id": session}
        res = store.create_node("Resultado", props, actor=ORQ)
        if "qualificador" in spec:  # propriedade de v18.6-review-evidence: ainda fora do schema do nó
            store._nodes[res].properties["qualificador"] = spec["qualificador"]
        store.create_edge(exp, "PRODUZIU", res, {}, actor=ORQ)
        if spec.get("mede", True):
            store.create_edge(res, "MEDE", metric.id, {}, actor=ORQ)
    return store, project_id


def test_contagem_nao_vira_acuracia(tmp_path) -> None:
    """Cenário "Contagem não vira acurácia": sem modelo treinado, só texto cita 1.0."""
    session, graph = tmp_path / "s", tmp_path / "g"
    session.mkdir()
    graph.mkdir()
    (session / "relatorio.md").write_text("accuracy: 1.0 (duplicatas)\n")
    declared = score_session(session)["acuracia_declarada_texto"]
    store, project_id = _graph_with_results(graph, [])
    board = graph_accuracy(store, project_id, "sess-1")
    assert board["accuracy_validated"] is None and declared == 1.0
    assert "acuracia_perfeita" not in scoreboard_anomalies(board)


def test_resultado_nao_validado_nao_conta(tmp_path) -> None:
    """Cenário "Resultado não validado não conta"."""
    store, project_id = _graph_with_results(
        tmp_path, [{"valor": 0.97, "status": "nao_validado"}, {"valor": 0.93, "status": "validado"}])
    assert graph_accuracy(store, project_id, "sess-1")["accuracy_validated"] == pytest.approx(0.93)


def test_validacao_cruzada_nao_conta(tmp_path) -> None:
    """Cenário "Validação cruzada não conta"."""
    store, project_id = _graph_with_results(
        tmp_path, [{"valor": 0.98, "qualificador": "cv"}, {"valor": 0.91, "qualificador": "teste"}])
    assert graph_accuracy(store, project_id, "sess-1")["accuracy_validated"] == pytest.approx(0.91)


def test_resultado_sem_mede_fica_nulo_com_nota_e_marca_sem_mede(tmp_path) -> None:
    store, project_id = _graph_with_results(tmp_path, [{"valor": 0.95, "mede": False}])
    board = graph_accuracy(store, project_id, "sess-1")
    assert board["accuracy_validated"] is None and board["accuracy_note"] == "sem MEDE"
    assert "sem_mede" in scoreboard_anomalies(board)


def test_resultado_de_outra_sessao_nao_conta(tmp_path) -> None:
    store, project_id = _graph_with_results(tmp_path, [{"valor": 0.95}], session="outra")
    assert graph_accuracy(store, project_id, "sess-1")["accuracy_validated"] is None


PLAN_AND_EVENTS_ALGOS = (
    {"eda": {"task_type": "eda"},
     "rf": {"task_type": "model_impl", "approach": {"nome": "random forest"}, "descricao": "train_test_split"},
     "svm": {"task_type": "model_impl", "approach": {"nome": "svm"}}},
)


def _review(task: str, approved: bool = True, artifacts: dict | None = None) -> dict:
    return {"event_type": "subtask_review", "task_name": task,
            "payload": {"approved": approved, "resolved_artifacts": artifacts or {}}}


def test_plano_cita_algoritmos_que_nao_rodaram(tmp_path) -> None:
    """Cenário "Plano cita algoritmos que não rodaram": só a EDA foi aprovada."""
    (tmp_path / "plano.md").write_text("Treinar random forest e svm, accuracy: 0.9\n")
    plan = PLAN_AND_EVENTS_ALGOS[0]
    board = {"elegiveis": []}
    checks = validated_checks(plan, [_review("eda")], board, "")
    assert checks["two_algorithms"] is False and checks["eda"] is True
    assert score_session(tmp_path)["checks_texto"]["two_algorithms"] is True


def test_checklist_validado_completo(tmp_path) -> None:
    plan = PLAN_AND_EVENTS_ALGOS[0]
    events = [_review("eda", artifacts={"eda.png": "eda/eda.png"}), _review("rf"), _review("svm"),
              _review("rejeitada", approved=False)]
    store, project_id = _graph_with_results(tmp_path, [{"valor": 0.95}, {"valor": 0.93}])
    board = validated_scoreboard(store, project_id, "sess-1", plan, events, "# Recomendação\nUse RF.")
    assert all(board["checks_validated"].values()) and board["score_validated"] == 6


def test_acuracia_perfeita_e_vocabulario_nao_semeado_nao_interrompem_o_fail_fast(tmp_path) -> None:
    """Cenário "Acurácia perfeita"."""
    store, project_id = _graph_with_results(tmp_path, [{"valor": 1.0}])
    board = graph_accuracy(store, project_id, "sess-1")
    assert "acuracia_perfeita" in scoreboard_anomalies(board)
    assert scoreboard_anomalies({"metrica_aprovada": False}) == ["vocabulario_nao_semeado"]
    result = {"name": "x", "status": "exit 0", "log_tail": "", "session": "s", "routing_check": {"ok": True},
              "operation_metrics": {}, "anomalias_placar": ["acuracia_perfeita"], "accuracy_validated": 1.0}
    assert anomalies(result) == []  # a marca vai para conferência manual; o runner segue
    assert any("placar" in p for p in anomalies({**result, "score_error": "RuntimeError: x"}))


# --------------------------------------------------------------------------------------------
# Arquivamento e repetições
# --------------------------------------------------------------------------------------------


def test_arquivos_presentes(monkeypatch, tmp_path) -> None:
    """Cenário "Arquivos presentes": a repetição deixa os quatro arquivos e ``archive_dir`` aponta para eles."""
    session = tmp_path / "outputs" / "sess-1"
    session.mkdir(parents=True)
    (session / "relatorio_final.md").write_text("# Relatório")
    result = _run_fake_combination(monkeypatch, tmp_path, session=session)
    folder = Path(result["archive_dir"])
    assert folder == archive_dir_for(tmp_path / "results.json", "combo", 1)
    for name in ("sessao.tar.gz", "run.log", "eventos.json", "grafo_projeto.json"):
        assert (folder / name).is_file(), name
    with tarfile.open(folder / "sessao.tar.gz") as tar:
        assert "sess-1/relatorio_final.md" in tar.getnames()
    assert json.loads((folder / "eventos.json").read_text())[0]["event_type"] == "x"


def test_arquivamento_sem_fontes_grava_erro_explicito(tmp_path) -> None:
    folder = archive_repetition(tmp_path / "r1", session_dir=None, log="", events=None, project_graph=None)
    assert "indisponível" in json.loads((folder / "eventos.json").read_text())["erro"]


def test_retomada_executa_so_as_repeticoes_que_faltam() -> None:
    """Cenário "Retomada"."""
    combos = [{"name": "sonnet"}, {"name": "haiku"}]
    results = [{"name": "sonnet", "repeticao": 1, "status": "exit 0"}, {"name": "legado", "status": "exit 0"}]
    plan = pending_runs(combos, results, 3, ["sonnet"])
    assert [(c["name"], r) for c, r in plan] == [("sonnet", 2), ("sonnet", 3)]
    # resultado antigo, sem ``repeticao``, conta como repetição 1
    assert [(c["name"], r) for c, r in pending_runs([{"name": "legado"}], results, 2)] == [("legado", 2)]


def test_agregado_ignora_nulos() -> None:
    """Cenário "Agregado ignora nulos"."""
    def run(rep: int, accuracy: float | None) -> dict:
        return {"name": "sonnet", "repeticao": rep, "status": "exit 0", "wall_seconds": 100.0 + rep,
                "accuracy_validated": accuracy, "stop_reason": "concluida",
                "tokens": {"cost_usd": 0.5}, "outcome": {"subtasks_ok": 4}}

    text = report.render_aggregates([run(1, 0.95), run(2, None), run(3, 0.97)])
    row = next(line for line in text.splitlines() if line.startswith("| sonnet"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == "3" and cells[4].startswith("0.960") and cells[5] == "1"
    assert "concluida: 3" in cells[7]


# --------------------------------------------------------------------------------------------
# Custo com tokens em cache da OpenAI
# --------------------------------------------------------------------------------------------


def test_responses_com_cache_cobra_800_tokens_a_preco_de_cache(monkeypatch) -> None:
    """Cenário "Responses com cache" (e o equivalente de Chat Completions)."""
    monkeypatch.setenv("LLM_PRICING_OVERRIDES", json.dumps({"openai/gpt-6-luna": [1.0, 2.0, 0.1]}))
    provider = OpenAIProvider(api_key="sk", model="gpt-6-luna", reasoning_effort="high")
    data = {"model": "gpt-6-luna", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000,
                      "input_tokens_details": {"cached_tokens": 800}}}
    usage = provider._parse_responses(data, 0).usage
    assert usage["cached_tokens"] == 800
    cost = pricing.estimate_cost("openai", "gpt-6-luna", usage["prompt_tokens"], 0, cached_tokens=usage["cached_tokens"])
    assert cost == pytest.approx((200 * 1.0 + 800 * 0.1) / 1_000_000)

    chat = OpenAIProvider(api_key="sk", model="gpt-6-luna", reasoning_effort=None)
    chat_data = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 1000, "completion_tokens": 0, "total_tokens": 1000,
                           "prompt_tokens_details": {"cached_tokens": 800}}}

    async def fake_post(path, payload):
        return chat_data, 0

    chat._post_with_retry = fake_post  # type: ignore[method-assign]
    chat_usage = asyncio.run(chat.generate([{"role": "user", "content": "oi"}])).usage
    assert chat_usage["cached_tokens"] == 800


# --- Juiz declarado por combinação (ADR 020 §7) ---------------------------------------------------------------------

HAIKU, SONNET, GEMINI = "anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "google/gemini-4-argon"


def test_juiz_nao_declarado() -> None:
    """Cenário "Juiz não declarado": o '*' não cobre o validator; a mensagem pede o VALIDATOR."""
    combo = {"name": "c", "roles": {"*": HAIKU}}
    with pytest.raises(run_benchmark.CombinationRefused, match="VALIDATOR"):
        run_benchmark.validate_combination(combo)
    env = run_benchmark.build_env({"VALIDATOR_MODEL": "x"}, combo["roles"])
    assert "VALIDATOR_MODEL" not in env
    assert env["DEVELOPER_MODEL"] == HAIKU and env["BASE_MODEL"] == HAIKU


def test_juiz_da_mesma_familia() -> None:
    """Cenário "Juiz da mesma família": claude nos dois lados é recusado; outra família passa."""
    combo = {"name": "c", "roles": {"*": HAIKU, "VALIDATOR": SONNET}}
    with pytest.raises(run_benchmark.CombinationRefused, match="claude"):
        run_benchmark.validate_combination(combo)
    run_benchmark.validate_combination({"name": "c", "roles": {"*": HAIKU, "VALIDATOR": GEMINI}})


def test_combinacao_de_controle(monkeypatch, tmp_path) -> None:
    """Cenário "Combinação de controle": aceita na validação, LLM_JUDGE_INDEPENDENCE=off no subprocesso, controle: true."""
    combo = {"name": "controle", "roles": {"*": HAIKU, "VALIDATOR": SONNET}, "independencia_julgamento": "off",
             "sem_projeto": True}
    run_benchmark.validate_combination(combo)
    seen: dict = {}
    result = _run_fake_combination(monkeypatch, tmp_path, combo=combo, popen_env=seen)
    assert seen["LLM_JUDGE_INDEPENDENCE"] == "off" and seen["VALIDATOR_MODEL"] == SONNET
    assert result["controle"] is True
    normal = {"name": "n", "roles": {"*": HAIKU, "VALIDATOR": GEMINI}, "sem_projeto": True}
    seen2: dict = {}
    result2 = _run_fake_combination(monkeypatch, tmp_path, combo=normal, popen_env=seen2)
    assert result2["controle"] is False and "LLM_JUDGE_INDEPENDENCE" not in seen2


def test_combinacao_de_controle_exige_validator_e_valor_off() -> None:
    with pytest.raises(run_benchmark.CombinationRefused, match="VALIDATOR"):
        run_benchmark.validate_combination({"name": "c", "roles": {"*": HAIKU}, "independencia_julgamento": "off"})
    with pytest.raises(run_benchmark.CombinationRefused, match="off"):
        run_benchmark.validate_combination(
            {"name": "c", "roles": {"*": HAIKU, "VALIDATOR": GEMINI}, "independencia_julgamento": "on"})


def test_check_pins_juiz_e_registro_de_independencia() -> None:
    """check_pins: juiz não herda '*'; registro independencia_julgamento esperado conforme o controle."""
    roles = {"*": HAIKU, "VALIDATOR": SONNET}
    routing = {"papeis": {"developer": {"id": HAIKU, "origem": "pin"}, "base": {"id": HAIKU, "origem": "pin"},
                          "researcher": {"id": HAIKU, "origem": "pin"}, "summarizer": {"id": HAIKU, "origem": "pin"},
                          "validator": {"id": SONNET, "origem": "pin"}},
               "independencia_julgamento": {"modo": "off"}}
    assert run_benchmark.check_pins(roles, routing, controle=True) == []
    problems = run_benchmark.check_pins(roles, routing, controle=False)
    assert len(problems) == 1 and "off" in problems[0]
    routing["independencia_julgamento"] = {"modo": "required"}
    assert "controle" in run_benchmark.check_pins(roles, routing, controle=True)[0]


def test_matriz_v18_6_valida() -> None:
    """A matriz versionada passa na validação e inclui ao menos uma combinação de controle."""
    matrix = json.loads(Path("scripts/benchmark/matrix_modelos_v18_6.json").read_text(encoding="utf-8"))
    for combo in matrix["combinations"]:
        run_benchmark.validate_combination(combo)
    assert any(run_benchmark.is_control(c) for c in matrix["combinations"])


def test_semeadura_e_entrada_por_exploracao(monkeypatch, tmp_path) -> None:
    """v18.8-verdict-controlled-sessions: ``seeder`` e ``input_dir`` chegam ao projeto e ao ambiente do subprocesso."""
    seen: list[str] = []
    env: dict = {}

    def seeder(name: str) -> str:
        seen.append(name)
        return "proj-regime"

    combo = {"name": "combo", "roles": {"*": "anthropic/claude-haiku-5-5"}}
    result = _run_fake_combination(
        monkeypatch, tmp_path, combo=combo, popen_env=env, seeder=seeder, input_dir=tmp_path / "entrada"
    )
    assert seen == ["combo"] and result["project_id"] == "proj-regime"
    assert env["INPUT_CONTEXT_DIR"] == str(tmp_path / "entrada")


def test_iris_inalterado_sem_os_parametros_novos(monkeypatch, tmp_path) -> None:
    env: dict = {}
    nomes: list[str] = []
    monkeypatch.setattr("scripts.benchmark.seed_project.seed_project", lambda name, *a, **k: nomes.append(name) or "iris")
    combo = {"name": "combo", "roles": {"*": "anthropic/claude-haiku-5-5"}}
    result = _run_fake_combination(monkeypatch, tmp_path, combo=combo, popen_env=env)
    assert nomes == ["combo"] and result["project_id"] == "iris"
    assert "INPUT_CONTEXT_DIR" not in env
