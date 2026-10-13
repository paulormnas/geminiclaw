"""Arquivamento de cada repetição do benchmark (v18.6-benchmark-harness §5).

A pasta da sessão fica em ``OUTPUT_BASE_DIR`` da worktree e some quando a worktree é limpa; os eventos e o grafo ficam
nos bancos, que o próximo reset apaga. Antes disso, cada repetição leva para ``<results>.d/<combinação>/r<r>/``:

- ``sessao.tar.gz``: a pasta da sessão;
- ``run.log``: a saída do subprocesso;
- ``eventos.json``: os eventos ``agent_events`` da sessão;
- ``grafo_projeto.json``: nós (com propriedades) e arestas do projeto;
- ``pre_reset/``: o arquivo de segurança do reset (gravado por ``reset_stores``).
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any


def archive_dir_for(results_path: Path, combination: str, repetition: int) -> Path:
    """``<results>.d/<combinação>/r<r>/`` ao lado do arquivo de resultados."""
    return results_path.with_name(results_path.name + ".d") / combination / f"r{repetition}"


def archive_repetition(
    dest: Path,
    *,
    session_dir: Path | None,
    log: str,
    events: list[dict[str, Any]] | None,
    project_graph: dict[str, Any] | None,
) -> Path:
    """Grava os quatro arquivos da repetição em ``dest`` e devolve ``dest``.

    Uma fonte indisponível (sem sessão, sem eventos, sem grafo) grava o arquivo com ``{"erro": ...}`` em vez de ser
    omitida, para que a ausência apareça na conferência.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if session_dir is not None and session_dir.is_dir():
        with tarfile.open(dest / "sessao.tar.gz", "w:gz") as tar:
            tar.add(session_dir, arcname=session_dir.name)
    else:
        (dest / "sessao.tar.gz").write_bytes(b"")
    (dest / "run.log").write_text(log or "", encoding="utf-8")
    for name, data, label in (("eventos.json", events, "eventos"), ("grafo_projeto.json", project_graph, "grafo")):
        payload = data if data is not None else {"erro": f"{label} indisponível"}
        (dest / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return dest


def fetch_events(session_id: str) -> list[dict[str, Any]] | None:
    """Eventos da sessão (``agent_events``), ou ``None`` se o banco estiver indisponível."""
    try:
        from scripts.benchmark.communication import fetch_session_data

        return fetch_session_data(session_id)["events"]
    except Exception:  # noqa: BLE001 - indisponibilidade vira {"erro"} no arquivo
        return None
