"""``proveniencia_numerica.json`` por sessão e leitor para as métricas de operação (design §8)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.numeric_refs.literal_metrics import LITERALS_FILE

FILE_NAME = "proveniencia_numerica.json"
GROUP = "proveniencia"


def build_payload(
    session_id: str,
    codes: list[Any],
    not_verified: list[dict[str, Any]],
    literals: list[dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "versao": 1,
        "session_id": session_id,
        "codigos": [
            {
                "codigo": c.codigo, "tipo": c.tipo, "valor_exato": c.valor_exato, "unidade": c.unidade,
                "detalhe": c.detalhe, "ocorrencias": c.ocorrencias,
            }
            for c in codes
        ],
        "nao_verificados": not_verified,
        "metricas_literais": literals,
        "contagens": {
            "res": counts.get("res", 0), "calc": counts.get("calc", 0), "src": counts.get("src", 0),
            "nao_verificados": len(not_verified), "metricas_literais": len(literals),
        },
    }


def write_payload(session_dir: Path, payload: dict[str, Any]) -> Path:
    """Grava o arquivo de forma atômica."""
    target = session_dir / FILE_NAME
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    return target


def read_literal_findings(session_dir: Path) -> list[dict[str, Any]]:
    """Achados de ``metricas_literais.json`` de todas as subtarefas da sessão (com o ``exec_id``)."""
    found: list[dict[str, Any]] = []
    for path in sorted(session_dir.glob(f"*/{LITERALS_FILE}")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in data.get("achados") or []:
            found.append({"exec_id": data.get("exec_id"), **item})
    return found


class NumericProvenanceReader:
    """Leitor do grupo ``proveniencia`` de ``v18.5-operation-metrics`` (produtor: ``v18.5-numeric-references``)."""

    group = GROUP

    def __init__(self, output_dir: Path | str) -> None:
        self.output_dir = Path(output_dir)

    def read(self, session_id: str) -> dict[str, Any]:
        """``numeros_por_origem``, ``numeros_nao_verificados`` e ``metricas_literais`` da sessão.

        Raises:
            FileNotFoundError: A sessão não gerou ``proveniencia_numerica.json`` (o relatório não passou pelo pipeline).
        """
        path = self.output_dir / session_id / FILE_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = data.get("contagens", {})
        return {
            "numeros_por_origem": {k: int(counts.get(k, 0)) for k in ("res", "calc", "src")},
            "numeros_nao_verificados": int(counts.get("nao_verificados", 0)),
            "metricas_literais": int(counts.get("metricas_literais", 0)),
        }
