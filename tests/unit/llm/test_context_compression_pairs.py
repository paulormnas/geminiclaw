"""Compressão de contexto sem quebrar os pares chamada/resposta de ferramenta (benchmark de 2026-10-12)."""

from __future__ import annotations

import pytest

from src.llm.context_compression import (
    _blocks,
    _truncate_by_priority,
    compress_messages,
    drop_orphan_tool_messages,
)

pytestmark = pytest.mark.unit


def _call(cid: str, name: str = "f") -> dict:
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}]}


def _result(cid: str, size: int = 10) -> dict:
    return {"role": "tool", "tool_call_id": cid, "content": "x" * size}


def _consistent(messages: list[dict]) -> bool:
    calls: set[str] = set()
    answered: set[str] = set()
    for m in messages:
        for tc in m.get("tool_calls") or []:
            calls.add(tc["id"])
        if m.get("role") == "tool":
            if m["tool_call_id"] not in calls:
                return False
            answered.add(m["tool_call_id"])
    return calls == answered


def test_blocos_agrupam_a_chamada_e_suas_respostas() -> None:
    history = [{"role": "user", "content": "oi"}, _call("a"), _result("a"), _call("b"), _result("b"),
               {"role": "assistant", "content": "ok"}]
    assert [len(b) for b in _blocks(history)] == [1, 2, 2, 1]


@pytest.mark.parametrize("budget", range(5, 400, 7))
def test_truncagem_nunca_deixa_resposta_de_ferramenta_sem_a_chamada(budget: int) -> None:
    history = [{"role": "user", "content": "tarefa " * 5}]
    for i in range(8):
        history += [_call(f"c{i}"), _result(f"c{i}", size=60 + 13 * i)]
    history.append({"role": "assistant", "content": "fim"})
    out = _truncate_by_priority(history, budget)
    assert _consistent(out) and out[-1]["role"] == "assistant"  # a última mensagem sempre fica (truncada se preciso)


def test_ultimo_bloco_com_resposta_de_ferramenta_mantem_a_chamada() -> None:
    history = [{"role": "user", "content": "x" * 400}, _call("z"), _result("z", size=40)]
    out = _truncate_by_priority(history, 30)
    assert _consistent(out) and out[-2]["tool_calls"][0]["id"] == "z"


@pytest.mark.asyncio
async def test_compress_messages_com_orcamento_minimo_devolve_o_bloco_final_consistente() -> None:
    history = [{"role": "user", "content": "hi"}, _call("q"), _result("q")]
    out = await compress_messages(history, max_tokens=5)
    assert _consistent(out) and len(out) == 2


@pytest.mark.asyncio
async def test_sem_compressao_devolve_a_mesma_lista() -> None:
    history = [{"role": "user", "content": "hi"}, _call("q"), _result("q")]
    assert await compress_messages(history, max_tokens=100_000) is history


def test_rede_de_seguranca_remove_orfas_e_chamadas_sem_resposta() -> None:
    history = [_result("sem_chamada"), {"role": "user", "content": "oi"}, _call("a"), _call("so_chamada"),
               _result("a")]
    out = drop_orphan_tool_messages(history)
    ids = [m.get("tool_call_id") or [tc["id"] for tc in m.get("tool_calls", [])] for m in out if m["role"] != "user"]
    assert ids == [["a"], "a"] and _consistent(out)
