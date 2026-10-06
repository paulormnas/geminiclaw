"""Testes das faixas de similaridade, da fila e da geração de candidatos.

Cobrem "Faixas de similaridade", "Sem limite de conexões", "Fila de revisão fora do
grafo" e "Oportunidades entre projetos exigem evidência" (knowledge-semantics).
"""

import pytest

from src.knowledge.candidates import CandidateGenerator
from src.knowledge.domains import area_ancestor, between_domains, node_domains
from tests.support.controlled_embedding_provider import pair_vectors
from tests.unit.knowledge.conftest import DIM, ORQ


def _pair(env, axis: int, cosine: float, a: str | None = None, b: str | None = None):
    """Define vetores dos marcadores ``par{axis}a``/``par{axis}b`` com o cosseno dado."""
    va, vb = pair_vectors(DIM, axis, cosine)
    env.provider.vectors[a or f"par{axis}a"] = va
    env.provider.vectors[b or f"par{axis}b"] = vb


def _dominio(env, termo: str, nivel: str = "area", pai: str | None = None) -> str:
    dom_id = env.make("Dominio", termo=termo, nivel=nivel)
    if pai:
        env.store.create_edge(dom_id, "SUBAREA_DE", pai, {}, actor=ORQ)
    return dom_id


def _no_dominio(env, node_id: str, dominio_id: str) -> None:
    env.store.create_edge(node_id, "NO_DOMINIO", dominio_id, {}, actor=ORQ)


def _vetores_dominios(env) -> None:
    """Domínios não precisam de vetor próprio, mas são vetorizados: marcadores neutros e isolados."""
    for i, name in enumerate(("Quimica", "Historia", "Organica", "Inorganica")):
        va, _ = pair_vectors(DIM, 20 + i, 1.0)
        env.provider.vectors[f"termo: {name}"] = va


@pytest.mark.unit
class TestDominios:
    def test_subarea_sobe_para_area(self, env):
        _vetores_dominios(env)
        quimica = _dominio(env, "Quimica")
        organica = _dominio(env, "Organica", nivel="subarea", pai=quimica)
        assert area_ancestor(env.raw, organica) == quimica
        assert area_ancestor(env.raw, quimica) == quimica

    def test_quimica_organica_e_inorganica_sao_o_mesmo_dominio(self, env):
        _vetores_dominios(env)
        _pair(env, 0, 0.8)
        quimica = _dominio(env, "Quimica")
        org = _dominio(env, "Organica", nivel="subarea", pai=quimica)
        ino = _dominio(env, "Inorganica", nivel="subarea", pai=quimica)
        p1 = env.make("Problema", titulo="par0a")
        p2 = env.make("Problema", titulo="par0b")
        _no_dominio(env, p1, org)
        _no_dominio(env, p2, ino)
        d1 = node_domains(env.raw, env.node(p1))
        d2 = node_domains(env.raw, env.node(p2))
        assert d1 == d2 == frozenset({quimica})
        assert not between_domains(d1, d2)

    def test_dominios_de_nos_nao_problema_vem_do_problema_do_projeto(self, env):
        _vetores_dominios(env)
        _pair(env, 0, 0.8)
        quimica = _dominio(env, "Quimica")
        p1 = env.make("Problema", titulo="par0a", projeto_id="projX")
        _no_dominio(env, p1, quimica)
        abordagem = env.make("Abordagem", projeto_id="projX", nome="par0b")
        assert node_domains(env.raw, env.node(abordagem)) == frozenset({quimica})

    def test_sem_dominio_nao_conta_como_entre_dominios(self):
        assert not between_domains(frozenset(), frozenset({"x"}))
        assert between_domains(frozenset({"a"}), frozenset({"b"}))


