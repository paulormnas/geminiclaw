import pytest
import asyncio
import struct
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, AsyncMock

from src.ipc import (
    Message,
    IPCChannel,
    create_message,
    VALID_MESSAGE_TYPES,
    HEADER_SIZE,
    MAX_RECONNECT_ATTEMPTS,
)


# ============================================================
# Testes do protocolo de mensagens
# ============================================================


@pytest.mark.unit
class TestMessageSerialization:
    """Testes de serialização e desserialização de Message."""

    def test_message_serialize_deserialize_roundtrip(self) -> None:
        """Message → bytes → Message deve preservar todos os campos."""
        original = Message(
            type="request",
            session_id="sess_123",
            payload={"key": "value", "number": 42},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        raw = original.serialize()

        # Extrai body sem header
        header = raw[:HEADER_SIZE]
        body = raw[HEADER_SIZE:]
        msg_length = struct.unpack(">I", header)[0]
        assert msg_length == len(body)

        restored = Message.deserialize(body)
        assert restored.type == original.type
        assert restored.session_id == original.session_id
        assert restored.payload == original.payload
        assert restored.timestamp == original.timestamp

    def test_message_serialize_length_prefix(self) -> None:
        """Verifica que o framing de 4 bytes big-endian está correto."""
        msg = Message(
            type="response",
            session_id="s1",
            payload={},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        raw = msg.serialize()

        # Primeiros 4 bytes = tamanho do JSON
        expected_json = json.dumps(
            {
                "type": "response",
                "session_id": "s1",
                "payload": {},
                "timestamp": "2025-01-01T00:00:00+00:00",
            },
            ensure_ascii=False,
        ).encode("utf-8")

        header = struct.unpack(">I", raw[:4])[0]
        assert header == len(expected_json)
        assert raw[4:] == expected_json

    def test_message_serialize_unicode(self) -> None:
        """Serialização deve suportar caracteres Unicode."""
        msg = Message(
            type="request",
            session_id="s1",
            payload={"mensagem": "olá, ação"},
            timestamp="2025-01-01T00:00:00+00:00",
        )
        raw = msg.serialize()
        body = raw[HEADER_SIZE:]
        restored = Message.deserialize(body)
        assert restored.payload["mensagem"] == "olá, ação"


@pytest.mark.unit
class TestMessageValidation:
    """Testes de validação dos campos de Message."""

    def test_message_required_fields_present(self) -> None:
        """Message deve conter todos os campos obrigatórios."""
        msg = create_message("request", "sess_1", {"data": True})
        assert msg.type == "request"
        assert msg.session_id == "sess_1"
        assert msg.payload == {"data": True}
        assert msg.timestamp  # não vazio

    def test_message_invalid_type_raises(self) -> None:
        """Tipo fora dos válidos deve lançar ValueError."""
        with pytest.raises(ValueError, match="Tipo de mensagem inválido"):
            Message(
                type="invalid_type",
                session_id="s1",
                payload={},
                timestamp="2025-01-01T00:00:00+00:00",
            )

    def test_message_empty_session_id_raises(self) -> None:
        """session_id vazio deve lançar ValueError."""
        with pytest.raises(ValueError, match="session_id não pode ser vazio"):
            Message(
                type="request",
                session_id="",
                payload={},
                timestamp="2025-01-01T00:00:00+00:00",
            )

    def test_all_valid_types_accepted(self) -> None:
        """Todos os tipos válidos devem ser aceitos sem erro."""
        for msg_type in VALID_MESSAGE_TYPES:
            msg = Message(
                type=msg_type,
                session_id="s1",
                payload={},
                timestamp="2025-01-01T00:00:00+00:00",
            )
            assert msg.type == msg_type

    def test_deserialize_missing_fields_raises(self) -> None:
        """Desserializar JSON sem campos obrigatórios deve lançar ValueError."""
        incomplete = json.dumps({"type": "request"}).encode("utf-8")
        with pytest.raises(ValueError, match="Campos obrigatórios ausentes"):
            Message.deserialize(incomplete)

    def test_deserialize_invalid_json_raises(self) -> None:
        """Desserializar bytes inválidos deve lançar ValueError."""
        with pytest.raises(ValueError, match="Falha ao desserializar"):
            Message.deserialize(b"not valid json")


@pytest.mark.unit
class TestCreateMessage:
    """Testes da função create_message."""

    def test_create_message_default_payload(self) -> None:
        """create_message sem payload deve usar dict vazio."""
        msg = create_message("heartbeat", "sess_1")
        assert msg.payload == {}
        assert msg.type == "heartbeat"
        assert msg.session_id == "sess_1"

    def test_create_message_with_payload(self) -> None:
        """create_message com payload deve preservá-lo."""
        msg = create_message("request", "sess_2", {"query": "test"})
        assert msg.payload == {"query": "test"}


# ============================================================
# Testes do IPCChannel (loopback local, sem container)
# ============================================================


@pytest.mark.unit
@pytest.mark.asyncio
class TestIPCChannelLoopback:
    """Testes de envio e recepção via socket local (sem container)."""

    async def test_send_receive_loopback(self) -> None:
        """Envia e recebe uma mensagem via socket Unix local."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)
            container_id = "test_container"

            await channel.create_socket(container_id)
            socket_path = channel._socket_path(container_id)

            # Simula o client (container) conectando ao socket
            reader, writer = await asyncio.open_unix_connection(socket_path)

            # Host envia mensagem
            msg = create_message("request", "sess_1", {"action": "echo"})
            await channel.send(container_id, msg)

            # Client recebe a mensagem
            header = await reader.readexactly(HEADER_SIZE)
            length = struct.unpack(">I", header)[0]
            body = await reader.readexactly(length)
            received = Message.deserialize(body)

            assert received.type == "request"
            assert received.session_id == "sess_1"
            assert received.payload == {"action": "echo"}

            # Client envia resposta
            response = create_message("response", "sess_1", {"result": "ok"})
            response_data = response.serialize()
            writer.write(response_data)
            await writer.drain()

            # Host recebe resposta
            host_response = await channel.receive(container_id, timeout=5.0)
            assert host_response.type == "response"
            assert host_response.payload == {"result": "ok"}

            writer.close()
            await channel.close(container_id)

    async def test_receive_timeout(self) -> None:
        """receive() deve lançar TimeoutError quando o timeout expirar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)
            container_id = "timeout_test"

            await channel.create_socket(container_id)
            socket_path = channel._socket_path(container_id)

            # Client conecta mas não envia nada
            reader, writer = await asyncio.open_unix_connection(socket_path)
            await channel.wait_for_connection(container_id, timeout=5.0)

            with pytest.raises(TimeoutError):
                await channel.receive(container_id, timeout=0.5)

            writer.close()
            await channel.close(container_id)

    async def test_create_duplicate_socket_raises(self) -> None:
        """Criar socket duplicado para o mesmo container deve lançar RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)
            container_id = "dup_test"

            await channel.create_socket(container_id)

            with pytest.raises(RuntimeError, match="Socket já existe"):
                await channel.create_socket(container_id)

            await channel.close(container_id)

    async def test_send_without_connection_raises(self) -> None:
        """send() sem conexão ativa deve lançar ConnectionError após tentativas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)
            msg = create_message("request", "s1")

            with pytest.raises(ConnectionError, match="Falha ao enviar mensagem"):
                await channel.send("nonexistent", msg)

    async def test_close_removes_socket_file(self) -> None:
        """close() deve remover o arquivo de socket."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)
            container_id = "cleanup_test"

            await channel.create_socket(container_id)
            socket_path = channel._socket_path(container_id)
            assert os.path.exists(socket_path)

            await channel.close(container_id)
            assert not os.path.exists(socket_path)

    async def test_close_all(self) -> None:
        """close_all() deve fechar todos os sockets ativos."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)

            await channel.create_socket("c1")
            await channel.create_socket("c2")
            assert len(channel._servers) == 2

            await channel.close_all()
            assert len(channel._servers) == 0
            assert len(channel._connections) == 0

    async def test_multiple_containers_isolated(self) -> None:
        """Múltiplos containers devem ter sockets isolados."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)

            await channel.create_socket("c1")
            await channel.create_socket("c2")

            path1 = channel._socket_path("c1")
            path2 = channel._socket_path("c2")

            assert path1 != path2
            assert os.path.exists(path1)
            assert os.path.exists(path2)

            await channel.close_all()

    async def test_length_prefix_framing_integrity(self) -> None:
        """Verifica integridade do length-prefix com múltiplas mensagens consecutivas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            channel = IPCChannel(socket_dir=tmpdir)
            container_id = "framing_test"

            await channel.create_socket(container_id)
            socket_path = channel._socket_path(container_id)

            # Client conecta
            client_reader, client_writer = await asyncio.open_unix_connection(socket_path)
            await channel.wait_for_connection(container_id, timeout=5.0)

            # Host envia múltiplas mensagens seguidas
            msgs = [
                create_message("request", "s1", {"idx": 0}),
                create_message("request", "s1", {"idx": 1}),
                create_message("heartbeat", "s1"),
            ]
            for msg in msgs:
                await channel.send(container_id, msg)

            # Client lê todas as mensagens em sequência
            received = []
            for _ in range(3):
                header = await client_reader.readexactly(HEADER_SIZE)
                length = struct.unpack(">I", header)[0]
                body = await client_reader.readexactly(length)
                received.append(Message.deserialize(body))

            assert received[0].payload == {"idx": 0}
            assert received[1].payload == {"idx": 1}
            assert received[2].type == "heartbeat"

            client_writer.close()
            await channel.close(container_id)
