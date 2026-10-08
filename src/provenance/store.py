"""Armazenamento dos registros de execução: PostgreSQL (produção) e memória (testes).

O acréscimo é **serializado por projeto**: no PostgreSQL, com ``pg_advisory_xact_lock`` na mesma transação do
``INSERT``, de modo que execuções paralelas e sessões concorrentes nunca criem bifurcação nem lacuna na cadeia
(design §3).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from src.logger import get_logger
from src.provenance.canonical import RECORD_FORMAT, ZERO_HASH, record_hash
from src.provenance.errors import ProvenanceUnavailable

logger = get_logger(__name__)

LOCK_CLASSID = 19019  # identifica o uso do advisory lock (ADR 019 §4)
TABLE_MISSING_HINT = (
    "A tabela execution_records não existe. Aplique a migração com `uv run python scripts/migrate_v18_5_provenance.py` "
    "(com aprovação do pesquisador) e tente novamente."
)

TIPO_INICIO = "inicio"
TIPO_TERMINO = "termino"
TIPOS = (TIPO_INICIO, TIPO_TERMINO)


class DuplicateRecord(Exception):
    """Já existe um registro com o mesmo ``(exec_id, tipo)`` (acréscimo repetido)."""


@dataclass(frozen=True)
class StoredRecord:
    """Registro da cadeia, como lido do armazenamento."""

    project_id: str
    seq: int
    exec_id: str
    tipo: str
    session_id: str
    subtask_id: str | None
    task_name: str
    registrado_em: str
    prev_hash: str
    record_hash: str
    corpo: dict[str, Any]

    def hashed_form(self) -> dict[str, Any]:
        """O registro tal como entra no hash (design §1)."""
        return {
            "formato": RECORD_FORMAT,
            "project_id": self.project_id,
            "seq": self.seq,
            "exec_id": self.exec_id,
            "tipo": self.tipo,
            "session_id": self.session_id,
            "subtask_id": self.subtask_id,
            "task_name": self.task_name,
            "registrado_em": self.registrado_em,
            "prev_hash": self.prev_hash,
            "corpo": self.corpo,
        }

    def recompute_hash(self) -> str:
        return record_hash(self.hashed_form())

    def to_export(self) -> dict[str, Any]:
        """Linha de ``execution_records.jsonl``: o registro hasheado mais o ``record_hash``."""
        return {**self.hashed_form(), "record_hash": self.record_hash}

    @classmethod
    def from_export(cls, data: dict[str, Any]) -> "StoredRecord":
        return cls(
            project_id=data["project_id"],
            seq=int(data["seq"]),
            exec_id=data["exec_id"],
            tipo=data["tipo"],
            session_id=data["session_id"],
            subtask_id=data.get("subtask_id"),
            task_name=data["task_name"],
            registrado_em=data["registrado_em"],
            prev_hash=data["prev_hash"],
            record_hash=data["record_hash"],
            corpo=dict(data["corpo"]),
        )


def build_record(
    *,
    project_id: str,
    seq: int,
    prev_hash: str,
    exec_id: str,
    tipo: str,
    session_id: str,
    subtask_id: str | None,
    task_name: str,
    registrado_em: str,
    corpo: dict[str, Any],
) -> StoredRecord:
    """Monta o registro e calcula o seu ``record_hash``."""
    partial = StoredRecord(
        project_id, seq, exec_id, tipo, session_id, subtask_id, task_name, registrado_em, prev_hash, "", corpo
    )
    return StoredRecord(**{**partial.__dict__, "record_hash": partial.recompute_hash()})


class LedgerStore(Protocol):
    """Contrato do armazenamento (síncrono; o chamador usa ``asyncio.to_thread``)."""

    def check_ready(self) -> None: ...

    def append(
        self,
        *,
        project_id: str,
        exec_id: str,
        tipo: str,
        session_id: str,
        subtask_id: str | None,
        task_name: str,
        registrado_em: str,
        corpo: dict[str, Any],
    ) -> StoredRecord: ...

    def get(self, exec_id: str, tipo: str) -> StoredRecord | None: ...

    def tip(self, project_id: str) -> StoredRecord | None: ...

    def at(self, project_id: str, seq: int) -> StoredRecord | None: ...

    def records(self, project_id: str) -> list[StoredRecord]: ...

    def by_session(self, session_id: str) -> list[StoredRecord]: ...

    def by_subtask(self, subtask_id: str) -> list[StoredRecord]: ...

    def projects_of_session(self, session_id: str) -> list[str]: ...


class MemoryStore:
    """Armazenamento em memória com a mesma semântica de acréscimo (testes e verificação de exportações)."""

    def __init__(self) -> None:
        self._rows: dict[str, list[StoredRecord]] = {}
        self._lock = threading.Lock()
        self.unavailable = False  # testes: simula banco fora do ar

    def check_ready(self) -> None:
        if self.unavailable:
            raise ProvenanceUnavailable("armazenamento do registro indisponível (simulado)")

    def append(
        self,
        *,
        project_id: str,
        exec_id: str,
        tipo: str,
        session_id: str,
        subtask_id: str | None,
        task_name: str,
        registrado_em: str,
        corpo: dict[str, Any],
    ) -> StoredRecord:
        self.check_ready()
        with self._lock:
            rows = self._rows.setdefault(project_id, [])
            if any(r.exec_id == exec_id and r.tipo == tipo for chain in self._rows.values() for r in chain):
                raise DuplicateRecord(f"{exec_id}/{tipo}")
            seq = rows[-1].seq + 1 if rows else 1
            prev = rows[-1].record_hash if rows else ZERO_HASH
            record = build_record(
                project_id=project_id, seq=seq, prev_hash=prev, exec_id=exec_id, tipo=tipo, session_id=session_id,
                subtask_id=subtask_id, task_name=task_name, registrado_em=registrado_em, corpo=_roundtrip(corpo),
            )
            rows.append(record)
            return record

    def get(self, exec_id: str, tipo: str) -> StoredRecord | None:
        self.check_ready()
        with self._lock:
            for chain in self._rows.values():
                for row in chain:
                    if row.exec_id == exec_id and row.tipo == tipo:
                        return row
        return None

    def tip(self, project_id: str) -> StoredRecord | None:
        self.check_ready()
        with self._lock:
            rows = self._rows.get(project_id) or []
            return rows[-1] if rows else None

    def at(self, project_id: str, seq: int) -> StoredRecord | None:
        self.check_ready()
        with self._lock:
            return next((r for r in self._rows.get(project_id, []) if r.seq == seq), None)

    def records(self, project_id: str) -> list[StoredRecord]:
        self.check_ready()
        with self._lock:
            return list(self._rows.get(project_id, []))

    def by_session(self, session_id: str) -> list[StoredRecord]:
        self.check_ready()
        with self._lock:
            found = [r for chain in self._rows.values() for r in chain if r.session_id == session_id]
        return sorted(found, key=lambda r: (r.project_id, r.seq))

    def by_subtask(self, subtask_id: str) -> list[StoredRecord]:
        self.check_ready()
        with self._lock:
            found = [r for chain in self._rows.values() for r in chain if r.subtask_id == subtask_id]
        return sorted(found, key=lambda r: (r.project_id, r.seq))

    def projects_of_session(self, session_id: str) -> list[str]:
        return sorted({r.project_id for r in self.by_session(session_id)})

    def tamper(self, project_id: str, seq: int, **changes: Any) -> None:
        """Testes: altera um registro diretamente (simula adulteração com os gatilhos desativados)."""
        from dataclasses import replace

        with self._lock:
            rows = self._rows[project_id]
            index = next(i for i, r in enumerate(rows) if r.seq == seq)
            rows[index] = replace(rows[index], **changes)


def _roundtrip(corpo: dict[str, Any]) -> dict[str, Any]:
    """Cópia via JSON (como o JSONB): garante que o hash recalculado depois seja o do que foi gravado."""
    return json.loads(json.dumps(corpo, ensure_ascii=False, sort_keys=True))


_COLUMNS = (
    "project_id, seq, exec_id, tipo, session_id, subtask_id, task_name, registrado_em, prev_hash, record_hash, corpo"
)


def _from_row(row: dict[str, Any]) -> StoredRecord:
    return StoredRecord(
        project_id=row["project_id"],
        seq=int(row["seq"]),
        exec_id=row["exec_id"],
        tipo=row["tipo"],
        session_id=row["session_id"],
        subtask_id=row["subtask_id"],
        task_name=row["task_name"],
        registrado_em=row["registrado_em"],
        prev_hash=str(row["prev_hash"]).strip(),
        record_hash=str(row["record_hash"]).strip(),
        corpo=row["corpo"] if isinstance(row["corpo"], dict) else json.loads(row["corpo"]),
    )


class PostgresStore:
    """Tabela ``execution_records`` (somente-acréscimo, com gatilhos), via o pool de ``src.db``."""

    def __init__(self) -> None:
        self._ready = False

    @staticmethod
    def _unavailable(exc: Exception) -> ProvenanceUnavailable:
        import psycopg

        if isinstance(exc, psycopg.errors.UndefinedTable):
            return ProvenanceUnavailable(TABLE_MISSING_HINT)
        return ProvenanceUnavailable(
            f"banco de dados indisponível para o registro de execuções ({type(exc).__name__}): {exc}"
        )

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        import psycopg
        from psycopg_pool import PoolTimeout

        return isinstance(exc, (psycopg.OperationalError, psycopg.errors.UndefinedTable, PoolTimeout, OSError))

    def _run(self, fn):  # noqa: ANN001, ANN202
        from src.db import get_connection

        try:
            with get_connection() as conn:
                return fn(conn)
        except DuplicateRecord:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._is_connection_error(exc):
                raise self._unavailable(exc) from exc
            raise

    def check_ready(self) -> None:
        if self._ready:
            return

        def check(conn):  # noqa: ANN001, ANN202
            conn.execute("SELECT 1 FROM execution_records LIMIT 1")

        self._run(check)
        self._ready = True

    def append(
        self,
        *,
        project_id: str,
        exec_id: str,
        tipo: str,
        session_id: str,
        subtask_id: str | None,
        task_name: str,
        registrado_em: str,
        corpo: dict[str, Any],
    ) -> StoredRecord:
        import psycopg
        from psycopg.types.json import Jsonb

        def append_tx(conn):  # noqa: ANN001, ANN202
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (LOCK_CLASSID, project_id))
                tip = conn.execute(
                    "SELECT seq, record_hash FROM execution_records WHERE project_id = %s ORDER BY seq DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
                seq = int(tip["seq"]) + 1 if tip else 1
                prev = str(tip["record_hash"]).strip() if tip else ZERO_HASH
                record = build_record(
                    project_id=project_id, seq=seq, prev_hash=prev, exec_id=exec_id, tipo=tipo,
                    session_id=session_id, subtask_id=subtask_id, task_name=task_name, registrado_em=registrado_em,
                    corpo=_roundtrip(corpo),
                )
                try:
                    conn.execute(
                        f"INSERT INTO execution_records ({_COLUMNS}) VALUES ({', '.join(['%s'] * 11)})",
                        (
                            record.project_id, record.seq, record.exec_id, record.tipo, record.session_id,
                            record.subtask_id, record.task_name, record.registrado_em, record.prev_hash,
                            record.record_hash, Jsonb(record.corpo),
                        ),
                    )
                except psycopg.errors.UniqueViolation as exc:
                    raise DuplicateRecord(f"{exec_id}/{tipo}") from exc
                return record

        return self._run(append_tx)

    def get(self, exec_id: str, tipo: str) -> StoredRecord | None:
        def query(conn):  # noqa: ANN001, ANN202
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM execution_records WHERE exec_id = %s AND tipo = %s", (exec_id, tipo)
            ).fetchone()
            return _from_row(row) if row else None

        return self._run(query)

    def tip(self, project_id: str) -> StoredRecord | None:
        def query(conn):  # noqa: ANN001, ANN202
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM execution_records WHERE project_id = %s ORDER BY seq DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            return _from_row(row) if row else None

        return self._run(query)

    def at(self, project_id: str, seq: int) -> StoredRecord | None:
        def query(conn):  # noqa: ANN001, ANN202
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM execution_records WHERE project_id = %s AND seq = %s", (project_id, seq)
            ).fetchone()
            return _from_row(row) if row else None

        return self._run(query)

    def records(self, project_id: str) -> list[StoredRecord]:
        def query(conn):  # noqa: ANN001, ANN202
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM execution_records WHERE project_id = %s ORDER BY seq", (project_id,)
            ).fetchall()
            return [_from_row(r) for r in rows]

        return self._run(query)

    def by_session(self, session_id: str) -> list[StoredRecord]:
        def query(conn):  # noqa: ANN001, ANN202
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM execution_records WHERE session_id = %s ORDER BY project_id, seq",
                (session_id,),
            ).fetchall()
            return [_from_row(r) for r in rows]

        return self._run(query)

    def by_subtask(self, subtask_id: str) -> list[StoredRecord]:
        def query(conn):  # noqa: ANN001, ANN202
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM execution_records WHERE subtask_id = %s ORDER BY project_id, seq",
                (subtask_id,),
            ).fetchall()
            return [_from_row(r) for r in rows]

        return self._run(query)

    def projects_of_session(self, session_id: str) -> list[str]:
        def query(conn):  # noqa: ANN001, ANN202
            rows = conn.execute(
                "SELECT DISTINCT project_id FROM execution_records WHERE session_id = %s ORDER BY project_id",
                (session_id,),
            ).fetchall()
            return [r["project_id"] for r in rows]

        return self._run(query)
