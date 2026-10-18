"""Contrato da subtarefa na ``ExplorationSession`` (v18.7-subtask-contract, design §2 e §8.1).

``ContractMixin`` entrega ao montador do contrato o que depende do grafo: o critério do ``Problema`` e o vocabulário de
métricas (termo novo vira candidato, sem bloquear a subtarefa), e retira do ciclo a subtarefa com campo do contrato
acima do teto.
"""

from __future__ import annotations

from typing import Any

from src import config
from src.agents.subtask_contract import (
    ProblemObjective,
    SubtaskContract,
    build_developer_contract,
    oversized_fields,
)
from src.knowledge.objective import effective_type
from src.knowledge.projects import get_active_problem
from src.knowledge.provenance import Actor
from src.knowledge.service import KnowledgeService
from src.knowledge.vocabulary import resolve_metric
from src.logger import get_logger
from src.orchestration.exploration_linking import DROP_LONG_FIELD

logger = get_logger(__name__)

_ORQUESTRADOR = Actor(kind="orquestrador")


def contract_applies(task: Any) -> bool:
    """O contrato só vai ao Developer, e só com ``SUBTASK_CONTRACT_ENABLED``."""
    return bool(config.SUBTASK_CONTRACT_ENABLED) and getattr(task, "agent_id", "") == "developer"


class ContractMixin:
    """Usa ``store``, ``ctx`` e ``_emit`` da ``ExplorationSession``."""

    def problem_objective(self) -> ProblemObjective | None:
        """Critério do ``Problema`` ativo para o item 6; ``None`` sem Problema ou sem métrica canônica."""
        try:
            problem = get_active_problem(self.store, self.ctx.project_id)  # type: ignore[attr-defined]
            if problem is None:
                return None
            criterion, metric = KnowledgeService(self.store).criterion_for(problem)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - sem Problema legível o contrato sai com o item 6 "não se aplica"
            logger.warning("Objetivo do Problema indisponível", extra={"extra": {"erro": type(exc).__name__}})
            return None
        raw = problem.properties.get("criterio_sucesso")
        raw = raw if isinstance(raw, dict) else {}
        return ProblemObjective(
            metric=str(metric.properties.get("nome", "")),
            direction=str(criterion.sentido),
            target=criterion.alvo,
            reference=str(raw.get("baseline_descricao") or ""),
            objective_type=effective_type(raw) or "limiar",
        )

    def objective_type(self) -> str | None:
        """Tipo do objetivo do ``Problema`` ativo para o regimento: ``limiar`` quando o critério não declara tipo;
        ``None`` sem projeto, sem ``Problema`` ou sem leitura do grafo."""
        try:
            problem = get_active_problem(self.store, self.ctx.project_id)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - o regimento segue só com as seções comuns
            logger.warning("Tipo de objetivo indisponível", extra={"extra": {"erro": type(exc).__name__}})
            return None
        if problem is None:
            return None
        raw = problem.properties.get("criterio_sucesso")
        return effective_type(raw if isinstance(raw, dict) else None) or "limiar"

    def metric_resolver(self) -> Any:
        """Resolvedor de nomes pelo vocabulário: canônico e se o termo é novo (candidato criado)."""

        def resolve(name: str, sentido: str | None) -> tuple[str, bool]:
            try:
                res = resolve_metric(
                    self.store, name, actor=_ORQUESTRADOR,  # type: ignore[attr-defined]
                    sessao_id=self.ctx.session_id, sentido=sentido or "maior_melhor",  # type: ignore[attr-defined]
                )
                node = self.store.get_node(res.node_id) if res.node_id else None  # type: ignore[attr-defined]
                if node is not None:
                    return str(node.properties.get("nome") or name), res.status == "candidato_criado"
            except Exception as exc:  # noqa: BLE001 - o vocabulário não bloqueia a subtarefa
                logger.warning("Vocabulário indisponível", extra={"extra": {"erro": type(exc).__name__}})
            return name, True

        return resolve

    def build_contract(
        self, task: Any, plan: list[Any], original_task: str, *, dependency_artifacts: Any = ()
    ) -> SubtaskContract:
        """Contrato da tentativa a partir do plano vigente (síncrono: usar ``to_thread``)."""
        return build_developer_contract(
            task, plan, self.problem_objective(), original_task, metric_resolver=self.metric_resolver(),
            dependency_artifacts=dependency_artifacts,
        )

    def drop_long_contract_fields(self, live: list[Any], plan: list[Any], dropped: dict[str, str]) -> None:
        """Retira a subtarefa com campo do contrato acima do teto (design §8.1 item 9); o campo nunca é cortado."""
        for task in live:
            name = task.task_name
            if name in dropped or not contract_applies(task):
                continue
            long_fields = oversized_fields(build_developer_contract(task, plan, None, ""))
            if long_fields:
                dropped[name] = DROP_LONG_FIELD
                logger.warning(
                    "Subtarefa retirada: campo do contrato acima do teto",
                    extra={"extra": {"task_name": name[:128], "campos": long_fields}},
                )
