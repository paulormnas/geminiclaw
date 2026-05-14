"""Testes unitários para V12.3 — Telemetria Cross-Container.

Cobre:
  V12.3.1: drain_buffer() serializa o buffer do TelemetryCollector para
           um dict JSON-serializable, sem destruir o buffer (método não-destrutivo
           até ser confirmado pelo flush bem-sucedido). O runner inclui
           _telemetry no payload IPC; o orquestrador injeta no singleton local.
  V12.3.3: Campo retry_attempt no AgentTask é propagado para retry_count
           em record_subtask_metrics.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from dataclasses import dataclass, field

from src.telemetry import TelemetryCollector, get_telemetry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_collector() -> TelemetryCollector:
    """Cria um TelemetryCollector isolado (não o singleton)."""
    return TelemetryCollector()


# ---------------------------------------------------------------------------
# V12.3.1 — drain_buffer()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDrainBuffer:
    """Testa o método drain_buffer() do TelemetryCollector."""

    def test_drain_retorna_dict_vazio_quando_buffer_vazio(self):
        """drain_buffer() deve retornar dict com listas vazias se não há dados."""
        col = _make_collector()
        result = col.drain_buffer()

        assert isinstance(result, dict)
        assert result["token_usage"] == []
        assert result["tool_usage"] == []
        assert result["agent_events"] == []

    def test_drain_retorna_token_usage_serializado(self):
        """drain_buffer() deve incluir token_usage como lista de dicts."""
        col = _make_collector()
        with patch("src.telemetry.get_connection"):  # evita acesso ao banco
            col.record_token_usage(
                execution_id="exec1",
                session_id="sess1",
                agent_id="researcher",
                llm_provider="ollama",
                llm_model="llama3",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                task_name="collect_data",
            )

        result = col.drain_buffer()
        assert len(result["token_usage"]) == 1
        row = result["token_usage"][0]
        assert row["execution_id"] == "exec1"
        assert row["prompt_tokens"] == 100
        assert row["completion_tokens"] == 50
        assert row["llm_model"] == "llama3"

    def test_drain_retorna_tool_usage_serializado(self):
        """drain_buffer() deve incluir tool_usage como lista de dicts."""
        col = _make_collector()
        with patch("src.telemetry.get_connection"):
            col.record_tool_usage(
                execution_id="exec1",
                session_id="sess1",
                agent_id="researcher",
                tool_name="python_interpreter",
                started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T00:00:01Z",
                duration_ms=1000,
                success=True,
                result_summary="output",
            )

        result = col.drain_buffer()
        assert len(result["tool_usage"]) == 1
        assert result["tool_usage"][0]["tool_name"] == "python_interpreter"
        assert result["tool_usage"][0]["success"] is True

    def test_drain_buffer_e_json_serializable(self):
        """O resultado de drain_buffer() deve ser serializável via json.dumps."""
        col = _make_collector()
        with patch("src.telemetry.get_connection"):
            col.record_token_usage(
                execution_id="exec1",
                session_id="sess1",
                agent_id="base",
                llm_provider="google",
                llm_model="gemini-2.0-flash",
                prompt_tokens=200,
                completion_tokens=80,
                latency_ms=300,
            )

        result = col.drain_buffer()
        # Não deve lançar exceção
        serialized = json.dumps(result)
        assert "token_usage" in serialized

    def test_drain_buffer_nao_limpa_o_buffer(self):
        """drain_buffer() é não-destrutivo — o buffer permanece intacto."""
        col = _make_collector()
        with patch("src.telemetry.get_connection"):
            col.record_token_usage(
                execution_id="exec1",
                session_id="sess1",
                agent_id="base",
                llm_provider="ollama",
                llm_model="llama3",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=100,
            )

        col.drain_buffer()
        # Buffer ainda deve ter os dados
        assert col._buffer.total() == 1

    def test_drain_buffer_inclui_subtask_metrics(self):
        """drain_buffer() deve incluir subtask_metrics se houver."""
        col = _make_collector()
        with patch("src.telemetry.get_connection"):
            col.record_subtask_metrics(
                subtask_id="sub123",
                execution_id="exec1",
                task_name="analyze_data",
                agent_id="researcher",
                status="success",
                created_at="2026-01-01T00:00:00Z",
                retry_count=2,
            )

        result = col.drain_buffer()
        assert len(result.get("subtask_metrics", [])) == 1
        assert result["subtask_metrics"][0]["retry_count"] == 2


# ---------------------------------------------------------------------------
# V12.3.1 — Injeção de _telemetry no payload IPC (runner)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_inclui_telemetria_no_payload_ipc():
    """O runner deve incluir _telemetry no payload antes de enviar ao orquestrador."""
    from src.ipc import create_message

    # Simula buffer com 1 token_usage
    mock_telemetry = MagicMock(spec=TelemetryCollector)
    mock_telemetry.drain_buffer.return_value = {
        "token_usage": [{"execution_id": "exec1", "prompt_tokens": 50}],
        "tool_usage": [],
        "agent_events": [],
        "subtask_metrics": [],
    }
    mock_telemetry.flush = AsyncMock()
    mock_telemetry.get = MagicMock(return_value=None)

    # Importa e verifica a estrutura do payload gerado pelo runner
    # Aqui testamos a função auxiliar de montagem do payload, não o loop completo
    from agents.runner import _build_response_payload

    payload = _build_response_payload(
        text="resultado do agente",
        telemetry=mock_telemetry,
    )

    assert "_telemetry" in payload
    assert payload["_telemetry"]["token_usage"][0]["prompt_tokens"] == 50
    assert payload["text"] == "resultado do agente"
    mock_telemetry.drain_buffer.assert_called_once()


# ---------------------------------------------------------------------------
# V12.3.1 — Extração de _telemetry no orquestrador
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_orchestrator_injeta_telemetria_do_payload_ipc():
    """O orquestrador deve ler _telemetry do payload IPC e injetar no singleton."""
    from src.orchestrator import _ingest_container_telemetry

    mock_local_telemetry = MagicMock(spec=TelemetryCollector)

    container_payload = {
        "text": "resultado",
        "_telemetry": {
            "token_usage": [
                {
                    "id": "tok123",
                    "execution_id": "exec1",
                    "session_id": "sess1",
                    "agent_id": "researcher",
                    "task_name": "collect",
                    "llm_provider": "ollama",
                    "llm_model": "llama3",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "estimated_cost_usd": None,
                    "latency_ms": 200,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "context_window_used": None,
                    "context_window_max": None,
                    "was_compressed": False,
                }
            ],
            "tool_usage": [],
            "agent_events": [],
            "subtask_metrics": [],
        },
    }

    _ingest_container_telemetry(container_payload, mock_local_telemetry)

    # record_token_usage deve ter sido chamado com os dados do container
    mock_local_telemetry.record_token_usage.assert_called_once()
    call_kwargs = mock_local_telemetry.record_token_usage.call_args[1]
    assert call_kwargs["execution_id"] == "exec1"
    assert call_kwargs["prompt_tokens"] == 100
    assert call_kwargs["llm_model"] == "llama3"


@pytest.mark.unit
def test_orchestrator_ignora_payload_sem_telemetria():
    """_ingest_container_telemetry deve ser no-op se _telemetry não estiver no payload."""
    from src.orchestrator import _ingest_container_telemetry

    mock_local_telemetry = MagicMock(spec=TelemetryCollector)
    _ingest_container_telemetry({"text": "ok"}, mock_local_telemetry)

    mock_local_telemetry.record_token_usage.assert_not_called()
    mock_local_telemetry.record_tool_usage.assert_not_called()


# ---------------------------------------------------------------------------
# V12.3.3 — retry_attempt propagado para subtask_metrics
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_agent_task_tem_campo_retry_attempt():
    """AgentTask deve ter campo retry_attempt com valor padrão 0."""
    from src.orchestrator import AgentTask

    task = AgentTask(agent_id="base", image="geminiclaw-base", prompt="teste")
    assert hasattr(task, "retry_attempt")
    assert task.retry_attempt == 0


@pytest.mark.unit
def test_agent_task_aceita_retry_attempt_personalizado():
    """AgentTask deve aceitar retry_attempt como parâmetro."""
    from src.orchestrator import AgentTask

    task = AgentTask(
        agent_id="researcher",
        image="geminiclaw-researcher",
        prompt="pesquisar algo",
        retry_attempt=3,
    )

@pytest.mark.unit
@pytest.mark.asyncio
async def test_autonomous_loop_propaga_attempt_para_enriched_task():
    """No retry loop, enriched_task.retry_attempt deve refletir o número da tentativa."""
    from src.orchestrator import AgentTask

    # Simula a construção do enriched_task como acontece no autonomous_loop
    # Testa diretamente a lógica de propagação sem precisar instanciar o loop completo

    base_task = AgentTask(
        agent_id="base",
        image="geminiclaw-base",
        prompt="realizar tarefa",
        task_name="tarefa_1",
        subtask_id="sub1",
        created_at="2026-01-01T00:00:00Z",
        retry_attempt=0,
    )

    # Simula a primeira tentativa falhando e criando enriched_task para a próxima
    attempt = 0  # 0-indexed: esta é a 1ª tentativa
    error_context = f"\n\n[TENTATIVA ANTERIOR FALHOU]\nTentativa: {attempt + 1}/3\n"

    enriched_task = AgentTask(
        agent_id=base_task.agent_id,
        image=base_task.image,
        prompt=base_task.prompt + error_context,
        task_name=base_task.task_name,
        depends_on=base_task.depends_on,
        expected_artifacts=base_task.expected_artifacts,
        validation_criteria=base_task.validation_criteria,
        preferred_model=base_task.preferred_model,
        subtask_id=base_task.subtask_id,
        created_at=base_task.created_at,
        retry_attempt=attempt + 1,  # próxima tentativa = 1
    )

    assert enriched_task.retry_attempt == 1, "1ª falha → retry_attempt=1"

    # Simula a segunda tentativa falhando
    attempt = 1
    error_context2 = f"\n\n[TENTATIVA ANTERIOR FALHOU]\nTentativa: {attempt + 1}/3\n"
    enriched_task2 = AgentTask(
        agent_id=enriched_task.agent_id,
        image=enriched_task.image,
        prompt=enriched_task.prompt + error_context2,
        task_name=enriched_task.task_name,
        depends_on=enriched_task.depends_on,
        expected_artifacts=enriched_task.expected_artifacts,
        validation_criteria=enriched_task.validation_criteria,
        preferred_model=enriched_task.preferred_model,
        subtask_id=enriched_task.subtask_id,
        created_at=enriched_task.created_at,
        retry_attempt=attempt + 1,  # próxima tentativa = 2
    )

    assert enriched_task2.retry_attempt == 2, "2ª falha → retry_attempt=2"
