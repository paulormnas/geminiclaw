from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json
import os
import docker
import docker.errors
import pathlib
import re
import shutil
import stat
import sys
import threading
import time
import io
import tarfile
import uuid
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from src import config
from src.llm.retry import RETRY_BACKOFFS_SECONDS, emit_connection_retry, is_retryable_status
from src.logger import get_logger

logger = get_logger(__name__)


def _is_docker_connection_error(exc: Exception) -> bool:
    """True se `exc` representa uma falha de conexão com o daemon Docker
    (Roadmap V18 / Spec `usage-limits`) — vale a pena retentar.

    V18/usage-limits — code review do PR #68 (apontamento importante 2):
    `docker.errors.DockerException` é a classe-base de praticamente todas as
    exceções do SDK docker (`ImageNotFound`, `InvalidVersion`,
    `ContainerError`, etc.), não apenas falhas de conexão com o daemon. Tratar
    qualquer `DockerException` como transitória fazia erros PERMANENTES de
    configuração (ex.: imagem inexistente) serem retentados 3x com backoff e
    emitirem eventos `connection_retry` espúrios, poluindo a contagem usada
    por `SESSION_MAX_CONNECTION_RETRIES`.

    Restrito, análogo a `is_retryable_status`/`is_retryable_error` em
    `src/llm/retry.py`, a: `docker.errors.APIError` com status HTTP
    transitório (429/5xx — ex.: daemon sobrecarregado), e `ConnectionError`/
    `OSError` (inclui `requests.exceptions.ConnectionError`/`Timeout`, que o
    docker-py deixa propagar sem encapsular em `DockerException` e que já são
    subclasses de `OSError`, cobrindo a indisponibilidade real do daemon).

    Args:
        exc: Exceção capturada ao chamar a API do Docker.
    """
    if isinstance(exc, docker.errors.APIError):
        return is_retryable_status(exc.status_code)
    return isinstance(exc, (ConnectionError, OSError))

@dataclass
class SandboxResult:
    """Resultado da execução de código no sandbox."""
    stdout: str
    stderr: str
    exit_code: int
    artifacts: List[str] = field(default_factory=list)
    timed_out: bool = False
    # A instalação de pacotes sob demanda falhou ou estourou o timeout; o script não rodou.
    install_failed: bool = False
    # Pacotes instalados sob demanda, no formato "nome==versão" (vazio sem instalação).
    packages_installed: List[str] = field(default_factory=list)
    # Saída estruturada (v17-structural-fact-ingestion): a classificação da causa da falha não
    # depende de heurística sobre mensagens. ``oom_killed``: exit 137 sem timeout (SIGKILL por
    # memória); ``exception_type``: tipo da exceção do traceback do script (``None`` sem traceback);
    # ``infra_error``: categoria quando o sandbox não chegou a rodar o script (daemon, imagem, início).
    oom_killed: bool = False
    exception_type: Optional[str] = None
    infra_error: Optional[str] = None
    image: str = ""

SANDBOX_PROJECT_LABEL = "geminiclaw"

# Conjunto científico básico presente na imagem (containers/sandbox/requirements.in).
# Pedidos desses nomes sem especificador de versão não geram instalação.
BASIC_PACKAGES = frozenset(
    canonicalize_name(n) for n in ("numpy", "pandas", "scipy", "matplotlib", "scikit-learn", "seaborn")
)

# Módulos da stdlib que o código gerado às vezes pede em `packages`: nunca são instalados.
_STDLIB_NAMES = frozenset(canonicalize_name(n) for n in sys.stdlib_module_names)

# Limites da lista `packages` (texto vem do LLM): quantidade e tamanho de cada requisito.
MAX_PACKAGES = 20
MAX_PACKAGE_LENGTH = 200

# `session_id` e `task_name` viram diretórios no host montados com escrita no container.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

SANDBOX_VENV_PYTHON = "/opt/sandbox-venv/bin/python"
SANDBOX_DEPS_DIR = "/deps"

