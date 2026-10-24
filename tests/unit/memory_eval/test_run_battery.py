import pytest

from scripts.memory_eval.run_battery import over_limit, rotated, spent_by_provider, with_cutoff

pytestmark = pytest.mark.unit


def test_gasto_por_provedor_e_parada():
    results = [
        {"tokens": {"cost_by_provider": {"openai": 2.0, "anthropic": 0.5}}},
        {"tokens": {"cost_by_provider": {"openai": 3.0}}},
        {"status": "skipped"},
    ]
    spent = spent_by_provider(results)
    assert spent == {"openai": 5.0, "anthropic": 0.5}
    assert over_limit(spent, {"openai": 5.0, "anthropic": 3.0}) == "openai"
    assert over_limit(spent, {"openai": 6.0}) is None


def test_ordem_rotacionada_por_rodada():
    arms = ["a", "b", "c"]
    assert rotated(arms, 1) == ["a", "b", "c"]
    assert rotated(arms, 2) == ["b", "c", "a"]
    assert rotated(arms, 4) == ["a", "b", "c"]


def test_corte_entra_no_env_de_cada_braco_sem_alterar_a_matriz():
    matrix = {"combinations": [{"name": "a", "env": {"X": "1"}}, {"name": "b"}]}
    copy = with_cutoff(matrix, "2026-10-25T00:00:00+00:00")
    assert all(c["env"]["RELATED_RECORDS_CUTOFF"] == "2026-10-25T00:00:00+00:00" for c in copy["combinations"])
    assert copy["combinations"][0]["env"]["X"] == "1"
    assert "env" not in matrix["combinations"][1]
