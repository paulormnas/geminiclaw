"""Exportação do segmento da cadeia de uma sessão (design §8): ``outputs/<sessão>/provenance/``."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.logger import get_logger
from src.provenance.errors import ProvenanceError
from src.provenance.store import LedgerStore

logger = get_logger(__name__)

EXPORT_DIR = "provenance"
RECORDS_FILE = "execution_records.jsonl"
TIP_FILE = "chain_tip.json"


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def export_session(store: LedgerStore, session_id: str, output_dir: Path | str) -> Path | None:
    """Grava o segmento contíguo da cadeia da sessão (do primeiro registro dela até a ponta) e a ponta.

    O segmento inclui registros intercalados de outras sessões do mesmo projeto, necessários para verificar os elos.

    Returns:
        O diretório ``outputs/<sessão>/provenance/``, ou ``None`` se a sessão não tem registros.

    Raises:
        ProvenanceUnavailable: O armazenamento está indisponível.
        ProvenanceError: Falha ao gravar os arquivos.
    """
    projects = store.projects_of_session(session_id)
    if not projects:
        return None
    target = Path(output_dir) / session_id / EXPORT_DIR
    lines: list[str] = []
    tips: list[dict[str, Any]] = []
    for project_id in projects:
        chain = store.records(project_id)
        first = next((i for i, r in enumerate(chain) if r.session_id == session_id), None)
        if first is None:
            continue
        segment = chain[first:]
        lines.extend(json.dumps(r.to_export(), ensure_ascii=False, sort_keys=True) for r in segment)
        tips.append(
            {
                "project_id": project_id,
                "seq": segment[-1].seq,
                "record_hash": segment[-1].record_hash,
                "primeiro_seq": segment[0].seq,
                "primeiro_prev_hash": segment[0].prev_hash,
            }
        )
    if not tips:
        return None
    try:
        target.mkdir(parents=True, exist_ok=True)
        _write_atomic(target / RECORDS_FILE, "\n".join(lines) + "\n")
        main = max(tips, key=lambda t: t["seq"])
        payload = {**main, "pontas": tips, "exportado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _write_atomic(target / TIP_FILE, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise ProvenanceError(f"exportação da proveniência não gravada: {exc}") from exc
    return target
