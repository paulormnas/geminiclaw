"""Corpo dos registros ``inicio`` e ``termino`` a partir da chamada da skill de código e do resultado do sandbox."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.logger import get_logger
from src.provenance.canonical import json_sha256, metric_text, sha256_text
from src.provenance.hashing import HashCache, hash_file, sha256_file

logger = get_logger(__name__)

STATUS_SUCESSO = "sucesso"
STATUS_FALHA_EXECUCAO = "falha_execucao"
STATUS_TIMEOUT = "timeout"
STATUS_FALHA_INSTALL = "falha_install"
STATUS_FALHA_FETCH = "falha_fetch_assets"
STATUS_ERRO_SANDBOX = "erro_sandbox"
STATUS_ERRO_ORQUESTRADOR = "erro_orquestrador"
STATUSES = (
    STATUS_SUCESSO, STATUS_FALHA_EXECUCAO, STATUS_TIMEOUT, STATUS_FALHA_INSTALL, STATUS_FALHA_FETCH,
    STATUS_ERRO_SANDBOX, STATUS_ERRO_ORQUESTRADOR,
)


def status_of(result: Any | None, error: BaseException | None = None) -> str:
    """``status`` do ``termino`` a partir do ``SandboxResult`` (ou da exceção que impediu o resultado)."""
    if result is None or error is not None:
        return STATUS_ERRO_ORQUESTRADOR
    if result.timed_out:
        return STATUS_TIMEOUT
    if result.install_failed or result.fase_falha == "install":
        return STATUS_FALHA_INSTALL
    if result.fase_falha == "fetch_assets":
        return STATUS_FALHA_FETCH
    if result.fase_falha == "infra" or result.infra_error or (result.exit_code == -1 and not result.fases):
        return STATUS_ERRO_SANDBOX
    return STATUS_SUCESSO if result.exit_code == 0 else STATUS_FALHA_EXECUCAO


@dataclass
class FileStamp:
    """Estado de um arquivo de saída antes da execução (tamanho e ``mtime_ns``)."""

    size: int
    mtime_ns: int


def snapshot_dir_state(directory: Path) -> dict[str, FileStamp]:
    """``{caminho relativo: (tamanho, mtime_ns)}`` dos arquivos de ``directory`` (sem seguir symlinks)."""
    state: dict[str, FileStamp] = {}
    if not directory.is_dir():
        return state
    for dirpath, _dirs, filenames in os.walk(directory, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            state[path.relative_to(directory).as_posix()] = FileStamp(stat.st_size, stat.st_mtime_ns)
    return state


def _walk_files(directory: Path) -> Iterable[Path]:
    if not directory.is_dir() or directory.is_symlink():
        return
    for dirpath, _dirs, filenames in os.walk(directory, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if not path.is_symlink() and path.is_file():
                yield path


def _entry(path: Path, base: Path, cache: HashCache | None) -> dict[str, Any]:
    try:
        rel = path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    try:
        digest, size = hash_file(path, cache)
    except OSError as exc:
        return {"caminho": rel, "sha256": None, "tamanho": None, "erro": type(exc).__name__}
    return {"caminho": rel, "sha256": digest, "tamanho": size}


def collect_inputs(
    *, output_root: Path, session_id: str, task_name: str, prior_dirs: Iterable[Path], cache: HashCache | None
) -> list[dict[str, Any]]:
    """Tudo que o script vê somente leitura: ``input_snapshot/``, ``/prior/*`` e o que já existia na pasta da tarefa."""
    session_dir = output_root / session_id
    roots = [session_dir / "input_snapshot", session_dir / task_name, *[Path(d) for d in prior_dirs]]
    rows: dict[str, dict[str, Any]] = {}
    for root in roots:
        for path in _walk_files(root):
            if root.name == task_name and path.name.startswith("step_"):
                continue
            row = _entry(path, output_root, cache)
            rows[row["caminho"]] = row
    return [rows[k] for k in sorted(rows)]


def collect_outputs(
    *,
    output_root: Path,
    session_id: str,
    task_name: str,
    before: Mapping[str, FileStamp],
    ignore_names: Iterable[str],
    cache: HashCache | None,
) -> list[dict[str, Any]]:
    """Arquivos novos ou alterados em ``outputs/<sessão>/<tarefa>/`` (exceto ``step_*`` e os injetados)."""
    task_dir = output_root / session_id / task_name
    ignored = set(ignore_names)
    rows: list[dict[str, Any]] = []
    for rel, stamp in sorted(snapshot_dir_state(task_dir).items()):
        name = rel.rsplit("/", 1)[-1]
        if name.startswith("step_") or rel in ignored:
            continue
        old = before.get(rel)
        if old is not None and (old.size, old.mtime_ns) == (stamp.size, stamp.mtime_ns):
            continue
        rows.append(_entry(task_dir / rel, output_root, cache))
    return rows


def inicio_body(
    *,
    code: str,
    extra_files: Mapping[str, str] | None,
    inputs: list[dict[str, Any]],
    packages: list[str],
    assets: list[dict[str, Any]],
    image: str,
) -> dict[str, Any]:
    """Corpo do ``inicio`` (gravado antes de qualquer container)."""
    return {
        "hash_codigo": sha256_text(code),
        "arquivos_injetados": [
            {"nome": name, "sha256": sha256_text(text)} for name, text in sorted((extra_files or {}).items())
        ],
        "entradas": inputs,
        "pacotes_solicitados": list(packages),
        "ativos_declarados": [
            {key: (a.get(key) if isinstance(a.get(key), str) else None) for key in ("url", "destino", "sha256")}
            for a in assets
            if isinstance(a, dict)
        ],
        "imagem_solicitada": image,
    }


@dataclass
class ReadMetrics:
    """Leitura de ``params.json``/``metrics.json`` de uma execução."""

    hash_params: str | None = None
    seed: int | None = None
    metricas: dict[str, str] = field(default_factory=dict)
    hash_metrics: str | None = None
    metrics_invalido: bool = False


def read_metrics(task_dir: Path) -> ReadMetrics:
    """``hash_params``, ``seed``, métricas (texto) e ``hash_metrics`` dos arquivos da tarefa."""
    out = ReadMetrics()
    params_data: dict[str, Any] = {}
    params_file = task_dir / "params.json"
    if params_file.is_file():
        try:
            loaded = json.loads(params_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                params_data = loaded
                parameters = loaded.get("parameters")
                if parameters:
                    out.hash_params = json_sha256(parameters)
        except (OSError, ValueError):
            logger.warning("params.json ilegível; hash_params fica nulo", extra={"path": str(params_file)})
    metrics_data: dict[str, Any] = {}
    metrics_file = task_dir / "metrics.json"
    if metrics_file.is_file():
        try:
            out.hash_metrics = sha256_file(metrics_file)
            loaded = json.loads(metrics_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metrics_data = loaded
                raw_metrics = loaded.get("metrics")
                if isinstance(raw_metrics, dict):
                    for name, value in raw_metrics.items():
                        text = metric_text(value)
                        if text is not None:
                            out.metricas[str(name)] = text
            else:
                out.metrics_invalido = True
        except (OSError, ValueError):
            out.metrics_invalido = True
    seed = params_data.get("seed", metrics_data.get("seed"))
    out.seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else None
    return out


def termino_body(
    *,
    inicio: Mapping[str, Any],
    inicio_hash: str,
    status: str,
    result: Any | None,
    outputs: list[dict[str, Any]],
    metrics: ReadMetrics,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """Corpo do ``termino`` (autossuficiente: repete código, injetados e entradas do ``inicio``)."""
    body: dict[str, Any] = {
        "inicio_hash": inicio_hash,
        "status": status,
        "hash_codigo": inicio.get("hash_codigo"),
        "arquivos_injetados": inicio.get("arquivos_injetados", []),
        "entradas": inicio.get("entradas", []),
        "hash_params": metrics.hash_params,
        "seed": metrics.seed,
        "saidas": outputs,
        "metricas": dict(sorted(metrics.metricas.items())),
        "hash_metrics": metrics.hash_metrics,
        "metrics_invalido": metrics.metrics_invalido,
    }
    if error is not None:
        body["erro_tipo"] = type(error).__name__
    if result is None:
        body.update(
            fase_falha=None, download_nao_declarado=False, rede_na_execucao=False, exit_code=None,
            inicio_execucao=None, fim_execucao=None, fases=[], imagem=None, python_version=None, pacotes={},
            ativos=[],
        )
        return body
    execute = next((p for p in result.fases if p.nome == "execute"), None)
    body.update(
        fase_falha=result.fase_falha,
        download_nao_declarado=bool(result.download_nao_declarado),
        rede_na_execucao=bool(result.rede_na_execucao),
        exit_code=result.exit_code,
        inicio_execucao=execute.inicio if execute else None,
        fim_execucao=execute.fim if execute else None,
        fases=[
            {"nome": p.nome, "inicio": p.inicio, "fim": p.fim, "exit_code": p.exit_code} for p in result.fases
        ],
        imagem=(
            {"nome": result.imagem.nome, "id": result.imagem.id, "repo_digests": list(result.imagem.repo_digests)}
            if result.imagem is not None
            else {"nome": result.image or None, "id": None, "repo_digests": []}
        ),
        python_version=result.python_version,
        pacotes=dict(sorted(result.pacotes.items())),
        ativos=[
            {
                "url": a.url, "sha256": a.sha256, "destino": a.destino, "tamanho": a.tamanho,
                "hash_declarado": bool(a.hash_declarado), "origem": a.origem,
            }
            for a in result.ativos
        ],
    )
    return body
