"""Pegada de conhecimento e de operação por combinação do benchmark.

Compara, antes e depois de cada execução, o que os repositórios receberam: pontos do Qdrant (vetores de embeddings),
linhas das tabelas do Postgres (telemetria, egresso, proveniência, auditoria do grafo) e nós/arestas do grafo AGE.
Também lê o ``operation_metrics`` gravado na sessão (v18.5-operation-metrics). Nenhuma chamada LLM.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

# Tabelas de interesse (nome fixo: o texto SQL nunca recebe entrada externa).
TABLES = (
    "token_usage",
    "agent_events",
    "subtask_metrics",
    "hardware_snapshots",
    "egress_log",
    "execution_records",
    "knowledge_audit",
    "agent_sessions",
)


def snapshot() -> dict[str, Any]:
    """Estado atual: pontos por coleção do Qdrant, linhas por tabela e totais do grafo. Falhas viram ``*_erro``."""
    out: dict[str, Any] = {}
    try:
        from qdrant_client import QdrantClient

        from src import config

        client = QdrantClient(url=config.QDRANT_URL)
        out["qdrant"] = {
            c.name: int(client.get_collection(c.name).points_count or 0) for c in client.get_collections().collections
        }
    except Exception as exc:  # noqa: BLE001 - o benchmark segue sem a medida
        out["qdrant_erro"] = f"{type(exc).__name__}: {exc}"
    try:
        from src import config
        from src.db import get_connection

        tables: dict[str, int] = {}
        with get_connection() as conn:
            for table in TABLES:
                # Tabelas criadas por migrações do pool (ex.: knowledge_audit) podem estar em ag_catalog, que o
                # search_path do pool põe à frente de public.
                for schema in ("public", "ag_catalog"):
                    try:
                        count = conn.execute(f"SELECT count(*) AS n FROM {schema}.{table}").fetchone()["n"]
                        tables[table] = int(count)
                        break
                    except Exception:  # noqa: BLE001 - tabela ausente neste schema
                        conn.rollback()
            out["tabelas"] = tables
            conn.execute("LOAD 'age'")
            conn.execute('SET search_path = ag_catalog, "$user", public')
            graph = config.KNOWLEDGE_GRAPH_NAME
            nodes = f"SELECT * FROM cypher('{graph}', $$ MATCH (n) RETURN count(n) $$) AS (c agtype)"
            edges = f"SELECT * FROM cypher('{graph}', $$ MATCH ()-[r]->() RETURN count(r) $$) AS (c agtype)"
            out["grafo"] = {
                "nos": int(str(conn.execute(nodes).fetchone()["c"])),
                "arestas": int(str(conn.execute(edges).fetchone()["c"])),
            }
    except Exception as exc:  # noqa: BLE001
        out["postgres_erro"] = f"{type(exc).__name__}: {exc}"
    return out


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Diferença ``depois - antes`` das contagens de ``snapshot`` (chaves ausentes contam como zero)."""

    def sub(a: dict[str, int] | None, b: dict[str, int] | None) -> dict[str, int]:
        a, b = a or {}, b or {}
        return {k: b.get(k, 0) - a.get(k, 0) for k in sorted(set(a) | set(b)) if b.get(k, 0) != a.get(k, 0)}

    result: dict[str, Any] = {
        "qdrant": sub(before.get("qdrant"), after.get("qdrant")),
        "tabelas": sub(before.get("tabelas"), after.get("tabelas")),
        "grafo": sub(before.get("grafo"), after.get("grafo")),
    }
    for key in ("qdrant_erro", "postgres_erro"):
        if key in before or key in after:
            result[key] = after.get(key) or before.get(key)
    return result


def project_graph(project_id: str, store: Any | None = None) -> dict[str, Any]:
    """Nós por rótulo e arestas por tipo do subgrafo do projeto (memória de grafo usada pela sessão)."""
    try:
        if store is None:
            from src.knowledge.factory import open_raw_graph_store

            store = open_raw_graph_store()
        sub = store.project_subgraph(project_id)
        return {
            "nos_por_rotulo": dict(sorted(Counter(n.label for n in sub.nodes).items())),
            "arestas_por_tipo": dict(sorted(Counter(e.rel_type for e in sub.edges).items())),
            "total_nos": len(sub.nodes),
            "total_arestas": len(sub.edges),
        }
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"{type(exc).__name__}: {exc}"}


