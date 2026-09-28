"""ArtifactReader — lê métricas, parâmetros e metadados de disco para popular o
relatório científico final (Roadmap V15.4 / Spec G8).

A tabela de métricas do relatório é construída a partir de dados REAIS lidos de
``metrics.json``/``params.json`` — nunca do texto gerado pelo LLM — evitando que
o Summarizer "invente" ou arredonde números incorretamente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactReader:
    """Lê os artefatos estruturados de uma sessão (``outputs/<session_id>/``)."""

    def __init__(self, session_dir: str | Path):
        self.session_dir = Path(session_dir)

    def read_session_metadata(self) -> dict[str, Any]:
        """Lê ``session_metadata.json`` da sessão, se existir."""
        path = self.session_dir / "session_metadata.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def read_subtask_metrics(self) -> dict[str, dict[str, Any]]:
        """Retorna ``{task_name: metrics_dict}`` para cada ``metrics.json`` encontrado
        sob o diretório da sessão (subtarefas ficam em subpastas aninhadas).
        """
        results: dict[str, dict[str, Any]] = {}
        if not self.session_dir.exists():
            return results
        for metrics_file in self.session_dir.rglob("metrics.json"):
            try:
                data = json.loads(metrics_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            task_name = data.get("task_name") or metrics_file.parent.name
            results[task_name] = data
        return results

    def read_subtask_params(self) -> dict[str, dict[str, Any]]:
        """Retorna ``{task_name: params_dict}`` para cada ``params.json`` encontrado."""
        results: dict[str, dict[str, Any]] = {}
        if not self.session_dir.exists():
            return results
        for params_file in self.session_dir.rglob("params.json"):
            try:
                data = json.loads(params_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            task_name = data.get("task_name") or params_file.parent.name
            results[task_name] = data
        return results

    def read_input_snapshot_files(self) -> list[str]:
        """Lista os nomes dos arquivos de referência usados na sessão (Spec G9)."""
        snapshot_dir = self.session_dir / "input_snapshot"
        if not snapshot_dir.is_dir():
            return []
        return sorted(p.name for p in snapshot_dir.iterdir() if p.is_file())

    def build_metrics_context_block(self) -> str:
        """Bloco de texto com dados REAIS de métricas, pronto para injeção no prompt
        do Summarizer — a tabela de resultados do relatório deve ser construída a
        partir deste bloco, não de texto solto gerado pelo LLM.
        """
        metrics_by_task = self.read_subtask_metrics()
        if not metrics_by_task:
            return "Nenhum metrics.json encontrado nas subtarefas desta sessão."

        lines = ["| Subtarefa | Métricas | Seed | Divergência |", "|---|---|---|---|"]
        for task_name, data in sorted(metrics_by_task.items()):
            metrics = data.get("metrics", {})
            seed = data.get("seed", "—")
            divergence = data.get("divergence_note") or "—"
            lines.append(f"| {task_name} | {json.dumps(metrics, ensure_ascii=False)} | {seed} | {divergence} |")
        return "\n".join(lines)
