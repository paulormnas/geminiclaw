"""Testes da consulta híbrida ``related_experience`` (Qdrant -> grafo -> ranking)."""

from datetime import datetime, timedelta, timezone

import pytest

from src import config
from tests.support.controlled_embedding_provider import pair_vectors
from tests.unit.knowledge.conftest import DIM, ORQ


def _setup(env):
    """P1 (consulta); P2 similar 0,8 (projB); P3 similar 0,7 (projC); P4 distante (0,3)."""
    va, vb = pair_vectors(DIM, 0, 0.8)
    env.provider.vectors["titulo: P1"] = va
    env.provider.vectors["titulo: P2"] = vb
    _, vc = pair_vectors(DIM, 0, 0.7)
    vc = list(vc)
    vc[3] = vc[1]
    vc[1] = 0.0  # mesmo cosseno (0,7) com P1, em outro eixo ortogonal
    env.provider.vectors["titulo: P3"] = vc
    _, vd = pair_vectors(DIM, 0, 0.3)
    vd = list(vd)
    vd[5] = vd[1]
    vd[1] = 0.0
    env.provider.vectors["titulo: P4"] = vd
    ids = {
        "P1": env.make("Problema", projeto_id="projA", titulo="P1"),
        "P2": env.make("Problema", projeto_id="projB", titulo="P2"),
        "P3": env.make("Problema", projeto_id="projC", titulo="P3"),
        "P4": env.make("Problema", projeto_id="projD", titulo="P4"),
    }
    return ids


def _abordagem(env, nome: str, projeto: str) -> str:
    env.provider.vectors[f"nome: {nome}"] = [0.0] * (DIM - 1) + [1.0]
    return env.make("Abordagem", projeto_id=projeto, nome=nome)


def _funcionou(env, abordagem: str, problema: str, registro: str | None = None) -> None:
    props = {"metrica": "f1", "melhor_valor": 0.9, "n_exp": 3}
    if registro:
        props["registro_id"] = registro
    env.store.create_edge(abordagem, "FUNCIONOU_PARA", problema, props, actor=ORQ)


def _registro(env, projeto: str, replicas: int) -> str:
    """``RegistroResultado`` com ``replicas`` réplicas independentes (o peso do atalho satura em três)."""
    return env.make(
        "RegistroResultado", projeto_id=projeto, n_replicas_independentes=replicas, n_atingiu_alvo=replicas,
    )


def _descoberta(env, texto: str, projeto: str, n_evidencias: int | None, **extra) -> str:
    env.provider.vectors[f"enunciado: {texto}"] = [0.0] * (DIM - 2) + [1.0, 0.0]
    props = dict(extra)
    if n_evidencias is not None:
        props["n_evidencias"] = n_evidencias
    return env.make("Descoberta", projeto_id=projeto, enunciado=texto, **props)


@pytest.mark.unit
class TestRelatedExperience:
    def test_experiencia_de_outro_projeto(self, env):
        """Scenario: Experiência de outro projeto"""
        ids = _setup(env)
        a = _abordagem(env, "A", "projB")
        _funcionou(env, a, ids["P2"])

        itens = env.index.related_experience(ids["P1"])

        (item,) = itens
        assert item.node.id == a
        assert item.kind == "funcionou"
        assert item.origem_problema_id == ids["P2"]
        assert item.similarity == pytest.approx(0.8, abs=1e-3)

    def test_ordena_por_similaridade_x_confianca_x_recencia(self, env):
        """Ranking = similaridade × max(confiança das réplicas, piso) × recência (tarefa 6.9)."""
        ids = _setup(env)
        forte = _abordagem(env, "forte", "projB")
        fraca = _abordagem(env, "fraca", "projC")
        sem_registro = _abordagem(env, "semregistro", "projB")
        r_forte = _registro(env, "projB", 3)
        r_fraco = _registro(env, "projC", 1)
        _funcionou(env, forte, ids["P2"], r_forte)  # 0,8 × 1,0 (três réplicas)
        _funcionou(env, fraca, ids["P3"], r_fraco)  # 0,7 × 1/3 (uma réplica)
        _funcionou(env, sem_registro, ids["P2"])  # 0,8 × piso (0,05)

        now = datetime.now(timezone.utc) + timedelta(seconds=1)
        itens = env.index.related_experience(ids["P1"], now=now)

        nomes = [i.node.properties.get("nome") for i in itens]
        assert nomes == ["forte", "fraca", "semregistro"]
        ranks = [i.rank for i in itens]
        assert ranks == sorted(ranks, reverse=True)
        assert itens[0].rank == pytest.approx(0.8 * 1.0, rel=2e-2)
        assert itens[1].rank == pytest.approx(0.7 / 3, rel=2e-2)
        assert itens[2].confidence == config.CONFIDENCE_FLOOR  # sem registro não zera
        assert itens[2].rank > 0

    def test_recencia_decai_pela_meia_vida(self, env):
        ids = _setup(env)
        a = _abordagem(env, "A", "projB")
        _funcionou(env, a, ids["P2"])
        agora = datetime.now(timezone.utc)
        (novo,) = env.index.related_experience(ids["P1"], now=agora)
        (velho,) = env.index.related_experience(
            ids["P1"], now=agora + timedelta(days=config.RECENCY_HALF_LIFE_DAYS)
        )
        assert velho.recency == pytest.approx(0.5, abs=1e-3)
        assert velho.rank == pytest.approx(novo.rank * 0.5, rel=2e-2)

    def test_problema_distante_e_descoberta_contestada_ficam_fora(self, env):
        ids = _setup(env)
        distante = _abordagem(env, "distante", "projD")
        _funcionou(env, distante, ids["P4"])
        contestada = _descoberta(env, "contestada", "projB", 4, status="contestada")
        env.store.create_edge(contestada, "SOBRE", ids["P2"], {}, actor=ORQ)
        ativa = _descoberta(env, "ativa", "projB", 4)
        env.store.create_edge(ativa, "SOBRE", ids["P2"], {}, actor=ORQ)

        itens = env.index.related_experience(ids["P1"])

        assert [i.node.id for i in itens] == [ativa]
        assert itens[0].kind == "descoberta"

    def test_inclui_decisoes_do_projeto_do_problema_similar(self, env):
        ids = _setup(env)
        env.provider.vectors["contexto: ctx"] = [0.0] * (DIM - 3) + [1.0, 0.0, 0.0]
        decisao = env.make("Decisao", projeto_id="projB", contexto="ctx")
        itens = env.index.related_experience(ids["P1"])
        assert [(i.node.id, i.kind) for i in itens] == [(decisao, "decisao")]

    def test_limite_e_deduplicacao(self, env):
        ids = _setup(env)
        a = _abordagem(env, "A", "projB")
        _funcionou(env, a, ids["P2"])
        _funcionou(env, a, ids["P3"])  # mesma abordagem por dois problemas: um item só
        b = _abordagem(env, "B", "projB")
        _funcionou(env, b, ids["P2"])
        itens = env.index.related_experience(ids["P1"], limit=10)
        assert len({i.node.id for i in itens}) == len(itens) == 2
        assert len(env.index.related_experience(ids["P1"], limit=1)) == 1
