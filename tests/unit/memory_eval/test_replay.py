import json

import numpy as np
import pytest

from scripts.memory_eval import replay
from scripts.memory_eval.replay import ReplayError, auc

pytestmark = pytest.mark.unit


def _snapshot(positive_pairs=True):
    """P1..P4 semelhantes; 'bom' é abordagem que funciona em todos, 'ruim' em nenhum."""
    problems = [
        {"id": f"P{i}", "projeto_id": f"proj{i}", "assinatura": f"s{i}",
         "criterio": {"sentido": "maior_melhor", "delta_min": 0.01, "alvo": 0.9}}
        for i in range(1, 5)
    ]
    sims = {f"P{i}|P{j}": 0.9 for i in range(1, 5) for j in range(i + 1, 5)}
    att = []
    n = 0

    def add(problem, key, value, day):
        nonlocal n
        n += 1
        att.append({"id": f"a{n}", "problema_id": problem, "abordagem_key": key, "criado_em": f"2026-10-0{day}T00:00:00",
                    "valor": value, "baseline": 0.3, "config_hash": f"h{n}", "seed": n, "dataset_ids": []})

    add("P1", "bom", 0.95, 1)
    add("P1", "ruim", 0.4, 1)
    for i, day in ((2, 2), (3, 3), (4, 4)):
        add(f"P{i}", "bom", 0.95 if positive_pairs else 0.4, day)
    return {"versao": 1, "problemas": problems, "tentativas": att, "derivacoes": [], "similaridade": sims,
            "problemas_sem_tentativa": []}


def test_auc_perfeita_e_aleatoria():
    labels = np.array([1, 1, 0, 0, 0, 0] * 50, dtype=bool)
    assert auc(labels, np.array([9, 8, 1, 2, 3, 4] * 50, dtype=float)) == 1.0
    random_auc = np.mean([auc(labels, np.random.default_rng(s).random(len(labels))) for s in range(100)])
    assert 0.4 < random_auc < 0.6


def test_auc_com_empates_vale_meio():
    assert auc(np.array([1, 0, 1, 0], dtype=bool), np.ones(4)) == 0.5


def test_ordem_perfeita_no_corpus_sintetico():
    rows = replay.build_rows(_snapshot())
    report = replay.evaluate(rows)
    assert report["padrao"]["auc"] == 1.0
    assert 0.4 < report["aleatoria"]["auc"] < 0.6


def test_corpus_sem_positivos_falha_com_erro_explicito():
    snap = _snapshot(positive_pairs=False)
    with pytest.raises(ReplayError, match="positivo"):
        replay.run(json.dumps(snap))


def test_candidatos_nao_usam_o_futuro():
    rows = replay.build_rows(_snapshot())
    first_cut = min(r.corte for r in rows)
    # no primeiro corte só P1 existe: 'ruim' tem registro em P1 e nenhum par com 'bom' em P1 entra
    assert all(not (r.corte == first_cut and r.problema_id == "P1") for r in rows)


def test_entre_problemas_distintos_zera_a_semelhanca_da_mesma_assinatura():
    snap = _snapshot()
    for p in snap["problemas"]:
        p["assinatura"] = "igual"
    rows = replay.build_rows(snap, distinct_problems=True)
    assert all(r.scores["padrao"] == 0.0 for r in rows)
