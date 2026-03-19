import pytest
import asyncio
import struct
import json
import tempfile
import socket
import os
from pathlib import Path

from src.ipc import (
    Message,
    IPCChannel,
    create_message,
    HEADER_SIZE,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_roundtrip_loopback_full() -> None:
    """Teste de integração round-trip completo: host envia → client recebe → client responde → host recebe.

    Simula o papel do container com um client local conectando
    ao Unix socket do host. Valida o fluxo completo sem Docker.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        channel = IPCChannel(socket_dir=tmpdir)
        container_id = "integration_roundtrip"

        # Host cria o socket
        await channel.create_socket(container_id)
        socket_path = channel._socket_path(container_id)

        # Simula container: conecta ao socket
        client_reader, client_writer = await asyncio.open_unix_connection(socket_path)

        # Aguarda o host registrar a conexão
        await channel.wait_for_connection(container_id, timeout=5.0)

        # 1. Host → Client: envia request
        request = create_message("request", "sess_int", {"prompt": "Olá, agente!"})
        await channel.send(container_id, request)

        # 2. Client recebe o request
        header_bytes = await client_reader.readexactly(HEADER_SIZE)
        msg_length = struct.unpack(">I", header_bytes)[0]
        body = await client_reader.readexactly(msg_length)
        received_request = Message.deserialize(body)

        assert received_request.type == "request"
        assert received_request.session_id == "sess_int"
        assert received_request.payload["prompt"] == "Olá, agente!"

        # 3. Client → Host: envia response (echo com dados processados)
        response = create_message(
            "response",
            received_request.session_id,
            {"answer": f"Recebi: {received_request.payload['prompt']}"},
        )
        client_writer.write(response.serialize())
        await client_writer.drain()

        # 4. Host recebe a response
        host_response = await channel.receive(container_id, timeout=5.0)

        assert host_response.type == "response"
        assert host_response.session_id == "sess_int"
        assert host_response.payload["answer"] == "Recebi: Olá, agente!"

        # Cleanup
        client_writer.close()
        await channel.close(container_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_containers_concurrent_roundtrip() -> None:
    """Testa comunicação simultânea com múltiplos containers isolados."""
    with tempfile.TemporaryDirectory() as tmpdir:
        channel = IPCChannel(socket_dir=tmpdir)

        container_ids = ["container_a", "container_b", "container_c"]
        clients: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}

        # Cria sockets para todos os containers
        for cid in container_ids:
            await channel.create_socket(cid)
            socket_path = channel._socket_path(cid)
            reader, writer = await asyncio.open_unix_connection(socket_path)
            clients[cid] = (reader, writer)
            await channel.wait_for_connection(cid, timeout=5.0)

        # Host envia mensagem diferente para cada container
        for i, cid in enumerate(container_ids):
            msg = create_message("request", f"sess_{i}", {"index": i})
            await channel.send(cid, msg)

        # Cada client recebe sua mensagem e responde
        for i, cid in enumerate(container_ids):
            reader, writer = clients[cid]

            header = await reader.readexactly(HEADER_SIZE)
            length = struct.unpack(">I", header)[0]
            body = await reader.readexactly(length)
            received = Message.deserialize(body)

            assert received.payload["index"] == i

            # Client responde
            resp = create_message("response", received.session_id, {"echo": i})
            writer.write(resp.serialize())
            await writer.drain()

        # Host recebe todas as respostas
        for i, cid in enumerate(container_ids):
            response = await channel.receive(cid, timeout=5.0)
            assert response.type == "response"
            assert response.payload["echo"] == i

        # Cleanup
        for cid in container_ids:
            _, writer = clients[cid]
            writer.close()
        await channel.close_all()