def project_graph_full(project_id: str, store: Any | None = None) -> dict[str, Any]:
    """Nós (com propriedades) e arestas do subgrafo do projeto, para o arquivamento da repetição.

    Inclui os nós ``Metrica`` (vocabulário, fora do projeto) ligados por ``MEDE`` aos ``Resultado`` do projeto, para
    que os registros de resultado possam ser recalculados do arquivo.
    """
    try:
        if store is None:
            from src.knowledge.factory import open_raw_graph_store

            store = open_raw_graph_store()
        sub = store.project_subgraph(project_id)
        nodes = list(sub.nodes)
        edges = list(sub.edges)
        known = {n.id for n in nodes}
        seen_edges = {(e.src_id, e.rel_type, e.dst_id) for e in edges}
        for result in [n for n in sub.nodes if n.label == "Resultado"]:
            for edge in store.neighbors(result.id, ["MEDE"], "out", 1).edges:
                if edge.src_id != result.id or edge.rel_type != "MEDE":
                    continue
                if edge.dst_id not in known:
                    metric = store.get_node(edge.dst_id)
                    if metric is None:
                        continue
                    nodes.append(metric)
                    known.add(metric.id)
                key = (edge.src_id, edge.rel_type, edge.dst_id)
                if key not in seen_edges:
                    edges.append(edge)
                    seen_edges.add(key)
        return {
            "nos": [{"id": n.id, "label": n.label, "propriedades": n.properties} for n in nodes],
            "arestas": [
                {"origem": e.src_id, "tipo": e.rel_type, "destino": e.dst_id, "propriedades": e.properties}
                for e in edges
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"{type(exc).__name__}: {exc}"}


def session_operation_metrics(session_id: str) -> dict[str, Any] | None:
    """``payload["operation_metrics"]`` da sessão mestra, ou ``None`` se a sessão não o gravou."""
    try:
        from src.session.manager import SessionManager

        session = SessionManager().get(session_id)
        payload = getattr(session, "payload", None)
        metrics = payload.get("operation_metrics") if isinstance(payload, dict) else None
        return metrics if isinstance(metrics, dict) else None
    except Exception:  # noqa: BLE001
        return None


def embedding_events(session_id: str) -> dict[str, Any]:
    """Eventos de telemetria ligados a vetorização na sessão (contagens por tipo; vazio se não houver)."""
    try:
        from src.observability.telemetry import get_telemetry

        counts = get_telemetry().get_event_counts(
            session_id, ("knowledge_ingestion", "knowledge_recompute", "input_index", "memory_promotion")
        )
        return {event: sum(agents.values()) for event, agents in counts.items()}
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------------------------
# Crescimento das memórias no tempo (v18.6-benchmark-harness §3)
# --------------------------------------------------------------------------------------------

# Tabelas amostradas: as de ``TABLES`` mais as de memória e índice (nomes fixos; o SQL nunca recebe entrada externa).
SAMPLED_TABLES = (*TABLES, "similarity_queue", "long_term_memory", "document_chunks")
DEFAULT_STORE_SAMPLE_SECONDS = 30.0


def collect_store_sample(database_url: str, qdrant_url: str, graph_name: str) -> dict[str, Any]:
    """Uma amostra das três memórias, por conexão própria (fora do pool do processo medido).

    Cada seção falha isoladamente: o motivo vai para ``erro`` e as demais seções seguem.
    """
    sample: dict[str, Any] = {}
    errors: list[str] = []
    try:
        sample["postgres"], sample["grafo"] = _sample_postgres(database_url, graph_name)
    except Exception as exc:  # noqa: BLE001 - o benchmark segue sem a medida
        errors.append(f"postgres: {type(exc).__name__}: {exc}")
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=qdrant_url)
        sample["qdrant"] = {
            c.name: int(client.get_collection(c.name).points_count or 0) for c in client.get_collections().collections
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"qdrant: {type(exc).__name__}: {exc}")
    if errors:
        sample["erro"] = "; ".join(errors)
    return sample


