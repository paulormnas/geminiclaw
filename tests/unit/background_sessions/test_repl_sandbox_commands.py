"""Comandos de container do REPL renomeados (v18.7-background-sessions, decisão de 2026-10-16)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.cli.repl as repl

pytestmark = pytest.mark.unit


def _run_repl(lines: list[str]) -> tuple[MagicMock, MagicMock, AsyncMock]:
    show, stop, execute = MagicMock(), MagicMock(), AsyncMock(return_value=True)
    with (
        patch.object(repl, "show_sandboxes", show),
        patch.object(repl, "stop_sandboxes", stop),
        patch.object(repl, "execute_prompt", execute),
        patch.object(repl, "print_session_banner"),
        patch("builtins.input", side_effect=[*lines, "sair"]),
    ):
        asyncio.run(repl.interactive_mode(MagicMock()))
    return show, stop, execute


def test_sandboxes_lista_containers():
    show, stop, execute = _run_repl(["sandboxes"])
    show.assert_called_once()
    stop.assert_not_called()
    execute.assert_not_called()


def test_parar_sandboxes_com_e_sem_id():
    _, stop, execute = _run_repl(["parar-sandboxes", "parar-sandboxes sess_1"])
    assert [c.kwargs for c in stop.call_args_list] == [{"session_id": None}, {"session_id": "sess_1"}]
    execute.assert_not_called()


def test_nomes_antigos_nao_tratam_containers():
    show, stop, execute = _run_repl(["sessions", "stop"])
    show.assert_not_called()
    stop.assert_not_called()
    assert execute.call_count == 2
