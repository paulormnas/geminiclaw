"""Resolvedor de provedor registrado na partida e ``unwrap()`` (v18.7-layer-cycles; ADR 017; ADR 024 §4)."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

from src.egress.gate import GatedProvider
from src.egress.routing import ModelRouter
from src.llm import factory
from src.llm.base import LLMProvider, LLMResponse
from src.llm.destination import Destination
from src.llm.metering import provider_name

pytestmark = pytest.mark.unit

MESSAGE = "resolvedor de provedor não registrado: a partida deve registrar o roteador com filtro de egresso"


class FakeProvider(LLMProvider):
    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096):
        return LLMResponse(text="ok")

    async def generate_stream(self, messages, system=None):
        yield "ok"

    async def health_check(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "fake-model"


def test_sem_registro_falha_explicita(monkeypatch) -> None:
    monkeypatch.setattr(factory, "_resolver", None)
    double = MagicMock()
    monkeypatch.setattr(ModelRouter, "get_provider", double)
    with pytest.raises(RuntimeError) as error:
        factory.get_provider()
    assert str(error.value) == MESSAGE
    double.assert_not_called()


def test_partida_registra_o_roteador(monkeypatch) -> None:
    import src.cli.main as cli_main

    monkeypatch.setattr(factory, "_resolver", None)
    monkeypatch.setattr(sys, "argv", ["geminiclaw", "--help"])
    with pytest.raises(SystemExit):
        cli_main.main()
    provider = factory.get_provider()
    assert isinstance(provider, GatedProvider)
    assert provider.dest.papel == "researcher"
    assert provider is ModelRouter.get_provider("researcher")


def test_nome_do_provedor_com_e_sem_filtro() -> None:
    raw = FakeProvider()
    dest = Destination(
        canal="llm", provedor="fake", modelo="fake-model", trust="third_party", localidade="fora_do_no",
        aceita_dados_brutos=False, papel="researcher",
    )
    gated = GatedProvider(raw, dest)
    assert raw.unwrap() is raw
    assert gated.unwrap() is raw
    assert provider_name(raw) == provider_name(gated) == "fake"


def test_triagem_nao_engole_a_falta_de_resolvedor(monkeypatch) -> None:
    """Sem resolvedor registrado, o ``RuntimeError`` propaga e nenhuma geração é feita (S3)."""
    from src.orchestration.autonomous_loop import AutonomousLoop

    monkeypatch.setattr(factory, "_resolver", None)
    generate = MagicMock()
    monkeypatch.setattr(FakeProvider, "generate", generate)
    loop = AutonomousLoop(orchestrator=MagicMock())
    with pytest.raises(RuntimeError, match="resolvedor de provedor não registrado"):
        asyncio.run(loop._llm_triage_direct("qualquer pedido"))
    generate.assert_not_called()


def test_roteador_nao_existe_mais_no_caminho_antigo() -> None:
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.llm.model_router")
