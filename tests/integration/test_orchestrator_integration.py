import pytest
import asyncio
import struct
import tempfile
import os
from unittest.mock import MagicMock, AsyncMock, patch

from src.orchestrator import Orchestrator, AgentTask
from src.session import SessionManager
from src.ipc import IPCChannel, Message, create_message, HEADER_SIZE


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orchestrator_single_agent_flow() -> None:
    """Teste de integração: fluxo completo com IPC real (loopback) sem Docker.

    Simula o papel do container com uma coroutine local que conecta ao socket,
    recebe o prompt, e envia uma resposta.
    """
    # Usa /tmp diretamente com nome curto para evitar AF_UNIX path too long
    ipc_dir = tempfile.mkdtemp(prefix="gc_", dir="/tmp")
    db_dir = tempfile.mkdtemp(prefix="gcdb_", dir="/tmp")
    output_dir = tempfile.mkdtemp(prefix="gcout_", dir="/tmp")

    try:
        ipc = IPCChannel(socket_dir=ipc_dir, use_tcp=False)
        db_path = f"{db_dir}/test.db"
        session_manager = SessionManager(db_path=db_path)
        
        from src.output_manager import OutputManager
        output_manager = OutputManager(base_dir=output_dir)

        mock_runner = MagicMock()
        mock_runner.spawn = AsyncMock()
        mock_runner.stop = AsyncMock()
        mock_runner.is_running = AsyncMock(return_value=True)
        mock_runner.get_logs = AsyncMock(return_value="logs")

        orchestrator = Orchestrator(
            runner=mock_runner,
            ipc=ipc,
            session_manager=session_manager,
            output_manager=output_manager,
        )

        task = AgentTask(
            agent_id="ag1",
            image="geminiclaw-base",
            prompt="Qual é a resposta para tudo?",
        )

        async def fake_container(session_id: str, output_session_id: str) -> None:
            """Simula o container: conecta ao socket, recebe request, envia response e gera artefato."""
            ipc_id = f"ag1_{session_id}"
            socket_path = ipc._socket_path(ipc_id)

            # Aguarda o socket ser criado
            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                await asyncio.sleep(0.05)

            # Conecta ao socket
            reader, writer = await asyncio.open_unix_connection(socket_path)

            # Simula a escrita de um artefato no "volume" associado à sessão
            # No teste, usamos o output_session_id (mestra) se fornecido
            task_dir = output_manager.get_task_dir(output_session_id, "ag1")
            (task_dir / "result.txt").write_text("Resposta final: 42")

            # Recebe o request
            header = await reader.readexactly(HEADER_SIZE)
            length = struct.unpack(">I", header)[0]
            body = await reader.readexactly(length)
            received = Message.deserialize(body)

            assert received.type == "request"
            assert received.payload["prompt"] == "Qual é a resposta para tudo?"

            # Envia response
            response = create_message(
                "response",
                received.session_id,
                {"answer": "42", "source": "Douglas Adams"},
            )
            writer.write(response.serialize())
            await writer.drain()
            writer.close()

        # Mock do runner.spawn que inicia o "container" fake
        async def fake_spawn(agent_id: str, image: str, session_id: str, ipc_port: int | None = None, output_session_id: str | None = None, logs_session_id: str | None = None) -> str:
            asyncio.create_task(fake_container(session_id, output_session_id or session_id))
            return "fake_container_id"

        mock_runner.spawn = AsyncMock(side_effect=fake_spawn)

        # Executa o orquestrador
        result = await orchestrator.handle_request(
            "Qual é a resposta para tudo?", [task]
        )

        # Validações
        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.results[0].status == "success"
        assert result.results[0].response["answer"] == "42"
        assert result.results[0].response["source"] == "Douglas Adams"
        assert result.results[0].agent_id == "ag1"

        # Verifica se o artefato foi listado
        assert len(result.artifacts) == 1
        assert result.artifacts[0]["name"] == "result.txt"
        assert result.artifacts[0]["task"] == "ag1"

        # Verifica que a sessão foi criada e fechada
        session = session_manager.get(result.results[0].session_id)
        assert session is not None
        assert session.status == "closed"

    finally:
        # Cleanup dos diretórios temporários
        import shutil
        shutil.rmtree(ipc_dir, ignore_errors=True)
        shutil.rmtree(db_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
