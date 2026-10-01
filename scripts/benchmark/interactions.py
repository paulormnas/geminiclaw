"""Métricas de interação entre agentes e de uso de conhecimento (vetores e grafo) por sessão.

Respondem a perguntas de avaliação: quem consumiu mais tokens, quantas mensagens trocaram, as
validações e revisões foram relevantes, o ``ask_researcher`` foi usado e os repositórios de
conhecimento (Qdrant e grafo AGE) receberam dados. Tudo vem do Postgres e do Qdrant; nenhuma chamada LLM.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# Eventos que são mensagens entre agentes/orquestrador, em oposição a ciclo de vida do processo.
MESSAGE_EVENTS = ("plan_generated", "plan_validation", "subtask_review", "replan_triggered", "ask_researcher")


def summarize_events(events: list[dict[str, Any]]) -> dict:
    """Resume eventos ``agent_events`` (dicts com ``event_type`` e ``payload_json`` já decodificado)."""
    counts = Counter(e["event_type"] for e in events)
    validations = [e["payload"] for e in events if e["event_type"] == "plan_validation"]
    reviews = [e["payload"] for e in events if e["event_type"] == "subtask_review"]
    questions = [e["payload"] for e in events if e["event_type"] == "ask_researcher"]
    return {
        "event_counts": dict(counts),
        "messages": sum(counts[t] for t in MESSAGE_EVENTS),
        "plan_validations": {
            "total": len(validations),
            "approved": sum(1 for v in validations if v.get("approved")),
            "rejections": [v.get("issues") or [v.get("reason")] for v in validations if not v.get("approved")],
        },
        "subtask_reviews": {
            "total": len(reviews),
            "approved": sum(1 for r in reviews if r.get("approved")),
            "rejections": [r.get("issues") or [r.get("feedback")] for r in reviews if not r.get("approved")],
        },
        "ask_researcher": [
            {"question": q.get("question"), "why": q.get("why_cant_proceed"), "options": q.get("options")}
            for q in questions
        ],
    }


def tokens_by_agent(rows: list[dict[str, Any]]) -> list[dict]:
    total = sum((r["completion_tokens"] or 0) + (r["prompt_tokens"] or 0) for r in rows) or 1
    return [
        {
            "agent": r["agent_id"],
            "calls": r["calls"],
            "prompt_tokens": int(r["prompt_tokens"] or 0),
            "completion_tokens": int(r["completion_tokens"] or 0),
            "share_pct": round(100 * ((r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)) / total, 1),
            "cost_usd": round(float(r["cost_usd"] or 0), 6),
            "avg_latency_ms": round(float(r["avg_latency_ms"] or 0)),
        }
        for r in rows
    ]


def collect_session(session_id: str) -> dict:
    """Consulta o banco e devolve o resumo de interações da sessão (``{}`` + ``error`` se indisponível)."""
    import json

    from src.db import get_connection

    try:
        with get_connection() as conn:
            agent_rows = conn.execute(
                "SELECT agent_id, count(*) AS calls, sum(prompt_tokens) AS prompt_tokens, "
                "sum(completion_tokens) AS completion_tokens, sum(estimated_cost_usd) AS cost_usd, "
                "avg(latency_ms) AS avg_latency_ms FROM token_usage WHERE execution_id = %s "
                "GROUP BY agent_id ORDER BY sum(prompt_tokens + completion_tokens) DESC",
                (session_id,),
            ).fetchall()
            event_rows = conn.execute(
                "SELECT event_type, agent_id, target_agent_id, payload_json FROM agent_events "
                "WHERE execution_id = %s ORDER BY timestamp",
                (session_id,),
            ).fetchall()
        events = []
        for r in event_rows:
            raw = r["payload_json"]
            payload = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else (raw or {})
            events.append({"event_type": r["event_type"], "payload": payload if isinstance(payload, dict) else {}})
        return {"tokens_by_agent": tokens_by_agent([dict(r) for r in agent_rows]), **summarize_events(events)}
    except Exception as exc:  # telemetria indisponível não invalida a medição
        return {"error": str(exc)}


def knowledge_footprint() -> dict:
    """Quanto conhecimento persistente existe: pontos no Qdrant, linhas de memória e nós/arestas do grafo."""
    out: dict[str, Any] = {}
    try:
        from qdrant_client import QdrantClient

        from src import config

        client = QdrantClient(url=config.QDRANT_URL)
        out["qdrant"] = {
            c.name: client.get_collection(c.name).points_count for c in client.get_collections().collections
        }
    except Exception as exc:
        out["qdrant_error"] = str(exc)
    try:
        from src import config
        from src.db import get_connection

        with get_connection() as conn:
            out["long_term_memory_rows"] = conn.execute("SELECT count(*) AS n FROM long_term_memory").fetchone()["n"]
            conn.execute("LOAD 'age'")
            conn.execute('SET search_path = ag_catalog, "$user", public')
            g = config.KNOWLEDGE_GRAPH_NAME
            nodes_sql = f"SELECT * FROM cypher('{g}', $$ MATCH (n) RETURN count(n) $$) AS (c agtype)"
            edges_sql = f"SELECT * FROM cypher('{g}', $$ MATCH ()-[r]->() RETURN count(r) $$) AS (c agtype)"
            out["graph_nodes"] = conn.execute(nodes_sql).fetchone()["c"]
            out["graph_edges"] = conn.execute(edges_sql).fetchone()["c"]
    except Exception as exc:
        out["postgres_error"] = str(exc)
    return out
