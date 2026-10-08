"""Fixtures da ingestão de dados de pesquisa (nenhum teste usa rede, provedor real ou banco)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.egress.gate import Destination, EgressGate, bind_gate_for_tests
from src.egress.log import EgressRecord


class MemoryLog:
    def __init__(self) -> None:
        self.records: list[EgressRecord] = []

    def write(self, record: EgressRecord, payload: dict[str, Any] | None = None) -> None:
        self.records.append(record)


@pytest.fixture
def memory_log() -> MemoryLog:
    return MemoryLog()


@pytest.fixture
def gate(memory_log: MemoryLog):
    portao = EgressGate("sessao-teste", log=memory_log, min_group_size=10, output_max_chars=4000, table_min_rows=3)
    token = bind_gate_for_tests(portao)
    yield portao
    from src.egress import gate as gate_module

    gate_module._current_gate.reset(token)


def make_dest(*, raw: bool, local: bool = False, role: str = "researcher") -> Destination:
    return Destination(
        canal="llm",
        provedor="ollama" if local else "google",
        modelo="m",
        trust="self_hosted" if local else "third_party",
        localidade="no_no" if local else "fora_do_no",
        aceita_dados_brutos=raw or local,
        papel=role,
    )


@pytest.fixture
def third_party() -> Destination:
    return make_dest(raw=False)


@pytest.fixture
def local_node() -> Destination:
    return make_dest(raw=True, local=True)


@pytest.fixture
def context_dir(tmp_path: Path) -> Path:
    path = tmp_path / "input_context"
    path.mkdir()
    return path


def write_manifest(context_dir: Path, text: str) -> None:
    (context_dir / "dados.yaml").write_text(text, encoding="utf-8")
