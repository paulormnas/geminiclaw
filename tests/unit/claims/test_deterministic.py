"""Conferência determinística (spec: conferência determinística primeiro). Nenhum teste aqui usa LLM."""

import pytest

from src.claims.deterministic import evaluate_sentence, has_causal_marker
from tests.unit.claims.helpers import code

TOL = 0.05


def check(sentence, codes, **kwargs):
    return evaluate_sentence(sentence, codes, approx_rel_tol=TOL, **kwargs)


SENSE = {"acuracia": "maior_melhor", "rmse": "menor_melhor", "mae": "menor_melhor"}


def sense_of(name):
    return SENSE.get(name.lower())


@pytest.mark.unit
class TestOrdemEQualidade:
    def test_comparacao_refutada_pelos_valores(self):
        codes = {"R1": code("R1", 0.81, "acuracia"), "R2": code("R2", 0.84, "acuracia")}
        result = check("A abordagem A (0,81 [R1]) é melhor que B (0,84 [R2]).", codes, sense_of=sense_of)
        assert result.status == "refutada_deterministica"
        assert result.valores["R1"]["valor"] == 0.81 and result.valores["R2"]["valor"] == 0.84
        assert result.valores["sentido"] == "maior_melhor"

    def test_comparacao_suportada(self):
        codes = {"R1": code("R1", 0.9, "acuracia"), "R2": code("R2", 0.84, "acuracia")}
        assert check("A (0,9 [R1]) é melhor que B (0,84 [R2]).", codes, sense_of=sense_of).status == "suportada"

    def test_menor_melhor_inverte(self):
        codes = {"R1": code("R1", 0.3, "rmse"), "R2": code("R2", 0.5, "rmse")}
        assert check("O modelo A (0,3 [R1]) é melhor que B (0,5 [R2]).", codes, sense_of=sense_of).status == "suportada"
        assert check("O modelo A (0,3 [R1]) é pior que B (0,5 [R2]).", codes, sense_of=sense_of).status == (
            "refutada_deterministica"
        )

    def test_metricas_diferentes_vao_ao_verificador(self):
        codes = {"R1": code("R1", 0.3, "rmse"), "R2": code("R2", 0.2, "mae")}
        assert check("A (0,3 [R1]) é melhor que B (0,2 [R2]).", codes, sense_of=sense_of) is None

    def test_sem_sentido_conhecido_vai_ao_verificador(self):
        codes = {"R1": code("R1", 1.0, "xyz"), "R2": code("R2", 2.0, "xyz")}
        assert check("A (1 [R1]) é melhor que B (2 [R2]).", codes) is None

    @pytest.mark.parametrize(
        "frase,valores,esperado",
        [
            ("A (5 [R1]) é maior que B (3 [R2]).", (5, 3), "suportada"),
            ("A (5 [R1]) é maior que B (7 [R2]).", (5, 7), "refutada_deterministica"),
            ("A (2 [R1]) é inferior a B (3 [R2]).", (2, 3), "suportada"),
            ("A (5 [R1]) supera B (7 [R2]).", (5, 7), "refutada_deterministica"),
            ("A (5 [R1]) não supera B (7 [R2]).", (5, 7), "suportada"),
            ("A (9 [R1]) não supera B (7 [R2]).", (9, 7), "refutada_deterministica"),
            ("A (5 [R1]) não é maior que B (7 [R2]).", (5, 7), "suportada"),
        ],
    )
    def test_ordem_e_negacao(self, frase, valores, esperado):
        codes = {"R1": code("R1", valores[0]), "R2": code("R2", valores[1])}
        assert check(frase, codes).status == esperado

    def test_unidades_diferentes_vao_ao_verificador(self):
        codes = {"R1": code("R1", 5, unidade="mm"), "R2": code("R2", 3, unidade="kg")}
        assert check("A (5 mm [R1]) é maior que B (3 kg [R2]).", codes) is None


@pytest.mark.unit
class TestIgualdadeEAproximacao:
    def test_igualdade_pela_precisao_exibida(self):
        codes = {"R1": code("R1", 0.8149), "R2": code("R2", 0.81)}
        # 0,81 exibido com 2 casas: meia unidade = 0,005; |0,8149 − 0,81| = 0,0049
        assert check("O valor de A (0,81 [R1]) é igual a B (0,81 [R2]).", codes).status == "suportada"

    def test_igualdade_refutada(self):
        codes = {"R1": code("R1", 0.85), "R2": code("R2", 0.81)}
        assert check("A (0,85 [R1]) é igual a B (0,81 [R2]).", codes).status == "refutada_deterministica"

    def test_aproximacao_usa_tolerancia_relativa(self):
        near = {"R1": code("R1", 100.0), "R2": code("R2", 103.0)}
        far = {"R1": code("R1", 100.0), "R2": code("R2", 120.0)}
        frase = "A (100 [R1]) é aproximadamente B (103 [R2])."
        assert check(frase, near).status == "suportada"
        assert check(frase.replace("103", "120"), far).status == "refutada_deterministica"


@pytest.mark.unit
class TestAtribuicao:
    def test_metrica_errada_refutada(self):
        codes = {"R1": code("R1", 0.81, "f1")}
        result = check(
            "A acurácia foi de 0,81 [R1].", codes,
            known_metrics=lambda: ["acuracia", "f1"],
        )
        assert result.status == "refutada_deterministica"

    def test_metrica_correta_suportada(self):
        codes = {"R1": code("R1", 0.81, "f1")}
        result = check("O F1 foi de 0,81 [R1].", codes, known_metrics=lambda: ["acuracia", "f1"])
        assert result.status == "suportada"

    def test_nome_desconhecido_vai_ao_verificador(self):
        codes = {"R1": code("R1", 0.81, "f1")}
        assert check("A pontuação foi de 0,81 [R1].", codes, known_metrics=lambda: ["acuracia", "f1"]) is None


@pytest.mark.unit
class TestRegrasGerais:
    def test_marcador_causal_vai_ao_verificador(self):
        codes = {"R1": code("R1", 5), "R2": code("R2", 3)}
        frase = "A (5 [R1]) é maior que B (3 [R2]) porque o dado era maior."
        assert has_causal_marker(frase)
        assert check(frase, codes) is None

    def test_referencia_desconhecida_vai_ao_verificador(self):
        assert check("A (5 [R1]) é maior que B (3 [R9]).", {"R1": code("R1", 5)}) is None

    def test_dois_comparadores_vao_ao_verificador(self):
        codes = {"R1": code("R1", 5), "R2": code("R2", 3)}
        assert check("A (5 [R1]) é maior que e igual a B (3 [R2]).", codes) is None

    def test_frase_sem_referencia(self):
        assert check("O modelo é bom.", {}) is None