@pytest.mark.unit
class TestFaixas:
    def _dois_problemas(self, env, cosine: float, dom_a: str, dom_b: str):
        _vetores_dominios(env)
        _pair(env, 0, cosine)
        d_a = _dominio(env, dom_a)
        d_b = d_a if dom_a == dom_b else _dominio(env, dom_b)
        p1 = env.make("Problema", titulo="par0a")
        _no_dominio(env, p1, d_a)
        p2 = env.make("Problema", titulo="par0b")
        _no_dominio(env, p2, d_b)
        return p1, p2

    def test_faixa_baixa_no_mesmo_dominio(self, env):
        """Scenario: Faixa baixa no mesmo domínio"""
        self._dois_problemas(env, 0.65, "Quimica", "Quimica")
        assert env.queue.pending_count() == 0

    def test_faixa_baixa_entre_dominios(self, env):
        """Scenario: Faixa baixa entre domínios"""
        p1, p2 = self._dois_problemas(env, 0.65, "Quimica", "Historia")
        itens = env.queue.next_batch(10)
        assert len(itens) == 1
        c = itens[0].candidate
        assert c.tipo == "relacionado"
        assert c.entre_dominios is True
        assert {c.node_a, c.node_b} == {p1, p2}
        assert c.node_a < c.node_b
        assert c.score == pytest.approx(0.65, abs=1e-4)

    def test_mesmo_dominio_acima_de_070_entra(self, env):
        self._dois_problemas(env, 0.75, "Quimica", "Quimica")
        (item,) = env.queue.next_batch(10)
        assert item.candidate.tipo == "relacionado"
        assert item.candidate.entre_dominios is False

    def test_abaixo_de_060_e_ignorado(self, env):
        self._dois_problemas(env, 0.55, "Quimica", "Historia")
        assert env.queue.pending_count() == 0

    def test_duplicata(self, env):
        """Scenario: Duplicata"""
        _pair(env, 0, 0.93, "nome: par0a", "nome: par0b")
        env.make("Abordagem", nome="par0a")
        env.make("Abordagem", nome="par0b")
        (item,) = env.queue.next_batch(10)
        assert item.candidate.tipo == "duplicata"

    def test_hipotese_e_decisao_nao_geram_candidatos(self, env):
        _pair(env, 0, 0.95, "contexto: par0a", "contexto: par0b")
        env.make("Decisao", contexto="par0a")
        env.make("Decisao", contexto="par0b")
        assert env.queue.pending_count() == 0

    def test_status_substituida_e_ignorado(self, env):
        _pair(env, 0, 0.95, "enunciado: par0a", "enunciado: par0b")
        env.make("Descoberta", enunciado="par0a", status="substituida")
        env.make("Descoberta", enunciado="par0b")
        assert env.queue.pending_count() == 0

    def test_dominio_atribuido_depois_da_criacao_reavalia_o_par(self, env):
        _vetores_dominios(env)
        _pair(env, 0, 0.65)
        quimica = _dominio(env, "Quimica")
        historia = _dominio(env, "Historia")
        p1 = env.make("Problema", titulo="par0a")
        _no_dominio(env, p1, quimica)
        p2 = env.make("Problema", titulo="par0b")
        assert env.queue.pending_count() == 0  # P2 ainda sem domínio
        _no_dominio(env, p2, historia)
        assert env.queue.pending_count() == 1


@pytest.mark.unit
class TestSemLimite:
    @pytest.mark.parametrize("scan_limit", [200, 7])
    def test_muitos_vizinhos(self, env, scan_limit):
        """Scenario: Muitos vizinhos"""
        env.generator = CandidateGenerator(env.raw, env.index, env.queue, scan_limit=scan_limit)
        env.index._listeners.clear()  # noqa: SLF001
        env.generator.attach()
        base = [0.0] * DIM
        base[0] = 1.0
        env.provider.vectors["titulo: base"] = base
        env.make("Problema", titulo="base")
        for k in range(1, 51):
            vec = [0.0] * DIM
            vec[0], vec[k + 1 if k + 1 < DIM else DIM - 1] = 0.8, 0.6
            env.provider.vectors[f"titulo: viz{k:03d}"] = vec
            env.make("Problema", titulo=f"viz{k:03d}")
        # 50 pares base<->vizinho (0,80); pares vizinho<->vizinho (0,64) ficam fora (mesma faixa baixa, sem domínio)
        assert env.queue.pending_count() == 50


