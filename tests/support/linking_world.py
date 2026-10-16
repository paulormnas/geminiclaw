"""Mundo de teste da ligação a hipóteses (v18.7-hypothesis-linking, design §12): sem provedor pago, sem rede, sem banco.

Planos entregues como JSON a ``split_plan`` e convertidos em ``AgentTask`` como no orquestrador; ``Problema`` confirmado
``P`` com a ``Metrica`` ``acuracia`` aprovada (sinônimos ``accuracy`` e ``test_accuracy``); aprovação do ``assisted`` por
``Approver``/``ApprovalPort`` injetado; ``prepare_cycle`` chamado direto, sem Researcher real.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agent_runtime.types import AgentTask
from src.knowledge.hypotheses import split_plan
from src.orchestration.exploration import CycleOutcome, ExplorationSession
from src.orchestration.exploration_roles import declared_role
from tests.support.hypothesis_world import HypothesisWorld

ACURACIA = ("accuracy", "test_accuracy")


def sub(name: str, *, criteria: tuple[str, ...] | None = ("accuracy >= 0.9",), **over: Any) -> dict[str, Any]:
    """Subtarefa do plano (Developer, ``model_impl``); ``criteria=None`` omite os critérios quantitativos."""
    base: dict[str, Any] = {
        "agent_id": "developer", "task_name": name, "task_type": "model_impl", "prompt": f"faça {name}",
        "validation_criteria": list(criteria) if criteria else ["artefato gerado"], "depends_on": [],
    }
    base.update(over)
    return base


def to_task(item: dict[str, Any]) -> AgentTask:
    """Mapeamento do plano para ``AgentTask`` como em ``Orchestrator._run_planning_loop``."""
    return AgentTask(
        agent_id=item.get("agent_id", "base"), prompt=item.get("prompt", ""), task_name=item.get("task_name", ""),
        depends_on=item.get("depends_on", []), expected_artifacts=item.get("expected_artifacts", []),
        validation_criteria=item.get("validation_criteria", []), task_type=item.get("task_type"),
        hypothesis=item.get("hypothesis", ""), scientific_rationale=item.get("scientific_rationale", ""),
        approach=item.get("approach") if isinstance(item.get("approach"), dict) else None,
        hypothesis_ref=str(item.get("hypothesis_ref") or "")[:128], papel=declared_role(item.get("papel")),
        subtask_id=f"id-{item.get('task_name', '')}",
    )


class LinkingCycle:
    """Mundo + ``ExplorationSession`` + atalhos para planos, eventos e ciclos sucessivos."""

    def __init__(self, tmp_path: Path, *, mode: str = "auto", approver: Any = None, per_cycle: int = 50,
                 **world_kw: Any) -> None:
        world_kw.setdefault("metrica", "acuracia")
        world_kw.setdefault("sinonimos", ACURACIA)
        self.w = HypothesisWorld(mode=mode, **world_kw)
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.session = ExplorationSession(
            lambda: self.w.store, self.w.ctx, tmp_path, mode=mode, approver=approver,
            telemetry=lambda kind, payload: self.events.append((kind, payload)),
        )
        self.session.cycle._per_cycle = per_cycle  # noqa: SLF001 - o teto de hipóteses por ciclo não é o assunto aqui
        self.done_tasks: dict[str, AgentTask] = {}
        self.tasks: dict[str, AgentTask] = {}

    def run(self, subtarefas: list[dict[str, Any]], hipoteses: list[dict[str, Any]] | None = None,
            done: set[str] | None = None, **extra: Any) -> CycleOutcome:
        raw = {"hipoteses": hipoteses or [], "decisoes": [], "respostas_sugestoes": [], "subtarefas": subtarefas, **extra}
        items, extras = split_plan(raw)
        tasks = [to_task(d) for d in items]
        outcome = self.session.prepare_cycle(tasks, extras, done=set(done or ()), done_tasks=self.done_tasks)
        self.tasks = {t.task_name: t for t in tasks}
        return outcome

    def finish(self, outcome: CycleOutcome, *names: str) -> None:
        """Marca as subtarefas como executadas (concluídas) para o ciclo seguinte."""
        for name in names or [t.task_name for t in outcome.tasks]:
            self.done_tasks[name] = self.tasks[name]

    def events_of(self, kind: str) -> list[dict[str, Any]]:
        return [p for k, p in self.events if k == kind]

    def system_hypotheses(self) -> list[Any]:
        return [n for n in self.w.store.find_nodes("Hipotese", {"projeto_id": self.w.pid}, limit=100)
                if n.properties.get("origem") == "sistema"]

    def status(self, hypothesis_id: str) -> str:
        node = self.w.store.get_node(hypothesis_id)
        assert node is not None
        return str(node.properties["status"])
