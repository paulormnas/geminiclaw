"""Testes unitários para src/knowledge/provenance.py (Actor e preenchimento de proveniência)."""

import pytest

from src.knowledge.provenance import Actor, prepare_edge_properties, prepare_node_properties, prepare_node_update


@pytest.mark.unit
class TestActor:
    def test_criado_por_orquestrador(self):
        assert Actor(kind="orquestrador").criado_por == "orquestrador"

    def test_criado_por_pesquisador(self):
        assert Actor(kind="pesquisador").criado_por == "pesquisador"

    def test_criado_por_agente_com_modelo(self):
        actor = Actor(kind="agente", role="curator", model="qwen3:8b")
        assert actor.criado_por == "curator/qwen3:8b"

    def test_criado_por_agente_sem_modelo(self):
        actor = Actor(kind="agente", role="curator")
        assert actor.criado_por == "curator"

    def test_agente_sem_role_levanta_erro(self):
        with pytest.raises(ValueError):
            Actor(kind="agente")

    def test_requires_provenance_justification(self):
        assert Actor(kind="agente", role="curator").requires_provenance_justification is True
        assert Actor(kind="orquestrador").requires_provenance_justification is False
        assert Actor(kind="pesquisador").requires_provenance_justification is False


@pytest.mark.unit
class TestPrepareNodeProperties:
    def test_autoria_nao_forjavel(self):
        """Scenario: Autoria não forjável — criado_por do chamador é ignorado."""
        actor = Actor(kind="agente", role="curator", model="qwen3:8b")
        caller_props = {"titulo": "x", "criado_por": "pesquisador"}
        full = prepare_node_properties(caller_props, actor)
        assert full["criado_por"] == "curator/qwen3:8b"

    def test_preenche_id_e_timestamps(self):
        actor = Actor(kind="orquestrador")
        full = prepare_node_properties({}, actor)
        assert full["id"]
        assert full["criado_em"] == full["atualizado_em"]

    def test_preenche_defaults(self):
        actor = Actor(kind="orquestrador")
        full = prepare_node_properties({}, actor)
        assert full["visibilidade"] == "privado"
        assert full["origem_no"] == "local"
        assert full["versao_schema"] == 1

    def test_respeita_valores_explicitos(self):
        actor = Actor(kind="orquestrador")
        full = prepare_node_properties({"visibilidade": "compartilhavel"}, actor)
        assert full["visibilidade"] == "compartilhavel"

    def test_ids_diferentes_a_cada_chamada(self):
        actor = Actor(kind="orquestrador")
        a = prepare_node_properties({}, actor)
        b = prepare_node_properties({}, actor)
        assert a["id"] != b["id"]


@pytest.mark.unit
class TestPrepareNodeUpdate:
    def test_adiciona_atualizado_em(self):
        result = prepare_node_update({"status": "contestada"})
        assert "atualizado_em" in result
        assert result["status"] == "contestada"


@pytest.mark.unit
class TestPrepareEdgeProperties:
    def test_autoria_edge_nao_forjavel(self):
        actor = Actor(kind="agente", role="curator", model="qwen3:8b")
        full = prepare_edge_properties({"criado_por": "pesquisador"}, actor)
        assert full["criado_por"] == "curator/qwen3:8b"

    def test_defaults_de_edge(self):
        actor = Actor(kind="orquestrador")
        full = prepare_edge_properties({}, actor)
        assert full["status"] == "confirmada"
        assert full["origem"] == "afirmado"
        assert full["evidencias"] == []
