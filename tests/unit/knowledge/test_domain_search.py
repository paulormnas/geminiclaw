"""Testes de v17-domain-search (capacidade domain-search): texto, payload, reconciliação, busca e resolução.

Sem rede, sem banco e sem modelo: grafo, Qdrant e embeddings em memória (``tests/support/domain_env.py``).
"""

from unittest.mock import MagicMock

import pytest

from src import config
from src.embeddings.base import text_hash
from src.knowledge.graph_store import Node
from src.knowledge.semantic_index import domain_canonical_text
from src.knowledge.vocabulary import resolve_domain
from tests.support.domain_env import DIM, ORQ, DomainEnv


def _node(termo, nivel, **extra) -> Node:
    return Node(id=f"id-{termo}", label="Dominio", properties={"termo": termo, "nivel": nivel, **extra})


def _conjuntos_chain() -> tuple[Node, list[Node]]:
    ga = _node("Ciências Exatas e da Terra", "grande_area")
    mat = _node("Matemática", "area")
    alg = _node("Álgebra", "subarea")
    conj = _node("Conjuntos", "especialidade", sinonimos=["teoria dos conjuntos", "set theory"])
    return conj, [ga, mat, alg]


@pytest.fixture
def env() -> DomainEnv:
    return DomainEnv()


@pytest.mark.unit
class TestTextoCanonicoHierarquico:
    def test_especialidade_com_todos_os_ancestrais(self):
        """Scenario: Especialidade com todos os ancestrais"""
        conj, ancestors = _conjuntos_chain()
        text = domain_canonical_text(conj, ancestors)
        assert text.splitlines()[:3] == [
            "Domínio: Conjuntos",
            "Nível: especialidade",
            "Caminho: Ciências Exatas e da Terra > Matemática > Álgebra > Conjuntos",
        ]
        assert "Grande área: Ciências Exatas e da Terra" in text
        assert "Área: Matemática" in text
        assert "Subárea: Álgebra" in text
        assert text.endswith("Sinônimos: teoria dos conjuntos; set theory")

    def test_grande_area(self):
        """Scenario: Grande área"""
        ga = _node("Ciências Exatas e da Terra", "grande_area")
        text = domain_canonical_text(ga, [])
        assert text.splitlines() == [
            "Domínio: Ciências Exatas e da Terra",
            "Nível: grande_area",
            "Caminho: Ciências Exatas e da Terra",
        ]

    def test_sinonimos_candidatos_ficam_de_fora(self):
        """Scenario: Sinônimos candidatos ficam de fora"""
        node = _node("Conjuntos", "especialidade", sinonimos=["set theory"], sinonimos_candidatos=["conjuntos fuzzy"])
        text = domain_canonical_text(node, [])
        assert "Sinônimos: set theory" in text
        assert "conjuntos fuzzy" not in text

    def test_texto_estavel(self):
        """Scenario: Texto estável"""
        conj, ancestors = _conjuntos_chain()
        first, second = domain_canonical_text(conj, ancestors), domain_canonical_text(conj, ancestors)
        assert first == second
        assert text_hash(first) == text_hash(second)


