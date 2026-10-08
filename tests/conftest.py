import json
import os

import pytest

# Define variáveis de ambiente necessárias para a importação do src.config nos testes unitários
os.environ["GENAI_API_KEY"] = "dummy_key_for_testing"
os.environ["GEMINI_API_KEY"] = "dummy_key_for_testing"
os.environ["AGENT_TIMEOUT_SECONDS"] = "120"
# DATABASE_URL: valor fictício para testes unitários (sem banco real)
# Testes de integração sobrescrevem com uma URL real
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@localhost:5432/test_geminiclaw"
)
# Roteamento de modelos (ADR 017): política padrão restritiva e determinística nos testes.
os.environ["LLM_DATA_POLICY"] = "self_hosted_only"
os.environ["LLM_ROUTING"] = "flexible"
os.environ.pop("LLM_PROVIDER_PRIORITY", None)
os.environ["SEARCH_CACHE_TTL_SECONDS"] = "3600"
# v17-curator-agent: o Curator (LLM) fica desligado por padrão nos testes que atravessam o orquestrador; os testes do
# Curator o ligam explicitamente e usam um provedor simulado (nenhum teste chama provedor ou rede).
os.environ["CURATOR_ENABLED"] = "false"
# v18.5-egress-gate: k das estatísticas é decisão do pesquisador; os testes o fixam (a ausência é testada à parte).
os.environ["LOCALITY_MIN_GROUP_SIZE"] = "10"

# Sinaliza para pular testes de integração que consomem cota de API durante a suíte completa
os.environ["CI_SKIP_INTEGRATION"] = "1"
os.environ["QDRANT_URL"] = ":memory:"
os.environ["QDRANT_CHECK_COMPATIBILITY"] = "false"

from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_embedding_provider(monkeypatch):
    """Evita carregar o modelo FastEmbed real durante a suíte de testes.

    Roadmap V16 removeu os embeddings aleatórios de código de produção
    (`_generate_mock_embedding`); qualquer indexador construído sem um
    `embedding_provider` explícito cairia no `FastEmbedProvider` real, o que
    tentaria carregar/baixar um modelo ONNX em toda suíte de testes. Este
    fixture injeta um provedor falso e determinístico
    (`tests.support.fake_embedding_provider.FakeEmbeddingProvider`) no
    singleton do processo antes de cada teste.

    Testes que precisam validar comportamento semântico real (ex.:
    relevância de busca) devem chamar `reset_embedding_provider()` e
    construir um `FastEmbedProvider()` explicitamente, injetando-o via
    parâmetro no indexador — nesse caso este fixture é contornado.
    """
    from src.embeddings import base as embeddings_base
    from tests.support.fake_embedding_provider import FakeEmbeddingProvider

    fake = FakeEmbeddingProvider()
    monkeypatch.setattr(embeddings_base, "_provider_singleton", fake)
    yield fake
    monkeypatch.setattr(embeddings_base, "_provider_singleton", None)

