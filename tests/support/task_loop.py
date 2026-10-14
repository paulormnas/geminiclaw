"""Executa uma lista fixa de tarefas por ``Orchestrator.handle_request`` sem o laço autônomo.

O atalho ``agent_tasks`` de ``handle_request`` foi removido (v18.6-remove-unused-agents). Os testes que só
precisam do ciclo de vida da requisição (sessão mestra, telemetria, fechamento) com tarefas conhecidas
substituem o ``AutonomousLoop`` por um laço que executa as tarefas em sequência com ``_execute_agent``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from src.orchestrator import AgentTask, Orchestrator, OrchestratorResult


class _SequentialLoop:
    """Substituto do ``AutonomousLoop``: executa cada tarefa em ordem e agrega o resultado."""

    def __init__(self, orchestrator: Orchestrator, tasks: list[AgentTask]):
        self.orchestrator = orchestrator
        self.tasks = tasks

    async def run(self, prompt: str, exec_id: str, mode: str | None = None, budget: Any = None) -> OrchestratorResult:
        master_session_id = list(self.orchestrator._session_modes)[-1]
        results = []
        for task in self.tasks:
            task.mode = task.mode or mode
            results.append(await self.orchestrator._execute_agent(task, master_session_id))
        succeeded = sum(1 for r in results if r.status == "success")
        return OrchestratorResult(
            results=results,
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
        )


async def run_tasks(orchestrator: Orchestrator, prompt: str, tasks: list[AgentTask], **kwargs: Any) -> OrchestratorResult:
    """``handle_request(prompt, **kwargs)`` com o laço substituído por ``tasks`` em sequência.

    Sem ``input_context/`` (sem ``context_bundle``) e sem exploração de hipóteses: só o ciclo de vida da requisição.
    """
    no_context = MagicMock()
    no_context.return_value.load.return_value = None
    with (
        patch("src.orchestrator.AutonomousLoop", lambda orch: _SequentialLoop(orch, tasks)),
        patch("src.orchestrator.ContextLoader", no_context),
        patch.object(Orchestrator, "_start_exploration"),
    ):
        return await orchestrator.handle_request(prompt, **kwargs)
