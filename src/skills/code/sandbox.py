from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
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
from src.reserved_files import is_reserved_name
from src.skills.code import fetch_assets as _fetch_script
from src.skills.code.assets import AssetRecord, AssetSpec, cached_path, parse_assets, verify_and_cache
from src.skills.code.inputs import (
    InputClassifier,
    MountSourceError,
    NoneShareableClassifier,
    check_mount_source,
    list_input_files,
)

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
class ImageInfo:
    """Imagem usada na execução: nome, id e digests de repositório (ADR 019 §4)."""

    nome: str
    id: str = ""
    repo_digests: List[str] = field(default_factory=list)


@dataclass
class PhaseTiming:
    """Início, fim (ISO 8601, UTC) e código de saída de uma fase da execução."""

    nome: str
    inicio: str
    fim: str
    exit_code: Optional[int] = None


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
    # v18.5-sandbox-phases (design §7): fase que falhou, rede e entrega de dados, e insumos de proveniência.
    fase_falha: Optional[Literal["install", "fetch_assets", "execute", "infra"]] = None
    download_nao_declarado: bool = False
    rede_na_execucao: bool = False
    # Condição que impediu a rede pedida com ``needs_network`` (sem nomes de arquivos de dados).
    nota_rede: Optional[str] = None
    modo_entrega: Literal["mount", "copy"] = "mount"
    entradas_entregues: List[str] = field(default_factory=list)  # caminhos relativos a /inputs
    imagem: Optional[ImageInfo] = None
    python_version: Optional[str] = None
    pacotes_solicitados: List[str] = field(default_factory=list)
    pacotes: Dict[str, str] = field(default_factory=dict)  # distribuição -> versão, visíveis na execução
    ativos: List[AssetRecord] = field(default_factory=list)
    fases: List[PhaseTiming] = field(default_factory=list)

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

# PATH fechado da preparação (nenhuma variável do host é repassada); espelha o PATH da imagem.
SANDBOX_PATH = "/opt/sandbox-venv/bin:/usr/local/bin:/usr/bin:/bin"
SANDBOX_INPUTS_DIR = "/inputs"
SANDBOX_ASSETS_DIR = "/assets"
SANDBOX_STAGING_DIR = "/staging"
SANDBOX_PRIOR_DIR = "/prior"

# Introspecção fixa (código do projeto, sem entrada do usuário): versão do Python e distribuições visíveis
# na execução (imagem e /deps). `-I` ignora PYTHONPATH, então /deps entra explicitamente.
_INTROSPECT_CODE = (
    "import importlib.metadata as m, json, sys; "
    f"sys.path.insert(0, '{SANDBOX_DEPS_DIR}'); "
    "dists = lambda p: sorted({(d.metadata['Name'], d.version) for d in m.distributions(path=p)}); "
    "print(json.dumps({'python': sys.version, 'all': dists(sys.path), "
    f"'deps': dists(['{SANDBOX_DEPS_DIR}'])}}))"
)

# Assinaturas (no stderr do script) de falha de rede na fase `execute`, que roda sem rede (design §5).
NETWORK_FAILURE_SIGNATURES = (
    "socket.gaierror",
    "Temporary failure in name resolution",
    "Name or service not known",
    "Network is unreachable",
    "urllib.error.URLError",
    "requests.exceptions.ConnectionError",
    "Max retries exceeded with url",
    "We couldn't connect to 'https://huggingface.co'",
    "LocalEntryNotFoundError",
)

NETWORK_UNDECLARED_MESSAGE = (
    "A fase de execução não tem acesso à rede. Se o script precisa baixar pesos, corpora ou datasets, "
    "declare-os no parâmetro `assets` (url e, se souber, sha256) e leia de `/assets/<destino>`. "
    "Pacotes Python vão no parâmetro `packages`."
)