@pytest.fixture(autouse=True)
def mock_db_connection(request):
    """Mock global do banco de dados com estado em memória.

    Ignorado para testes unitários do módulo src.db, para os testes de pool
    real (tests/integration/test_db_integration.py, que se auto-pulam sem
    PostgreSQL) e para os testes de integração do grafo de conhecimento
    (tests/integration/knowledge/), que precisam de uma conexão real com
    Apache AGE — ver tests/integration/knowledge/conftest.py.
    """
    path = request.node.fspath.strpath
    if (
        "test_db.py" in path
        or "test_db_integration.py" in path
        or "test_egress_log_integration.py" in path
        or f"{os.sep}tests{os.sep}integration{os.sep}knowledge{os.sep}" in path
    ):
        yield
        return

    db_state = {}

    def _execute(query, params=None):
        mock_cursor = MagicMock()
        # Normaliza query para facilitar o matching: remove quebras de linha e espaços extras
        query_norm = " ".join(query.strip().upper().split())
        
        # V18 continuidade — consultas novas modeladas sobre `db_state` (semântica das cláusulas WHERE, em Python).
        # Isto NÃO prova o SQL real (JSONB, TIMESTAMPTZ): a validação em PostgreSQL é tarefa pendente (tasks.md 6.1).
        def _payload_of(row):
            raw = row["payload"]
            return json.loads(raw) if isinstance(raw, str) else dict(raw)

        def _orch_rows():
            return [r for r in db_state.values() if isinstance(r, dict) and r.get("agent_id") == "orchestrator"]

        if "UPDATE AGENT_SESSIONS SET UPDATED_AT" in query_norm:
            row = db_state.get(params[1])
            if row and row["status"] == "active":
                row["updated_at"] = params[0]
                mock_cursor.fetchone.return_value = {"id": params[1]}
            else:
                mock_cursor.fetchone.return_value = None
            return mock_cursor
        if "UPDATE AGENT_SESSIONS SET STATUS = 'INTERROMPIDA'" in query_norm:
            patch_json, now_iso, cutoff = params
            hit = [r for r in _orch_rows() if r["status"] == "active" and str(r["updated_at"]) < cutoff]
            for r in hit:
                r["status"] = "interrompida"
                r["payload"] = json.dumps({**_payload_of(r), **json.loads(patch_json)})
                r["updated_at"] = now_iso
            mock_cursor.fetchall.return_value = [dict(r) for r in hit]
            return mock_cursor
        if "UPDATE AGENT_SESSIONS SET PAYLOAD = PAYLOAD || JSONB_BUILD_OBJECT('CONTINUED_BY'" in query_norm:
            new_id, now_iso, source = params[0], params[1], params[2]
            row = db_state.get(source)
            pl = _payload_of(row) if row else {}
            ok = row is not None and (
                ("continued_by" not in pl) if len(params) == 3 else pl.get("continued_by") == params[3]
            )
            if ok:
                row["payload"] = json.dumps({**pl, "continued_by": new_id})
            mock_cursor.fetchone.return_value = {"id": source} if ok else None
            return mock_cursor
        if "UPDATE AGENT_SESSIONS SET PAYLOAD = PAYLOAD - 'CONTINUED_BY'" in query_norm:
            source, new_id = params
            row = db_state.get(source)
            pl = _payload_of(row) if row else {}
            ok = row is not None and pl.get("continued_by") == new_id
            if ok:
                pl.pop("continued_by")
                row["payload"] = json.dumps(pl)
            mock_cursor.fetchone.return_value = {"id": source} if ok else None
            return mock_cursor
        if "UPDATE AGENT_SESSIONS SET STATUS = 'ACTIVE'" in query_norm:
            now_iso, sid = params
            row = db_state.get(sid)
            ok = row is not None and row["status"] == "interrompida"
            if ok:
                pl = _payload_of(row)
                pl.pop("motivo_parada", None)
                row.update(status="active", payload=json.dumps(pl), updated_at=now_iso)
            mock_cursor.fetchone.return_value = {"id": sid} if ok else None
            return mock_cursor
        if "FROM AGENT_SESSIONS WHERE AGENT_ID = 'ORCHESTRATOR'" in query_norm:
            if "CONTINUES_SESSION_ID" in query_norm:
                found = [r for r in _orch_rows() if _payload_of(r).get("continues_session_id") == params[0]]
            else:
                found = [r for r in _orch_rows() if _payload_of(r).get("project_id") == params[0]]
            found.sort(key=lambda r: str(r["created_at"]), reverse=True)
            mock_cursor.fetchone.return_value = dict(found[0]) if found else None
            mock_cursor.fetchall.return_value = [dict(r) for r in found[: params[1] if len(params) > 1 else None]]
            return mock_cursor
        # v18.5-egress-gate — registro de egresso (INSERT e soma de bytes novos por sessão).
        if "INSERT INTO EGRESS_LOG" in query_norm:
            db_state[f"egress_{params[0]}"] = {
                "id": params[0], "session_id": params[1], "canal": params[3],
                "bytes_saida_execucao_novos": params[12], "recusado": params[15],
            }
            return mock_cursor
        if "FROM EGRESS_LOG" in query_norm:
            rows = [r for k, r in db_state.items() if k.startswith("egress_") and r["session_id"] == params[0]]
            mock_cursor.fetchone.return_value = {"total": sum(r["bytes_saida_execucao_novos"] for r in rows)}
            return mock_cursor
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
    
    # Patches opcionais (Search Deep e Doc Processor)
    try:
        from src.skills import _HAS_DEEP_SEARCH
        if _HAS_DEEP_SEARCH:
            patches.append(patch("src.skills.search_deep.cache.get_connection", return_value=ctx))
    except (ImportError, AttributeError):
        pass

    try:
        from src.skills import _HAS_DOC_PROCESSOR
        if _HAS_DOC_PROCESSOR:
            patches.append(patch("src.skills.document_processor.indexer.get_connection", return_value=ctx))
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


