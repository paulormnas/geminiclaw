import pytest

from scripts.memory_eval.metrics import (
    Exploration,
    Failure,
    compute_metrics,
    exploration_from_graph,
    repeated_failure_counts,
)

pytestmark = pytest.mark.unit


def test_falha_repetida_conta_assinatura_e_escopo():
    falhas = (Failure("oom", "A"), Failure("oom", "A"), Failure("instalacao_pacotes", "ambiente"))
    assert repeated_failure_counts(falhas) == (1, 3)
    assert repeated_failure_counts((Failure("oom", "A"), Failure("oom", "B"))) == (0, 2)


def test_metricas_por_braco_com_intervalo_e_n():
    arms = {
        "com": [Exploration(True, True, 0.2, ()), Exploration(True, True, 0.4, ())],
        "sem": [Exploration(False, True, None, (Failure("oom", "A"), Failure("oom", "A")))],
    }
    report = compute_metrics(arms)
    assert report["com"]["n_exploracoes"] == 2
    assert report["com"]["taxa_sucesso"]["valor"] == 1.0
    assert report["com"]["ganho_base"]["valor"] == pytest.approx(0.3)
    assert report["sem"]["falhas_repetidas"]["valor"] == 0.5
    assert len(report["com"]["taxa_sucesso"]["ic95"]) == 2


def test_braco_vazio_e_erro():
    with pytest.raises(ValueError, match="sem explorações"):
        compute_metrics({"x": []})


def test_exploracao_a_partir_do_grafo_arquivado():
    def node(i, label, **props):
        return {"id": i, "label": label, "propriedades": props}

    graph = {
        "nos": [
            node("p", "Problema", objetivo_atingido=[{"marco": 1}]),
            node("e1", "Experimento", status="falha", assinatura_falha="oom", criado_em="1"),
            node("e2", "Experimento", status="falha", assinatura_falha="oom", criado_em="2"),
            node("e3", "Experimento", status="sucesso", criado_em="3"),
            node("a", "Abordagem", nome="rf"),
            node("r", "Resultado", qualificador="teste"),
            node("g", "RegistroResultado", delta_base=0.25),
        ],
        "arestas": [
            {"origem": "e1", "tipo": "APLICOU", "destino": "a"},
            {"origem": "e3", "tipo": "PRODUZIU", "destino": "r"},
        ],
    }
    exp = exploration_from_graph(graph)
    assert exp.objetivo_atingido and exp.valida and exp.ganho_base == 0.25
    assert [f.escopo for f in exp.falhas] == ["ambiente", "ambiente"]
    assert repeated_failure_counts(exp.falhas) == (1, 2)
