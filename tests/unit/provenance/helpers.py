"""Auxiliares dos testes de proveniência (nenhum usa banco, rede ou container)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.provenance.ledger import ExecutionLedger
from src.provenance.store import MemoryStore


def make_ledger(tmp_path: Path) -> ExecutionLedger:
    return ExecutionLedger(MemoryStore(), tmp_path / "outputs")


def inicio(**over: Any) -> dict[str, Any]:
    base = {
        "hash_codigo": "c" * 64,
        "arquivos_injetados": [],
        "entradas": [],
        "pacotes_solicitados": [],
        "ativos_declarados": [],
        "imagem_solicitada": "geminiclaw-sandbox",
    }
    base.update(over)
    return base


def termino(inicio_hash: str, **over: Any) -> dict[str, Any]:
    base = {
        "inicio_hash": inicio_hash,
        "status": "sucesso",
        "hash_codigo": "c" * 64,
        "arquivos_injetados": [],
        "entradas": [],
        "hash_params": None,
        "seed": None,
        "saidas": [],
        "metricas": {},
        "hash_metrics": None,
        "metrics_invalido": False,
        "fase_falha": None,
        "download_nao_declarado": False,
        "rede_na_execucao": False,
        "exit_code": 0,
        "inicio_execucao": None,
        "fim_execucao": None,
        "fases": [],
        "imagem": {"nome": "geminiclaw-sandbox", "id": "sha256:abc", "repo_digests": []},
        "python_version": "3.11.9",
        "pacotes": {},
        "ativos": [],
    }
    base.update(over)
    return base


def run_one(
    ledger: ExecutionLedger,
    *,
    project_id: str | None = "proj",
    session_id: str = "s1",
    subtask_id: str | None = "sub-1",
    task_name: str = "tarefa",
    inicio_over: dict[str, Any] | None = None,
    termino_over: dict[str, Any] | None = None,
    finish: bool = True,
):
    """Grava um par inicio/termino e devolve ``(BeginResult, FinishResult | None)``."""
    began = ledger.begin(
        project_id=project_id, session_id=session_id, subtask_id=subtask_id, task_name=task_name,
        body=inicio(**(inicio_over or {})),
    )
    if not finish:
        return began, None
    done = ledger.finish(
        exec_id=began.exec_id, chain_id=began.chain_id, session_id=session_id, subtask_id=subtask_id,
        task_name=task_name, body=termino(began.record.record_hash, **(termino_over or {})),
    )
    return began, done
