"""Repetição sobre grafos arquivados e arquivamento da métrica (v18.8-verdict-lab)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark import footprint
from scripts.verdict_lab import __main__ as cli
from scripts.verdict_lab.replay import ReplayError, matches_stored, replay
from scripts.verdict_lab.variants import current_variant
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.verdict import Attempt, Criterion, VerdictParams, compute_verdict

pytestmark = pytest.mark.unit

CRIT = {"metrica": "acuracia", "alvo": 0.95, "delta_min": 0.01, "metrica_id": "m1"}


def snapshot(*, com_metrica: bool, veredito: float | None = None, n: int = 2) -> dict:
    nos = [
        {"id": "p", "label": "Problema", "propriedades": {"id": "p", "projeto_id": "pj", "criterio_sucesso": CRIT}},
        {
            "id": "h1",
            "label": "Hipotese",
            "propriedades": {"id": "h1", "projeto_id": "pj", "enunciado": "h", "veredito": veredito},
        },
        {"id": "h2", "label": "Hipotese", "propriedades": {"id": "h2", "projeto_id": "pj", "enunciado": "sem teste"}},
    ]
    arestas = [
        {"origem": "h1", "tipo": "SOBRE", "destino": "p", "propriedades": {}},
        {"origem": "h2", "tipo": "SOBRE", "destino": "p", "propriedades": {}},
    ]
    if com_metrica:
        nos.append(
            {
                "id": "m1",
                "label": "Metrica",
                "propriedades": {"id": "m1", "nome": "acuracia", "sentido": "maior_melhor"},
            }
        )
    for i in range(n):
        e, r = f"e{i}", f"r{i}"
        nos.append(
            {
                "id": e,
                "label": "Experimento",
                "propriedades": {
                    "id": e,
                    "status": "sucesso",
                    "criado_em": f"2026-01-01T00:0{i}:00+00:00",
                    "seed": i,
                    "hash_params": f"hp{i}",
                    "sessao_id": "s",
                    "no_execucao": "n1",
                    "projeto_id": "pj",
                },
            }
        )
        nos.append(
            {
                "id": r,
                "label": "Resultado",
                "propriedades": {
                    "id": r,
                    "valor": 0.96 + i * 0.01,
                    "nome_original": "acuracia",
                    "status_validacao": "validado",
                    "projeto_id": "pj",
                },
            }
        )
        arestas += [
            {"origem": e, "tipo": "TESTA", "destino": "h1", "propriedades": {}},
            {"origem": e, "tipo": "PRODUZIU", "destino": r, "propriedades": {}},
        ]
        if com_metrica:
            arestas.append({"origem": r, "tipo": "MEDE", "destino": "m1", "propriedades": {}})
    return {"nos": nos, "arestas": arestas}


def expected(n: int = 2) -> float:
    attempts = [
        Attempt(
            attempt_id=f"r{i}",
            timestamp=f"2026-01-01T00:0{i}:00+00:00",
            node_id="n1",
            session_id="s",
            seed=i,
            dataset_ids=(),
            config_hash=f"hp{i}",
            outcome_kind="resultado",
            value=0.96 + i * 0.01,
            validation="validado",
            contract_complete=True,
        )
        for i in range(n)
    ]
    return compute_verdict(attempts, Criterion("maior_melhor", 0.01, 0.95), VerdictParams(modelo="adr015")).veredito


def write(tmp_path: Path, data: dict, name: str = "g/grafo_projeto.json") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_arquivo_com_metrica(tmp_path: Path) -> None:
    path = write(tmp_path, snapshot(com_metrica=True, veredito=round(expected(), 6)))
    files, hs = replay([path], [current_variant()])
    assert len(hs) == 1 and hs[0].metrica_reconstruida is False
    assert matches_stored(hs[0]) is True and files[0].nao_testadas == 1


def test_arquivo_anterior_sem_metrica_e_hipotese_nao_testada(tmp_path: Path) -> None:
    path = write(tmp_path, snapshot(com_metrica=False, veredito=0.5))
    files, hs = replay([path], [current_variant()])
    assert hs[0].metrica_reconstruida is True and len(hs[0].attempts) == 2
    assert hs[0].vereditos["atual"] == pytest.approx(expected())
    assert matches_stored(hs[0]) is False  # gravado diverge e o relatório conta
    assert files[0].hipoteses == 2 and files[0].nao_testadas == 1


def test_relatorio_conta_divergentes_e_manifesto_lista_entradas(tmp_path: Path) -> None:
    a = write(tmp_path, snapshot(com_metrica=True, veredito=0.9), "a/grafo_projeto.json")
    b = write(tmp_path, snapshot(com_metrica=True, veredito=round(expected(), 6)), "b/grafo_projeto.json")
    out = tmp_path / "out"
    assert cli.main(["replay", str(tmp_path / "a"), str(b), "--saida", str(out), "--variante", "atual"]) == 0
    manifest = json.loads((out / "manifesto.json").read_text(encoding="utf-8"))
    assert {e["caminho"] for e in manifest["entradas"]} >= {str(a), str(b)} and all(
        e["sha256"] for e in manifest["entradas"]
    )
    report = (out / "relatorio.md").read_text(encoding="utf-8")
    assert "Iguais: 1; diferentes: 1" in report


def test_grafo_com_erro_e_caminho_inexistente(tmp_path: Path) -> None:
    path = write(tmp_path, {"erro": "RuntimeError: x"})
    files, hs = replay([path], [current_variant()])
    assert files[0].erro and not hs
    with pytest.raises(ReplayError):
        replay([tmp_path / "nao_existe"], [current_variant()])
    with pytest.raises(ReplayError):
        replay([write(tmp_path, {"nos": 3}, "x/grafo_projeto.json")], [current_variant()])


def test_arquivamento_inclui_metrica_e_mede_uma_vez() -> None:
    store = InMemoryGraphStore()
    from src.knowledge.graph_store import Edge, Node

    store._nodes["m1"] = Node("m1", "Metrica", {"id": "m1", "nome": "acuracia"})
    store._nodes["pj"] = Node("pj", "Projeto", {"id": "pj", "projeto_id": "pj"})
    for i in range(10):
        rid = f"r{i}"
        store._nodes[rid] = Node(rid, "Resultado", {"id": rid, "projeto_id": "pj", "valor": 1.0})
        store._edges.append(Edge(rid, "MEDE", "m1", {}))
    graph = footprint.project_graph_full("pj", store)
    labels = [n["label"] for n in graph["nos"]]
    assert labels.count("Metrica") == 1 and sum(a["tipo"] == "MEDE" for a in graph["arestas"]) == 10
    assert labels.count("Resultado") == 10 and "Projeto" in labels
