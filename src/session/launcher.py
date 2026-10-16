"""Lançamento do processo da sessão (v18.7-background-sessions, design §1.2 e §1.3).

O terminal confirma o que exige o pesquisador (contexto, projeto e Problema, modo sem limite, retomada de sessão
resolvida), verifica a memória e grava o **arquivo de lançamento** (modo ``0600``, criado com ``O_EXCL``); o processo da
sessão o lê e o apaga ao iniciar. O prompt não vai na linha de comando (ficaria visível em ``ps``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src import config
from src.logger import get_logger
from src.session.manager import Session, SessionManager

logger = get_logger(__name__)

LAUNCH_VERSION = 1
LAUNCH_SUBDIR = ".launch"
SESSION_PROCESS_MODULE = "src.cli.session_process"
#: Nomes que nunca chegam ao processo da sessão; o gate persistente acrescenta aqui as credenciais do terminal.
FIXED_ENV_DENYLIST: tuple[str, ...] = ()
MAX_LAUNCH_BYTES = 4 * 1024 * 1024
MAX_PROMPT_CHARS = 200_000
MAX_CONTEXT_BLOCK_CHARS = 200_000
LAUNCH_KINDS = ("nova", "retomada")
LAUNCH_MODES = ("assisted", "semi", "auto")
LOG_TAIL_BYTES = 2000


class LaunchError(RuntimeError):
    """Arquivo de lançamento inválido ou processo da sessão que não chegou a registrar a sessão."""


@dataclass(frozen=True)
class LaunchSpec:
    """Conteúdo do arquivo de lançamento (dado não confiável na leitura)."""

    tipo: str
    prompt: str
    modo: str
    orcamento: dict[str, Any]
    contexto: dict[str, str]
    primeiro_plano: bool
    ilimitado: dict[str, str] | None = None
    projeto: dict[str, str | None] | None = None
    project_mode: str | None = None
    model_pin: str | None = None
    retomada: dict[str, Any] | None = None
    terminal_id: str | None = None
    resumo: str | None = None
    launch_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_json(self) -> str:
        return json.dumps({"versao_lancamento": LAUNCH_VERSION, **asdict(self)}, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Any) -> "LaunchSpec":
        """Valida e monta o lançamento; qualquer desvio levanta ``LaunchError`` (o processo sai com 1)."""
        if not isinstance(data, dict):
            raise LaunchError("arquivo de lançamento inválido: esperado um objeto JSON.")
        if data.get("versao_lancamento") != LAUNCH_VERSION:
            raise LaunchError(f"versão de lançamento não suportada: {data.get('versao_lancamento')!r}.")
        launch_id = data.get("launch_id")
        if not _is_uuid(launch_id):
            raise LaunchError("launch_id inválido (esperado UUID).")
        tipo, modo = data.get("tipo"), data.get("modo")
        if tipo not in LAUNCH_KINDS:
            raise LaunchError(f"tipo de lançamento inválido: {tipo!r}.")
        if modo not in LAUNCH_MODES:
            raise LaunchError(f"modo inválido no lançamento: {modo!r}.")
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
            raise LaunchError("prompt ausente ou acima do tamanho máximo.")
        orcamento = data.get("orcamento")
        contexto = data.get("contexto")
        if not isinstance(orcamento, dict):
            raise LaunchError("orçamento inválido no lançamento.")
        if not isinstance(contexto, dict) or not isinstance(contexto.get("dir"), str) or not isinstance(
            contexto.get("digest"), str
        ):
            raise LaunchError("contexto inválido no lançamento (esperado dir e digest).")
        projeto = data.get("projeto")
        if projeto is not None:
            if not isinstance(projeto, dict) or not isinstance(projeto.get("project_context", ""), str):
                raise LaunchError("projeto inválido no lançamento.")
            if len(projeto.get("project_context") or "") > MAX_CONTEXT_BLOCK_CHARS:
                raise LaunchError("contexto do projeto acima do tamanho máximo.")
        retomada = data.get("retomada")
        if tipo == "retomada":
            from src.session.continuity import SESSION_ID_RE

            if not isinstance(retomada, dict) or not isinstance(retomada.get("session_id"), str) or not (
                SESSION_ID_RE.fullmatch(retomada["session_id"])
            ):
                raise LaunchError("retomada sem session_id válido.")
        terminal_id = data.get("terminal_id")
        if terminal_id is not None and not _is_uuid(terminal_id):
            raise LaunchError("terminal_id inválido (esperado UUID).")
        ilimitado = data.get("ilimitado")
        if ilimitado is not None and not (
            isinstance(ilimitado, dict)
            and isinstance(ilimitado.get("origem"), str)
            and isinstance(ilimitado.get("confirmado_em"), str)
        ):
            raise LaunchError("ativação do modo sem limite inválida no lançamento.")
        return cls(
            tipo=tipo,
            prompt=prompt,
            modo=modo,
            orcamento=orcamento,
            contexto={"dir": contexto["dir"], "digest": contexto["digest"]},
            primeiro_plano=bool(data.get("primeiro_plano", False)),
            ilimitado=ilimitado,
            projeto=projeto,
            project_mode=data.get("project_mode"),
            model_pin=data.get("model_pin"),
            retomada=retomada if tipo == "retomada" else None,
            terminal_id=terminal_id,
            resumo=data.get("resumo") if isinstance(data.get("resumo"), str) else None,
            launch_id=launch_id,
        )


def _is_uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def context_digest(context_dir: str | Path) -> str:
    """SHA-256 do conteúdo de ``input_context/`` (caminhos relativos e bytes, em ordem); vazio se não existe."""
    root = Path(context_dir)
    digest = hashlib.sha256()
    if root.is_dir():
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def summarize_task(prompt: str, limit: int = 160) -> str:
    """Resumo da tarefa em poucas linhas para as listas do terminal, sem LLM (espaços normalizados e truncado)."""
    text = " ".join((prompt or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class MemoryCheck:
    """Resultado da verificação de memória antes de iniciar ou retomar (design §1.3)."""

    available_mb: float | None
    minimum_mb: float
    running: tuple[Session, ...] = ()

    @property
    def unknown(self) -> bool:
        return self.available_mb is None

    @property
    def ok(self) -> bool:
        return self.available_mb is not None and self.available_mb >= self.minimum_mb

    def message(self) -> str:
        if self.available_mb is None:
            return f"memória disponível desconhecida (mínimo configurado: MIN_AVAILABLE_MEMORY_MB={self.minimum_mb:g})"
        return (
            f"memória disponível {self.available_mb:g} MB abaixo do mínimo "
            f"MIN_AVAILABLE_MEMORY_MB={self.minimum_mb:g} MB"
        )


def check_memory(monitor: Any, running: Sequence[Session] = (), *, minimum_mb: float | None = None) -> MemoryCheck:
    """Lê a memória disponível (``HealthMonitor.get_memory_usage``) e a compara com ``MIN_AVAILABLE_MEMORY_MB``."""
    usage = monitor.get_memory_usage()
    available = float(usage["available_mb"]) if usage else None
    return MemoryCheck(
        available_mb=available,
        minimum_mb=float(config.MIN_AVAILABLE_MEMORY_MB if minimum_mb is None else minimum_mb),
        running=tuple(running),
    )


def launch_dir(base_dir: Path) -> Path:
    """Diretório ``<base>/.launch`` (modo ``0700``); nunca montado no sandbox, que só monta ``outputs/<session_id>``."""
    directory = Path(base_dir) / LAUNCH_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def write_launch_file(spec: LaunchSpec, base_dir: Path) -> Path:
    """Grava o lançamento com modo ``0600``, ``O_EXCL`` e ``O_NOFOLLOW``."""
    if not _is_uuid(spec.launch_id):
        raise LaunchError("launch_id inválido (esperado UUID).")
    path = launch_dir(base_dir) / f"{spec.launch_id}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(spec.to_json())
    return path


def read_launch_file(path: str | Path, *, delete: bool = True) -> LaunchSpec:
    """Lê e valida o lançamento (dado não confiável) e o apaga. Recusa link simbólico e dono diferente."""
    target = Path(path)
    try:
        info = os.lstat(target)
    except OSError as exc:
        raise LaunchError(f"arquivo de lançamento ilegível: {exc.strerror or exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise LaunchError("arquivo de lançamento recusado: não é um arquivo regular (link simbólico?).")
    if info.st_uid != os.getuid():
        raise LaunchError("arquivo de lançamento recusado: o dono não é o usuário deste processo.")
    if info.st_size > MAX_LAUNCH_BYTES:
        raise LaunchError("arquivo de lançamento acima do tamanho máximo.")
    try:
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            raw = handle.read(MAX_LAUNCH_BYTES + 1)
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise LaunchError(f"arquivo de lançamento inválido: {type(exc).__name__}.") from exc
    finally:
        if delete:
            try:
                target.unlink()
            except OSError:
                pass
    return LaunchSpec.from_dict(data)


def filtered_env(environ: Mapping[str, str], denylist: Sequence[str] | None = None) -> dict[str, str]:
    """Ambiente do processo da sessão: sem os nomes negados e com o marcador que ativa o filtro pós-``.env``."""
    denied = set(FIXED_ENV_DENYLIST)
    denied.update(n.strip() for n in environ.get("SESSION_ENV_DENYLIST", "").split(",") if n.strip())
    denied.update(denylist or ())
    env = {k: v for k, v in environ.items() if k not in denied}
    env[config.SESSION_PROCESS_MARKER] = "1"
    return env


def spawn_session(
    launch_path: Path,
    *,
    foreground: bool,
    log_dir: Path | None = None,
    module: str = SESSION_PROCESS_MODULE,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Cria o processo da sessão: ``python -m <módulo> --launch <caminho>`` com ``stdin`` fechado.

    Em segundo plano (REPL e ``--background``) o processo tem grupo próprio e ``stdout``/``stderr`` em
    ``logs/sessions/<launch_id>.log`` (``0600``); em primeiro plano herda a saída do terminal e o grupo.
    """
    args = [sys.executable, "-m", module, "--launch", str(launch_path)]
    process_env = filtered_env(os.environ if env is None else env)
    if foreground:
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, env=process_env, cwd=cwd)
    directory = Path(log_dir or config.SESSION_LOG_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    log_path = directory / f"{launch_path.stem}.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        return subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, env=process_env, cwd=cwd, start_new_session=True
        )
    finally:
        os.close(fd)