def _sample_postgres(database_url: str, graph_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    import psycopg
    from psycopg import sql

    with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as conn:
        postgres: dict[str, Any] = {
            "db_bytes": int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])
        }
        tables: dict[str, int] = {}
        for table in SAMPLED_TABLES:
            # Tabelas criadas por migrações do pool podem estar em ag_catalog (ver ``snapshot``).
            for schema in ("public", "ag_catalog"):
                if conn.execute("SELECT to_regclass(%s)", (f"{schema}.{table}",)).fetchone()[0]:
                    query = sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
                    tables[table] = int(conn.execute(query).fetchone()[0])
                    break
        postgres["tabelas"] = tables
        grafo: dict[str, dict[str, int]] = {"nos": {}, "arestas": {}}
        labels = conn.execute(
            "SELECT l.name, l.kind FROM ag_catalog.ag_label l JOIN ag_catalog.ag_graph g ON g.graphid = l.graph "
            "WHERE g.name = %s AND l.name NOT LIKE '\\_ag\\_label%%'",
            (graph_name,),
        ).fetchall()
        for name, kind in labels:  # contagem pela tabela do rótulo: sem Cypher de caminho (custo baixo no Pi)
            query = sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(graph_name), sql.Identifier(name))
            count = int(conn.execute(query).fetchone()[0])
            if count:
                grafo["nos" if kind == "v" else "arestas"][name] = count
    return postgres, grafo


class StoreSampler:
    """Amostra o crescimento das memórias a cada ``interval`` segundos, mais uma amostra no início e uma no fim.

    Args:
        source: Função sem argumentos que devolve uma amostra (``collect_store_sample`` com os alvos fixados).
            Exceção da fonte vira ``{"t": ..., "erro": ...}`` e o benchmark continua.
        interval: Segundos entre amostras (``BENCHMARK_STORE_SAMPLE_SECONDS``).
    """

    def __init__(self, source: Callable[[], dict[str, Any]], interval: float = DEFAULT_STORE_SAMPLE_SECONDS) -> None:
        self._source = source
        self._interval = max(float(interval), 0.05)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="store-sampler", daemon=True)
        self._t0 = time.monotonic()
        self.timeline: list[dict[str, Any]] = []

    def _take(self) -> None:
        try:
            sample = dict(self._source())
        except Exception as exc:  # noqa: BLE001
            sample = {"erro": f"{type(exc).__name__}: {exc}"}
        self.timeline.append({"t": round(time.monotonic() - self._t0, 1), **sample})

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._take()

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._take()
        self._thread.start()

    def stop(self) -> list[dict[str, Any]]:
        """Para o laço, grava a amostra final e devolve a série."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self._interval + 30)
        self._take()
        return self.timeline


def growth(timeline: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Crescimento total (última amostra sem erro menos a primeira) e taxa por minuto; ``None`` sem duas amostras."""
    valid = [s for s in timeline if not s.get("erro")]
    if len(valid) < 2:
        return None
    first, last = valid[0], valid[-1]
    minutes = max((last["t"] - first["t"]) / 60.0, 1e-9)

    def total(sample: dict[str, Any], *path: str) -> int:
        node: Any = sample
        for key in path:
            node = (node or {}).get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            return sum(node.values())
        return int(node or 0)

    metrics = {
        "nos_grafo": ("grafo", "nos"),
        "arestas_grafo": ("grafo", "arestas"),
        "pontos_qdrant": ("qdrant",),
        "agent_events": ("postgres", "tabelas", "agent_events"),
        "egress_log": ("postgres", "tabelas", "egress_log"),
        "execution_records": ("postgres", "tabelas", "execution_records"),
        "db_bytes": ("postgres", "db_bytes"),
    }
    out: dict[str, Any] = {"duracao_min": round(minutes, 3), "amostras": len(valid)}
    for name, path in metrics.items():
        diff = total(last, *path) - total(first, *path)
        out[name] = {"total": diff, "por_minuto": round(diff / minutes, 2)}
    return out
