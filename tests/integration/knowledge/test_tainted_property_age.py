"""Propriedade `tainted` em nós escritos por agentes, contra o Apache AGE real (v18.5-egress-gate, tarefa 4.3).

Escrito e NÃO executado no PR da mudança (restrição de ambiente: sem containers reais). Pulado automaticamente sem
uma instância de Apache AGE migrada (ver ``conftest.py`` deste diretório).
"""

from __future__ import annotations

import uuid

import pytest

from src.knowledge.graph_store import AgeGraphStore
from src.knowledge.provenance import Actor

CURATOR = Actor(kind="agente", role="curator", model="qwen3:8b")
ORQUESTRADOR = Actor(kind="orquestrador")


@pytest.mark.integration
def test_no_de_agente_guarda_e_devolve_tainted_booleano(age_store: AgeGraphStore):
    projeto_id = f"proj-{uuid.uuid4().hex[:8]}"
    sessao_id = f"sess-{uuid.uuid4().hex[:8]}"
    age_store.create_node(
        "Projeto",
        {"titulo": "T", "objetivo": "O", "status": "ativo", "projeto_id": projeto_id, "sessao_id": sessao_id},
        actor=ORQUESTRADOR,
    )
    node_id = age_store.create_node(
        "Descoberta",
        {
            "projeto_id": projeto_id,
            "sessao_id": sessao_id,
            "tipo": "funciona",
            "enunciado": "A acurácia chegou a 0.93",
            "n_evidencias": 1,
            "status": "ativa",
            "justificativa_criacao": "teste",
            "nos_consultados": [],
            "tainted": True,
        },
        actor=CURATOR,
    )

    node = age_store.get_node(node_id)

    assert node is not None and node.properties["tainted"] is True


@pytest.mark.integration
def test_no_anterior_a_v18_5_nao_tem_a_propriedade(age_store: AgeGraphStore):
    projeto_id = f"proj-{uuid.uuid4().hex[:8]}"
    node_id = age_store.create_node(
        "Projeto",
        {"titulo": "T", "objetivo": "O", "status": "ativo", "projeto_id": projeto_id, "sessao_id": "s"},
        actor=ORQUESTRADOR,
    )
    assert "tainted" not in age_store.get_node(node_id).properties
