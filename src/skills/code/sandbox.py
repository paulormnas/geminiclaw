from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
import docker
import pathlib
import time
from src.logger import get_logger

logger = get_logger(__name__)

@dataclass
class SandboxResult:
    """Resultado da execução de código no sandbox."""
    stdout: str
    stderr: str
    exit_code: int
    artifacts: List[str] = field(default_factory=list)
    timed_out: bool = False

class PythonSandbox:
    """Implementa um sandbox seguro para execução de código Python via Docker."""

    def __init__(
        self,
        image: str = "ghcr.io/astral-sh/uv:python3.11-bookworm-slim",
        memory_limit: str = "256m",
        cpu_quota: float = 0.5,
        timeout: int = 60,
    ):
        self.client = docker.from_env()
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_period = 100000
        self.cpu_quota = int(cpu_quota * self.cpu_period)
        self.timeout = timeout

    def _ensure_image(self):
        """Garante que a imagem base existe localmente."""
        try:
            self.client.images.get(self.image)
        except docker.errors.ImageNotFound:
            logger.info(f"Baixando imagem {self.image}...")
            self.client.images.pull(self.image)

    def run(
        self,
        code: str,
        session_id: str,
        task_name: str,
        output_dir: str,
        timeout: Optional[int] = None,
        setup_commands: Optional[List[List[str]]] = None,
    ) -> SandboxResult:
        """Executa o código fornecido em um container isolado.

        Args:
            code: Código Python como string.
            session_id: ID da sessão para organização de artefatos.
            task_name: Nome da tarefa para organização de artefatos.
            output_dir: Diretório raiz para artefatos no host.
            timeout: Tempo limite em segundos (sobrescreve o default).
            setup_commands: Comandos de setup (ex: [['pip', 'install', 'pandas']])
        """
        container = None
        try:
            self._ensure_image()
            
            exec_timeout = timeout or self.timeout
            
            # Preparar diretório de saída
            abs_output_dir = pathlib.Path(output_dir).resolve() / session_id / task_name
            abs_output_dir.mkdir(parents=True, exist_ok=True)
            abs_output_dir.chmod(0o777)  # Garante acesso para escrita em containers
            
            script_path = abs_output_dir / "script.py"
            script_path.write_text(code)

            logger.info(f"Iniciando sandbox para sessão {session_id}, tarefa {task_name}")

            # Criar o container em modo 'idle' para poder rodar comandos de setup
            container = self.client.containers.run(
                image=self.image,
                command=["tail", "-f", "/dev/null"], # Mantém o container vivo
                volumes={
                    str(abs_output_dir): {"bind": "/outputs", "mode": "rw"}
                },
                working_dir="/outputs",
                mem_limit=self.memory_limit,
                cpu_period=self.cpu_period,
                cpu_quota=self.cpu_quota,
                network_disabled=not bool(setup_commands), # Habilitar rede apenas se houver setup_commands
                detach=True,
                remove=False,
            )

            # Executar comandos de setup (ex: instalação de pacotes)
            if setup_commands:
                for cmd in setup_commands:
                    logger.info(f"Executando comando de setup no sandbox: {' '.join(cmd)}")
                    # Setup costuma ser rápido o suficiente para não precisar de timeout complexo aqui
                    exit_code, output = container.exec_run(cmd)
                    if exit_code != 0:
                        logger.error(f"Falha no comando de setup: {output.decode()}")

            logger.info("Executando script principal no sandbox")
            import threading
            timed_out = False

            def kill_container():
                nonlocal timed_out
                timed_out = True
                try:
                    container.kill()
                except Exception:
                    pass

            timer = threading.Timer(exec_timeout, kill_container)
            timer.start()
            
            stdout = ""
            stderr = ""
            exit_code = -1
            
            try:
                exec_result = container.exec_run(["python", "/outputs/script.py"])
                if timed_out:
                    stdout = ""
                    exit_code = -1
                else:
                    stdout = exec_result.output.decode("utf-8")
                    exit_code = exec_result.exit_code
            except Exception as e:
                if not timed_out:
                    raise
            finally:
                timer.cancel()


            return SandboxResult(
                stdout=stdout,
                stderr=stderr if not timed_out else "Timeout atingido durante a execução.",
                exit_code=exit_code,
                artifacts=[
                    str(p.relative_to(abs_output_dir))
                    for p in abs_output_dir.glob("**/*")
                    if p.is_file()
                ],
                timed_out=timed_out
            )

        except Exception as e:
            logger.error(f"Erro ao executar sandbox: {str(e)}")
            return SandboxResult(
                stdout="",
                stderr=f"Exception during sandbox execution: {str(e)}",
                exit_code=-1,
                artifacts=[]
            )
        finally:
            if container:
                try:
                    container.remove(force=True)
                except:
                    pass
            # Preservar o script como solicitado pelo usuário (removido unlink)
            pass