@pytest.mark.unit
class TestFila:
    def test_candidato_nao_vira_aresta(self, env):
        """Scenario: Candidato não vira aresta"""
        _pair(env, 0, 0.93, "nome: par0a", "nome: par0b")
        a = env.make("Abordagem", nome="par0a")
        b = env.make("Abordagem", nome="par0b")
        assert env.queue.pending_count() == 1
        assert env.raw.neighbors(a, ["SEMELHANTE_A"]).edges == []
        assert env.raw.neighbors(b, ["SEMELHANTE_A"]).edges == []

    def test_prioridade_entre_dominios(self, env):
        """Scenario: Prioridade entre domínios"""
        _vetores_dominios(env)
        _pair(env, 0, 0.75)  # par entre domínios
        _pair(env, 1, 0.75)  # par no mesmo domínio
        quimica, historia = _dominio(env, "Quimica"), _dominio(env, "Historia")
        # o par do mesmo domínio é criado primeiro, para provar que a ordem vem da prioridade
        s1 = env.make("Problema", titulo="par1a")
        _no_dominio(env, s1, quimica)
        s2 = env.make("Problema", titulo="par1b")
        _no_dominio(env, s2, quimica)
        c1 = env.make("Problema", titulo="par0a")
        _no_dominio(env, c1, quimica)
        c2 = env.make("Problema", titulo="par0b")
        _no_dominio(env, c2, historia)

        primeiro, segundo = env.queue.next_batch(10)
        assert primeiro.candidate.entre_dominios is True
        assert segundo.candidate.entre_dominios is False
        assert primeiro.candidate.prioridade == pytest.approx(segundo.candidate.prioridade * 1.5, rel=1e-3)

    def test_prioridade_usa_maior_confianca_ou_peso_padrao(self, env):
        _pair(env, 0, 0.8, "enunciado: par0a", "enunciado: par0b")
        _pair(env, 1, 0.8, "enunciado: par1a", "enunciado: par1b")
        env.make("Descoberta", enunciado="par0a")  # sem veredito
        env.make("Descoberta", enunciado="par0b")
        env.make("Descoberta", enunciado="par1a", confianca=0.9, veredito=0.9)
        env.make("Descoberta", enunciado="par1b", confianca=0.4, veredito=0.4)
        com_evidencia, sem_evidencia = env.queue.next_batch(10)
        assert com_evidencia.candidate.prioridade == pytest.approx(0.8 * 0.9, rel=1e-3)
        assert sem_evidencia.candidate.prioridade == pytest.approx(0.8 * 0.5, rel=1e-3)

    def test_par_ja_avaliado(self, env):
        """Scenario: Par já avaliado"""
        _pair(env, 0, 0.93, "nome: par0a", "nome: par0b")
        env.provider.vectors["nome: par0c"] = env.provider.vectors["nome: par0b"]
        a = env.make("Abordagem", nome="par0a")
        b = env.make("Abordagem", nome="par0b")
        (item,) = env.queue.next_batch(10)
        env.queue.mark_discarded(item.id, "pesquisador", "variação irrelevante")
        assert env.queue.pending_count() == 0

        # mesma varredura, mesmos textos: não volta
        assert env.generator.scan(env.node(a)) == 0
        assert env.generator.scan(env.node(b)) == 0
        assert env.queue.pending_count() == 0

        # o texto de um dos nós muda: o par pode voltar como novo registro
        env.provider.vectors["nome: par0c"] = env.provider.vectors["nome: par0b"]
        env.store.update_node(b, {"nome": "par0c"}, actor=ORQ)
        assert env.queue.pending_count() == 1

    def test_confirmar_e_descartar_registram_revisao(self, env):
        _pair(env, 0, 0.93, "nome: par0a", "nome: par0b")
        env.make("Abordagem", nome="par0a")
        env.make("Abordagem", nome="par0b")
        (item,) = env.queue.next_batch(10)
        env.queue.mark_confirmed(item.id, "curator", "mesma técnica")
        from src.knowledge.similarity_queue import QueueItemError

        with pytest.raises(QueueItemError):
            env.queue.mark_confirmed(item.id, "curator")


@pytest.mark.unit
class TestOportunidadeEntreProjetos:
    def _par(self, env, veredito: float, cosine: float = 0.75):
        va, vb = pair_vectors(DIM, 0, cosine)
        env.provider.vectors["enunciado: descob"] = va
        env.provider.vectors["titulo: probl"] = vb
        env.make("Problema", projeto_id="projB", titulo="probl")
        env.make("Descoberta", projeto_id="projA", enunciado="descob", veredito=veredito, confianca=abs(veredito))

    def test_descoberta_fraca(self, env):
        """Scenario: Descoberta fraca"""
        self._par(env, 0.2)
        assert env.queue.pending_count() == 0

    def test_descoberta_com_evidencia_moderada_entra(self, env):
        self._par(env, 0.35)
        (item,) = env.queue.next_batch(10)
        c = item.candidate
        assert c.tipo == "relacionado"
        assert c.entre_projetos is True
        assert {c.label_a, c.label_b} == {"Descoberta", "Problema"}

    def test_veredito_negativo_forte_tambem_entra(self, env):
        self._par(env, -0.5)
        assert env.queue.pending_count() == 1

    def test_mesmo_projeto_nao_entra(self, env):
        va, vb = pair_vectors(DIM, 0, 0.75)
        env.provider.vectors["enunciado: descob"] = va
        env.provider.vectors["titulo: probl"] = vb
        env.make("Problema", projeto_id="projA", titulo="probl")
        env.make("Descoberta", projeto_id="projA", enunciado="descob", veredito=0.9, confianca=0.9)
        assert env.queue.pending_count() == 0
