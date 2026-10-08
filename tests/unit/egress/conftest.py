"""Fixtures da camada de saída (dublê de registro em memória; nenhum teste usa banco, rede ou provedor real)."""

from __future__ import annotations

from typing import Any

import pytest

from src.egress.gate import Destination, EgressGate
from src.egress.log import EgressLogError, EgressRecord


class MemoryLog:
    """Substitui ``EgressLog`` guardando as linhas e os payloads em memória."""

    def __init__(self) -> None:
        self.records: list[EgressRecord] = []
        self.payloads: list[dict[str, Any] | None] = []
        self.fail = False

    def write(self, record: EgressRecord, payload: dict[str, Any] | None = None) -> None:
        if self.fail:
            raise EgressLogError("banco indisponível (dublê)")
        self.records.append(record)
        self.payloads.append(payload)


@pytest.fixture
def memory_log() -> MemoryLog:
    return MemoryLog()


@pytest.fixture
def gate(memory_log: MemoryLog) -> EgressGate:
    return EgressGate("sessao-teste", log=memory_log, min_group_size=10, output_max_chars=4000, table_min_rows=3)


def make_dest(
    *, raw: bool, local: bool = False, role: str = "researcher", provider: str = "google", model: str = "m"
) -> Destination:
    return Destination(
        canal="llm",
        provedor=provider,
        modelo=model,
        trust="self_hosted" if local else "third_party",
        localidade="no_no" if local else "fora_do_no",
        aceita_dados_brutos=raw or local,
        papel=role,
    )


@pytest.fixture
def third_party() -> Destination:
    """Terceiro, fora do nó, sem dados brutos."""
    return make_dest(raw=False)


@pytest.fixture
def local_node() -> Destination:
    """Modelo no nó (aceita_dados_brutos efetivo true)."""
    return make_dest(raw=True, local=True, role="developer", provider="ollama", model="qwen3:8b")


@pytest.fixture
def remote_raw() -> Destination:
    """Fora do nó, mas com aceita_dados_brutos declarado (servidor próprio)."""
    return make_dest(raw=True, local=False, role="developer", provider="openai_compatible", model="llama")
