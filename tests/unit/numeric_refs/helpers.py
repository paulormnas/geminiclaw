"""Auxiliares dos testes de referências numéricas (nenhum usa banco, rede ou container)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from src.numeric_refs.resolver import ReferenceResolver
from src.provenance.hashing import sha256_file
from src.provenance.ledger import ExecutionLedger
from src.provenance.store import MemoryStore
from tests.unit.provenance.helpers import inicio, termino


def new_ledger(outputs: Path) -> ExecutionLedger:
    return ExecutionLedger(MemoryStore(), outputs)


def record_run(
    ledger: ExecutionLedger,
    outputs: Path,
    *,
    session: str = "s1",
    task: str = "treinar",
    metrics: dict[str, Any] | None = None,
    unidades: dict[str, str] | None = None,
    parameters: dict[str, Any] | None = None,
    status: str = "sucesso",
    finish: bool = True,
    tamper_after: bool = False,
) -> str:
    """Executa (simulado) uma subtarefa: grava metrics.json/params.json e o início/término; devolve o exec_id."""
    folder = outputs / session / task
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"task_name": task, "metrics": metrics or {"rmse": 0.4498}, "unidades": unidades or {}}
    (folder / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    (folder / "params.json").write_text(json.dumps({"parameters": parameters or {"k": 3}}), encoding="utf-8")
    saidas = [
        {
            "caminho": f"{session}/{task}/{name}",
            "sha256": sha256_file(folder / name),
            "tamanho": (folder / name).stat().st_size,
        }
        for name in ("metrics.json", "params.json")
    ]
    began = ledger.begin(project_id="proj", session_id=session, subtask_id=f"sub-{task}", task_name=task,
                         body=inicio(), output_dir=outputs)
    if finish:
        recorded = {k: repr(v) if isinstance(v, float) else str(v) for k, v in (metrics or {"rmse": 0.4498}).items()}
        ledger.finish(
            exec_id=began.exec_id, chain_id=began.chain_id, session_id=session, subtask_id=f"sub-{task}",
            task_name=task,
            body=termino(began.record.record_hash, status=status, saidas=saidas, metricas=recorded,
                         exit_code=0 if status == "sucesso" else 1),
            output_dir=outputs,
        )
    if tamper_after:
        (folder / "metrics.json").write_text(json.dumps({"metrics": {"rmse": 9.99}}), encoding="utf-8")
    return began.exec_id


def make_resolver(outputs: Path, ledger: ExecutionLedger, **kwargs: Any) -> ReferenceResolver:
    return ReferenceResolver(ledger=ledger, output_dir=outputs, **kwargs)


def fake_exec_id() -> str:
    return f"exec_{uuid.uuid4()}"