# Hosts dos provedores LLM pagos: nenhum teste pode alcançá-los (créditos só para o benchmark).
_PAID_LLM_HOSTS = ("api.openai.com", "api.anthropic.com", "googleapis.com")


@pytest.fixture(autouse=True)
def block_paid_llm_network(request, monkeypatch):
    """Falha qualquer teste que tente abrir conexão com a API de um provedor LLM pago.

    A resolução de DNS é o ponto comum de todos os clientes (httpx, SDKs, requests). Os dublês
    (``respx``, SDK simulado) não resolvem DNS, então continuam funcionando. Testes ``e2e``
    marcados explicitamente podem usar a rede.
    """
    if request.node.get_closest_marker("e2e"):
        return
    import socket

    real_getaddrinfo = socket.getaddrinfo

    def guarded(host, *args, **kwargs):
        if isinstance(host, str) and host.endswith(_PAID_LLM_HOSTS):
            raise AssertionError(f"Teste tentou acessar a API paga '{host}'; simule o provedor (gasta créditos).")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


@pytest.fixture(autouse=True)
def reset_egress_state(tmp_path_factory, monkeypatch):
    """Zera o portão ``sem_sessao`` e o vínculo de portão entre testes (v18.5-egress-gate).

    A cópia local do portão ``sem_sessao`` vai para um diretório temporário (nunca para ``outputs/`` do repositório).
    """
    from src import config as app_config
    from src.egress import gate as egress_gate

    # Testes que recarregam `src.config` com o ambiente limpo não podem deixar o k indefinido para os demais.
    monkeypatch.setattr(app_config, "LOCALITY_MIN_GROUP_SIZE", 10)
    egress_gate.fallback_output_dir = tmp_path_factory.mktemp("egress_sem_sessao")
    egress_gate.reset_fallback_gate()
    egress_gate.bind_gate_for_tests(None)
    yield
    egress_gate.reset_fallback_gate()
    egress_gate.bind_gate_for_tests(None)


_ROUTING_ENV_PREFIXES = ("RESEARCHER", "DEVELOPER", "REVIEWER", "SUMMARIZER", "VALIDATOR", "BASE", "PLANNER")
_REMOVED_LLM_VARS = ("LLM_PROVIDER", "LLM_MODEL", "DEFAULT_MODEL", "AGENT_MODEL")


class _AlwaysHealthyProvider:
    """Dublê do provedor no health check: nunca toca a rede."""

    async def check_availability(self):
        return None


@pytest.fixture(autouse=True)
def isolate_model_routing(monkeypatch):
    """Isola o roteador de modelos (ADR 017) do ambiente e da rede.

    - remove do ambiente os pins ``{PAPEL}_MODEL``/``{PAPEL}_PROVIDER`` e as variáveis removidas
      (um ``.env`` real não pode alterar a resolução nos testes);
    - troca o provedor real do health check por um dublê sempre saudável (nenhum teste faz
      chamada de rede a provedor);
    - limpa o catálogo em cache e o aviso único de variáveis removidas.
    """
    for prefix in _ROUTING_ENV_PREFIXES:
        monkeypatch.delenv(f"{prefix}_MODEL", raising=False)
        monkeypatch.delenv(f"{prefix}_PROVIDER", raising=False)
    for name in _REMOVED_LLM_VARS:
        monkeypatch.delenv(name, raising=False)

    from src.llm import availability, routing, session

    monkeypatch.setattr(availability, "default_provider_factory", lambda provider, model: _AlwaysHealthyProvider())
    session.clear_catalog_cache()
    routing.reset_removed_variables_warning()
    yield
    session.clear_catalog_cache()
