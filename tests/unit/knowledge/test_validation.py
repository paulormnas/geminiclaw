"""Testes unitários para src/knowledge/validation.py.

Cobrem os cenários de `openspec/changes/v17-graph-store/specs/knowledge-graph/spec.md`
(tarefa 4.1 de tasks.md): rótulo desconhecido, propriedade obrigatória
ausente, enumeração inválida, relação não permitida, justificativa de
agente ausente e campos imutáveis.
"""

import pytest

from src.knowledge import validation
from src.knowledge.errors import (
    DisallowedRelationError,
    ImmutableFieldError,
    InvalidEnumValueError,
    MissingJustificationError,
    MissingRequiredPropertyError,
    UnknownLabelError,
    UnknownPropertyError,
)

_BASE_COMMON = {
    "id": "id-1",
    "criado_em": "2026-01-01T00:00:00Z",
    "atualizado_em": "2026-01-01T00:00:00Z",
    "criado_por": "orquestrador",
    "projeto_id": "proj-1",
    "sessao_id": "sess-1",
    "visibilidade": "privado",
    "origem_no": "local",
    "versao_schema": 1,
}


@pytest.mark.unit
class TestValidateNodeWrite:
    def test_rotulo_desconhecido(self):
        """Scenario: Rótulo desconhecido — create_node('Pessoa', ...) é recusado."""
        with pytest.raises(UnknownLabelError):
            validation.validate_node_write("Pessoa", dict(_BASE_COMMON), requires_agent_provenance=False)

    def test_propriedade_obrigatoria_ausente(self):
        """Scenario: Problema criado sem 'resumo' é recusado."""
        props = {**_BASE_COMMON, "titulo": "x", "status": "rascunho"}  # falta 'resumo'
        with pytest.raises(MissingRequiredPropertyError) as exc_info:
            validation.validate_node_write("Problema", props, requires_agent_provenance=False)
        assert exc_info.value.prop == "resumo"

    def test_enumeracao_invalida(self):
        """Scenario: Hipotese com status='talvez' é recusada."""
        props = {
            **_BASE_COMMON,
            "enunciado": "x",
            "justificativa": "y",
            "status": "talvez",
            "origem": "pesquisador",
        }
        with pytest.raises(InvalidEnumValueError):
            validation.validate_node_write("Hipotese", props, requires_agent_provenance=False)

    def test_propriedade_desconhecida_recusada(self):
        props = {**_BASE_COMMON, "titulo": "x", "objetivo": "y", "status": "ativo", "campo_invalido": 1}
        with pytest.raises(UnknownPropertyError):
            validation.validate_node_write("Projeto", props, requires_agent_provenance=False)

    def test_no_valido_passa(self):
        props = {**_BASE_COMMON, "titulo": "x", "objetivo": "y", "status": "ativo"}
        validation.validate_node_write("Projeto", props, requires_agent_provenance=False)

    def test_no_de_agente_sem_justificativa_e_recusado(self):
        """Scenario: Nó de agente sem justificativa_criacao é recusado."""
        props = {
            **_BASE_COMMON,
            "tipo": "funciona",
            "enunciado": "x",
            "n_evidencias": 1,
            "status": "ativa",
        }
        with pytest.raises(MissingJustificationError):
            validation.validate_node_write("Descoberta", props, requires_agent_provenance=True)

    def test_no_de_agente_com_justificativa_passa(self):
        props = {
            **_BASE_COMMON,
            "tipo": "funciona",
            "enunciado": "x",
            "n_evidencias": 1,
            "status": "ativa",
            "justificativa_criacao": "porque sim",
            "nos_consultados": [],
        }
        validation.validate_node_write("Descoberta", props, requires_agent_provenance=True)

    def test_justificativa_em_branco_e_recusada(self):
        props = {
            **_BASE_COMMON,
            "tipo": "funciona",
            "enunciado": "x",
            "n_evidencias": 1,
            "status": "ativa",
            "justificativa_criacao": "   ",
            "nos_consultados": [],
        }
        with pytest.raises(MissingJustificationError):
            validation.validate_node_write("Descoberta", props, requires_agent_provenance=True)


