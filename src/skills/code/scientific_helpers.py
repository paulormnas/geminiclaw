"""Helpers de reprodutibilidade científica injetados no sandbox (Roadmap V15.2 / Spec G2).

Este módulo é copiado para dentro do container do sandbox junto do script gerado
pelo Developer Agent (ver ``src/skills/code/skill.py``), permitindo que o script
faça ``from scientific_helpers import save_experiment_artifacts`` e persista
parâmetros e métricas em formato legível por máquina, com schema padronizado.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def save_experiment_artifacts(
    task_name: str,
    params: dict[str, Any],
    metrics: dict[str, Any],
    output_dir: str = "/outputs",
    seed: Optional[int] = None,
    divergence_note: Optional[str] = None,
    datasets: Optional[list[str]] = None,
    baselines: Optional[dict[str, float]] = None,
) -> None:
    """Salva ``params.json`` e ``metrics.json`` com schema padronizado de rastreabilidade.

    Args:
        task_name: Nome da subtarefa (usado no schema, não no nome do arquivo).
        params: Parâmetros/hiperparâmetros usados na execução (deve incluir 'seed'
            se não for passado explicitamente via ``seed``).
        metrics: Métricas obtidas (ex: {"accuracy": 0.87, "f1": 0.84}).
        output_dir: Diretório onde salvar os arquivos (padrão: /outputs, dentro do sandbox).
        seed: Seed de aleatoriedade usada. Se omitido, tenta ler de ``params["seed"]``.
        divergence_note: Nota explicando divergência do resultado em relação ao esperado
            (ex: valor de um artigo de referência). ``None`` quando não há divergência.
        datasets: Nomes dos arquivos de ``input_snapshot/`` usados pela execução (opcional,
            v17-structural-fact-ingestion). Só nomes, nunca caminhos.
        baselines: Valor de referência (baseline) por métrica, quando houver (opcional).
    """
    resolved_seed = seed if seed is not None else params.get("seed")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session_id = os.environ.get("SESSION_ID", "")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    params_payload = {
        "task_name": task_name,
        "session_id": session_id,
        "timestamp": timestamp,
        "seed": resolved_seed,
        "parameters": params,
        "datasets": list(datasets) if datasets else [],
    }
    metrics_payload = {
        "task_name": task_name,
        "session_id": session_id,
        "timestamp": timestamp,
        "seed": resolved_seed,
        "parameters": params,
        "metrics": metrics,
        "divergence_note": divergence_note,
        "datasets": list(datasets) if datasets else [],
        "baselines": dict(baselines) if baselines else {},
    }

    (out_dir / "params.json").write_text(
        json.dumps(params_payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics_payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
