import asyncio
import docker
import os
import functools
from pathlib import Path
from typing import Any
from src.logger import get_logger
from src.config import AGENT_TIMEOUT_SECONDS

logger = get_logger(__name__)

# Diretório base para sockets IPC
IPC_SOCKET_DIR = "/tmp/geminiclaw-ipc"


class ContainerRunner:
    """Gerencia o ciclo de vida de containers Docker para agentes."""

    def __init__(self, semaphore_limit: int = 3):
        """Inicializa o runner com um limite de concorrência.

        Args:
            semaphore_limit: Número máximo de containers simultâneos.
        """
        try:
            self.client = docker.from_env()
        except Exception as e:
            logger.error("Erro ao conectar ao Docker", extra={"event": "docker_connection_error", "error": str(e)})
            raise RuntimeError("Não foi possível conectar ao daemon do Docker.") from e
        
        self.semaphore = asyncio.Semaphore(semaphore_limit)

    async def spawn(self, agent_id: str, image: str, session_id: str) -> str:
        """Cria e inicia um container para um agente.

        Args:
            agent_id: Identificador do agente.
            image: Nome da imagem Docker.
            session_id: ID da sessão associada.

        Returns:
            O ID do container criado.
        """
        async with self.semaphore:
            logger.info("Iniciando container para agente", extra={"agent_id": agent_id, "image": image, "session_id": session_id})
            
            try:
                # Execução em thread separada para não bloquear o loop de eventos
                loop = asyncio.get_running_loop()
                
                # Prepara o caminho do socket IPC para este container
                # Usa agent_id + session_id para garantir unicidade
                socket_name = f"{agent_id}_{session_id}.sock"
                host_socket_path = str(Path(IPC_SOCKET_DIR) / socket_name)

                # Prepara caminhos para volume
                db_path_host = os.environ.get("SQLITE_DB_PATH", "store/geminiclaw.db")
                db_dir_host = str(Path(db_path_host).parent.absolute())
                
                # Parâmetros para a execução do container
                run_kwargs: dict[str, Any] = {
                    "image": image,
                    "mem_limit": "512m",
                    "nano_cpus": 1_000_000_000,
                    "network": "geminiclaw-net",
                    "user": "appuser",
                    "remove": True,
                    "detach": True,
                    "labels": {"project": "geminiclaw", "agent_id": agent_id, "session_id": session_id},
                    "environment": {
                        "SESSION_ID": session_id,
                        "AGENT_ID": agent_id,
                        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
                        "SQLITE_DB_PATH": "/data/geminiclaw.db",
                    },
                    "volumes": {
                        host_socket_path: {
                            "bind": "/tmp/geminiclaw-ipc/agent.sock",
                            "mode": "rw",
                        },
                        db_dir_host: {
                            "bind": "/data",
                            "mode": "rw",
                        }
                    },
                }
                
                def _run(*args: Any, **kwargs: Any) -> Any:
                    return self.client.containers.run(**run_kwargs)

                container = await loop.run_in_executor(None, _run)
                
                logger.info("Container iniciado com sucesso", extra={"container_id": container.id, "agent_id": agent_id})
                return str(container.id)

            except Exception as e:
                logger.error("Falha ao spawnar container", extra={"agent_id": agent_id, "error": str(e)})
                raise

        raise RuntimeError("Faixa de código inalcançável atingida em spawn.")


    async def stop(self, container_id: str) -> None:
        """Encerra um container específico.

        Args:
            container_id: ID do container.
        """
        try:
            loop = asyncio.get_running_loop()
            
            def _get_and_stop(cid: str) -> None:
                c = self.client.containers.get(cid)
                c.stop()

            await loop.run_in_executor(None, _get_and_stop, container_id)
            logger.info("Container encerrado", extra={"container_id": container_id})
        except Exception as e:
            logger.warning("Falha ao encerrar container", extra={"container_id": container_id, "error": str(e)})

    def cleanup_all(self) -> None:
        """Remove todos os containers do projeto geminiclaw."""
        try:
            containers = self.client.containers.list(filters={"label": "project=geminiclaw"}, all=True)
            for container in containers:
                try:
                    container.stop()
                    logger.info("Cleanup: container interrompido", extra={"container_id": container.id})
                except Exception:
                    pass
            logger.info("Cleanup concluído", extra={"count": len(containers)})
        except Exception as e:
            logger.error("Erro durante o cleanup", extra={"error": str(e)})
