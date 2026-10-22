"""Testes unitários para src/knowledge/schema.py."""

import pytest

from src.knowledge import schema


@pytest.mark.unit
class TestNodeSchemas:
    def test_tem_16_tipos_de_no(self):
        """O ADR 015 §3 define 13 tipos de nó; v18.5-claim-verification acrescenta ``Afirmacao`` e
        v18.7-exploration-limits acrescenta ``Restricao`` e v18.9-result-records acrescenta ``RegistroResultado``."""
        assert len(schema.NODE_SCHEMAS) == 16

    def test_rotulos_esperados_presentes(self):
        esperados = {
            "Projeto", "Sessao", "Insumo", "Problema", "Hipotese", "Abordagem",
            "Experimento", "Resultado", "Decisao", "Descoberta", "Oportunidade",
            "Dominio", "Metrica", "Afirmacao", "Restricao", "RegistroResultado",
        }
        assert set(schema.NODE_SCHEMAS) == esperados

    def test_problema_tem_resumo_obrigatorio(self):
        assert schema.NODE_SCHEMAS["Problema"].properties["resumo"].required is True

    def test_hipotese_status_tem_enumeracao(self):
        status_schema = schema.NODE_SCHEMAS["Hipotese"].properties["status"]
        assert status_schema.enum == (
            "proposta", "em_teste", "validada", "refutada", "inconclusiva", "abandonada",
        )


@pytest.mark.unit
class TestRelationSchemas:
    def test_find_relation_schema_permite_par_valido(self):
        result = schema.find_relation_schema("Experimento", "APLICOU", "Abordagem")
        assert result is not None
        assert result.rel_type == "APLICOU"

    def test_find_relation_schema_recusa_par_invalido(self):
        """FUNCIONOU_PARA só é permitida partindo de Abordagem, nunca de Resultado."""
        result = schema.find_relation_schema("Resultado", "FUNCIONOU_PARA", "Problema")
        assert result is None

    def test_semelhante_a_mesmo_rotulo(self):
        for label in ("Projeto", "Problema", "Abordagem", "Descoberta", "Oportunidade"):
            result = schema.find_relation_schema(label, "SEMELHANTE_A", label)
            assert result is not None, f"SEMELHANTE_A deveria ser permitido para {label}"

    def test_descoberta_semelhante_a_problema(self):
        result = schema.find_relation_schema("Descoberta", "SEMELHANTE_A", "Problema")
        assert result is not None

    def test_derivada_de_aceita_multiplos_rotulos_origem(self):
        for src in ("Insumo", "Descoberta", "Oportunidade"):
            result = schema.find_relation_schema("Hipotese", "DERIVADA_DE", src)
            assert result is not None, f"DERIVADA_DE deveria aceitar origem {src}"
