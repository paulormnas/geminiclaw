"""Ferramenta ``ler_regimento`` (agent-runtime: Ferramenta de leitura do regimento)."""

import builtins

import pytest

from src.agents.base.tools import ler_regimento
from src.agents.regimento import encerrar_sessao, iniciar_sessao
from src.utils.egress_fragments import ContentOrigin, ToolOutput

pytestmark = pytest.mark.unit


@pytest.fixture
def sessao_limiar():
    sessao, token = iniciar_sessao("auto", "limiar")
    yield sessao
    encerrar_sessao(token)


@pytest.mark.asyncio
async def test_secao_fora_do_recorte(sessao_limiar):
    assert "Objetivo do tipo discriminação" not in sessao_limiar.recorte_atual().texto
    resposta = await ler_regimento("objetivo_discriminacao")
    assert "Objetivo do tipo discriminação" in resposta and "`todas_contrariadas`" in resposta


@pytest.mark.asyncio
async def test_resposta_e_instrucao_sem_contaminacao(sessao_limiar):
    resposta = await ler_regimento("paradas")
    assert isinstance(resposta, ToolOutput)
    assert resposta.origin is ContentOrigin.INSTRUCAO and resposta.tainted is False


@pytest.mark.asyncio
async def test_sem_argumento_lista_as_secoes(sessao_limiar):
    resposta = await ler_regimento()
    assert "- fluxo:" in resposta and "- objetivo_fronteira:" in resposta


@pytest.mark.asyncio
async def test_caminho_no_argumento_devolve_a_lista_e_nao_abre_arquivo(sessao_limiar, monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("nenhum arquivo deveria ser aberto")

    monkeypatch.setattr(builtins, "open", proibido)
    resposta = await ler_regimento("../../.env")
    assert "- fluxo:" in resposta and "Seção desconhecida" in resposta


@pytest.mark.asyncio
async def test_nao_le_o_adendo(sessao_limiar):
    resposta = await ler_regimento("regimento_adendo")
    assert "Seção desconhecida" in resposta and "Regras adicionais do projeto" not in resposta


@pytest.mark.asyncio
async def test_saida_respeita_o_teto(sessao_limiar, monkeypatch):
    monkeypatch.setattr("src.config.REGIMENTO_EXCERPT_MAX_CHARS", 200)
    assert len(await ler_regimento("paradas")) <= 200


@pytest.mark.asyncio
async def test_fora_de_sessao_devolve_erro():
    assert (await ler_regimento("fluxo")).startswith("Erro:")


def test_ferramenta_registrada_para_researcher_developer_e_curator():
    from src.agents.curator.agent import create_agent
    from src.agents.developer.agent import root_agent as developer
    from src.agents.researcher.agent import root_agent as researcher

    for agente in (researcher, developer, create_agent()):
        assert "ler_regimento" in [getattr(t, "__name__", "") for t in agente.tools]
