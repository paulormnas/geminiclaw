"""Testes do índice semântico (v17-knowledge-semantic-index, capacidade knowledge-semantics).

Cobrem os cenários de "Vetor com o mesmo ID do nó" e "Grafo como fonte da verdade"
com Qdrant em memória e provedor de embedding controlado (sem rede).
"""

import pytest

from src.knowledge.errors import ImmutableFieldError
from src.knowledge.semantic_index import IndexDimensionError, canonical_text
from tests.support.controlled_embedding_provider import ControlledEmbeddingProvider, pair_vectors
from tests.unit.knowledge.conftest import DIM, ORQ


def _vec(env, marker: str, axis: int = 0, cosine: float = 1.0, second: bool = False):
    a, b = pair_vectors(DIM, axis, cosine)
    env.provider.vectors[marker] = b if second else a


@pytest.mark.unit
class TestCanonicalText:
    def test_problema_inclui_campos_na_ordem_com_rotulos(self):
        text = canonical_text(
            "Problema",
            {
                "titulo": "T", "resumo": "R", "classe": "classificacao",
                "criterio_sucesso": {"metrica": "f1", "alvo": 0.8},
            },
        )
        assert text == "titulo: T\nresumo: R\nclasse: classificacao\ncriterio_sucesso: alvo=0.8, metrica=f1"

    def test_dominio_usa_o_texto_hierarquico(self):
        """Scenario: Reindexação dos domínios existentes (texto novo; v17-domain-search)."""
        assert canonical_text(
            "Dominio", {"termo": "Química", "nivel": "area", "sinonimos": ["Chemistry", "Quím."]}
        ) == "Domínio: Química\nNível: area\nCaminho: Química\nSinônimos: Chemistry; Quím."

    @pytest.mark.parametrize("label", ["Sessao", "Insumo", "Experimento", "Resultado"])
    def test_rotulos_nao_vetorizados_devolvem_none(self, label):
        assert canonical_text(label, {"titulo": "x"}) is None


@pytest.mark.unit
class TestVetorComMesmoId:
    def test_no_criado(self, env):
        """Scenario: Nó criado"""
        _vec(env, "titulo: P1")
        node_id = env.make("Problema", titulo="P1")

        point = env.point(node_id)
        assert point is not None
        assert str(point.id) == node_id
        assert point.payload["tipo_no"] == "Problema"
        info = env.provider.info
        assert point.payload["embedding_model"] == info.model
        assert point.payload["embedding_version"] == info.version
        assert point.payload["embedding_dim"] == info.dimension
        assert point.payload["text_hash"]
        assert env.node(node_id).properties["estado_vetorizacao"] == "ok"

    def test_payload_tem_metadados_de_filtro(self, env):
        _vec(env, "titulo: P1")
        node_id = env.make("Problema", titulo="P1", visibilidade="compartilhavel")
        payload = env.point(node_id).payload
        assert payload["projeto_id"] == "proj1"
        assert payload["status"] == "confirmado"
        assert payload["visibilidade"] == "compartilhavel"
        assert payload["dominios"] == []
        assert payload["criado_em"]

    def test_tipos_nao_vetorizados(self, env):
        """Scenario: Tipos não vetorizados"""
        exp_id = env.make("Experimento")
        res_id = env.make("Resultado")
        assert env.point(exp_id) is None
        assert env.point(res_id) is None
        assert "estado_vetorizacao" not in env.node(exp_id).properties
        assert env.provider.embedded_texts == []

    def test_caller_nao_pode_gravar_estado_de_vetorizacao(self, env):
        with pytest.raises(ImmutableFieldError):
            env.store.create_node(
                "Problema",
                {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": "p", "sessao_id": "s",
                 "estado_vetorizacao": "ok"},
                actor=ORQ,
            )


