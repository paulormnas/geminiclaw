"""Pegada de conhecimento e de operação por combinação do benchmark.

Compara, antes e depois de cada execução, o que os repositórios receberam: pontos do Qdrant (vetores de embeddings),
linhas das tabelas do Postgres (telemetria, egresso, proveniência, auditoria do grafo) e nós/arestas do grafo AGE.
Também lê o ``operation_metrics`` gravado na sessão (v18.5-operation-metrics). Nenhuma chamada LLM.
"""

from __future__ import annotations

from collections import Counter
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
                try:
                    tables[table] = int(conn.execute(f"SELECT count(*) AS n FROM public.{table}").fetchone()["n"])
                except Exception:  # noqa: BLE001 - tabela ausente (migração não aplicada)
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


def session_operation_metrics(session_id: str) -> dict[str, Any] | None:
    """``payload["operation_metrics"]`` da sessão mestra, ou ``None`` se a sessão não o gravou."""
    try:
        from src.session import SessionManager

        session = SessionManager().get(session_id)
        payload = getattr(session, "payload", None)
        metrics = payload.get("operation_metrics") if isinstance(payload, dict) else None
        return metrics if isinstance(metrics, dict) else None
    except Exception:  # noqa: BLE001
        return None


def embedding_events(session_id: str) -> dict[str, Any]:
    """Eventos de telemetria ligados a vetorização na sessão (contagens por tipo; vazio se não houver)."""
    try:
        from src.telemetry import get_telemetry

        counts = get_telemetry().get_event_counts(
            session_id, ("knowledge_ingestion", "knowledge_recompute", "input_index", "memory_promotion")
        )
        return {event: sum(agents.values()) for event, agents in counts.items()}
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"{type(exc).__name__}: {exc}"}