# Comando fixo (sem entrada do usuário) que lista as distribuições instaladas em /deps.
_LIST_DEPS_CODE = (
    "import importlib.metadata as m, json; "
    "print(json.dumps([{'name': d.metadata['Name'], 'version': d.version} "
    f"for d in m.distributions(path=['{SANDBOX_DEPS_DIR}'])]))"
)


_TRACEBACK_MARKER = "Traceback (most recent call last):"
_EXCEPTION_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*)(?::|$)")
OOM_EXIT_CODE = 137  # 128 + SIGKILL: sandbox encerrado por falta de memória (mem_limit)
MAX_EXCEPTION_TYPE_LENGTH = 100


def extract_exception_type(stderr: str) -> Optional[str]:
    """Extrai o tipo da exceção da última linha de um traceback do Python.

    O stderr vem do código gerado (não confiável): só um identificador simples, curto e
    precedido de ``Traceback`` é aceito; qualquer outra coisa devolve ``None``.

    Args:
        stderr: Saída de erro do script no sandbox.

    Returns:
        Nome da classe da exceção sem o módulo (ex.: ``"MemoryError"``), ou ``None``.
    """
    if not stderr or _TRACEBACK_MARKER not in stderr:
        return None
    lines = [ln for ln in stderr.rstrip().splitlines() if ln.strip()]
    if not lines:
        return None
    match = _EXCEPTION_LINE_RE.match(lines[-1].strip())
    if match is None:
        return None
    name = match.group(1).rsplit(".", 1)[-1]
    if not name or len(name) > MAX_EXCEPTION_TYPE_LENGTH:
        return None
    return name


class SandboxImageNotFoundError(RuntimeError):
    """A imagem do sandbox não existe localmente (nunca é baixada: o nome é local)."""


def prepare_packages(packages: Optional[List[str]]) -> tuple[List[str], List[str]]:
    """Valida e filtra os pacotes pedidos para instalação sob demanda (ADR 018 §1).

    Cada item é validado pela gramática de requisito do PEP 508: recusa URL direta (``@``),
    marcador de ambiente, opções (nome iniciado por ``-``) e caminhos. Itens da stdlib e do
    conjunto científico básico (sem especificador de versão) já estão disponíveis e não são
    instalados.

    Args:
        packages: Lista de requisitos pedida pela skill.

    Returns:
        Tupla ``(a_instalar, invalidos)``. ``invalidos`` traz uma mensagem por item recusado.
    """
    to_install: List[str] = []
    invalid: List[str] = []
    if len(packages or []) > MAX_PACKAGES:
        return [], [f"lista com {len(packages)} itens: o máximo é {MAX_PACKAGES}"]
    for raw in packages or []:
        item = raw.strip() if isinstance(raw, str) else ""
        if len(item) > MAX_PACKAGE_LENGTH:
            invalid.append(f"{item[:40]!r}...: requisito com mais de {MAX_PACKAGE_LENGTH} caracteres")
            continue
        if not item:
            invalid.append(f"{raw!r}: requisito vazio ou que não é texto")
            continue
        if item.startswith("-") or "/" in item or "\\" in item or "@" in item:
            invalid.append(f"{item!r}: opções, caminhos e URLs não são permitidos")
            continue
        try:
            req = Requirement(item)
        except InvalidRequirement as exc:
            invalid.append(f"{item!r}: requisito inválido ({exc})")
            continue
        if req.url or req.marker is not None:
            invalid.append(f"{item!r}: URL direta e marcadores de ambiente não são permitidos")
            continue
        name = canonicalize_name(req.name)
        if name in _STDLIB_NAMES:
            continue
        if name in BASIC_PACKAGES and not str(req.specifier):
            continue
        if item not in to_install:
            to_install.append(item)
    return to_install, invalid


def _setting(name: str):
    """Lê uma variável ``SANDBOX_*`` no momento do uso, com o padrão de ``src/config.py``."""
    default = getattr(config, name)
    return config.get_env(name, default=str(default))