def is_undeclared_download_failure(stderr: str) -> bool:
    """True se o ``stderr`` do script casa com uma assinatura de falha de rede (``NETWORK_FAILURE_SIGNATURES``)."""
    return any(signature in (stderr or "") for signature in NETWORK_FAILURE_SIGNATURES)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _purge_reserved_names(root: pathlib.Path) -> list[str]:
    """Remove de ``root`` arquivos/links com nome reservado do orquestrador (qualquer caixa, em qualquer nível).

    Args:
        root: Pasta da tarefa a varrer.

    Returns:
        Caminhos (relativos a ``root``) removidos.
    """
    removed: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            if not is_reserved_name(name):
                continue
            path = os.path.join(dirpath, name)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.unlink(path)
            removed.append(os.path.relpath(path, root))
    if removed:
        logger.warning("Arquivos reservados do orquestrador removidos da saída", extra={"removed": removed})
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
    """Sandbox de execução de código Python em containers sem privilégios (ADR 014, ADR 018, ADR 019 §5).

    Cada execução tem até duas etapas, em containers separados:

    * **preparação** (só com ``packages`` ou ativos a baixar): com rede e **sem dados** (nem a saída da
      subtarefa, nem os insumos). Fase ``fetch_assets`` e depois ``install``; o container é removido
      antes da execução.
    * **execução**: **sem rede** (exceto o caso de ``needs_network`` com entradas compartilháveis);
      insumos, dependências e ativos somente leitura; só ``/outputs`` é gravável.

    Os containers rodam com o UID/GID do orquestrador, sem capacidades, com raiz somente leitura e
    ``/tmp`` em ``tmpfs``.
    """

    def __init__(
        self,
        image: Optional[str] = None,
        memory_limit: str = "256m",
        cpu_quota: float = 0.5,
        timeout: int = 60,
        setup_timeout: Optional[int] = None,
        work_dir: Optional[str] = None,
        asset_cache_dir: Optional[str] = None,
        input_classifier: Optional[InputClassifier] = None,
        allow_private_asset_hosts: tuple[str, ...] = (),
    ):
        self._client: Optional["docker.DockerClient"] = None
        self.image = image or _setting("SANDBOX_IMAGE")
        self.memory_limit = memory_limit
        self.cpu_period = 100000
        self.cpu_quota = int(cpu_quota * self.cpu_period)
        self.timeout = timeout
        self.setup_timeout = int(
            setup_timeout if setup_timeout is not None else _setting("SANDBOX_INSTALL_TIMEOUT_SECONDS")
        )
        self.fetch_timeout = int(_setting("SANDBOX_FETCH_TIMEOUT_SECONDS"))
        self.asset_max_bytes = int(_setting("SANDBOX_ASSET_MAX_BYTES"))
        self.input_delivery = str(_setting("SANDBOX_INPUT_DELIVERY")).strip().lower()
        self.copy_max_bytes = int(_setting("SANDBOX_COPY_MAX_BYTES"))
        self.pids_limit = int(_setting("SANDBOX_PIDS_LIMIT"))
        self.tmpfs_size = _setting("SANDBOX_TMPFS_SIZE")
        self.install_log_tail_lines = int(_setting("SANDBOX_INSTALL_LOG_TAIL_LINES"))
        self.work_dir = self._absolute(work_dir or _setting("SANDBOX_WORK_DIR"))
        self.asset_cache_dir = self._absolute(asset_cache_dir or _setting("SANDBOX_ASSET_CACHE_DIR"))
        # Até v18.5-research-data-ingestion existir, nenhum insumo é compartilhável: execução sempre sem rede.
        self.input_classifier: InputClassifier = input_classifier or NoneShareableClassifier()
        # Somente testes: hosts liberados do bloqueio de IPs internos no download. Nunca vem do LLM.
        self.allow_private_asset_hosts = tuple(allow_private_asset_hosts)

    @staticmethod
    def _absolute(path: str) -> pathlib.Path:
        """Caminho absoluto; relativo é resolvido a partir da raiz do repositório."""
        resolved = pathlib.Path(path)
        return resolved if resolved.is_absolute() else pathlib.Path(__file__).resolve().parents[3] / resolved

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

    @staticmethod
    def _create_inputs_tar(base: pathlib.Path, files: List[pathlib.Path]) -> bytes:
        """Tar com os insumos (caminhos relativos a ``base``), com o UID/GID do orquestrador."""
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w") as tar:
            for path in files:
                info = tar.gettarinfo(str(path), arcname=str(path.relative_to(base)))
                info.uid, info.gid, info.uname, info.gname = os.getuid(), os.getgid(), "", ""
                info.mode = 0o444
                with open(path, "rb") as handle:
                    tar.addfile(info, handle)
        return out.getvalue()

    def _ensure_image(self) -> ImageInfo:
        """Garante que a imagem do sandbox existe localmente (nunca faz ``pull``) e a descreve.

        Returns:
            Nome, id e ``RepoDigests`` da imagem.

        Raises:
            SandboxImageNotFoundError: Se a imagem não existe, com a instrução para construí-la.
        """
        try:
            image = self.client.images.get(self.image)
        except docker.errors.ImageNotFound as exc:
            raise SandboxImageNotFoundError(
                f"Imagem do sandbox '{self.image}' não encontrada localmente. Construa-a com "
                "`bash scripts/build_images.sh` (ou ajuste SANDBOX_IMAGE para uma imagem existente)."
            ) from exc
        image_id = getattr(image, "id", "")
        attrs = getattr(image, "attrs", None)
        digests = attrs.get("RepoDigests") if isinstance(attrs, dict) else None
        return ImageInfo(
            nome=self.image,
            id=image_id if isinstance(image_id, str) else "",
            repo_digests=[d for d in digests if isinstance(d, str)] if isinstance(digests, list) else [],
        )

    def _create_container(
        self,
        *,
        role: str,
        network: bool,
        volumes: Dict[str, dict],
        environment: Dict[str, str],
        session_id: str,
        task_name: str,
        working_dir: str,
        mounts: Optional[list] = None,
        extra_tmpfs: Optional[Dict[str, str]] = None,
    ):
        """Cria um container ocioso do sandbox (usuário do orquestrador, sem capacidades), com retentativa.

        V18/usage-limits — retentativa limitada em falha de conexão com o daemon Docker, emitindo o
        evento ``connection_retry`` na telemetria a cada retentativa. Método síncrono (executado fora
        do event loop, via ``asyncio.to_thread`` pela skill): usa ``threading.Event().wait`` em vez de
        ``time.sleep`` para a espera entre tentativas, conforme AGENTS.md.
        """
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
                kwargs = dict(
                    image=self.image,
                    command=["sleep", "infinity"],
                    user=f"{os.getuid()}:{os.getgid()}",
                    working_dir=working_dir,
                    mem_limit=self.memory_limit,
                    memswap_limit=self.memory_limit,
                    cpu_period=self.cpu_period,
                    cpu_quota=self.cpu_quota,
                    pids_limit=self.pids_limit,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    read_only=True,
                    tmpfs={"/tmp": f"size={self.tmpfs_size},noexec,nosuid,nodev", **(extra_tmpfs or {})},
                    network_disabled=not network,
                    environment=environment,
                    volumes=volumes,
                    detach=True,
                    remove=False,
                    # Rótulos usados pela CLI ('sessions', 'stop') e pelo cleanup de Ctrl+C.
                    labels={
                        "project": SANDBOX_PROJECT_LABEL,
                        "geminiclaw.role": role,
                        "session_id": session_id,
                        "task_name": task_name,
                    },
                )
                if mounts:
                    kwargs["mounts"] = mounts
                return self.client.containers.run(**kwargs)
            except Exception as e:
                last_exc = e
                if not _is_docker_connection_error(e):
                    raise
        logger.error("Sandbox: conexão com o daemon Docker esgotou as retentativas")
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _exec_with_timeout(container, cmd: List[str], timeout: int, **kwargs):
        """Executa ``cmd`` no container com limite de tempo (o timer mata o container).

        Returns:
            Tupla ``(resultado, estourou_o_tempo)``; ``resultado`` é ``None`` se o tempo estourou.
        """
        timed_out = False

        def kill_on_timeout():
            nonlocal timed_out
            timed_out = True
            try:
                container.kill()
            except Exception:
                pass

        timer = threading.Timer(timeout, kill_on_timeout)
        timer.start()
        result = None
        try:
            result = container.exec_run(cmd, **kwargs)
        except Exception:
            if not timed_out:
                raise
        finally:
            timer.cancel()
        return (None if timed_out else result), timed_out

    @staticmethod
    def _output_text(output) -> str:
        return output.decode("utf-8", errors="replace") if isinstance(output, (bytes, bytearray)) else str(output)

    def _install_packages(self, container, to_install: List[str]) -> Optional[SandboxResult]:
        """Instala os pacotes em ``/deps`` com o usuário do container (sem root).

        O comando é montado aqui, sem entrada livre: os nomes já foram validados por
        :func:`prepare_packages`.

        Returns:
            ``SandboxResult`` de falha (``install_failed=True``, ``fase_falha="install"``) se a instalação
            falhar ou estourar o timeout; ``None`` se a instalação teve sucesso.
        """
        # --no-config: o uv não lê uv.toml/pyproject.toml da pasta corrente (controlável pelo código
        # gerado). --only-binary :all: evita executar setup.py/backends de build com rede ligada.
        cmd = [
            "uv", "pip", "install", "--no-config", "--only-binary", ":all:",
            "--python", SANDBOX_VENV_PYTHON, "--target", SANDBOX_DEPS_DIR, *to_install,
        ]
        requested = ", ".join(to_install)
        logger.info(f"Instalando pacotes no sandbox (sem root, em {SANDBOX_DEPS_DIR}): {requested}")
        # A instalação tem rede e pode travar (mirror lento, DNS); sem limite, a thread do sandbox
        # ficaria presa para sempre. O timer mata o container.
        exec_result, timed_out = self._exec_with_timeout(
            container, cmd, self.setup_timeout, workdir="/tmp", environment={"UV_NO_CONFIG": "1"}
        )
        if timed_out:
            logger.error("Timeout na instalação de pacotes do sandbox", extra={"setup_timeout": self.setup_timeout})
            return SandboxResult(
                stdout="",
                stderr=f"Timeout de {self.setup_timeout}s atingido na instalação dos pacotes: {requested}.",
                exit_code=-1,
                timed_out=True,
                install_failed=True,
                fase_falha="install",
            )
        if exec_result.exit_code != 0:
            text = self._output_text(exec_result.output)
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
                fase_falha="install",
            )
        return None

    def _fetch_assets(
        self, container, downloads: List[AssetSpec], staging_dir: pathlib.Path
    ) -> tuple[List[AssetRecord], Optional[SandboxResult]]:
        """Fase ``fetch_assets``: baixa no container, verifica o hash no host e move para o cache.

        Returns:
            Tupla ``(registros, falha)``; ``falha`` é um ``SandboxResult`` com ``fase_falha="fetch_assets"``.
        """
        spec = {
            "assets": [{"url": a.url, "destino": a.destino} for a in downloads],
            "max_bytes": self.asset_max_bytes,
            "allow_private_hosts": list(self.allow_private_asset_hosts),
        }
        script_source = pathlib.Path(_fetch_script.__file__).read_text(encoding="utf-8")
        container.put_archive(
            "/tmp", self._create_tar_archive({"fetch_assets.py": script_source, "fetch_spec.json": json.dumps(spec)})
        )
        logger.info("Baixando ativos declarados no sandbox", extra={"count": len(downloads)})
        exec_result, timed_out = self._exec_with_timeout(
            container, ["python", "/tmp/fetch_assets.py", "/tmp/fetch_spec.json"], self.fetch_timeout, workdir="/tmp"
        )
        if timed_out:
            return [], SandboxResult(
                stdout="",
                stderr=f"Timeout de {self.fetch_timeout}s atingido no download dos ativos declarados.",
                exit_code=-1,
                timed_out=True,
                fase_falha="fetch_assets",
            )
        if exec_result.exit_code != 0:
            text = self._output_text(exec_result.output)
            tail = "\n".join(text.splitlines()[-self.install_log_tail_lines:])
            return [], SandboxResult(
                stdout="",
                stderr=f"Falha no download dos ativos declarados.\n{tail}",
                exit_code=exec_result.exit_code,
                fase_falha="fetch_assets",
            )
        records, error = verify_and_cache(downloads, staging_dir, self.asset_cache_dir)
        if error:
            return records, SandboxResult(stdout="", stderr=error, exit_code=-1, fase_falha="fetch_assets")
        return records, None

    def _network_decision(
        self,
        needs_network: bool,
        input_files: List[pathlib.Path],
        task_dir: pathlib.Path,
        injected_names: set[str],
        prior_mounts: List[pathlib.Path],
    ) -> tuple[bool, Optional[str]]:
        """Decide se a fase ``execute`` roda com rede (design §6).

        Só com ``needs_network`` explícito, todas as entradas ``compartilhavel`` e nenhum dado produzido
        por execução visível. A nota devolvida não cita nomes de arquivos de dados.

        Returns:
            Tupla ``(rede, nota)``; ``nota`` explica a condição que falhou quando a rede foi pedida e negada.
        """
        if not needs_network:
            return False, None
        if any(not self.input_classifier.is_shareable(path) for path in input_files):
            return False, "há entradas não compartilháveis em /inputs; a execução roda sem rede"
        produced = [
            p for p in task_dir.glob("**/*")
            if p.is_file() and p.relative_to(task_dir).as_posix() not in injected_names
        ]
        if produced:
            return False, "há dados produzidos por execuções anteriores em /outputs; a execução roda sem rede"
        if prior_mounts:
            return False, "há saídas de sessões anteriores visíveis em /prior; a execução roda sem rede"
        return True, None

    def run(
        self,
        code: str,
        session_id: str,
        task_name: str,
        output_dir: str,
        timeout: Optional[int] = None,
        packages: Optional[List[str]] = None,
        extra_files: Optional[Dict[str, str]] = None,
        assets: Optional[List[dict]] = None,
        needs_network: bool = False,
        prior_dirs: Optional[List[pathlib.Path]] = None,
    ) -> SandboxResult:
        """Executa o código fornecido em containers isolados, em fases (ADR 019 §5).

        Args:
            code: Código Python como string.
            session_id: ID da sessão para organização de artefatos.
            task_name: Nome da tarefa para organização de artefatos.
            output_dir: Diretório raiz para artefatos no host.
            timeout: Tempo limite em segundos (sobrescreve o default).
            packages: Requisitos (PEP 508) a instalar em ``/deps`` na fase ``install`` (com rede e sem
                dados). Falha ou timeout encerram a execução sem rodar o script.
            extra_files: Arquivos adicionais para copiar para /outputs junto do script
                (ex: {"scientific_helpers.py": "<código-fonte>"} — Roadmap V15.2 / Spec G2).
            assets: Ativos a baixar na fase ``fetch_assets``: ``{"url", "destino", "sha256"?}``; ficam
                em ``/assets/<destino>`` (somente leitura) na execução.
            needs_network: Pede rede na execução; só vale com todas as entradas compartilháveis e sem
                dados produzidos por execuções visíveis (design §6).
            prior_dirs: Saídas de sessões anteriores a montar em ``/prior/<sessão>`` (somente leitura).
        """
        to_install, invalid = prepare_packages(packages)
        if invalid:
            return SandboxResult(
                stdout="",
                stderr="Pacotes inválidos em 'packages': " + "; ".join(invalid),
                exit_code=-1,
                artifacts=[],
            )
        asset_specs, asset_errors = parse_assets(assets)
        if asset_errors:
            return SandboxResult(
                stdout="",
                stderr="Ativos inválidos em 'assets': " + "; ".join(asset_errors),
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
            if not isinstance(value, str)
            or not _SAFE_NAME_RE.fullmatch(value)
            or ".." in value
            or value == "."  # "." faria do bind mount a pasta da sessão (ou a raiz de todas as sessões)
            or is_reserved_name(value)
        ]
        resolved = abs_output_dir.resolve()
        # A pasta da tarefa é sempre <raiz>/<sessão>/<tarefa>, mesmo através de symlinks: nunca a pasta da sessão.
        if bad_names or not resolved.is_relative_to(output_root) or len(resolved.relative_to(output_root).parts) != 2:
            return SandboxResult(
                stdout="",
                stderr=(
                    "Nome inválido para pasta de saída (use letras, dígitos, '.', '_' e '-', sem '..'): "
                    + (", ".join(bad_names) or "caminho fora do diretório de saída")
                ),
                exit_code=-1,
                artifacts=[],
            )

        res = SandboxResult(
            stdout="",
            stderr="",
            exit_code=-1,
            image=self.image,
            pacotes_solicitados=list(to_install),
            modo_entrega="copy" if self.input_delivery == "copy" else "mount",
        )
        session_dir = output_root / str(session_id)
        snapshot_dir = session_dir / "input_snapshot"
        container = None
        run_work_dir = self.work_dir / uuid.uuid4().hex
        try:
            if self.input_delivery not in ("mount", "copy"):
                raise _MountRefused(
                    f"SANDBOX_INPUT_DELIVERY inválido: {self.input_delivery!r} (use 'mount' ou 'copy')"
                )

            # Origens de montagem: resolvidas, descendentes do lugar esperado e sem symlinks (antes de qualquer
            # container).
            input_files: List[pathlib.Path] = []
            try:
                if snapshot_dir.exists() or snapshot_dir.is_symlink():
                    input_files = list_input_files(snapshot_dir, session_dir)
                prior_mounts = [check_mount_source(pathlib.Path(d), output_root) for d in (prior_dirs or [])]
                for prior in prior_mounts:
                    if not _SAFE_NAME_RE.fullmatch(prior.name) or ".." in prior.name:
                        raise MountSourceError(f"nome de sessão anterior inválido: {prior.name!r}")
            except MountSourceError as exc:
                raise _MountRefused(str(exc)) from exc
            inputs_size = sum(p.stat().st_size for p in input_files)
            if res.modo_entrega == "copy" and inputs_size > self.copy_max_bytes:
                raise _MountRefused(
                    f"insumos somam {inputs_size} bytes, acima de SANDBOX_COPY_MAX_BYTES={self.copy_max_bytes}; "
                    "use SANDBOX_INPUT_DELIVERY=mount"
                )
            res.entradas_entregues = [p.relative_to(snapshot_dir).as_posix() for p in input_files]

            res.imagem = self._ensure_image()

            exec_timeout = timeout or self.timeout

            # Pasta da subtarefa no host, com o modo padrão (umask do usuário): o container roda
            # com o mesmo UID/GID, então não é preciso abrir permissões.
            abs_output_dir.mkdir(parents=True, exist_ok=True)
            injected_names = {"script.py", *(extra_files or {})}
            network, res.nota_rede = self._network_decision(
                needs_network, input_files, abs_output_dir, injected_names, prior_mounts
            )

            logger.info(f"Iniciando sandbox para sessão {session_id}, tarefa {task_name}")

            # Ativos já em cache (sha256 declarado) dispensam o download.
            records: List[AssetRecord] = []
            downloads: List[AssetSpec] = []
            for spec in asset_specs:
                hit = cached_path(self.asset_cache_dir, spec.sha256) if spec.sha256 else None
                if hit is None:
                    downloads.append(spec)
                else:
                    records.append(
                        AssetRecord(spec.url, spec.sha256, spec.destino, hit.stat().st_size, True, "cache")
                    )

            deps_dir = run_work_dir / "deps"
            if to_install or downloads:
                if not self._run_preparation(res, run_work_dir, to_install, downloads, records, session_id, task_name):
                    return res
            res.ativos = sorted(records, key=lambda r: r.destino)

            volumes: Dict[str, dict] = {str(abs_output_dir): {"bind": "/outputs", "mode": "rw"}}
            if to_install:
                volumes[str(deps_dir.resolve())] = {"bind": SANDBOX_DEPS_DIR, "mode": "ro"}
            extra_tmpfs: Dict[str, str] = {}
            if input_files and res.modo_entrega == "mount":
                volumes[str(snapshot_dir.resolve())] = {"bind": SANDBOX_INPUTS_DIR, "mode": "ro"}
            elif input_files:
                extra_tmpfs[SANDBOX_INPUTS_DIR] = (
                    f"size={self.copy_max_bytes},mode=0555,uid={os.getuid()},gid={os.getgid()},noexec,nosuid,nodev"
                )
            for prior in prior_mounts:
                volumes[str(prior)] = {"bind": f"{SANDBOX_PRIOR_DIR}/{prior.name}", "mode": "ro"}
            mounts = [
                docker.types.Mount(
                    target=f"{SANDBOX_ASSETS_DIR}/{rec.destino}",
                    source=str((self.asset_cache_dir / rec.sha256).resolve()),
                    type="bind",
                    read_only=True,
                )
                for rec in res.ativos
            ]

            container = self._create_container(
                role="sandbox",
                network=network,
                volumes=volumes,
                mounts=mounts,
                extra_tmpfs=extra_tmpfs,
                environment={
                    "HOME": "/tmp",
                    "MPLCONFIGDIR": "/tmp",
                    "PYTHONPATH": SANDBOX_DEPS_DIR,
                    "UV_CACHE_DIR": "/tmp/uv-cache",
                },
                session_id=session_id,
                task_name=task_name,
                working_dir="/outputs",
            )
            res.rede_na_execucao = network
            if network:
                logger.warning(
                    "Execução do sandbox COM rede (todas as entradas compartilháveis)",
                    extra={"session_id": session_id, "task_name": task_name},
                )

            phase_start = _now()
            if input_files and res.modo_entrega == "copy":
                container.put_archive(SANDBOX_INPUTS_DIR, self._create_inputs_tar(snapshot_dir, input_files))
            self._introspect(container, res)

            # Injetar o script (e arquivos extras) só depois da preparação: o código de instalação
            # (com rede) nunca viu a pasta de saída nem o script que vai rodar.
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
            res.fases.append(PhaseTiming("execute", phase_start, _now(), exit_code))

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
                reserved_removed = _purge_reserved_names(abs_output_dir)
            except OSError as e:
                logger.warning(f"Falha ao varrer a pasta da tarefa: {e}")
                reserved_removed = []
            if reserved_removed:
                stderr = (
                    f"{stderr}\nArquivo(s) reservado(s) do orquestrador removido(s) da saída da tarefa: "
                    f"{', '.join(reserved_removed)}. Esses nomes não podem ser gravados pelo código gerado."
                ).strip()
                if exit_code == 0:
                    exit_code = 1

            res.stdout = stdout
            res.stderr = stderr if not timed_out else "Timeout atingido durante a execução."
            res.exit_code = exit_code
            res.artifacts = [
                str(p.relative_to(abs_output_dir)) for p in abs_output_dir.glob("**/*") if p.is_file()
            ]
            res.timed_out = timed_out
            res.oom_killed = exit_code == OOM_EXIT_CODE and not timed_out
            res.exception_type = extract_exception_type(stderr) if not timed_out else None
            if exit_code != 0 or timed_out:
                res.fase_falha = "execute"
            res.download_nao_declarado = (
                exit_code != 0 and not timed_out and not network and is_undeclared_download_failure(stderr)
            )
            return res

        except Exception as e:
            logger.error(f"Erro ao executar sandbox: {str(e)}")
            if isinstance(e, SandboxImageNotFoundError):
                infra_error = "sandbox_image_missing"
            elif isinstance(e, _MountRefused):
                infra_error = "sandbox_mount_refused"
            elif _is_docker_connection_error(e):
                infra_error = "docker_unavailable"
            else:
                infra_error = "sandbox_start_failed"
            res.stdout = ""
            res.stderr = (
                f"Execução recusada: {e}"
                if isinstance(e, _MountRefused)
                else f"Exception during sandbox execution: {str(e)}"
            )
            res.exit_code = -1
            res.artifacts = []
            res.infra_error = infra_error
            res.fase_falha = "infra"
            return res
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            shutil.rmtree(run_work_dir, ignore_errors=True)

    def _run_preparation(
        self,
        res: SandboxResult,
        run_work_dir: pathlib.Path,
        to_install: List[str],
        downloads: List[AssetSpec],
        records: List[AssetRecord],
        session_id: str,
        task_name: str,
    ) -> bool:
        """Container de preparação: rede, **sem dados** (só ``/deps`` e ``/staging``). Removido ao terminar.

        Ordem: ``fetch_assets`` (o host verifica e move os ativos para o cache) e depois ``install``,
        para que o código de instalação nunca tenha acesso aos arquivos baixados.

        Returns:
            ``True`` se tudo teve sucesso; ``False`` com ``res`` preenchido com a falha.
        """
        volumes: Dict[str, dict] = {}
        staging_dir = run_work_dir / "staging"
        if to_install:
            deps_dir = run_work_dir / "deps"
            deps_dir.mkdir(parents=True, exist_ok=True)
            volumes[str(deps_dir.resolve())] = {"bind": SANDBOX_DEPS_DIR, "mode": "rw"}
        if downloads:
            staging_dir.mkdir(parents=True, exist_ok=True)
            volumes[str(staging_dir.resolve())] = {"bind": SANDBOX_STAGING_DIR, "mode": "rw"}
        prep = self._create_container(
            role="sandbox-prep",
            network=True,
            volumes=volumes,
            # Lista fechada: nenhuma variável do host é repassada ao código de instalação.
            environment={"HOME": "/tmp", "UV_CACHE_DIR": "/tmp/uv-cache", "PATH": SANDBOX_PATH},
            session_id=session_id,
            task_name=task_name,
            working_dir="/tmp",
        )
        failure: Optional[SandboxResult] = None
        try:
            if downloads:
                start = _now()
                new_records, failure = self._fetch_assets(prep, downloads, staging_dir)
                records.extend(new_records)
                res.fases.append(PhaseTiming("fetch_assets", start, _now(), -1 if failure else 0))
            if failure is None and to_install:
                start = _now()
                failure = self._install_packages(prep, to_install)
                res.fases.append(PhaseTiming("install", start, _now(), failure.exit_code if failure else 0))
        finally:
            try:
                prep.remove(force=True)
            except Exception as exc:  # noqa: BLE001 — limpeza best-effort; cleanup_sandbox_containers cobre sobras
                logger.warning(f"Falha ao remover o container de preparação: {exc}")
        if failure is None:
            return True
        for name in ("stdout", "stderr", "exit_code", "timed_out", "install_failed", "fase_falha"):
            setattr(res, name, getattr(failure, name))
        return False

    def _introspect(self, container, res: SandboxResult) -> None:
        """Registra versão do Python e distribuições visíveis na execução. Best-effort (não derruba a execução)."""
        try:
            # -I (modo isolado) e workdir /tmp: nada de /outputs entra no sys.path nem na configuração.
            exec_result = container.exec_run([SANDBOX_VENV_PYTHON, "-I", "-c", _INTROSPECT_CODE], workdir="/tmp")
            if exec_result.exit_code != 0:
                raise RuntimeError(f"código de saída {exec_result.exit_code}")
            data = json.loads(exec_result.output)
            res.python_version = str(data["python"]).split()[0]
            res.pacotes = {name: version for name, version in data["all"]}
            res.packages_installed = sorted(f"{name}=={version}" for name, version in data["deps"])
        except Exception as exc:  # noqa: BLE001 — o registro não deve derrubar uma execução válida
            logger.warning(f"Não foi possível registrar os pacotes e a versão do Python: {exc}")


class _MountRefused(RuntimeError):
    """Origem de montagem ou configuração de entrega recusada antes de criar qualquer container."""