@pytest.mark.unit
class TestRevetorizacao:
    def test_alterar_texto_revetoriza(self, env):
        _vec(env, "titulo: antigo")
        _vec(env, "titulo: novo", axis=1)
        node_id = env.make("Problema", titulo="antigo")
        old_hash = env.point(node_id).payload["text_hash"]
        calls = len(env.provider.embedded_texts)

        env.store.update_node(node_id, {"titulo": "novo"}, actor=ORQ)

        point = env.point(node_id)
        assert len(env.provider.embedded_texts) == calls + 1
        assert point.payload["text_hash"] != old_hash
        assert point.vector[2] == pytest.approx(1.0)  # vetor do eixo 1
        assert env.node(node_id).properties["estado_vetorizacao"] == "ok"

    def test_alterar_so_status_nao_revetoriza_mas_atualiza_payload(self, env):
        _vec(env, "titulo: P1")
        node_id = env.make("Problema", titulo="P1", status="rascunho")
        calls = len(env.provider.embedded_texts)

        env.store.update_node(node_id, {"status": "confirmado"}, actor=ORQ)

        assert len(env.provider.embedded_texts) == calls
        assert env.point(node_id).payload["status"] == "confirmado"


@pytest.mark.unit
class TestGrafoFonteDaVerdade:
    def test_qdrant_indisponivel_deixa_pendente_e_reconcile_corrige(self, env, monkeypatch):
        """Scenario: Qdrant indisponível"""
        _vec(env, "titulo: P1")
        env.index.ensure_collection()
        original = env.client.upsert

        def _down(*args, **kwargs):
            raise ConnectionError("qdrant fora do ar")

        monkeypatch.setattr(env.client, "upsert", _down)
        node_id = env.make("Problema", titulo="P1")

        assert env.node(node_id) is not None  # o nó existe no grafo
        assert env.node(node_id).properties["estado_vetorizacao"] == "pendente"
        assert env.point(node_id) is None

        monkeypatch.setattr(env.client, "upsert", original)
        report = env.index.reconcile()

        assert report.reindexed == 1
        assert env.point(node_id) is not None
        assert env.node(node_id).properties["estado_vetorizacao"] == "ok"

    def test_troca_de_modelo(self, env):
        """Scenario: Troca de modelo"""
        _vec(env, "titulo: P1")
        _vec(env, "nome: A1", axis=1)
        p_id = env.make("Problema", titulo="P1")
        a_id = env.make("Abordagem", nome="A1")
        assert env.point(p_id).payload["embedding_model"] == "controlled/test"

        env.provider.set_info(model="controlled/novo", version="2")
        report = env.index.reconcile()

        assert report.reindexed == 2
        for node_id in (p_id, a_id):
            payload = env.point(node_id).payload
            assert payload["embedding_model"] == "controlled/novo"
            assert payload["embedding_version"] == "2"

    def test_reconcile_sem_pendencias_nao_revetoriza(self, env):
        _vec(env, "titulo: P1")
        env.make("Problema", titulo="P1")
        calls = len(env.provider.embedded_texts)
        report = env.index.reconcile()
        assert report.reindexed == 0 and report.checked == 1
        assert len(env.provider.embedded_texts) == calls

    def test_reconcile_detecta_text_hash_divergente(self, env):
        _vec(env, "titulo: P1")
        node_id = env.make("Problema", titulo="P1")
        env.client.set_payload(env.index.collection, payload={"text_hash": "velho"}, points=[node_id])
        assert env.index.reconcile().reindexed == 1
        assert env.point(node_id).payload["text_hash"] != "velho"

    def test_dimensao_diferente_exige_confirmacao_para_recriar(self, env):
        _vec(env, "titulo: P1")
        node_id = env.make("Problema", titulo="P1")
        env.index._provider_arg = ControlledEmbeddingProvider(  # noqa: SLF001
            {"titulo: P1": [1.0] * 4}, dimension=4, model="controlled/outro"
        )
        env.index._ready = False  # noqa: SLF001
        with pytest.raises(IndexDimensionError):
            env.index.reconcile()
        report = env.index.reconcile(allow_recreate=True)
        assert report.reindexed == 1
        assert len(env.point(node_id).vector) == 4