@pytest.mark.unit
class TestPayloadHierarquico:
    def test_ordem_do_caminho(self, env):
        """Scenario: Ordem do caminho"""
        ga = env.dom("Exatas", "grande_area", codigo="C0")
        mat = env.dom("Matemática", "area", ga, codigo="C1")
        alg = env.dom("Álgebra", "subarea", mat, codigo="C2")
        conj = env.dom("Conjuntos", "especialidade", alg, codigo="C3")
        env.reconcile()
        payload = env.client.retrieve(env.index.collection, ids=[conj], with_payload=True)[0].payload
        assert payload["caminho_ids"] == [ga, mat, alg, conj]
        assert payload["caminho_termos"] == ["Exatas", "Matemática", "Álgebra", "Conjuntos"]
        assert payload["nivel"] == "especialidade"
        assert payload["caminho_completo"] is True
        assert payload["codigo_cnpq"] == "C3"

    def test_candidato_sem_pai(self, env):
        """Scenario: Candidato sem pai"""
        cand = env.dom("Termo Novo", "especialidade", status="candidato")
        env.reconcile()
        payload = env.client.retrieve(env.index.collection, ids=[cand], with_payload=True)[0].payload
        assert payload["caminho_ids"] == [cand]
        assert payload["caminho_completo"] is False

    def test_cadeia_interrompida(self, env, monkeypatch):
        """Scenario: Cadeia interrompida"""
        warning = MagicMock()
        monkeypatch.setattr("src.knowledge.domains.logger", MagicMock(warning=warning))
        orfao = env.dom("Órfão", "subarea")  # aprovado, mas sem SUBAREA_DE
        created = env.store.create_node(
            "Dominio",
            {"termo": "Outro", "nivel": "subarea", "status": "aprovado", "projeto_id": "__global__", "sessao_id": "s"},
            actor=ORQ,
        )
        point = env.client.retrieve(env.index.collection, ids=[created], with_payload=True)[0]
        assert point.payload["caminho_completo"] is False
        assert env.raw.get_node(created) is not None  # a escrita do nó não falhou
        env.reconcile()
        assert env.client.retrieve(env.index.collection, ids=[orfao], with_payload=True)[0].payload[
            "caminho_completo"
        ] is False
        assert warning.called

    def test_indice_keyword_em_caminho_ids_e_nivel(self, env, monkeypatch):
        created = []
        monkeypatch.setattr(
            env.client, "create_payload_index",
            lambda collection_name, field_name, field_schema: created.append((field_name, str(field_schema))),
        )
        env.index.ensure_collection()
        assert sorted(name for name, _ in created) == ["caminho_ids", "nivel"]
        assert all("keyword" in kind.lower() for _, kind in created)

    def test_reindexacao_dos_dominios_existentes(self, env):
        """Scenario: Reindexação dos domínios existentes"""
        ga = env.dom("Exatas", "grande_area", codigo="C0")
        mat = env.dom("Matemática", "area", ga, codigo="C1")
        env.index.ensure_collection()
        from qdrant_client.models import PointStruct

        old_text = "termo: Matemática"
        env.client.upsert(
            env.index.collection,
            points=[PointStruct(
                id=mat, vector=[0.0] * (DIM - 1) + [1.0],
                payload={"tipo_no": "Dominio", "status": "aprovado", "projeto_id": "__global__",
                         "visibilidade": "compartilhavel", "text_hash": text_hash(old_text),
                         "embedding_model": env.provider.info.model,
                         "embedding_version": env.provider.info.version},
            )],
        )
        env.raw.update_node(mat, {"estado_vetorizacao": "ok"}, actor=ORQ)
        report = env.reconcile()
        assert report.reindexed >= 1
        payload = env.client.retrieve(env.index.collection, ids=[mat], with_payload=True)[0].payload
        assert payload["caminho_ids"] == [ga, mat]
        assert payload["text_hash"] == text_hash(env.index.text_for(env.raw.get_node(mat)))


@pytest.mark.unit
class TestReconciliacaoPorAncestral:
    def test_renomeacao_de_uma_area(self, env):
        """Scenario: Renomeação de uma área"""
        ga = env.dom("Exatas", "grande_area", codigo="C0")
        area = env.dom("Matemática", "area", ga, codigo="C1")
        descendants = []
        for i in range(3):
            sub = env.dom(f"Sub{i}", "subarea", area, codigo=f"S{i}")
            descendants.append(sub)
            for j in range(3 if i < 2 else 4):
                descendants.append(env.dom(f"Esp{i}{j}", "especialidade", sub, codigo=f"E{i}{j}"))
        assert len(descendants) == 13
        env.reconcile()
        old_hash = {d: env.client.retrieve(env.index.collection, ids=[d], with_payload=True)[0].payload["text_hash"]
                    for d in descendants}

        env.store.update_node(area, {"termo": "Matemática Pura"}, actor=ORQ)

        assert all(env.raw.get_node(d).properties["estado_vetorizacao"] == "pendente" for d in descendants)
        env.reconcile()
        for d in descendants:
            node = env.raw.get_node(d)
            payload = env.client.retrieve(env.index.collection, ids=[d], with_payload=True)[0].payload
            assert node.properties["estado_vetorizacao"] == "ok"
            assert payload["text_hash"] != old_hash[d]
            assert payload["text_hash"] == text_hash(env.index.text_for(node))
            assert "Matemática Pura" in payload["caminho_termos"]

    def test_lote_limitado(self, env, monkeypatch):
        """Scenario: Lote limitado"""
        monkeypatch.setattr(config, "DOMAIN_REINDEX_BATCH", 200)
        ga = env.dom("Exatas", "grande_area")
        area = env.dom("Matemática", "area", ga)
        for i in range(450):
            env.dom(f"Sub{i}", "subarea", area)
        assert env.index.mark_descendants_pending(area) == [200, 200, 50]


def _ranked(hits):
    return [h.termo for h in hits]


