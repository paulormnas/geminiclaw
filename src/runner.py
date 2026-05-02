import asyncio
import docker
import os
import functools
import sys
from pathlib import Path
from typing import Any, List, Dict
from src.logger import get_logger
from src.config import (
    AGENT_TIMEOUT_SECONDS, 
    LLM_MODEL,
    LLM_PROVIDER,
    GEMINI_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_CTX,
    OLLAMA_ENABLE_THINKING,
    LLM_REQUESTS_PER_MINUTE,
    LLM_RATE_LIMIT_COOLDOWN_SECONDS,
    DEPLOYMENT_PROFILE,
    HEALTH_CHECK_ENABLED,
    DATABASE_URL,
    OUTPUT_BASE_DIR,
    LOGS_BASE_DIR,
    PI_TEMPERATURE_LIMIT,
    PI_MIN_AVAILABLE_MEMORY_MB
)
from src.health import PiHealthMonitor
from src.utils.terminal import (
    RESET, BOLD, DIM, RED, GREEN, YELLOW, CYAN, 
    STATUS_ICONS, print_status
)

logger = get_logger(__name__)

# Diretório base para sockets IPC
_root = Path(__file__).parent.parent
IPC_SOCKET_DIR = str((_root / "store" / "ipc").absolute())



class ContainerRunner:
    """Gerencia o ciclo de vida de containers Docker para agentes."""

    def __init__(self, semaphore_limit: int | None = None):
        """Inicializa o runner com um limite de concorrência.

        Args:
            semaphore_limit: Número máximo de containers simultâneos.
        """
        try:
            self.client = docker.from_env()
            # Tenta um comando simples para validar a conexão
            self.client.ping()
        except Exception as e:
            logger.error("Erro ao conectar ao Docker", extra={"event": "docker_connection_error", "error": str(e)})
            print(f"\n{STATUS_ICONS['error']} {RED}Erro: Não foi possível conectar ao Docker.{RESET}")
            print(f"   Certifique-se de que o Docker Desktop está rodando.")
            print(f"   Detalhes: {e}\n")
            sys.exit(1)

        self.health = PiHealthMonitor()
        
        # Etapa V15: Ajuste dinâmico de recursos
        if semaphore_limit is None:
            limit = self._calculate_dynamic_limit()
        else:
            limit = semaphore_limit
            
        self.semaphore = asyncio.Semaphore(limit)
        
        # V6.6: Limite de concorrência específico para inferência local (Ollama)
        from src.config import MAX_LOCAL_LLM_CONCURRENT
        self.local_llm_semaphore = asyncio.Semaphore(MAX_LOCAL_LLM_CONCURRENT)
        
        self.ensure_infrastructure()

    def _calculate_dynamic_limit(self) -> int:
        """Calcula o limite de containers simultâneos baseado na RAM disponível."""
        try:
            mem = self.health.get_memory_usage()
            if mem and "available_mb" in mem:
                avail_gb = mem["available_mb"] / 1024.0
                if avail_gb >= 6.0:
                    limit = 3
                elif avail_gb >= 3.0:
                    limit = 2
                else:
                    limit = 1
                logger.info(f"Ajuste dinâmico de Semaphore: {limit} (RAM livre: {avail_gb:.2f} GB)")
                return limit
            else:
                logger.warning("Falha ao ler memória (provavelmente macOS). Usando Semaphore(3) por padrão.")
                return 3
        except Exception as e:
            logger.warning(f"Erro ao calcular limite de recursos, usando default (3): {e}")
            return 3
        self._ensure_network()

    def _ensure_network(self) -> None:
        """Garante que a rede geminiclaw-net existe."""
        try:
            self.client.networks.get("geminiclaw-net")
        except docker.errors.NotFound:
            print_status("network", "Criando rede Docker: geminiclaw-net")
            logger.info("Criando rede geminiclaw-net")
            self.client.networks.create("geminiclaw-net", driver="bridge")
        except Exception as e:
            logger.warning("Falha ao verificar/criar rede Docker", extra={"error": str(e)})

    def ensure_infrastructure(self) -> None:
        """Verifica e prepara a infraestrutura necessária (rede, imagens, qdrant, postgres)."""
        print(f"\n{BOLD}🔍 Verificando infraestrutura do ambiente...{RESET}")
        self._ensure_network()
        self._ensure_images()
        self._ensure_qdrant()
        self._ensure_postgres()
        print(f"{BOLD}✅ Ambiente pronto.{RESET}\n")

    def _ensure_postgres(self) -> None:
        """Verifica se o PostgreSQL está acessível via DATABASE_URL."""
        import httpx
        try:
            import psycopg
            conn = psycopg.connect(DATABASE_URL, connect_timeout=3)
            conn.close()
            print(f"{STATUS_ICONS['success']} PostgreSQL está online.")
        except Exception as e:
            print(f"{STATUS_ICONS['warning']}  {YELLOW}Aviso: Não foi possível conectar ao PostgreSQL.{RESET}")
            print(f"   Suba o container: docker compose up postgres -d")
            print(f"   DATABASE_URL: {DATABASE_URL}")
            logger.warning("PostgreSQL inacessível", extra={"error": str(e)})

    def _ensure_qdrant(self) -> None:
        """Verifica se o Qdrant está acessível se a skill de deep search estiver ativa."""
        from src.config import SKILL_DEEP_SEARCH_ENABLED, QDRANT_URL
        if not SKILL_DEEP_SEARCH_ENABLED:
            return

        print(f"🔎 Verificando Qdrant em {QDRANT_URL}...")
        try:
            import httpx
            # Tenta um health check simples
            if QDRANT_URL.startswith("http"):
                try:
                    response = httpx.get(f"{QDRANT_URL}/healthz", timeout=2.0)
                    if response.status_code == 200:
                        print(f"{STATUS_ICONS['success']} Qdrant está online.")
                        return
                except Exception:
                    pass
            
            # Se falhou o healthz ou não é http, tenta conectar via QdrantClient
            from qdrant_client import QdrantClient
            if QDRANT_URL == ":memory:":
                return
            
            client = QdrantClient(url=QDRANT_URL) if QDRANT_URL.startswith("http") else QdrantClient(path=QDRANT_URL)
            client.get_collections()
            print(f"{STATUS_ICONS['success']} Qdrant está online.")
        except Exception as e:
            print(f"{STATUS_ICONS['warning']}  {YELLOW}Aviso: Não foi possível conectar ao Qdrant.{RESET}")
            print(f"   A skill 'deep_search' pode falhar.")
            print(f"   Para rodar o Qdrant localmente: docker run -p 6333:6333 qdrant/qdrant")
            logger.warning(f"Qdrant inacessível em {QDRANT_URL}: {e}")

    def _ensure_images(self) -> None:
        """Verifica se as imagens necessárias existem e as constrói se faltarem."""
        required_images = [
            ("geminiclaw-base", "containers/Dockerfile", {}),
            ("geminiclaw-base-slim", "containers/Dockerfile.slim", {}),
            ("geminiclaw-researcher", "containers/Dockerfile.researcher", {}),
            ("geminiclaw-researcher-slim", "containers/Dockerfile.researcher", {"BASE_IMAGE": "geminiclaw-base-slim"}),
            ("geminiclaw-planner", "containers/Dockerfile.planner", {}),
            ("geminiclaw-planner-slim", "containers/Dockerfile.planner", {"BASE_IMAGE": "geminiclaw-base-slim"}),
            ("geminiclaw-validator", "containers/Dockerfile.validator", {}),
            ("geminiclaw-validator-slim", "containers/Dockerfile.validator", {"BASE_IMAGE": "geminiclaw-base-slim"}),
            ("geminiclaw-summarizer", "containers/Dockerfile.summarizer", {}),
            ("geminiclaw-summarizer-slim", "containers/Dockerfile.summarizer", {"BASE_IMAGE": "geminiclaw-base-slim"}),
            ("geminiclaw-reviewer", "containers/Dockerfile.reviewer", {}),
            ("geminiclaw-reviewer-slim", "containers/Dockerfile.reviewer", {"BASE_IMAGE": "geminiclaw-base-slim"}),
        ]

        for tag, dockerfile, buildargs in required_images:
            try:
                self.client.images.get(tag)
            except docker.errors.ImageNotFound:
                print_status("package", f"Imagem não encontrada: {tag}. Iniciando build...")
                logger.info(f"Iniciando build da imagem {tag}", extra={"dockerfile": dockerfile, "buildargs": buildargs})
                
                try:
                    # Resolve o path do Dockerfile relativo à raiz do projeto
                    dockerfile_path = _root / dockerfile
                    if not dockerfile_path.exists():
                        logger.error(f"Dockerfile não encontrado: {dockerfile_path}")
                        continue

                    # Stream do build para mostrar progresso no terminal
                    stream = self.client.api.build(
                        path=str(_root),
                        dockerfile=dockerfile,
                        tag=tag,
                        buildargs=buildargs,
                        decode=True,
                        rm=True
                    )
                    
                    for chunk in stream:
                        if 'stream' in chunk:
                            print(f"   {DIM}{chunk['stream'].strip()}{RESET}")
                        elif 'error' in chunk:
                            print(f"   {RED}Erro no build: {chunk['error'].strip()}{RESET}")
                            raise RuntimeError(f"Falha no build da imagem {tag}: {chunk['error']}")

                    print(f"{STATUS_ICONS['success']} Imagem {tag} criada com sucesso.")
                except Exception as e:
                    logger.error(f"Erro ao construir imagem {tag}", extra={"error": str(e)})
                    print(f"{STATUS_ICONS['error']} Erro ao construir imagem {tag}: {e}")
            except Exception as e:
                logger.warning(f"Erro ao verificar imagem {tag}", extra={"error": str(e)})

    async def _wait_for_health(self) -> None:
        """Verifica os limites de saúde e aguarda se o sistema estiver sob stress."""
        max_wait_seconds = 60
        waited = 0
        interval = 5
        
        while waited < max_wait_seconds:
            temp = self.health.get_temperature()
            mem = self.health.get_memory_usage()
            
            # Log de warning se estiver perto do limite (ex: > 70C)
            if temp is not None and temp > 70.0:
                logger.warning("Temperatura do sistema elevada", extra={"temperature": temp})
                
            # Verifica limites
            temp_exceeded = temp is not None and temp >= PI_TEMPERATURE_LIMIT
            mem_exceeded = mem is not None and mem["available_mb"] < PI_MIN_AVAILABLE_MEMORY_MB
            
            if not temp_exceeded and not mem_exceeded:
                return  # Saúde OK
                
            reasons = []
            if temp_exceeded: reasons.append(f"Temperatura alta ({temp} >= {PI_TEMPERATURE_LIMIT})")
            if mem_exceeded: reasons.append(f"Memória livre baixa ({mem['available_mb']} < {PI_MIN_AVAILABLE_MEMORY_MB})")
            
            logger.warning("Aguardando resfriamento/liberação de memória", extra={"reasons": reasons, "waited_seconds": waited})
            await asyncio.sleep(interval)
            waited += interval
            
        raise RuntimeError("Timeout aguardando saúde do sistema. Limites excedidos por muito tempo.")

    async def spawn(
        self, 
        agent_id: str, 
        image: str, 
        session_id: str, 
        ipc_port: int | None = None, 
        output_session_id: str | None = None,
        logs_session_id: str | None = None,
        env_vars: Dict[str, str] | None = None
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
            # V6.6: Limite de concorrência para Ollama para não travar o Pi 5
            is_local = (env_vars and env_vars.get("LLM_PROVIDER") == "ollama") or (not env_vars and LLM_PROVIDER == "ollama")
            
            if is_local:
                async with self.local_llm_semaphore:
                    return await self._do_spawn(
                        agent_id, image, session_id, ipc_port, 
                        output_session_id, logs_session_id, env_vars
                    )
            else:
                return await self._do_spawn(
                    agent_id, image, session_id, ipc_port, 
                    output_session_id, logs_session_id, env_vars
                )

    async def _do_spawn(
        self, 
        agent_id: str, 
        image: str, 
        session_id: str, 
        ipc_port: int | None = None, 
        output_session_id: str | None = None,
        logs_session_id: str | None = None,
        env_vars: Dict[str, str] | None = None
    ) -> str:
        """Execução real do spawn (refatorado de spawn para suportar semáforos aninhados)."""
        if HEALTH_CHECK_ENABLED:
            await self._wait_for_health()

            logger.info("Iniciando container para agente", extra={"agent_id": agent_id, "image": image, "session_id": session_id, "ipc_mode": "TCP" if ipc_port else "UNIX"})
            
            try:
                # Execução em thread separada para não bloquear o loop de eventos
                loop = asyncio.get_running_loop()
                
                # Prepara o caminho do socket IPC para este container (apenas se não for TCP)
                socket_name = f"{agent_id}_{session_id}.sock"
                
                # Variáveis de ambiente padrão
                # DATABASE_URL aponta para o container postgres dentro da rede Docker
                db_url_for_container = DATABASE_URL.replace(
                    "@localhost:", "@geminiclaw-postgres:"
                ).replace(
                    "@127.0.0.1:", "@geminiclaw-postgres:"
                )
                ollama_url_for_container = OLLAMA_BASE_URL.replace(
                    "localhost", "host.docker.internal"
                ).replace(
                    "127.0.0.1", "host.docker.internal"
                )
                env = {
                    "AGENT_ID": agent_id,
                    "SESSION_ID": session_id,
                    "LLM_PROVIDER": LLM_PROVIDER,
                    "LLM_MODEL": LLM_MODEL,
                    "GEMINI_API_KEY": GEMINI_API_KEY or "",
                    "GOOGLE_API_KEY": GEMINI_API_KEY or "",
                    "OLLAMA_BASE_URL": ollama_url_for_container,
                    "OLLAMA_NUM_CTX": str(OLLAMA_NUM_CTX),
                    "OLLAMA_ENABLE_THINKING": str(OLLAMA_ENABLE_THINKING).lower(),
                    "LLM_REQUESTS_PER_MINUTE": str(LLM_REQUESTS_PER_MINUTE),
                    "LLM_RATE_LIMIT_COOLDOWN_SECONDS": str(LLM_RATE_LIMIT_COOLDOWN_SECONDS),
                    "DEPLOYMENT_PROFILE": DEPLOYMENT_PROFILE,
                    "DATABASE_URL": db_url_for_container,
                    "AGENT_SOCKET_NAME": socket_name,
                    "OUTPUT_BASE_DIR": "/outputs",
                    "LOGS_BASE_DIR": "/logs",
                }
                
                # Passa variáveis de skill e configuração do host
                for key, value in os.environ.items():
                    prefixes = [
                        "SKILL_", "QUICK_SEARCH_", "DEEP_SEARCH_", 
                        "CODE_", "MEMORY_", "LLM_CACHE_", "BRAVE_",
                        "LLM_", "DEPLOYMENT_"
                    ]
                    if any(key.startswith(p) for p in prefixes):
                        if key not in env:
                            env[key] = value
                
                # Adiciona variáveis de ambiente personalizadas passadas via argumento
                if env_vars:
                    env.update(env_vars)
                
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
                
                effective_output_id = output_session_id or session_id
                effective_logs_id = logs_session_id or session_id
                
                if host_root:
                    # Estamos dentro de um container, mapeamos os caminhos relativos ao HOST_PROJECT_PATH
                    output_session_host = str(Path(host_root) / OUTPUT_BASE_DIR / effective_output_id)
                    logs_session_host = str(Path(host_root) / LOGS_BASE_DIR / effective_logs_id)
                    ipc_socket_host = str(Path(host_root) / "store" / "ipc")
                else:
                    # Rodando diretamente no host
                    output_session_host = str(Path(OUTPUT_BASE_DIR).absolute() / effective_output_id)
                    logs_session_host = str(Path(LOGS_BASE_DIR).absolute() / effective_logs_id)
                    ipc_socket_host = str(Path(IPC_SOCKET_DIR))

                # Garante que as pastas existem localmente com permissões adequadas
                out_path = Path(OUTPUT_BASE_DIR).absolute().joinpath(effective_output_id)
                log_path = Path(LOGS_BASE_DIR).absolute().joinpath(effective_logs_id)
                
                out_path.mkdir(parents=True, exist_ok=True)
                log_path.mkdir(parents=True, exist_ok=True)
                
                out_path.chmod(0o777)
                log_path.chmod(0o777)

                # Volumes padrão (sem /data — PostgreSQL é acessado via rede Docker)
                volumes = {
                    output_session_host: {
                        "bind": "/outputs",
                        "mode": "rw",
                    },
                    logs_session_host: {
                        "bind": "/logs",
                        "mode": "rw",
                    }
                }
                
                # Mapeia o socket do Docker apenas se existir (permite spawnar sandboxes)
                if os.path.exists("/var/run/docker.sock"):
                    volumes["/var/run/docker.sock"] = {
                        "bind": "/var/run/docker.sock",
                        "mode": "rw",
                    }

                # Mapeia pastas de código para permitir desenvolvimento sem rebuild (S1.3)
                # Sempre mapeia se estivermos rodando no host ou se host_root for fornecido
                src_path = str(Path(host_root) / "src") if host_root else str(_root / "src")
                agents_path = str(Path(host_root) / "agents") if host_root else str(_root / "agents")
                
                volumes[src_path] = {"bind": "/app/src", "mode": "rw"}
                volumes[agents_path] = {"bind": "/app/agents", "mode": "rw"}
                
                logger.debug(f"Volume mapping: {src_path} -> /app/src")

                # Configurações extras para TCP e Host Gateway
                extra_hosts = {"host.docker.internal": "host-gateway"}
                if ipc_port:
                    env["AGENT_IPC_PORT"] = str(ipc_port)
                    env["AGENT_IPC_HOST"] = "host.docker.internal"
                else:
                    # Modo UNIX: monta o diretório de sockets
                    volumes[ipc_socket_host] = {
                        "bind": "/tmp/geminiclaw-ipc",
                        "mode": "rw",
                    }

                # Alocações de memória otimizadas para ARM64
                mem_limit = "384m"
                if agent_id in ("base", "researcher") or image.startswith("geminiclaw-base") or image.startswith("geminiclaw-researcher"):
                    mem_limit = "512m"
                elif agent_id in ("planner", "validator") or image.startswith("geminiclaw-planner") or image.startswith("geminiclaw-validator"):
                    mem_limit = "768m"

                # Seleção de imagem (-slim vs full)
                use_slim = False
                if agent_id in ("planner", "validator") or image.startswith("geminiclaw-planner") or image.startswith("geminiclaw-validator"):
                    use_slim = True
                else:
                    # Base/Researcher usam slim se deep search estiver desabilitado
                    if os.environ.get("SKILL_DEEP_SEARCH_ENABLED", "false").lower() != "true":
                        use_slim = True

                final_image = image
                if use_slim and not final_image.endswith("-slim"):
                    final_image = f"{final_image}-slim"

                # Parâmetros para a execução do container
                run_kwargs: dict[str, Any] = {
                    "image": final_image,
                    "mem_limit": mem_limit,
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
