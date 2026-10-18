"""Saída reprodutível do laboratório: ``resultados.csv``, ``relatorio.md`` e ``manifesto.json`` (design §7)."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST = "manifesto.json"
RESULTS = "resultados.csv"
REPORT = "relatorio.md"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class OutputError(ValueError):
    """Diretório de saída recusado."""


def prepare_output_dir(path: Path, *, overwrite: bool) -> Path:
    """Cria o diretório de saída, recusando links simbólicos, a raiz, o ``$HOME`` e resultado anterior."""
    if path.is_symlink():
        raise OutputError(f"{path}: o diretório de saída não pode ser um link simbólico.")
    resolved = path.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise OutputError(f"{path}: escolha um subdiretório próprio para a saída.")
    if resolved.exists() and not resolved.is_dir():
        raise OutputError(f"{path}: existe e não é um diretório.")
    if (resolved / MANIFEST).exists() and not overwrite:
        raise OutputError(f"{path}: já tem {MANIFEST}; use --sobrescrever para substituir o resultado.")
    for name in (MANIFEST, RESULTS, REPORT):
        if (resolved / name).is_symlink():
            raise OutputError(f"{path / name}: link simbólico recusado.")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def current_commit() -> str:
    """``git rev-parse HEAD`` do repositório do laboratório, ou ``desconhecido``."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, capture_output=True, text=True, timeout=10, check=True
        )
        return out.stdout.strip() or "desconhecido"
    except (OSError, subprocess.SubprocessError):
        return "desconhecido"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Linhas com a união das colunas, na ordem em que aparecem; ``None`` vira vazio."""
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _cell(row.get(k)) for k in fields})


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_manifest(
    out_dir: Path,
    *,
    comando: str,
    argumentos: dict[str, Any],
    variantes: list[dict[str, Any]],
    entradas: list[Path],
    sementes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = {
        "ferramenta": "scripts.verdict_lab",
        "commit": current_commit(),
        "data_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comando": comando,
        "argv": sys.argv[1:],
        "argumentos": argumentos,
        "variantes": variantes,
        "sementes": sementes or {},
        "entradas": [{"caminho": str(p), "sha256": sha256_file(p)} for p in entradas],
    }
    (out_dir / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def md_table(header: list[str], rows: list[list[Any]]) -> str:
    """Tabela Markdown; números com três casas."""

    def fmt(v: Any) -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v).replace("|", "\\|")

    head = [h.replace("|", "\\|") for h in header]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)