def log_tail(launch_path: Path, log_dir: Path | None = None) -> str:
    """Fim do log do processo em segundo plano (para a mensagem de falha do lançamento)."""
    log_path = Path(log_dir or config.SESSION_LOG_DIR) / f"{launch_path.stem}.log"
    try:
        with open(log_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(handle.tell() - LOG_TAIL_BYTES, 0))
            return handle.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


async def wait_registered(
    launch_id: str,
    proc: subprocess.Popen[bytes],
    timeout: float,
    *,
    session_manager: SessionManager | None = None,
    poll_seconds: float = 0.2,
    clock: Callable[[], float] = time.monotonic,
    on_failure_detail: Callable[[], str] | None = None,
) -> Session:
    """Espera a sessão com ``payload.launch_id`` e ``pid`` gravados; falha se o processo termina antes ou o prazo vence.

    Raises:
        LaunchError: O processo terminou sem registrar a sessão (cita o código de saída e o fim do log) ou o prazo
            ``timeout`` (``SESSION_LAUNCH_TIMEOUT_SECONDS``) esgotou.
    """
    manager = session_manager or SessionManager()
    deadline = clock() + timeout
    while True:
        session = await asyncio.to_thread(manager.find_by_launch_id, launch_id)
        if session is not None and session.pid is not None:
            return session
        code = proc.poll()
        if code is not None:
            # Um último olhar: o processo pode ter registrado e terminado rápido (ex.: erro logo depois).
            session = await asyncio.to_thread(manager.find_by_launch_id, launch_id)
            if session is not None and session.pid is not None:
                return session
            detail = on_failure_detail() if on_failure_detail else ""
            raise LaunchError(
                f"o processo da sessão terminou com código {code} antes de registrar a sessão."
                + (f"\n{detail}" if detail else "")
            )
        if clock() >= deadline:
            raise LaunchError(
                f"o processo da sessão não registrou a sessão em {timeout:g} s (SESSION_LAUNCH_TIMEOUT_SECONDS)."
            )
        await asyncio.sleep(poll_seconds)