@pytest.mark.unit
class TestBuscaHierarquica:
    def test_caminho_completo_no_resultado(self, env):
        """Scenario: Caminho completo no resultado"""
        ids = env.build_cs()
        env.query("inteligência artificial")
        env.vec("Inteligência Artificial", 0.9)
        env.reconcile()
        hits = env.search.search("inteligência artificial")
        assert hits[0].termo == "Inteligência Artificial"
        assert hits[0].caminho == ["Ciências Exatas e da Terra", "Ciência da Computação", "Inteligência Artificial"]
        assert hits[0].nivel == "subarea"
        assert hits[0].caminho_ids == [ids["ga"], ids["cs"], ids["ia"]]
        assert hits[0].status == "aprovado"

    def test_preferencia_pelo_mais_especifico(self, env, monkeypatch):
        """Scenario: Preferência pelo mais específico"""
        monkeypatch.setattr(config, "DOMAIN_SPECIFICITY_MARGIN", 0.03)
        env.build_cs()
        env.query("estatística")
        env.vec("Ciência da Computação", 0.72)
        env.vec("Inteligência Artificial", 0.71)
        env.reconcile()
        assert _ranked(env.search.search("estatística"))[:2] == ["Inteligência Artificial", "Ciência da Computação"]

    def test_fora_da_margem_vale_o_score(self, env, monkeypatch):
        """Scenario: Fora da margem vale o score"""
        monkeypatch.setattr(config, "DOMAIN_SPECIFICITY_MARGIN", 0.03)
        env.build_cs()
        env.query("estatística")
        env.vec("Ciência da Computação", 0.80)
        env.vec("Inteligência Artificial", 0.70)
        env.reconcile()
        assert _ranked(env.search.search("estatística"))[:2] == ["Ciência da Computação", "Inteligência Artificial"]

    def test_restricao_a_subarvore(self, env):
        """Scenario: Restrição à subárvore"""
        ids = env.build_cs()
        env.query("modelos")
        for termo in ("Ciência da Computação", "Inteligência Artificial", "Matemática", "Álgebra"):
            env.vec(termo, 0.8)
        env.reconcile()
        by_code = env.search.search("modelos", within="T1")
        by_id = env.search.search("modelos", within=ids["cs"])
        assert by_code and _ranked(by_code) == _ranked(by_id)
        assert all(ids["cs"] in h.caminho_ids for h in by_code)
        assert "Matemática" not in _ranked(by_code)

    def test_dentro_de_desconhecido_e_erro_sem_busca_global(self, env):
        env.build_cs()
        env.query("modelos")
        env.vec("Matemática", 0.8)
        env.reconcile()
        with pytest.raises(ValueError, match="dentro_de"):
            env.search.search("modelos", within="não-existe")
        assert env.provider.queries == []

    def test_nivel_maximo(self, env):
        """Scenario: Nível máximo"""
        env.build_cs()
        env.query("computação")
        termos = (
            "Ciência da Computação", "Inteligência Artificial", "Aprendizado Supervisionado",
            "Ciências Exatas e da Terra",
        )
        for termo in termos:
            env.vec(termo, 0.8)
        env.reconcile()
        hits = env.search.search("computação", max_level="area")
        assert hits and all(h.nivel in ("grande_area", "area") for h in hits)
        with pytest.raises(ValueError):
            env.search.search("computação", max_level="inexistente")

    def test_candidatos_excluidos_por_padrao(self, env):
        """Scenario: Candidatos excluídos por padrão"""
        ids = env.build_cs()
        cand = env.dom("Termo Candidato", "especialidade", ids["ia"], status="candidato")
        env.query("candidato similar")
        env.vec("Termo Candidato", 0.95)
        env.reconcile()
        assert cand not in [h.node_id for h in env.search.search("candidato similar")]
        hits = env.search.search("candidato similar", include_candidates=True)
        assert hits[0].node_id == cand and hits[0].status == "candidato"

    def test_sem_correspondencia(self, env):
        """Scenario: Sem correspondência"""
        env.build_cs()
        env.query("assunto sem relação")
        env.vec("Inteligência Artificial", 0.2)  # abaixo de DOMAIN_SEARCH_MIN_SCORE (0,35)
        env.reconcile()
        assert env.search.search("assunto sem relação") == []

    def test_limite_de_resultados(self, env):
        """Scenario: Limite de resultados"""
        ga = env.dom("Exatas", "grande_area")
        env.query("tema amplo")
        for i in range(14):
            env.dom(f"Área {i:02d}", "area", ga)
            env.vec(f"Área {i:02d}", 0.9)
        env.reconcile()
        assert len(env.search.search("tema amplo", limit=50)) == 10
        assert len(env.search.search("tema amplo")) == config.DOMAIN_SEARCH_LIMIT

    @pytest.mark.parametrize("text", ["", "   ", "a"])
    def test_entrada_vazia(self, env, text):
        """Scenario: Entrada vazia"""
        with pytest.raises(ValueError):
            env.search.search(text)

    def test_entrada_longa(self, env, monkeypatch):
        """Scenario: Entrada longa"""
        warning = MagicMock()
        monkeypatch.setattr("src.knowledge.domain_search.logger", MagicMock(warning=warning))
        monkeypatch.setattr(config, "DOMAIN_SEARCH_MAX_QUERY_CHARS", 300)
        env.build_cs()
        env.query("a" * 300)
        env.vec("Inteligência Artificial", 0.9)
        env.reconcile()
        hits = env.search.search("a" * 2000)
        assert hits and hits[0].termo == "Inteligência Artificial"
        assert env.provider.queries[-1] == "Domínio: " + "a" * 300
        assert warning.called
        logged = str(warning.call_args)
        assert "a" * 50 not in logged  # o texto da consulta não vai para o log

    def test_contexto_vai_para_a_consulta(self, env):
        env.build_cs()
        env.query("termo")
        env.vec("Inteligência Artificial", 0.9)
        env.reconcile()
        env.search.search("termo", context="Problema de classificação")
        assert env.provider.queries[-1] == "Domínio: termo\nContexto: Problema de classificação"


