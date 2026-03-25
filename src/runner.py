import asyncio
import docker
import os
import functools
from pathlib import Path
from typing import Any
from src.logger import get_logger
from src.config import AGENT_TIMEOUT_SECONDS, DEFAULT_MODEL

logger = get_logger(__name__)

# Diretório base para sockets IPC
_root = Path(__file__).parent.parent
IPC_SOCKET_DIR = str((_root / "store" / "ipc").absolute())


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
        self._ensure_network()

    def _ensure_network(self) -> None:
        """Garante que a rede geminiclaw-net existe."""
        try:
            self.client.networks.get("geminiclaw-net")
        except docker.errors.NotFound:
            logger.info("Criando rede geminiclaw-net")
            self.client.networks.create("geminiclaw-net", driver="bridge")
        except Exception as e:
            logger.warning("Falha ao verificar/criar rede Docker", extra={"error": str(e)})

    async def spawn(
        self, 
        agent_id: str, 
        image: str, 
        session_id: str, 
        ipc_port: int | None = None, 
        output_session_id: str | None = None,
        logs_session_id: str | None = None
    ) -> str:
        """Cria e inicia um container para um agente.

        Args:
            agent_id: Identificador do agente.
            image: Nome da imagem Docker.
            session_id: ID da sessão associada (usado para IPC temporário).
            ipc_port: Porta TCP para IPC (opcional, se usar TCP em vez de Unix Sockets).
            output_session_id: ID alternativo para o diretório de outputs compartilhado.
            logs_session_id: ID da sessão/tarefa para mapeamento de volumes de log.

        Returns:
            O ID do container criado.
        """
        async with self.semaphore:
            logger.info("Iniciando container para agente", extra={"agent_id": agent_id, "image": image, "session_id": session_id, "ipc_mode": "TCP" if ipc_port else "UNIX"})
            
            try:
                # Execução em thread separada para não bloquear o loop de eventos
                loop = asyncio.get_running_loop()
                
                # Prepara o caminho do socket IPC para este container (apenas se não for TCP)
                socket_name = f"{agent_id}_{session_id}.sock"
                
                # Prepara caminhos para volume
                db_path_host = os.environ.get("SQLITE_DB_PATH", "store/geminiclaw.db")
                db_dir_host = str(Path(db_path_host).parent.absolute())
                
                # Validação antecipada da GEMINI_API_KEY
                gemini_key = os.environ.get("GEMINI_API_KEY")
                if not gemini_key:
                    logger.error("GEMINI_API_KEY não encontrada no ambiente do host.")
                    raise RuntimeError("Variável GEMINI_API_KEY obrigatória não está definida no host.")

                # Variáveis de ambiente padrão
                env = {
                    "AGENT_ID": agent_id,
                    "SESSION_ID": session_id,
                    "GEMINI_API_KEY": gemini_key,
                    "GOOGLE_API_KEY": gemini_key,
                    "DEFAULT_MODEL": os.environ.get("DEFAULT_MODEL", DEFAULT_MODEL),
                    "SQLITE_DB_PATH": "/data/geminiclaw.db",
                    "AGENT_SOCKET_NAME": socket_name,
                    "OUTPUT_BASE_DIR": "/outputs",
                    "LOGS_BASE_DIR": "/logs",
                }
                
                # Passa variáveis de skill e configuração do host
                for key, value in os.environ.items():
                    if any(key.startswith(p) for p in ["SKILL_", "QUICK_SEARCH_", "DEEP_SEARCH_", "CODE_", "MEMORY_"]):
                        env[key] = value
                
                # Passa QDRANT_URL adiante se existir
                if "QDRANT_URL" in os.environ:
                    # Se estiver rodando dentro de Docker, usa o nome do serviço
                    if os.path.exists("/.dockerenv"):
                        env["QDRANT_URL"] = os.environ.get("QDRANT_URL", "http://geminiclaw-qdrant:6333")
                    else:
                        env["QDRANT_URL"] = os.environ["QDRANT_URL"]

                # Resolve paths for volumes
                # Se estiver rodando dentro de um container (com HOST_PROJECT_PATH), 
                # precisamos usar o caminho do HOST para os volumes montados em novos sub-containers.
                host_root = os.environ.get("HOST_PROJECT_PATH")
                
                db_path = os.environ.get("SQLITE_DB_PATH", "store/geminiclaw.db")
                output_base = os.environ.get("OUTPUT_BASE_DIR", "outputs")
                logs_base = os.environ.get("LOGS_BASE_DIR", "logs")
                
                effective_output_id = output_session_id or session_id
                effective_logs_id = logs_session_id or session_id
                
                if host_root:
                    # Estamos dentro de um container, mapeamos os caminhos relativos ao HOST_PROJECT_PATH
                    db_dir_host = str(Path(host_root) / "store")
                    output_session_host = str(Path(host_root) / "outputs" / effective_output_id)
                    logs_session_host = str(Path(host_root) / "logs" / effective_logs_id)
                    ipc_socket_host = str(Path(host_root) / "store" / "ipc")
                else:
                    # Rodando diretamente no host
                    db_dir_host = str(Path(db_path).parent.absolute())
                    output_session_host = str(Path(output_base).absolute() / effective_output_id)
                    logs_session_host = str(Path(logs_base).absolute() / effective_logs_id)
                    ipc_socket_host = str(Path(IPC_SOCKET_DIR))

                # Garante que as pastas existem localmente com permissões adequadas
                out_path = Path(output_base).absolute().joinpath(effective_output_id)
                log_path = Path(logs_base).absolute().joinpath(effective_logs_id)
                
                out_path.mkdir(parents=True, exist_ok=True)
                log_path.mkdir(parents=True, exist_ok=True)
                
                out_path.chmod(0o777)
                log_path.chmod(0o777)

                # Volumes padrão
                volumes = {
                    db_dir_host: {
                        "bind": "/data",
                        "mode": "rw",
                    },
                    output_session_host: {
                        "bind": "/outputs",
                        "mode": "rw",
                    },
                    logs_session_host: {
                        "bind": "/logs",
                        "mode": "rw",
                    }
                }

                # Mapeia pastas de código para permitir desenvolvimento sem rebuild (S1.3)
                if host_root:
                    volumes[str(Path(host_root) / "src")] = {"bind": "/app/src", "mode": "rw"}
                    volumes[str(Path(host_root) / "agents")] = {"bind": "/app/agents", "mode": "rw"}
                else:
                    # Rodando fora de container (local)
                    volumes[str(_root / "src")] = {"bind": "/app/src", "mode": "rw"}
                    volumes[str(_root / "agents")] = {"bind": "/app/agents", "mode": "rw"}

                # Configurações extras para TCP (Mac compatibility)
                extra_hosts = {}
                if ipc_port:
                    env["AGENT_IPC_PORT"] = str(ipc_port)
                    env["AGENT_IPC_HOST"] = "host.docker.internal"
                    extra_hosts["host.docker.internal"] = "host-gateway"
                else:
                    # Modo UNIX: monta o diretório de sockets
                    volumes[ipc_socket_host] = {
                        "bind": "/tmp/geminiclaw-ipc",
                        "mode": "rw",
                    }

                # Parâmetros para a execução do container
                run_kwargs: dict[str, Any] = {
                    "image": image,
                    "mem_limit": "512m",
                    "nano_cpus": 1_000_000_000,
                    "network": "geminiclaw-net",
                    "user": "appuser",
                    "remove": True,
                    "detach": True,
                    "group_add": [os.stat("/var/run/docker.sock").st_gid] if os.path.exists("/var/run/docker.sock") else [],
                    "labels": {"project": "geminiclaw", "agent_id": agent_id, "session_id": session_id},
                    "environment": env,
                    "volumes": volumes,
                    "extra_hosts": extra_hosts,
                }
                
                def _run(*args: Any, **kwargs: Any) -> Any:
                    return self.client.containers.run(**run_kwargs)

                container = await loop.run_in_executor(None, _run)
                
                logger.info("Container iniciado com sucesso", extra={"container_id": container.id, "agent_id": agent_id})
                return str(container.id)

            except Exception as e:
                logger.error("Falha ao spawnar container", extra={"agent_id": agent_id, "error": str(e)})
                raise

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
                try:
                    c = self.client.containers.get(cid)
                    c.stop()
                except docker.errors.NotFound:
                    pass

            await loop.run_in_executor(None, _get_and_stop, container_id)
            logger.info("Container encerrado", extra={"container_id": container_id})
        except Exception as e:
            logger.warning("Falha ao encerrar container", extra={"container_id": container_id, "error": str(e)})

    async def is_running(self, container_id: str) -> bool:
        """Verifica se o container ainda está em execução.

        Args:
            container_id: ID do container.

        Returns:
            True se estiver rodando, False caso contrário.
        """
        try:
            loop = asyncio.get_running_loop()
            def _check():
                c = self.client.containers.get(container_id)
                return c.status == "running"
            return await loop.run_in_executor(None, _check)
        except Exception:
            return False

    async def get_logs(self, container_id: str, tail: int = 20) -> str:
        """Obtém os últimos logs do container.

        Args:
            container_id: ID do container.
            tail: Número de linhas finais a retornar.

        Returns:
            String com os logs.
        """
        try:
            loop = asyncio.get_running_loop()
            def _read_logs():
                c = self.client.containers.get(container_id)
                return c.logs(tail=tail).decode("utf-8")
            return await loop.run_in_executor(None, _read_logs)
        except Exception as e:
            return f"Erro ao ler logs: {e}"

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
