"""Ferramentas de escrita do Curator e referências numéricas (spec numeric-provenance, requisito de contrato)."""

from __future__ import annotations

import pytest

from src.knowledge.curator_tools import CuratorToolError
from src.numeric_refs.resolver import ReferenceResolver
from src.provenance.ledger import get_ledger
from tests.support.controlled_embedding_provider import pair_vectors
from tests.unit.knowledge.conftest import DIM
from tests.unit.knowledge.test_curator_tools import _create, world  # noqa: F401 - fixture e helper compartilhados
from tests.unit.numeric_refs.helpers import record_run

pytestmark = pytest.mark.unit


@pytest.fixture
def toolkit(world, tmp_path):  # noqa: F811
    env, graph, tk, ids = world
    for axis, marker in ((1, "par1b"), (2, "par2c")):
        env.provider.vectors[marker] = pair_vectors(DIM, axis, 0.0)[1]
    outputs = tmp_path / "outputs"
    exec_id = record_run(get_ledger(), outputs, metrics={"acc": 0.87345})
    tk.numeric_resolver = ReferenceResolver(ledger=get_ledger(), output_dir=outputs, session_ids=["s1"])
    return tk, ids, exec_id


def test_referencia_valida_e_aceita_e_o_texto_canonico_e_gravado(toolkit):
    tk, ids, exec_id = toolkit
    enunciado = f"par1b: a acurácia chega a {{{{res:{exec_id}/acc}}}}"
    out = _create(tk, ids, enunciado=enunciado)
    assert out["ok"] is True and "avisos" not in out
    node = tk.store.get_node(out["id"])
    assert node.properties["enunciado"] == enunciado  # o grafo guarda o texto canônico (com a referência)


def test_referencia_que_nao_resolve_recusa_e_nada_e_gravado(toolkit):
    """Scenario: Ferramenta do Curator com referência inválida."""
    tk, ids, exec_id = toolkit
    before = len(tk.store.find_nodes("Descoberta", {}, limit=100))
    with pytest.raises(CuratorToolError, match="metrica_ausente"):
        _create(tk, ids, enunciado=f"par1b: {{{{res:{exec_id}/inexistente}}}}")
    assert len(tk.store.find_nodes("Descoberta", {}, limit=100)) == before


def test_referencia_malformada_recusa(toolkit):
    tk, ids, _ = toolkit
    with pytest.raises(CuratorToolError, match="inválidas"):
        _create(tk, ids, enunciado="par1b: {{res:exec_123/acc}}")


def test_numero_sem_referencia_e_aceito_com_aviso(toolkit):
    """Scenario: Ferramenta do Curator com número sem referência."""
    tk, ids, _ = toolkit
    out = _create(tk, ids, enunciado="par1b: reduz o erro em 12%")
    assert out["ok"] is True and out["avisos"] and "12%" in out["avisos"][0]
    assert "[não verificado]" in out["avisos"][0]
    # o aviso é por chamada: a seguinte não o repete
    again = _create(tk, ids, enunciado="par2c: outro achado distinto", tipo="licao_de_caminho")
    assert "avisos" not in again or all("12%" not in a for a in again["avisos"])


def test_nao_deixa_de_funcionar_sem_numeros(toolkit):
    tk, ids, _ = toolkit
    out = _create(tk, ids, enunciado="par1b: texto sem números")
    assert out["ok"] is True
