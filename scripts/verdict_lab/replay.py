"""Repetição do veredito sobre grafos arquivados (design §7 de ``v18.8-verdict-lab``; ADR 025, etapa 1).

Carrega cada ``grafo_projeto.json`` num grafo em memória e coleta as tentativas das hipóteses com o mesmo
código do Curator (``KnowledgeService.collect_attempts``). Arquivos anteriores a esta mudança não trazem o
nó ``Metrica`` nem a aresta ``MEDE``: nesse caso a métrica é reconstruída a partir do ``criterio_sucesso`` do
``Problema`` e ligada aos ``Resultado`` cujo ``nome_original`` é a métrica do critério.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.verdict_lab.variants import Variant, lab_verdict
from src.knowledge.graph_store import Edge, InMemoryGraphStore, Node
from src.knowledge.service import KnowledgeService, KnowledgeServiceError
from src.knowledge.verdict import Attempt, Criterion, VerdictParams

ARCHIVE_NAME = "grafo_projeto.json"
_TOL = 1e-4


class ReplayError(ValueError):
    """Arquivo de grafo fora do formato esperado."""


class SnapshotGraphStore(InMemoryGraphStore):
    """Grafo em memória restaurado de um arquivo, sem revalidar (os nós já foram validados quando gravados)."""

    @classmethod
    def from_snapshot(cls, data: dict[str, Any], source: str) -> SnapshotGraphStore:
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("nos"), list)
            or not isinstance(data.get("arestas"), list)
        ):
            raise ReplayError(f"{source}: esperado {{'nos': [...], 'arestas': [...]}}.")
        store = cls()
        for i, raw in enumerate(data["nos"]):
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("label"), str):
                raise ReplayError(f"{source}: nó {i} sem 'id' ou 'label'.")
            props = raw.get("propriedades") or {}
            if not isinstance(props, dict):
                raise ReplayError(f"{source}: nó {raw['id']} com 'propriedades' inválidas.")
            store._nodes[raw["id"]] = Node(id=raw["id"], label=raw["label"], properties=dict(props))  # noqa: SLF001
        for i, raw in enumerate(data["arestas"]):
            if not isinstance(raw, dict) or not all(isinstance(raw.get(k), str) for k in ("origem", "tipo", "destino")):
                raise ReplayError(f"{source}: aresta {i} sem 'origem', 'tipo' ou 'destino'.")
            props = raw.get("propriedades") or {}
            store._edges.append(  # noqa: SLF001 - restauração do arquivo
                Edge(src_id=raw["origem"], rel_type=raw["tipo"], dst_id=raw["destino"], properties=dict(props))
            )
        return store


@dataclass
class ReplayedHypothesis:
    """Uma hipótese recalculada."""

    arquivo: str
    execucao: str
    hipotese_id: str
    enunciado: str
    veredito_gravado: float | None
    criterion: Criterion
    attempts: list[Attempt]
    metrica_reconstruida: bool
    vereditos: dict[str, float] = field(default_factory=dict)


@dataclass
class ReplayFile:
    """Resumo de um arquivo."""

    arquivo: str
    execucao: str
    hipoteses: int
    nao_testadas: int
    erro: str | None = None


def find_archives(paths: list[Path]) -> list[Path]:
    """Arquivos ``grafo_projeto.json`` nos caminhos (diretórios são percorridos), em ordem estável."""
    found: list[Path] = []
    for p in paths:
        if p.is_dir():
            found.extend(sorted(p.rglob(ARCHIVE_NAME)))
        elif p.is_file():
            found.append(p)
        else:
            raise ReplayError(f"{p}: caminho inexistente.")
    return found


def _execution_label(path: Path) -> str:
    parts = path.parent.parts[-3:]
    return "/".join(parts).replace(".json.d", "")


def _ensure_metric(store: SnapshotGraphStore) -> bool:
    """Garante ``Metrica`` e ``MEDE`` para o critério do ``Problema``; ``True`` quando precisou reconstruir."""
    problems = [n for n in store._nodes.values() if n.label == "Problema"]  # noqa: SLF001
    rebuilt = False
    for problema in problems:
        criterio = problema.properties.get("criterio_sucesso")
        if not isinstance(criterio, dict):
            continue
        metric_id = str(criterio.get("metrica_id") or f"metrica-{criterio.get('metrica')}")
        nome = criterio.get("metrica")
        if metric_id in store._nodes:  # noqa: SLF001
            continue
        rebuilt = True
        store._nodes[metric_id] = Node(  # noqa: SLF001
            id=metric_id,
            label="Metrica",
            properties={"id": metric_id, "nome": nome, "sentido": criterio.get("sentido") or "maior_melhor"},
        )
        for node in list(store._nodes.values()):  # noqa: SLF001
            if node.label == "Resultado" and node.properties.get("nome_original") == nome:
                store._edges.append(Edge(src_id=node.id, rel_type="MEDE", dst_id=metric_id, properties={}))  # noqa: SLF001
    return rebuilt


def replay_file(path: Path) -> tuple[ReplayFile, list[ReplayedHypothesis]]:
    """Hipóteses com tentativas de um arquivo; as sem ``TESTA`` são só contadas."""
    label = _execution_label(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"{path}: não foi possível ler ({exc}).") from exc
    if isinstance(data, dict) and "erro" in data and "nos" not in data:
        return ReplayFile(str(path), label, 0, 0, erro=str(data["erro"])), []
    store = SnapshotGraphStore.from_snapshot(data, str(path))
    rebuilt = _ensure_metric(store)
    service = KnowledgeService(store, VerdictParams())  # só a coleta; o veredito vem das variantes
    hypotheses = [n for n in store._nodes.values() if n.label == "Hipotese"]  # noqa: SLF001
    out: list[ReplayedHypothesis] = []
    untested = 0
    for h in hypotheses:
        problema = service.problem_for(h)
        if problema is None:
            untested += 1
            continue
        try:
            criterion, metric = service.criterion_for(problema)
        except KnowledgeServiceError:
            untested += 1
            continue
        attempts = [c.attempt for c in service.collect_attempts(h, metric)]
        if not attempts:
            untested += 1
            continue
        stored = h.properties.get("veredito")
        out.append(
            ReplayedHypothesis(
                arquivo=str(path),
                execucao=label,
                hipotese_id=h.id,
                enunciado=str(h.properties.get("enunciado") or ""),
                veredito_gravado=float(stored) if isinstance(stored, (int, float)) else None,
                criterion=criterion,
                attempts=attempts,
                metrica_reconstruida=rebuilt,
            )
        )
    return ReplayFile(str(path), label, len(hypotheses), untested), out


def replay(paths: list[Path], variants: list[Variant]) -> tuple[list[ReplayFile], list[ReplayedHypothesis]]:
    """Recalcula todas as hipóteses dos arquivos sob cada variante."""
    files: list[ReplayFile] = []
    hypotheses: list[ReplayedHypothesis] = []
    for path in find_archives(paths):
        summary, hs = replay_file(path)
        files.append(summary)
        for h in hs:
            for v in variants:
                h.vereditos[v.nome] = lab_verdict(h.attempts, h.criterion, v).veredito
        hypotheses.extend(hs)
    return files, hypotheses


def matches_stored(h: ReplayedHypothesis, variant_name: str = "atual") -> bool | None:
    """``True`` quando o recálculo coincide com o gravado (tolerância de 1e-4); ``None`` sem valor gravado."""
    if h.veredito_gravado is None or variant_name not in h.vereditos:
        return None
    return abs(h.vereditos[variant_name] - h.veredito_gravado) < _TOL
