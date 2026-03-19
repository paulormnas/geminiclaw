import asyncio
import json
import struct
import datetime
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from src.logger import get_logger

logger = get_logger(__name__)

# Tipos de mensagem válidos
VALID_MESSAGE_TYPES = frozenset({"request", "response", "error", "heartbeat"})

# Tamanho do header de framing (4 bytes, big-endian unsigned int)
HEADER_SIZE = 4

# Configurações de reconexão
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_BASE_DELAY = 0.5  # segundos


@dataclass
class Message:
    """Mensagem do protocolo IPC entre host e container.

    Args:
        type: Tipo da mensagem ("request", "response", "error", "heartbeat").
        session_id: ID da sessão associada.
        payload: Dados arbitrários da mensagem.
        timestamp: Timestamp ISO 8601 UTC.
    """

    type: str
    session_id: str
    payload: dict[str, Any]
    timestamp: str

    def __post_init__(self) -> None:
        """Valida os campos da mensagem após criação."""
        if self.type not in VALID_MESSAGE_TYPES:
            raise ValueError(
                f"Tipo de mensagem inválido: '{self.type}'. "
                f"Tipos válidos: {sorted(VALID_MESSAGE_TYPES)}"
            )
        if not self.session_id:
            raise ValueError("session_id não pode ser vazio.")

    def serialize(self) -> bytes:
        """Serializa a mensagem para bytes com length-prefix.

        Returns:
            Bytes contendo 4 bytes de tamanho (big-endian) + JSON payload.
        """
        json_bytes = json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")
        header = struct.pack(">I", len(json_bytes))
        return header + json_bytes

    @classmethod
    def deserialize(cls, data: bytes) -> "Message":
        """Desserializa bytes (sem header) em um objeto Message.

        Args:
            data: Bytes contendo o JSON da mensagem (sem o header de tamanho).

        Returns:
            Objeto Message reconstruído.

        Raises:
            ValueError: Se os dados forem inválidos.
        """
        try:
            obj = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Falha ao desserializar mensagem: {e}") from e

        required_fields = {"type", "session_id", "payload", "timestamp"}
        missing = required_fields - set(obj.keys())
        if missing:
            raise ValueError(f"Campos obrigatórios ausentes: {missing}")

        return cls(
            type=obj["type"],
            session_id=obj["session_id"],
            payload=obj["payload"],
            timestamp=obj["timestamp"],
        )