@pytest.mark.unit
class TestValidateNodeUpdate:
    def test_campos_imutaveis(self):
        """Scenario: Campos imutáveis — update_node não altera id/criado_em/criado_por/projeto_id."""
        for field_name in ("id", "criado_em", "criado_por", "projeto_id"):
            with pytest.raises(ImmutableFieldError):
                validation.validate_node_update("Descoberta", {field_name: "novo_valor"})

    def test_campo_mutavel_valido_passa(self):
        validation.validate_node_update("Descoberta", {"status": "contestada"})

    def test_enum_invalida_no_update(self):
        with pytest.raises(InvalidEnumValueError):
            validation.validate_node_update("Descoberta", {"status": "nao_existe"})

    def test_campo_desconhecido_no_update(self):
        with pytest.raises(UnknownPropertyError):
            validation.validate_node_update("Descoberta", {"campo_inexistente": 1})


@pytest.mark.unit
class TestValidateNodeFilterKeys:
    """PR #64 review, achado 'Importante': find_nodes interpola chaves de filtro
    como identificadores Cypher (``n.{key} = $filters.{key}``) sem checar o
    schema. ``validate_node_filter_keys`` deve recusar qualquer chave que não
    seja propriedade conhecida (comum ou específica) do rótulo, antes de
    qualquer interpolação.
    """

    def test_rotulo_desconhecido(self):
        with pytest.raises(UnknownLabelError):
            validation.validate_node_filter_keys("Pessoa", {"status": "ativo"})

    def test_chave_de_filtro_desconhecida_e_recusada(self):
        with pytest.raises(UnknownPropertyError) as exc_info:
            validation.validate_node_filter_keys("Projeto", {"status": "ativo", "campo_invalido": 1})
        assert exc_info.value.prop == "campo_invalido"

    def test_chave_com_tentativa_de_injecao_cypher_e_recusada(self):
        """Uma chave forjada para escapar da interpolação também é apenas 'desconhecida'."""
        payload = "titulo = 'x' OR 1=1 //"
        with pytest.raises(UnknownPropertyError) as exc_info:
            validation.validate_node_filter_keys("Projeto", {payload: "y"})
        assert exc_info.value.prop == payload

    def test_filtro_vazio_passa(self):
        validation.validate_node_filter_keys("Projeto", {})

    def test_chave_de_propriedade_especifica_valida_passa(self):
        validation.validate_node_filter_keys("Projeto", {"status": "ativo"})

    def test_chave_de_propriedade_comum_valida_passa(self):
        """Propriedades comuns (ex.: 'projeto_id') também são filtros válidos."""
        validation.validate_node_filter_keys("Projeto", {"projeto_id": "p1"})


@pytest.mark.unit
class TestValidateEdgeWrite:
    _COMMON_EDGE = {
        "criado_em": "2026-01-01T00:00:00Z",
        "criado_por": "orquestrador",
        "origem": "afirmado",
        "status": "confirmada",
    }

    def test_relacao_nao_permitida(self):
        """Scenario: Resultado-FUNCIONOU_PARA->Problema é recusado (só parte de Abordagem)."""
        with pytest.raises(DisallowedRelationError):
            validation.validate_edge_write("Resultado", "FUNCIONOU_PARA", "Problema", dict(self._COMMON_EDGE))

    def test_relacao_permitida_passa(self):
        props = {**self._COMMON_EDGE, "config": {}, "hash_params": "abc"}
        validation.validate_edge_write("Experimento", "APLICOU", "Abordagem", props)

    def test_propriedade_obrigatoria_de_relacao_ausente(self):
        """DESCARTOU exige 'motivo'."""
        with pytest.raises(MissingRequiredPropertyError):
            validation.validate_edge_write("Decisao", "DESCARTOU", "Abordagem", dict(self._COMMON_EDGE))

    def test_status_edge_invalido(self):
        props = {**self._COMMON_EDGE, "status": "invalido"}
        with pytest.raises(InvalidEnumValueError):
            validation.validate_edge_write("Hipotese", "SOBRE", "Problema", props)
