from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
import docker
import pathlib
import time
import io
import tarfile
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
        image: str = "geminiclaw-base",
        memory_limit: str = "256m",
        cpu_quota: float = 0.5,
        timeout: int = 60,
    ):
        self.client = docker.from_env(timeout=300)
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_period = 100000
        self.cpu_quota = int(cpu_quota * self.cpu_period)
        self.timeout = timeout

    def _create_tar_archive(self, files: Dict[str, str]) -> bytes:
        """Cria um arquivo tar em memória contendo os arquivos especificados.
        
        Args:
            files: Dicionário mapeando nome do arquivo para seu conteúdo (string).
            
        Returns:
            Conteúdo do arquivo tar em bytes.
        """
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode='w') as tar:
            for name, content in files.items():
                content_bytes = content.encode('utf-8')
                info = tarfile.TarInfo(name=name)
                info.size = len(content_bytes)
                tar.addfile(info, io.BytesIO(content_bytes))
        return out.getvalue()

    def _extract_tar_archive(self, tar_data_gen, output_dir: pathlib.Path):
        """Extrai um gerador de dados tar para um diretório local.
        
        Args:
            tar_data_gen: Gerador de bytes (retorno do get_archive).
            output_dir: Diretório destino.
        """
        # get_archive retorna um gerador de chunks de bytes
        full_data = b"".join(tar_data_gen)
        with tarfile.open(fileobj=io.BytesIO(full_data), mode='r') as tar:
            tar.extractall(path=output_dir)

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
            
            # Preparar diretório de saída local
            abs_output_dir = pathlib.Path(output_dir).resolve() / session_id / task_name
            abs_output_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Iniciando sandbox para sessão {session_id}, tarefa {task_name}")

            # Criar o container em modo 'idle'
            # SEM volumes montados para compatibilidade com DinD
            container = self.client.containers.run(
                image=self.image,
                command=["tail", "-f", "/dev/null"],
                working_dir="/outputs",
                mem_limit=self.memory_limit,
                cpu_period=self.cpu_period,
                cpu_quota=self.cpu_quota,
                network_disabled=not bool(setup_commands),
                environment={"MPLCONFIGDIR": "/tmp", "VIRTUAL_ENV": "/app/.venv"},
                detach=True,
                remove=False,
            )

            # Injetar o script e garantir que o diretório /outputs existe
            container.exec_run("mkdir -p /outputs")
            tar_data = self._create_tar_archive({"script.py": code})
            container.put_archive("/outputs", tar_data)

            # Executar comandos de setup (ex: instalação de pacotes)
            if setup_commands:
                for cmd in setup_commands:
                    logger.info(f"Executando comando de setup no sandbox: {' '.join(cmd)}")
                    # Setup costuma ser rápido o suficiente para não precisar de timeout complexo aqui
                    exit_code, output = container.exec_run(cmd, user='root')
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
                exec_result = container.exec_run(["python", "/outputs/script.py"], demux=True)
                if timed_out:
                    stdout = ""
                    stderr = "Timeout atingido durante a execução."
                    exit_code = -1
                else:
                    out_bytes, err_bytes = exec_result.output
                    stdout = out_bytes.decode("utf-8") if out_bytes else ""
                    stderr = err_bytes.decode("utf-8") if err_bytes else ""
                    exit_code = exec_result.exit_code
            except Exception as e:
                if not timed_out:
                    raise
            finally:
                timer.cancel()

            # Extrair artefatos gerados
            logger.info("Extraindo artefatos do sandbox")
            try:
                # get_archive retorna (generator, stat)
                bits, stat = container.get_archive("/outputs")
                self._extract_tar_archive(bits, abs_output_dir)
            except Exception as e:
                logger.warning(f"Falha ao extrair artefatos: {str(e)}")

            # O tar extraído pode conter a pasta 'outputs' se o put_archive foi na raiz, 
            # ou o conteúdo direto se foi no path. No nosso caso, como put_archive foi em /outputs,
            # o get_archive("/outputs") retorna um tar onde o conteúdo está dentro de uma pasta 'outputs/'.
            # Vamos mover tudo para a raiz do abs_output_dir.
            extracted_path = abs_output_dir / "outputs"
            if extracted_path.exists() and extracted_path.is_dir():
                for item in extracted_path.iterdir():
                    dest = abs_output_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            import shutil
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    item.rename(dest)
                extracted_path.rmdir()

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
