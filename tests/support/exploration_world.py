"""Harness do laço de exploração (v18-hypothesis-loop): orquestrador real, Researcher e Developer simulados.

Sem rede, sem LLM, sem banco. O Researcher devolve os planos de ``plans`` na ordem (o último se repete); o Developer
sempre conclui com sucesso. Registra as subtarefas executadas e os prompts de planejamento.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.validator_agent import ValidationResult
from src.autonomous_loop import AutonomousLoop
from src.continuity import read_checkpoint
from src.orchestrator import AgentResult, Orchestrator
from src.output_manager import OutputManager
from src.usage import UsageBudget
from tests.support.hypothesis_world import HypothesisWorld
from tests.support.session_fakes import FakeSessionManager

APPROVED = ValidationResult(is_valid=True, status="approved", reason="ok")
REJECTED = ValidationResult(is_valid=False, status="revision_needed", reason="ruim", issues=["ruim"])


def task(name: str, ref: str | None = "h1", **over: Any) -> dict[str, Any]:
    """Subtarefa do plano (Developer, ``model_impl``)."""
    base: dict[str, Any] = {
        "agent_id": "developer", "task_name": name, "task_type": "model_impl", "prompt": f"faça {name}",
        "validation_criteria": ["r2 > 0.8"], "depends_on": [],
    }
    if ref is not None:
        base["hypothesis_ref"] = ref
    base.update(over)
    return base


def plan(subtasks: list[dict[str, Any]], hipoteses: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """Plano no formato novo."""
    return {"hipoteses": hipoteses or [], "decisoes": [], "respostas_sugestoes": [], "subtarefas": subtasks, **extra}


def hyp(ref: str, enunciado: str | None = None, **over: Any) -> dict[str, Any]:
    return {"ref": ref, "enunciado": enunciado or f"Hipótese {ref} distinta das demais", "justificativa": "J", **over}


class LoopHarness:
    """Orquestrador real sobre um projeto com Problema confirmado; planos e execuções simulados."""

    def __init__(self, tmp_path: Path, *, mode: str = "auto", plans: list[Any] | None = None,
                 approver: Any = None, confirmer: Any = None, validator: Any = None) -> None:
        self.tmp_path = tmp_path
        self.w = HypothesisWorld(mode=mode)
        self.mode = mode
        self.sm = FakeSessionManager()
        self.plans: list[Any] = list(plans or [])
        self.plan_calls = 0
        self.ran: list[str] = []
        self.planner_prompts: list[str] = []
        self.runtime = MagicMock()
        self.runtime.run = self._run
        self.orch = Orchestrator(
            session_manager=self.sm,
            output_manager=OutputManager(str(tmp_path / "out"), str(tmp_path / "logs")),
            agent_runtime=self.runtime,
            knowledge_store_factory=lambda: self.w.store,
        )
        self.orch.rate_limiter.acquire = AsyncMock()
        self.orch.validator.validate_plan = validator or AsyncMock(return_value=APPROVED)
        self.orch.exploration_approver = approver
        self.orch.solution_confirmer = confirmer
        self.orch.curator_consolidate = AsyncMock()
        self.orch.curator_close = AsyncMock(return_value=False)
        self.session_dir = self.orch.output_manager.base_dir / self.w.sid
        self.extra_patches: list[Any] = []

    async def _run(self, task_: Any, ctx: Any) -> AgentResult:
        if task_.agent_id == "researcher":
            self.planner_prompts.append(task_.prompt)
            index = min(self.plan_calls, len(self.plans) - 1)
            self.plan_calls += 1
            item = self.plans[index]
            text = item if isinstance(item, str) else json.dumps(item)
            return AgentResult(agent_id="researcher", session_id="x", status="success", response={"text": text})
        self.ran.append(task_.task_name)
        return AgentResult(agent_id=task_.agent_id, session_id="x", status="success", response={"text": "feito"})

    async def run(self, prompt: str = "Estudar o rendimento", budget: UsageBudget | None = None, **kw: Any) -> Any:
        with ExitStack() as stack:
            for p in (
                patch.object(AutonomousLoop, "_promote_findings", AsyncMock()),
                patch.object(AutonomousLoop, "_synthesize_results", AsyncMock(return_value=None)),
                patch("src.config.REVIEW_ENABLED", False),
                patch("src.orchestrator.generate_session_slug", return_value=self.w.sid),
                patch("src.orchestrator.bind_session_routing"),
                patch("src.orchestrator.build_session_routing", AsyncMock()),
                patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)),
                *self.extra_patches,
            ):
                stack.enter_context(p)
            routing = MagicMock(catalogo=MagicMock(hash="h", versao="1"), politica="p", modo="m",
                                payload=lambda: {})
            return await self.orch.handle_request(
                prompt, mode=self.mode, budget=budget, project_id=self.w.pid, project_context="", llm_routing=routing,
                **kw,
            )

    # -- inspeção ------------------------------------------------------------------------------------------

    @property
    def payload(self) -> dict[str, Any]:
        return self.sm.get(self.w.sid).payload

    @property
    def stop_reason(self) -> str | None:
        return self.payload.get("motivo_parada")

    def checkpoint(self) -> Any:
        return read_checkpoint(self.session_dir)[0]

    def hypotheses(self) -> list[Any]:
        return self.w.raw.find_nodes("Hipotese", {"projeto_id": self.w.pid}, limit=100)
