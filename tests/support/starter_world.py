"""``SessionStarter`` com tudo simulado, sem rede, banco nem processo (v18.7-background-sessions, tarefa 5).

``make_starter`` devolve o iniciador e a lista dos lançamentos feitos (o processo é um ``MagicMock``). O roteamento, o
banner, o grafo da marcação de modo sem limite e a infraestrutura são substituídos; a memória é a informada.
"""

from __future__ import annotations

import argparse
import contextlib
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.cli.session_start import SessionStarter
from src.orchestration.usage import UsageBudget
from tests.support.session_fakes import FakeSessionManager

BUDGET = UsageBudget.from_config()


def args(**over: Any) -> argparse.Namespace:
    base: dict[str, Any] = dict(
        project=None, model=None, unlimited=False, max_tokens=None, max_minutes=None, max_egress_bytes=None,
        max_task_retries=None, max_connection_retries=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def monitor(available_mb: float | None) -> Any:
    return SimpleNamespace(get_memory_usage=lambda: None if available_mb is None else {"available_mb": available_mb})


def make_starter(
    tmp_path: Path, *, binder: Any | None = None, available_mb: float | None = 4096, manager: Any | None = None,
    input_fn: Any = None, **kwargs: Any,
) -> tuple[SessionStarter, list[Path]]:
    launched: list[Path] = []

    def spawn(path: Path, **_kw: Any) -> Any:
        launched.append(path)
        return MagicMock(poll=MagicMock(return_value=None), pid=4242)

    ctx = tmp_path / "input_context"
    ctx.mkdir(exist_ok=True)
    default_binder = MagicMock()
    default_binder.bind = AsyncMock(return_value=MagicMock(mode="projeto", project_id="pid1", context_block="CTX"))
    starter = SessionStarter(
        session_manager=manager or FakeSessionManager(),
        base_dir=tmp_path / "outputs",
        context_dir=str(ctx),
        monitor=monitor(available_mb),
        input_fn=input_fn or (lambda _p: ""),
        output_fn=lambda _t: None,
        spawn=spawn,
        binder_factory=lambda _routing, _args: binder or default_binder,
        prerequisites=lambda: None,
        **kwargs,
    )
    return starter, launched


@contextlib.contextmanager
def patched_terminal() -> Iterator[MagicMock]:
    """Roteamento, banner e marcação de modo sem limite simulados; devolve o mock do roteamento."""
    routing = MagicMock()
    routing.resolution.return_value.id = "ollama/modelo"
    with (
        patch("src.llm.session.build_session_routing", AsyncMock(return_value=routing)),
        patch("src.llm.session.bind_session_routing"),
        patch("src.cli.session_start.print_session_banner"),
        patch("src.cli.session_start._project_marked_unlimited", lambda _p: False),
    ):
        yield routing