def cleanup_sandbox_containers() -> int:
    """Encerra e remove containers de sandbox que ficaram para trás (ex.: após Ctrl+C).

    O sandbox remove o próprio container ao terminar; isto cobre a interrupção do processo no
    meio de uma execução. Best-effort: nunca levanta exceção.

    Returns:
        Quantidade de containers removidos.
    """
    removed = 0
    try:
        client = docker.from_env(timeout=10)
        for container in client.containers.list(all=True, filters={"label": f"project={SANDBOX_PROJECT_LABEL}"}):
            try:
                container.remove(force=True)
                removed += 1
            except Exception as exc:  # noqa: BLE001 — limpeza best-effort
                logger.warning(f"Falha ao remover container de sandbox {container.short_id}: {exc}")
    except Exception as exc:  # noqa: BLE001 — sem daemon não há o que limpar
        logger.warning(f"Cleanup de sandboxes ignorado: {exc}")
    return removed


def _purge_escaping_symlinks(root: pathlib.Path) -> list[str]:
    """Remove de ``root`` os links simbólicos cujo alvo resolve para fora dele.

    O ``/outputs`` do container é um bind mount de escrita da pasta da tarefa, então o
    que o código gerado cria (inclusive symlinks para arquivos do host) aparece no host
    imediatamente. Deixar esses links ali faria qualquer leitor do
    host (manifest, leitor de relatórios, ingestão) seguir o link e ler fora da sessão.
    Links que permanecem dentro de ``root`` são preservados.

    Args:
        root: Pasta da tarefa a varrer.

    Returns:
        Caminhos (relativos a ``root``) dos links removidos.
    """
    real_root = os.path.realpath(root)
    removed: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                continue
            real = os.path.realpath(path)
            if real == real_root or real.startswith(real_root + os.sep):
                continue
            os.unlink(path)
            removed.append(os.path.relpath(path, root))
    if removed:
        logger.warning(
            "Symlinks que apontavam para fora da pasta da tarefa foram removidos",
            extra={"removed": removed},
        )
    return removed


def _purge_special_files(root: pathlib.Path) -> list[str]:
    """Remove de ``root`` tudo que não seja arquivo regular, diretório ou link simbólico.

    O usuário sem privilégios do sandbox pode criar FIFOs (e sockets) em ``/outputs``; um leitor
    do host que os abrisse ficaria bloqueado.

    Args:
        root: Pasta da tarefa a varrer.

    Returns:
        Caminhos (relativos a ``root``) dos arquivos especiais removidos.
    """
    removed: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            mode = os.lstat(path).st_mode
            if stat.S_ISREG(mode) or stat.S_ISDIR(mode):
                continue
            os.unlink(path)
            removed.append(os.path.relpath(path, root))
    if removed:
        logger.warning("Arquivos especiais removidos da pasta da tarefa", extra={"removed": removed})
    return removed


