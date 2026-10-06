"""Testes da ferramenta ``buscar_dominio`` (v17-domain-search §6): somente leitura, limites e telemetria."""

import re
from unittest.mock import MagicMock

import pytest

from src.agent_runtime.definitions import get_agent_definition, reset_definitions_cache
from src.knowledge.domain_search import DomainHit
from src.skills import registry
from src.skills.vocabulary import DomainSearchSkill, domain_search_tools
from src.skills.vocabulary.skill import format_hits
from tests.support.domain_env import DomainEnv

_LINE = re.compile(r"^\d+\. .+  \(.+, score \d,\d\d, id=.+\)$")


@pytest.fixture
def env() -> DomainEnv:
    e = DomainEnv()
    e.build_cs()
    e.query("aprendizado de máquina")
    e.vec("Inteligência Artificial", 0.71)
    e.vec("Ciência da Computação", 0.5)
    e.reconcile()
    return e


def _skill(env: DomainEnv) -> DomainSearchSkill:
    return DomainSearchSkill(lambda: env.search)


@pytest.mark.unit
class TestBuscarDominio:
    @pytest.mark.asyncio
    async def test_resposta_curta_e_estavel(self, env):
        """Scenario: Resposta curta e estável"""
        result = await _skill(env).run(texto="aprendizado de máquina")
        assert result.success
        lines = result.output.splitlines()
        assert lines and all(_LINE.match(line) for line in lines)
        assert lines[0].startswith("1. Ciências Exatas e da Terra > Ciência da Computação > Inteligência Artificial")
        assert "(subárea, score 0,71, id=" in lines[0]
        assert len(result.output) <= 2000

    def test_limites_de_tamanho_da_resposta(self):
        hits = [
            DomainHit(
                node_id=f"id-{i}", termo="t", nivel="especialidade",
                caminho=["x" * 150, "y" * 150, "z" * 150], caminho_ids=[], score=0.9, status="aprovado",
            )
            for i in range(10)
        ]
        out = format_hits(hits)
        assert len(out) <= 2000
        assert all(len(line) <= 300 for line in out.splitlines())

    @pytest.mark.asyncio
    async def test_sem_correspondencia(self, env):
        """Scenario: Sem correspondência"""
        result = await _skill(env).run(texto="outro assunto")  # sem vetor definido: ortogonal a tudo
        assert result.success
        assert "sem_correspondencia: true" in result.output

    @pytest.mark.asyncio
    async def test_dentro_de_desconhecido(self, env):
        """Scenario: `dentro_de` desconhecido"""
        before = len(env.provider.queries)
        result = await _skill(env).run(texto="aprendizado de máquina", dentro_de="999")
        assert not result.success
        assert "dentro_de" in result.error
        assert len(env.provider.queries) == before  # nenhuma busca (global) foi feita

    @pytest.mark.asyncio
    async def test_consulta_tratada_como_dado(self, env):
        """Scenario: Consulta tratada como dado"""
        payload = "}) DETACH DELETE (n) //"
        env.raw.read_query = MagicMock(side_effect=AssertionError("a consulta não pode virar Cypher"))
        nodes_before = len(env.raw.list_nodes("Dominio"))
        result = await _skill(env).run(texto=payload, contexto=payload, dentro_de="T1")
        assert result.success
        assert env.provider.queries[-1].startswith("Domínio: " + payload)  # só foi vetorizada
        env.raw.read_query.assert_not_called()
        assert len(env.raw.list_nodes("Dominio")) == nodes_before

    @pytest.mark.asyncio
    async def test_telemetria_sem_a_consulta(self, env, monkeypatch):
        """Scenario: Telemetria sem a consulta"""
        log = MagicMock()
        monkeypatch.setattr("src.skills.vocabulary.skill.logger", log)
        secret = "aprendizado de máquina"
        await _skill(env).run(texto=secret, contexto="conteudo reservado")
        events = [c for c in log.info.call_args_list if c.kwargs.get("extra", {}).get("event") == "domain_search"]
        assert len(events) == 1
        extra = events[0].kwargs["extra"]
        assert extra["resultados"] >= 1
        assert extra["melhor_score"] == pytest.approx(0.71, abs=0.01)
        assert extra["nivel_do_melhor"] == "subarea"
        assert extra["candidatos_incluidos"] is False
        dumped = repr(events[0])
        assert secret not in dumped and "reservado" not in dumped

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs",
        [{"texto": 5}, {"texto": "ok", "nivel_maximo": "xyz"}, {"texto": "ok", "incluir_candidatos": "talvez"},
         {"texto": None}, {"texto": "ok", "dentro_de": ["a"]}],
    )
    async def test_entradas_invalidas_viram_erro_explicito(self, env, kwargs):
        result = await _skill(env).run(**kwargs)
        assert not result.success and result.error

    @pytest.mark.asyncio
    async def test_indice_indisponivel_nao_vaza_detalhes(self):
        def boom():
            raise RuntimeError("postgresql://user:senha@host/db")

        result = await DomainSearchSkill(boom).run(texto="qualquer coisa")
        assert not result.success
        assert "senha" not in result.error


@pytest.mark.unit
class TestPapeisComAFerramenta:
    def test_papeis_com_a_ferramenta(self):
        """Scenario: Papéis com a ferramenta"""
        reset_definitions_cache()
        names = {role: {getattr(t, "__name__", "") for t in get_agent_definition(role).tools}
                 for role in ("researcher", "developer")}
        assert "buscar_dominio" in names["researcher"]
        assert "buscar_dominio" not in names["developer"]
        assert [t.__name__ for t in domain_search_tools("curator")] == ["buscar_dominio"]
        assert domain_search_tools("developer") == []
        assert "buscar_dominio" not in {s["name"] for s in registry.list_available()}
        reset_definitions_cache()
