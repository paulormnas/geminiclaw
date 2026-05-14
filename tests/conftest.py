import os
import pytest

# Define variáveis de ambiente necessárias para a importação do src.config nos testes unitários
os.environ["GENAI_API_KEY"] = "dummy_key_for_testing"
os.environ["GEMINI_API_KEY"] = "dummy_key_for_testing"
os.environ["DEFAULT_MODEL"] = "gemini-3-flash-preview"
os.environ["AGENT_TIMEOUT_SECONDS"] = "120"
# DATABASE_URL: valor fictício para testes unitários (sem banco real)
# Testes de integração sobrescrevem com uma URL real
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@localhost:5432/test_geminiclaw"
)
os.environ["SEARCH_CACHE_TTL_SECONDS"] = "3600"

# Sinaliza para pular testes de integração que consomem cota de API durante a suíte completa
os.environ["CI_SKIP_INTEGRATION"] = "1"

from unittest.mock import MagicMock, patch

@pytest.fixture(autouse=True)
def mock_db_connection(request):
    """Mock global do banco de dados com estado em memória.
    
    Ignorado para testes unitários do módulo src.db para permitir testar a lógica real.
    """
    if "test_db.py" in request.node.fspath.strpath:
        yield
        return

    db_state = {}

    def _execute(query, params=None):
        mock_cursor = MagicMock()
        # Normaliza query para facilitar o matching: remove quebras de linha e espaços extras
        query_norm = " ".join(query.strip().upper().split())
        
        # INSERT INTO agent_sessions (...) VALUES (%s, %s, %s, %s, %s, %s)
        if "INSERT INTO AGENT_SESSIONS" in query_norm:
            db_state[params[0]] = {
                "id": params[0], "agent_id": params[1], "status": params[2],
                "created_at": params[3], "updated_at": params[4], "payload": params[5],
                "source": "orchestrator"
            }
        # UPDATE agent_sessions SET status = %s, payload = %s, updated_at = %s WHERE id = %s
        elif "UPDATE AGENT_SESSIONS" in query_norm:
            session_id = params[3]
            if session_id in db_state:
                db_state[session_id]["status"] = params[0]
                db_state[session_id]["payload"] = params[1]
                db_state[session_id]["updated_at"] = params[2]
        # SELECT * FROM agent_sessions WHERE id = %s
        elif "SELECT * FROM AGENT_SESSIONS WHERE ID = %S" in query_norm:
            session_id = params[0]
            mock_cursor.fetchone.return_value = db_state.get(session_id)
        # SELECT * FROM agent_sessions ORDER BY created_at DESC LIMIT %s
        elif "SELECT * FROM AGENT_SESSIONS ORDER BY CREATED_AT DESC" in query_norm:
            mock_cursor.fetchall.return_value = list(db_state.values())
        
        # LONG_TERM_MEMORY
        elif "INSERT INTO LONG_TERM_MEMORY" in query_norm:
            key = params[1]
            db_state[f"ltm_{key}"] = {
                "id": params[0], "key": key, "value": params[2], "source": params[3],
                "importance": params[4], "tags": params[5], "created_at": params[6],
                "last_used": params[7], "use_count": params[8]
            }
        elif "SELECT * FROM LONG_TERM_MEMORY WHERE KEY = %S" in query_norm:
            key = params[0]
            mock_cursor.fetchone.return_value = db_state.get(f"ltm_{key}")
        elif "SELECT * FROM LONG_TERM_MEMORY" in query_norm:
            mock_cursor.fetchall.return_value = [v for k, v in db_state.items() if k.startswith("ltm_")]
            
        else:
            # Fallback para outras queries (histórico, telemetria, etc.)
            dummy_row = {
                "id": "dummy-id", "agent_id": "dummy-agent", "status": "active",
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                "payload": "{}", "prompt": "dummy-prompt", "plan_json": "[]",
                "results_json": "[]", "artifacts_json": "[]", "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z", "duration_seconds": 1.0,
                "total_subtasks": 1, "succeeded": 1, "failed": 0, "tags": "[]",
                "value": "dummy-value", "key": "dummy-key", "importance": 0.5,
                "source": "dummy-source", "use_count": 0, "last_used": "2026-01-01T00:00:00Z"
            }
            mock_cursor.fetchone.return_value = dummy_row
            mock_cursor.fetchall.return_value = [dummy_row]
            
        return mock_cursor

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = _execute
    
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    
    # Patches obrigatórios
    patches = [
        patch("src.db.get_connection", return_value=ctx),
        patch("src.session.get_connection", return_value=ctx),
        patch("src.history.get_connection", return_value=ctx),
        patch("src.telemetry.get_connection", return_value=ctx),
        patch("src.skills.memory.long_term.get_connection", return_value=ctx),
        patch("src.llm_cache.get_connection", return_value=ctx),
    ]
    
    # Patches opcionais (Search Deep)
    try:
        from src.skills import _HAS_DEEP_SEARCH
        if _HAS_DEEP_SEARCH:
            patches.append(patch("src.skills.search_deep.cache.get_connection", return_value=ctx))
    except (ImportError, AttributeError):
        pass

    from contextlib import ExitStack
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield ctx

@pytest.fixture(scope="session", autouse=True)
def global_container_cleanup_check():
    """Garante que não sobrou nenhum container do projeto após rodar os testes."""
    yield
    try:
        import docker
        client = docker.from_env()
        # all=True checks stopped containers as well
        containers = client.containers.list(filters={"label": "project=geminiclaw"}, all=True)
        if containers:
            container_ids = [c.short_id for c in containers]
            for c in containers:
                try:
                    c.remove(force=True)
                except Exception:
                    pass
            pytest.fail(f"Vazamento de containers detectado apos os testes: {container_ids}")
    except Exception as e:
        print(f"Aviso na verificacao de containers: {e}")