class PythonSandbox:
    """Sandbox de execução de código Python em container sem privilégios (ADR 014, ADR 018).

    O container roda com o UID/GID do orquestrador, sem capacidades, com raiz somente leitura
    e ``/tmp`` em ``tmpfs``. Só ``/outputs`` (pasta da subtarefa) e, quando há pacotes sob
    demanda, ``/deps`` (diretório temporário da execução) são graváveis a partir do host.
    """

    def __init__(
        self,
        image: Optional[str] = None,
        memory_limit: str = "256m",
        cpu_quota: float = 0.5,
        timeout: int = 60,
        setup_timeout: int = 300,
        work_dir: Optional[str] = None,
    ):
        self._client: Optional["docker.DockerClient"] = None
        self.image = image or _setting("SANDBOX_IMAGE")
        self.memory_limit = memory_limit
        self.cpu_period = 100000
        self.cpu_quota = int(cpu_quota * self.cpu_period)
        self.timeout = timeout
        self.setup_timeout = setup_timeout
        self.pids_limit = int(_setting("SANDBOX_PIDS_LIMIT"))
        self.tmpfs_size = _setting("SANDBOX_TMPFS_SIZE")
        self.install_log_tail_lines = int(_setting("SANDBOX_INSTALL_LOG_TAIL_LINES"))
        work = pathlib.Path(work_dir or _setting("SANDBOX_WORK_DIR"))
        if not work.is_absolute():
            work = pathlib.Path(__file__).resolve().parents[3] / work
        self.work_dir = work

    @property
    def client(self) -> "docker.DockerClient":
        """Cliente Docker, conectado sob demanda (lazy).

        Registrar ``CodeSkill`` (e, portanto, expor a ferramenta
        ``python_interpreter`` ao agente) não deveria exigir um daemon Docker
        já respondendo — só a execução de fato (``run()``) precisa dele. Antes,
        ``docker.from_env()`` era chamado em ``__init__``, então qualquer
        processo sem o daemon acessível (ex.: suíte de testes unitários, ou o
        orquestrador iniciando antes do Docker subir) fazia
        ``SkillRegistry._safe_register`` engolir a exceção e nunca registrar a
        skill — o Developer Agent perdia silenciosamente sua única ferramenta
        de execução de código. Adiando a conexão para o primeiro uso real, o
        registro sempre sucede; falhas de conectividade continuam sendo
        capturadas (e reportadas como ``SandboxResult`` de erro) dentro de
        ``run()``, como qualquer outro erro de execução.

        Returns:
            Cliente Docker conectado (``docker.from_env``), memoizado após a
            primeira chamada.
        """
        if self._client is None:
            self._client = docker.from_env(timeout=300)
        return self._client

    def _create_tar_archive(self, files: Dict[str, str]) -> bytes:
        """Cria um arquivo tar em memória contendo os arquivos especificados.

        Os membros levam o UID/GID e o modo do usuário do orquestrador (e não root), para que
        os arquivos injetados em ``/outputs`` pertençam ao usuário do host.

        Args:
            files: Dicionário mapeando nome do arquivo para seu conteúdo (string).

        Returns:
            Conteúdo do arquivo tar em bytes.
        """
        out = io.BytesIO()
        now = time.time()
        with tarfile.open(fileobj=out, mode='w') as tar:
            for name, content in files.items():
                content_bytes = content.encode('utf-8')
                info = tarfile.TarInfo(name=name)
                info.size = len(content_bytes)
                info.uid = os.getuid()
                info.gid = os.getgid()
                info.mode = 0o644
                info.mtime = now
                tar.addfile(info, io.BytesIO(content_bytes))
        return out.getvalue()

    def _ensure_image(self):
        """Garante que a imagem do sandbox existe localmente (nunca faz ``pull``).

        Raises:
            SandboxImageNotFoundError: Se a imagem não existe, com a instrução para construí-la.
        """
        try:
            self.client.images.get(self.image)
        except docker.errors.ImageNotFound as exc:
            raise SandboxImageNotFoundError(
                f"Imagem do sandbox '{self.image}' não encontrada localmente. Construa-a com "
                "`bash scripts/build_images.sh` (ou ajuste SANDBOX_IMAGE para uma imagem existente)."
            ) from exc

    def _install_packages(self, container, to_install: List[str]) -> Optional[SandboxResult]:
        """Instala os pacotes em ``/deps`` com o usuário do container (sem root).

        O comando é montado aqui, sem entrada livre: os nomes já foram validados por
        :func:`prepare_packages`.

        Returns:
            ``SandboxResult`` de falha (``install_failed=True``) se a instalação falhar ou
            estourar o timeout; ``None`` se a instalação teve sucesso.
        """
        # --no-config: o uv não lê uv.toml/pyproject.toml da pasta corrente (controlável pelo código
        # gerado). --only-binary :all: evita executar setup.py/backends de build com rede ligada.
        cmd = [
            "uv", "pip", "install", "--no-config", "--only-binary", ":all:",
            "--python", SANDBOX_VENV_PYTHON, "--target", SANDBOX_DEPS_DIR, *to_install,
        ]
        requested = ", ".join(to_install)
        setup_timed_out = False

        def kill_on_setup_timeout():
            nonlocal setup_timed_out
            setup_timed_out = True
            try:
                container.kill()
            except Exception:
                pass

        # A instalação tem rede e pode travar (mirror lento, DNS); sem limite, a thread do
        # sandbox ficaria presa para sempre. O timer mata o container.
        timer = threading.Timer(self.setup_timeout, kill_on_setup_timeout)
        timer.start()
        exec_result = None
        try:
            logger.info(f"Instalando pacotes no sandbox (sem root, em {SANDBOX_DEPS_DIR}): {requested}")
            exec_result = container.exec_run(cmd, workdir="/tmp", environment={"UV_NO_CONFIG": "1"})
        except Exception:
            if not setup_timed_out:
                raise
        finally:
            timer.cancel()

        if setup_timed_out:
            logger.error("Timeout na instalação de pacotes do sandbox", extra={"setup_timeout": self.setup_timeout})
            return SandboxResult(
                stdout="",
                stderr=f"Timeout de {self.setup_timeout}s atingido na instalação dos pacotes: {requested}.",
                exit_code=-1,
                timed_out=True,
                install_failed=True,
            )
        if exec_result.exit_code != 0:
            output = exec_result.output
            text = output.decode("utf-8", errors="replace") if isinstance(output, (bytes, bytearray)) else str(output)
            tail = "\n".join(text.splitlines()[-self.install_log_tail_lines:])
            logger.error("Falha na instalação de pacotes do sandbox", extra={"packages": requested})
            return SandboxResult(
                stdout="",
                stderr=(
                    f"Falha na instalação dos pacotes: {requested}.\n"
                    "Só são instalados pacotes com wheel (--only-binary :all:); um pacote que exige "
                    "compilar do código-fonte falha aqui. Use outro pacote ou versão com wheel.\n"
                    f"{tail}"
                ),
                exit_code=exec_result.exit_code,
                install_failed=True,
            )
        return None

    def _list_installed_packages(self, container) -> List[str]:
        """Lista ("nome==versão") o que ficou instalado em ``/deps``. Best-effort."""
        try:
            # -I (modo isolado) e workdir /tmp: nada de /outputs entra no sys.path nem na configuração.
            exec_result = container.exec_run(
                [SANDBOX_VENV_PYTHON, "-I", "-c", _LIST_DEPS_CODE], workdir="/tmp"
            )
            if exec_result.exit_code != 0:
                raise RuntimeError(f"código de saída {exec_result.exit_code}")
            entries = json.loads(exec_result.output)
            return sorted(f"{e['name']}=={e['version']}" for e in entries)
        except Exception as exc:  # noqa: BLE001 — o registro não deve derrubar uma execução válida
            logger.warning(f"Não foi possível registrar os pacotes instalados: {exc}")
            return []

    def _disconnect_networks(self, container) -> None:
        """Desconecta o container de todas as redes e confirma (fail-closed).

        Raises:
            RuntimeError: Se a desconexão falhar ou o container ainda estiver em alguma rede.
                A execução é abortada: o script não pode rodar com rede.
        """
        try:
            container.reload()
            networks = list((container.attrs["NetworkSettings"]["Networks"] or {}).keys())
            for network_name in networks:
                self.client.networks.get(network_name).disconnect(container)
            container.reload()
            remaining = container.attrs["NetworkSettings"]["Networks"] or {}
        except Exception as exc:
            raise RuntimeError(f"Falha na desconexão de rede do container; execução abortada: {exc}") from exc
        if remaining:
            raise RuntimeError(
                "Falha na desconexão de rede do container; execução abortada: "
                f"ainda conectado a {sorted(remaining)}"
            )

    def run(
        self,
        code: str,
        session_id: str,
        task_name: str,
        output_dir: str,
        timeout: Optional[int] = None,
        packages: Optional[List[str]] = None,
        extra_files: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        """Executa o código fornecido em um container isolado.

        Args:
            code: Código Python como string.
            session_id: ID da sessão para organização de artefatos.
            task_name: Nome da tarefa para organização de artefatos.
            output_dir: Diretório raiz para artefatos no host.
            timeout: Tempo limite em segundos (sobrescreve o default).
            packages: Requisitos (PEP 508) a instalar sob demanda em ``/deps``. A instalação
                roda sem root e com rede; falha ou timeout encerram a execução sem rodar o
                script. Depois da instalação o container é desconectado da rede.
            extra_files: Arquivos adicionais para copiar para /outputs junto do script
                (ex: {"scientific_helpers.py": "<código-fonte>"} — Roadmap V15.2 / Spec G2).
        """
        to_install, invalid = prepare_packages(packages)
        if invalid:
            return SandboxResult(
                stdout="",
                stderr="Pacotes inválidos em 'packages': " + "; ".join(invalid),
                exit_code=-1,
                artifacts=[],
            )

        if os.getuid() == 0:
            return SandboxResult(
                stdout="",
                stderr=(
                    "O orquestrador roda como root (UID 0); o sandbox herdaria root. Execute o "
                    "orquestrador com um usuário sem privilégios."
                ),
                exit_code=-1,
                artifacts=[],
            )

        # session_id e task_name viram diretórios do host montados com escrita no container.
        output_root = pathlib.Path(output_dir).resolve()
        abs_output_dir = output_root / str(session_id) / str(task_name)
        bad_names = [
            f"{label}={value!r}"
            for label, value in (("session_id", session_id), ("task_name", task_name))
            if not isinstance(value, str) or not _SAFE_NAME_RE.fullmatch(value) or ".." in value
        ]
        if bad_names or not abs_output_dir.resolve().is_relative_to(output_root):
            return SandboxResult(
                stdout="",
                stderr=(
                    "Nome inválido para pasta de saída (use letras, dígitos, '.', '_' e '-', sem '..'): "
                    + (", ".join(bad_names) or "caminho fora do diretório de saída")
                ),
                exit_code=-1,
                artifacts=[],
            )

        container = None
        run_work_dir = self.work_dir / uuid.uuid4().hex
        try:
            self._ensure_image()

            exec_timeout = timeout or self.timeout

            # Pasta da subtarefa no host, com o modo padrão (umask do usuário): o container roda
            # com o mesmo UID/GID, então não é preciso abrir permissões.
            abs_output_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Iniciando sandbox para sessão {session_id}, tarefa {task_name}")

            volumes = {str(abs_output_dir): {"bind": "/outputs", "mode": "rw"}}
            if to_install:
                deps_dir = run_work_dir / "deps"
                deps_dir.mkdir(parents=True, exist_ok=True)
                volumes[str(deps_dir.resolve())] = {"bind": SANDBOX_DEPS_DIR, "mode": "rw"}

            # Criar o container em modo 'idle' com volume montado.
            # V18/usage-limits — retentativa limitada em falha de conexão com o
            # daemon Docker, emitindo o evento connection_retry na telemetria a
            # cada retentativa. Método síncrono (executado fora do event loop,
            # tipicamente via asyncio.to_thread pela skill 'code'): usa
            # threading.Event().wait em vez de time.sleep para a espera entre
            # tentativas, conforme AGENTS.md (nunca time.sleep()).
            last_exc: Exception | None = None
            for attempt, backoff in enumerate((0.0, *RETRY_BACKOFFS_SECONDS)):
                if backoff:
                    logger.warning(
                        "Retentativa de conexão com o daemon Docker",
                        extra={"attempt": attempt, "backoff_seconds": backoff},
                    )
                    emit_connection_retry("sandbox_docker", str(last_exc))
                    threading.Event().wait(backoff)
                try:
                    container = self.client.containers.run(
                        image=self.image,
                        command=["sleep", "infinity"],
                        user=f"{os.getuid()}:{os.getgid()}",
                        working_dir="/outputs",
                        mem_limit=self.memory_limit,
                        memswap_limit=self.memory_limit,
                        cpu_period=self.cpu_period,
                        cpu_quota=self.cpu_quota,
                        pids_limit=self.pids_limit,
                        cap_drop=["ALL"],
                        security_opt=["no-new-privileges:true"],
                        read_only=True,
                        tmpfs={"/tmp": f"size={self.tmpfs_size},noexec,nosuid,nodev"},
                        network_disabled=not to_install,
                        environment={
                            "HOME": "/tmp",
                            "MPLCONFIGDIR": "/tmp",
                            "PYTHONPATH": SANDBOX_DEPS_DIR,
                            "UV_CACHE_DIR": "/tmp/uv-cache",
                        },
                        volumes=volumes,
                        detach=True,
                        remove=False,
                        # Rótulos usados pela CLI ('sessions', 'stop') e pelo cleanup de Ctrl+C.
                        labels={
                            "project": SANDBOX_PROJECT_LABEL,
                            "geminiclaw.role": "sandbox",
                            "session_id": session_id,
                            "task_name": task_name,
                        },
                    )
                    break
                except Exception as e:
                    last_exc = e
                    container = None
                    if not _is_docker_connection_error(e):
                        raise
            if container is None:
                logger.error("Sandbox: conexão com o daemon Docker esgotou as retentativas")
                raise last_exc

            packages_installed: List[str] = []
            if to_install:
                failure = self._install_packages(container, to_install)
                if failure is not None:
                    return failure
                # Script sem rede: desconecta e confirma (fail-closed) ANTES de qualquer outro
                # código rodar no container (a listagem abaixo já roda sem rede).
                self._disconnect_networks(container)
                packages_installed = self._list_installed_packages(container)

            # Injetar o script (e arquivos extras) só depois da instalação e da desconexão: o código
            # de instalação (com rede) não vê nem reescreve o script que vai rodar.
            tar_data = self._create_tar_archive({"script.py": code, **(extra_files or {})})
            container.put_archive("/outputs", tar_data)

            logger.info("Executando script principal no sandbox")
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
            except Exception:
                if not timed_out:
                    raise
            finally:
                timer.cancel()

            # Os artefatos já estão no host (bind mount, dono = usuário do orquestrador).
            # Antes da varredura o container é encerrado: um processo em segundo plano iniciado
            # pelo script não pode recriar links depois dela. O que o código gerado criou pode
            # incluir symlinks para fora da pasta da tarefa e arquivos especiais (FIFO).
            try:
                container.kill()
            except Exception as e:  # noqa: BLE001 — já parado (timeout) ou removido
                logger.debug(f"Container já encerrado antes da varredura: {e}")
            try:
                _purge_escaping_symlinks(abs_output_dir)
                _purge_special_files(abs_output_dir)
            except OSError as e:
                logger.warning(f"Falha ao varrer a pasta da tarefa: {e}")

            return SandboxResult(
                stdout=stdout,
                stderr=stderr if not timed_out else "Timeout atingido durante a execução.",
                exit_code=exit_code,
                artifacts=[
                    str(p.relative_to(abs_output_dir))
                    for p in abs_output_dir.glob("**/*")
                    if p.is_file()
                ],
                timed_out=timed_out,
                packages_installed=packages_installed,
                oom_killed=(exit_code == OOM_EXIT_CODE and not timed_out),
                exception_type=extract_exception_type(stderr) if not timed_out else None,
                image=self.image,
            )

        except Exception as e:
            logger.error(f"Erro ao executar sandbox: {str(e)}")
            if isinstance(e, SandboxImageNotFoundError):
                infra_error = "sandbox_image_missing"
            elif _is_docker_connection_error(e):
                infra_error = "docker_unavailable"
            else:
                infra_error = "sandbox_start_failed"
            return SandboxResult(
                stdout="",
                stderr=f"Exception during sandbox execution: {str(e)}",
                exit_code=-1,
                artifacts=[],
                infra_error=infra_error,
                image=self.image,
            )
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            shutil.rmtree(run_work_dir, ignore_errors=True)
            # Preservar o script como solicitado pelo usuário (removido unlink)
