"""Livro de execuções: ``inicio`` e ``termino`` por execução do sandbox, em cadeia de hash por projeto.

Ver o design §1–§5 e §9 de ``v18.5-execution-provenance``.

``begin`` é *fail-fast*: sem o registro de ``inicio`` a execução não começa. ``finish`` nunca perde um ``termino``: se o
armazenamento estiver indisponível, o registro vai para ``outputs/<sessão>/provenance_pending.jsonl`` (com ``fsync``) e
é acrescentado na próxima gravação possível; se nem o arquivo aceitar, o erro é explícito.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.logger import get_logger
from src.provenance.canonical import sha256_text
from src.provenance.errors import MetricNotRecorded, ProvenanceError, ProvenanceUnavailable
from src.provenance.store import (
    TIPO_INICIO,
    TIPO_TERMINO,
    DuplicateRecord,
    LedgerStore,
    PostgresStore,
    StoredRecord,
)

logger = get_logger(__name__)

PENDING_FILE = "provenance_pending.jsonl"
LOCAL_TIME_KEY = "registrado_localmente_em"
NO_PROJECT_PREFIX = "sem_projeto:"
PENDING_WRITE_ERROR = "término não registrado nem guardado localmente"


def _tip_dict(record: StoredRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {"project_id": record.project_id, "seq": record.seq, "record_hash": record.record_hash}


def chain_id_for(project_id: str | None, session_id: str) -> str:
    """Identificador da cadeia: o projeto; sem projeto (``sem_grafo`` ou chamada programática), uma cadeia por sessão.

    A cadeia por sessão mantém a execução registrada quando o grafo está fora do ar (contorno explícito de
    ``RESEARCH_PROJECT_GRAPH_OPTIONAL``); o relatório e o ``verify`` a identificam pelo prefixo ``sem_projeto:``.
    """
    return project_id if project_id else f"{NO_PROJECT_PREFIX}{session_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def corpo_sha256(corpo: dict[str, Any]) -> str:
    return sha256_text(json.dumps(corpo, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


@dataclass(frozen=True)
class RecordedMetric:
    """Métrica registrada no ``termino`` (fonte de ``{{res:<exec_id>/<nome>}}``)."""

    valor_texto: str
    exec_id: str
    seq: int
    record_hash: str


@dataclass(frozen=True)
class BeginResult:
    exec_id: str
    chain_id: str
    record: StoredRecord


@dataclass(frozen=True)
class FinishResult:
    record: StoredRecord | None  # None quando o término ficou pendente
    pending: bool


@dataclass
class FlushReport:
    appended: list[str] = field(default_factory=list)  # exec_ids acrescentados à cadeia
    already: list[str] = field(default_factory=list)  # já estavam na cadeia com o mesmo corpo
    conflicts: list[str] = field(default_factory=list)  # já na cadeia com corpo diferente (ou pendência adulterada)
    remaining: list[str] = field(default_factory=list)  # continuam no arquivo


@dataclass(frozen=True)
class ExperimentProvenance:
    """Campos do ``Experimento`` derivados do ``termino`` principal da subtarefa (design §9)."""

    exec_ids: list[str]
    exec_id: str
    hash_codigo: str | None
    hash_params: str | None
    seed: int | None
    ambiente: dict[str, Any]
    metricas: dict[str, str]
    hash_metrics: str | None
    status: str
    termino: StoredRecord


class ExecutionLedger:
    """Livro de execuções sobre um :class:`LedgerStore`."""

    def __init__(self, store: LedgerStore, output_dir: Path | str = "outputs") -> None:
        self.store = store
        self.output_dir = Path(output_dir)
        self._lock = threading.Lock()
        self._tips: dict[str, StoredRecord] = {}
        self._pending: dict[str, set[str]] = {}

    # --- caminhos e pendências -------------------------------------------------------------------------------------

    def pending_path(self, session_id: str, output_dir: Path | str | None = None) -> Path:
        return Path(output_dir if output_dir is not None else self.output_dir) / session_id / PENDING_FILE

    def _read_pending(self, session_id: str, output_dir: Path | str | None = None) -> list[dict[str, Any]]:
        path = self.pending_path(session_id, output_dir)
        if not path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"exec_id": "?", "invalido": line[:200]})
        return entries

    def pending_for_subtask(self, session_id: str, subtask_id: str, output_dir: Path | str | None = None) -> list[str]:
        """``exec_id`` dos términos pendentes da sessão que pertencem à subtarefa."""
        return [
            str(e.get("exec_id"))
            for e in self._read_pending(session_id, output_dir)
            if e.get("exec_id") and e.get("subtask_id") == subtask_id
        ]

    def pending_exec_ids(self, session_id: str, output_dir: Path | str | None = None) -> list[str]:
        """``exec_id`` dos términos pendentes da sessão (arquivo local)."""
        return [str(e.get("exec_id")) for e in self._read_pending(session_id, output_dir) if e.get("exec_id")]

    def _write_pending(
        self, session_id: str, entries: list[dict[str, Any]], output_dir: Path | str | None = None
    ) -> None:
        path = self.pending_path(session_id, output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not entries:
            path.unlink(missing_ok=True)
            return
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".pending-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for entry in entries:
                    handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _append_pending(self, entry: dict[str, Any], output_dir: Path | str | None = None) -> None:
        path = self.pending_path(entry["session_id"], output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    # --- ponta da cadeia -------------------------------------------------------------------------------------------

    def _remember(self, record: StoredRecord) -> None:
        with self._lock:
            current = self._tips.get(record.project_id)
            if current is None or record.seq >= current.seq:
                self._tips[record.project_id] = record

    def known_tip(self, project_id: str) -> dict[str, Any] | None:
        """Última ponta acrescentada por este processo (sem consulta ao banco; usada em cada checkpoint)."""
        with self._lock:
            record = self._tips.get(project_id)
        return _tip_dict(record)

    def chain_tip(self, project_id: str) -> dict[str, Any] | None:
        """Ponta atual da cadeia no armazenamento: ``{project_id, seq, record_hash}`` ou ``None``."""
        record = self.store.tip(project_id)
        return _tip_dict(record)

    # --- gravação --------------------------------------------------------------------------------------------------

    def begin(
        self,
        *,
        project_id: str | None,
        session_id: str,
        subtask_id: str | None,
        task_name: str,
        body: dict[str, Any],
        output_dir: Path | str | None = None,
    ) -> BeginResult:
        """Grava o ``inicio``. Acrescenta antes os términos pendentes da sessão.

        Raises:
            ProvenanceUnavailable: O armazenamento não aceitou o registro; a execução NÃO deve começar.
        """
        chain = chain_id_for(project_id, session_id)
        self.flush_pending(session_id, output_dir)
        exec_id = f"exec_{uuid.uuid4()}"
        record = self.store.append(
            project_id=chain, exec_id=exec_id, tipo=TIPO_INICIO, session_id=session_id, subtask_id=subtask_id,
            task_name=task_name, registrado_em=_now(), corpo=body,
        )
        self._remember(record)
        return BeginResult(exec_id, chain, record)

    def finish(
        self,
        *,
        exec_id: str,
        chain_id: str,
        session_id: str,
        subtask_id: str | None,
        task_name: str,
        body: dict[str, Any],
        output_dir: Path | str | None = None,
    ) -> FinishResult:
        """Grava o ``termino``; sem armazenamento, guarda-o em ``provenance_pending.jsonl``.

        Raises:
            ProvenanceError: Nem o armazenamento nem o arquivo local aceitaram o registro.
        """
        stamp = _now()
        try:
            record = self.store.append(
                project_id=chain_id, exec_id=exec_id, tipo=TIPO_TERMINO, session_id=session_id,
                subtask_id=subtask_id, task_name=task_name, registrado_em=stamp, corpo=body,
            )
        except ProvenanceUnavailable as exc:
            logger.warning(
                "Término da execução guardado localmente (registro indisponível)",
                extra={"exec_id": exec_id, "erro": str(exc)[:200]},
            )
            entry = {
                "exec_id": exec_id, "project_id": chain_id, "tipo": TIPO_TERMINO, "session_id": session_id,
                "subtask_id": subtask_id, "task_name": task_name, "registrado_em": stamp, "corpo": body,
                "corpo_sha256": corpo_sha256(body),
            }
            try:
                self._append_pending(entry, output_dir)
            except OSError as io_exc:
                raise ProvenanceError(f"{PENDING_WRITE_ERROR}: {io_exc}") from io_exc
            with self._lock:
                self._pending.setdefault(session_id, set()).add(exec_id)
            return FinishResult(None, True)
        self._remember(record)
        return FinishResult(record, False)

    def flush_pending(self, session_id: str, output_dir: Path | str | None = None) -> FlushReport:
        """Acrescenta à cadeia os términos pendentes da sessão (idempotente) e reescreve o arquivo sem eles."""
        report = FlushReport()
        entries = self._read_pending(session_id, output_dir)
        if not entries:
            return report
        keep: list[dict[str, Any]] = []
        unavailable = False
        for entry in entries:
            exec_id = str(entry.get("exec_id", "?"))
            if unavailable:
                keep.append(entry)
                report.remaining.append(exec_id)
                continue
            corpo = entry.get("corpo")
            if not isinstance(corpo, dict) or entry.get("corpo_sha256") != corpo_sha256(corpo):
                keep.append(entry)
                report.conflicts.append(exec_id)
                continue
            try:
                body = {**corpo, LOCAL_TIME_KEY: entry.get("registrado_em")}
                record = self.store.append(
                    project_id=entry["project_id"], exec_id=exec_id, tipo=TIPO_TERMINO,
                    session_id=entry["session_id"], subtask_id=entry.get("subtask_id"),
                    task_name=entry["task_name"], registrado_em=_now(), corpo=body,
                )
                self._remember(record)
                report.appended.append(exec_id)
            except DuplicateRecord:
                existing = self.store.get(exec_id, TIPO_TERMINO)
                stored = {k: v for k, v in (existing.corpo if existing else {}).items() if k != LOCAL_TIME_KEY}
                if existing is not None and stored == corpo:
                    report.already.append(exec_id)
                else:
                    keep.append(entry)
                    report.conflicts.append(exec_id)
            except ProvenanceUnavailable:
                unavailable = True
                keep.append(entry)
                report.remaining.append(exec_id)
        try:
            self._write_pending(session_id, keep, output_dir)
        except OSError as exc:
            logger.warning("Arquivo de pendências não reescrito", extra={"erro": type(exc).__name__})
        with self._lock:
            self._pending[session_id] = {str(e.get("exec_id")) for e in keep if e.get("exec_id")}
        return report

    def check_tip(self, tip: dict[str, Any]) -> str:
        """Confere uma ponta de checkpoint contra a cadeia: ``"ok"``, ``"divergente"`` ou ``"indisponivel"``."""
        try:
            record = self.store.at(str(tip.get("project_id")), int(tip.get("seq")))  # type: ignore[arg-type]
        except ProvenanceUnavailable:
            return "indisponivel"
        except (TypeError, ValueError):
            return "divergente"
        return "ok" if record is not None and record.record_hash == tip.get("record_hash") else "divergente"

    # --- consultas -------------------------------------------------------------------------------------------------

    def get_metric(self, exec_id: str, nome: str) -> RecordedMetric:
        """Valor registrado da métrica ``nome`` no ``termino`` de ``exec_id``.

        Raises:
            MetricNotRecorded: A execução, o ``termino`` ou a métrica não existem (nunca devolve valor padrão).
        """
        record = self.store.get(exec_id, TIPO_TERMINO)
        if record is None:
            raise MetricNotRecorded(f"execução '{exec_id}' sem registro de término.")
        metrics = record.corpo.get("metricas") or {}
        if nome not in metrics:
            raise MetricNotRecorded(f"a execução '{exec_id}' não registrou a métrica '{nome}'.")
        return RecordedMetric(str(metrics[nome]), exec_id, record.seq, record.record_hash)

    def derive_experiment_fields(self, subtask_id: str) -> ExperimentProvenance | None:
        """Campos do ``Experimento`` derivados do ``termino`` principal da subtarefa (design §9).

        Principal: o último ``termino`` com ``status="sucesso"`` cujas ``saidas`` contêm ``metrics.json``; na falta, o
        último ``termino`` da subtarefa. ``None`` se a subtarefa não tem execução registrada.
        """
        terminos = [r for r in self.store.by_subtask(subtask_id) if r.tipo == TIPO_TERMINO]
        if not terminos:
            return None

        def has_metrics(rec: StoredRecord) -> bool:
            return any(str(s.get("caminho", "")).endswith("/metrics.json") for s in rec.corpo.get("saidas") or [])

        with_metrics = [r for r in terminos if r.corpo.get("status") == "sucesso" and has_metrics(r)]
        main = with_metrics[-1] if with_metrics else terminos[-1]
        body = main.corpo
        seed = body.get("seed")
        return ExperimentProvenance(
            exec_ids=[r.exec_id for r in terminos],
            exec_id=main.exec_id,
            hash_codigo=body.get("hash_codigo"),
            hash_params=body.get("hash_params"),
            seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
            ambiente={
                "python": body.get("python_version"),
                "imagem": body.get("imagem"),
                "pacotes": body.get("pacotes"),
                "ativos": body.get("ativos"),
            },
            metricas={str(k): str(v) for k, v in (body.get("metricas") or {}).items()},
            hash_metrics=body.get("hash_metrics"),
            status=str(body.get("status")),
            termino=main,
        )


# --- instância compartilhada ----------------------------------------------------------------------------------------

_ledger: ExecutionLedger | None = None
_ledger_lock = threading.Lock()


def get_ledger() -> ExecutionLedger:
    """Livro de execuções do processo (PostgreSQL por padrão; ``OUTPUT_BASE_DIR`` para as pendências)."""
    global _ledger
    with _ledger_lock:
        if _ledger is None:
            from src import config

            _ledger = ExecutionLedger(PostgresStore(), config.OUTPUT_BASE_DIR)
        return _ledger


def set_ledger(ledger: ExecutionLedger | None) -> None:
    """Substitui (ou, com ``None``, descarta) o livro do processo. Uso em testes e na troca de diretório de saída."""
    global _ledger
    with _ledger_lock:
        _ledger = ledger