def create_message(
    msg_type: str, session_id: str, payload: dict[str, Any] | None = None
) -> Message:
    """Cria uma nova mensagem com timestamp automático.

    Args:
        msg_type: Tipo da mensagem.
        session_id: ID da sessão.
        payload: Dados opcionais.

    Returns:
        Objeto Message com timestamp UTC atual.
    """
    return Message(
        type=msg_type,
        session_id=session_id,
        payload=payload or {},
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


class IPCChannel:
    """Canal de comunicação IPC via Unix Domain Sockets.

    O host opera como server (bind + listen) e o container como client (connect).
    Cada container tem seu próprio socket isolado.
    """

    def __init__(self, socket_dir: str = "/tmp/geminiclaw-ipc") -> None:
        """Inicializa o canal IPC.

        Args:
            socket_dir: Diretório base para os arquivos de socket.
        """
        self.socket_dir = Path(socket_dir)
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        self._servers: dict[str, asyncio.AbstractServer] = {}
        self._connections: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}

    def _socket_path(self, container_id: str) -> str:
        """Retorna o caminho do socket para um container.

        Args:
            container_id: ID do container.

        Returns:
            Caminho absoluto do arquivo de socket.
        """
        return str(self.socket_dir / f"{container_id}.sock")

    async def create_socket(self, container_id: str) -> None:
        """Cria um Unix Domain Socket e aguarda a conexão do container.

        Args:
            container_id: ID do container que se conectará.

        Raises:
            RuntimeError: Se já existir um socket para este container.
        """
        if container_id in self._servers:
            raise RuntimeError(f"Socket já existe para container '{container_id}'.")

        socket_path = self._socket_path(container_id)

        # Remove socket antigo se existir (caso de crash anterior)
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        # Evento para sinalizar quando o client conectar
        connected_event = asyncio.Event()

        async def _on_client_connected(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            self._connections[container_id] = (reader, writer)
            logger.info(
                "Container conectado ao IPC",
                extra={"container_id": container_id, "socket": socket_path},
            )
            connected_event.set()

        server = await asyncio.start_unix_server(
            _on_client_connected, path=socket_path
        )

        # Ajusta permissões para que o appuser no container consiga acessar
        os.chmod(socket_path, 0o777)

        self._servers[container_id] = server
        logger.info(
            "Socket IPC criado",
            extra={"container_id": container_id, "socket": socket_path},
        )

    async def wait_for_connection(self, container_id: str, timeout: float | None = None) -> None:
        """Aguarda a conexão do container ao socket.

        Args:
            container_id: ID do container.
            timeout: Tempo máximo de espera em segundos.

        Raises:
            TimeoutError: Se o container não conectar dentro do timeout.
            KeyError: Se o socket não foi criado.
        """
        if container_id not in self._servers:
            raise KeyError(f"Socket não encontrado para container '{container_id}'.")

        # Aguarda até que a conexão seja estabelecida
        deadline = timeout or 30.0
        elapsed = 0.0
        interval = 0.1
        while container_id not in self._connections:
            if elapsed >= deadline:
                raise TimeoutError(
                    f"Container '{container_id}' não conectou dentro de {deadline}s."
                )
            await asyncio.sleep(interval)
            elapsed += interval

    async def send(self, container_id: str, message: Message) -> None:
        """Envia uma mensagem para o container.

        Args:
            container_id: ID do container.
            message: Mensagem a ser enviada.

        Raises:
            ConnectionError: Se falhar após todas as tentativas de reconexão.
        """
        data = message.serialize()

        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            try:
                reader, writer = self._get_connection(container_id)
                writer.write(data)
                await writer.drain()
                logger.info(
                    "Mensagem enviada via IPC",
                    extra={
                        "container_id": container_id,
                        "message_type": message.type,
                        "session_id": message.session_id,
                    },
                )
                return
            except (ConnectionError, OSError, BrokenPipeError) as e:
                logger.warning(
                    "Falha ao enviar mensagem, tentando reconexão",
                    extra={
                        "container_id": container_id,
                        "attempt": attempt + 1,
                        "max_attempts": MAX_RECONNECT_ATTEMPTS,
                        "error": str(e),
                    },
                )
                # Remove conexão falha
                self._connections.pop(container_id, None)

                if attempt < MAX_RECONNECT_ATTEMPTS - 1:
                    delay = RECONNECT_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)
                else:
                    raise ConnectionError(
                        f"Falha ao enviar mensagem para '{container_id}' "
                        f"após {MAX_RECONNECT_ATTEMPTS} tentativas."
                    ) from e

    async def receive(self, container_id: str, timeout: float = 30.0) -> Message:
        """Recebe uma mensagem do container.

        Args:
            container_id: ID do container.
            timeout: Tempo máximo de espera em segundos.

        Returns:
            Mensagem recebida.

        Raises:
            TimeoutError: Se não receber mensagem dentro do timeout.
            ConnectionError: Se falhar após todas as tentativas de reconexão.
        """
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            try:
                reader, writer = self._get_connection(container_id)

                # Lê o header de 4 bytes (tamanho da mensagem)
                header = await asyncio.wait_for(
                    reader.readexactly(HEADER_SIZE), timeout=timeout
                )
                msg_length = struct.unpack(">I", header)[0]

                # Lê o corpo da mensagem
                body = await asyncio.wait_for(
                    reader.readexactly(msg_length), timeout=timeout
                )

                message = Message.deserialize(body)
                logger.info(
                    "Mensagem recebida via IPC",
                    extra={
                        "container_id": container_id,
                        "message_type": message.type,
                        "session_id": message.session_id,
                    },
                )
                return message

            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Timeout ao aguardar mensagem do container '{container_id}' "
                    f"(limite: {timeout}s)."
                )
            except asyncio.IncompleteReadError as e:
                raise ConnectionError(
                    f"Conexão encerrada prematuramente pelo container '{container_id}'."
                ) from e
            except (ConnectionError, OSError, BrokenPipeError) as e:
                logger.warning(
                    "Falha ao receber mensagem, tentando reconexão",
                    extra={
                        "container_id": container_id,
                        "attempt": attempt + 1,
                        "max_attempts": MAX_RECONNECT_ATTEMPTS,
                        "error": str(e),
                    },
                )
                self._connections.pop(container_id, None)

                if attempt < MAX_RECONNECT_ATTEMPTS - 1:
                    delay = RECONNECT_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)
                else:
                    raise ConnectionError(
                        f"Falha ao receber mensagem de '{container_id}' "
                        f"após {MAX_RECONNECT_ATTEMPTS} tentativas."
                    ) from e

        # Inalcançável, mas satisfaz o type checker
        raise RuntimeError("Estado inalcançável em receive.")  # pragma: no cover

    def _get_connection(
        self, container_id: str
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Obtém a conexão ativa para um container.

        Args:
            container_id: ID do container.

        Returns:
            Tupla (reader, writer) da conexão.

        Raises:
            ConnectionError: Se não houver conexão ativa.
        """
        conn = self._connections.get(container_id)
        if conn is None:
            raise ConnectionError(
                f"Nenhuma conexão ativa para container '{container_id}'."
            )
        return conn

    async def close(self, container_id: str) -> None:
        """Fecha o socket e remove o arquivo para um container.

        Args:
            container_id: ID do container.
        """
        # Fecha a conexão do client
        conn = self._connections.pop(container_id, None)
        if conn:
            _, writer = conn
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        # Fecha o server
        server = self._servers.pop(container_id, None)
        if server:
            server.close()
            await server.wait_closed()

        # Remove o arquivo de socket
        socket_path = self._socket_path(container_id)
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        logger.info(
            "Socket IPC fechado",
            extra={"container_id": container_id},
        )

    async def close_all(self) -> None:
        """Fecha todos os sockets ativos."""
        container_ids = list(self._servers.keys())
        for container_id in container_ids:
            await self.close(container_id)
        logger.info("Todos os sockets IPC fechados", extra={"count": len(container_ids)})