@pytest.mark.unit
class TestResolveDomainSemantico:
    def _setup(self, env, cosines):
        ids = env.build_cs()
        env.query("aprendizado de máquina")
        for termo, cos in cosines.items():
            env.vec(termo, cos)
        env.reconcile()
        return ids

    def test_correspondencia_semantica(self, env):
        """Scenario: Correspondência semântica"""
        ids = self._setup(env, {"Inteligência Artificial": 0.95, "Ciência da Computação": 0.5})
        result = resolve_domain(
            env.raw, "aprendizado de máquina", actor=ORQ, sessao_id="s1", domain_search=env.search
        )
        assert result.status == "semantico"
        assert result.node_id == ids["ia"]
        assert (ids["cs"], pytest.approx(0.5, abs=0.01)) in result.alternativas

    def test_abaixo_do_limiar(self, env):
        """Scenario: Abaixo do limiar"""
        ids = self._setup(
            env,
            {"Inteligência Artificial": 0.6, "Ciência da Computação": 0.5, "Aprendizado Supervisionado": 0.45,
             "Matemática": 0.4},
        )
        result = resolve_domain(
            env.raw, "aprendizado de máquina", actor=ORQ, sessao_id="s1", domain_search=env.search
        )
        assert result.status == "candidato_criado"
        assert [a[0] for a in result.alternativas] == [ids["ia"], ids["cs"], ids["ml"]]

    def test_semantic_search_injetavel_tem_precedencia(self, env):
        ids = self._setup(env, {"Inteligência Artificial": 0.95})
        result = resolve_domain(
            env.raw, "aprendizado de máquina", actor=ORQ, sessao_id="s1",
            semantic_search=lambda label, term: [(ids["alg"], 0.99)], domain_search=env.search,
        )
        assert result.node_id == ids["alg"]
        assert env.provider.queries == []

    def test_termo_curto_segue_para_candidato(self, env):
        self._setup(env, {})
        result = resolve_domain(env.raw, "x", actor=ORQ, sessao_id="s1", domain_search=env.search)
        assert result.status == "candidato_criado"


@pytest.mark.unit
class TestConfiguracao:
    def test_padroes(self):
        """Padrões do design §7 (6.1)."""
        assert config.DOMAIN_SEARCH_LIMIT == 5
        assert config.DOMAIN_SEARCH_MIN_SCORE == pytest.approx(0.35)
        assert config.DOMAIN_SPECIFICITY_MARGIN == pytest.approx(0.03)
        assert config.DOMAIN_SEARCH_MAX_QUERY_CHARS == 300
        assert config.DOMAIN_REINDEX_BATCH == 200

    def test_env_example_documenta_as_variaveis(self):
        from pathlib import Path

        text = (Path(__file__).resolve().parents[3] / ".env.example").read_text(encoding="utf-8")
        for name in ("DOMAIN_SEARCH_LIMIT", "DOMAIN_SEARCH_MIN_SCORE", "DOMAIN_SPECIFICITY_MARGIN",
                     "DOMAIN_SEARCH_MAX_QUERY_CHARS", "DOMAIN_REINDEX_BATCH"):
            assert f"{name}=" in text

