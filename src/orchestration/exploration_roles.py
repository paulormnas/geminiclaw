"""Papel do experimento decidido por ordem fixa (v18.7-hypothesis-linking, design §2; ADR 021 §2).

Função pura, sem grafo e sem LLM: ``classify_role`` decide, para cada subtarefa não concluída do plano, se ela é
``teste`` de hipótese, ``preparacao`` ou ``referencia`` do Problema. O ``papel`` declarado vale primeiro; a ausência ou
o valor inválido nunca reprovam o plano nem retiram a subtarefa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.knowledge.metric_criteria import _CRITERION_VALUE_PATTERN, _METRIC_ALIASES
from src.knowledge.schema import PAPEIS_EXPERIMENTO
from src.knowledge.system_hypotheses import MetricRef
from src.orchestration.exploration_linking import PREPARATORY_TASK_TYPES
from src.utils.normalization import QUALIFIER_WORDS, criterion_qualifier, normalized_words, split_metric_name

PAPEL_TESTE = "teste"
PAPEL_PREPARACAO = "preparacao"
PAPEL_REFERENCIA = "referencia"

FONTE_DECLARADO = "declarado"
FONTE_HYPOTHESIS_REF = "hypothesis_ref"
FONTE_TASK_TYPE = "task_type"
FONTE_SINAL_DE_TESTE = "sinal_de_teste"
FONTE_ESTRUTURA_DAG = "estrutura_dag"
FONTE_RESIDUAL = "residual"
FONTES_PAPEL = (
    FONTE_DECLARADO, FONTE_HYPOTHESIS_REF, FONTE_TASK_TYPE, FONTE_SINAL_DE_TESTE, FONTE_ESTRUTURA_DAG, FONTE_RESIDUAL,
)

_MAX_DECLARED_ROLE_CHARS = 32


@dataclass(frozen=True)
class RoleDecision:
    """Papel decidido e a regra que o decidiu (``papel_fonte``)."""

    papel: str
    fonte: str


def declared_role(value: Any) -> str:
    """Papel declarado no plano, limpo e limitado (dado não confiável); vazio quando não é texto.

    O valor inválido segue no campo para o retorno ao Researcher registrar ``papel_invalido``; ``classify_role`` o
    trata como ausente.
    """
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:_MAX_DECLARED_ROLE_CHARS].lower()


def declared_roles(plan_data: list[dict[str, Any]]) -> dict[str, str]:
    """``task_name -> papel`` das subtarefas do plano com ``papel`` declarado válido (evento ``plan_validation``)."""
    out: dict[str, str] = {}
    for item in plan_data or []:
        if not isinstance(item, dict):
            continue
        name = item.get("task_name")
        papel = declared_role(item.get("papel"))
        if isinstance(name, str) and name and papel in PAPEIS_EXPERIMENTO:
            out[name[:128]] = papel
    return out


def _metric_bases(metric: MetricRef) -> set[str]:
    """Nomes de M e dos sinônimos, sem qualificador e pelos aliases do revisor (``acuracia`` -> ``accuracy``)."""
    bases: set[str] = set()
    for name in (metric.nome, *metric.sinonimos):
        if not isinstance(name, str) or not name.strip():
            continue
        base = split_metric_name(name).base
        if base:
            bases.add(_METRIC_ALIASES.get(base, base))
    return bases


def has_test_signal(criteria: list[str], metric: MetricRef | None) -> bool:
    """Algum critério compara numericamente M (nome ou sinônimo), sem qualificador ou com qualificador de teste.

    ``cv``, ``treino`` e ``validacao`` não contam (como em ``v18.6-review-evidence``); limiares sobre outras
    grandezas ("proporção de nulos <= 0") também não.
    """
    if metric is None:
        return False
    wanted = _metric_bases(metric)
    if not wanted:
        return False
    for criterion in criteria or []:
        if not isinstance(criterion, str):
            continue
        for raw_name, _operator, _value in _CRITERION_VALUE_PATTERN.findall(criterion):
            if criterion_qualifier(raw_name) not in ("", "teste"):
                continue
            words = [w for w in normalized_words(raw_name) if w not in QUALIFIER_WORDS]
            candidates = {_METRIC_ALIASES.get(w, w) for w in words}
            candidates.add(_METRIC_ALIASES.get("".join(words), "".join(words)))
            if candidates & wanted:
                return True
    return False


def has_dependents(task: Any, plan_tasks: list[Any]) -> bool:
    """Alguma subtarefa do plano depende diretamente desta."""
    name = getattr(task, "task_name", "")
    return bool(name) and any(name in (getattr(t, "depends_on", None) or []) for t in plan_tasks)


def classify_role(
    task: Any, plan_tasks: list[Any], metric: MetricRef | None, resolved_ref: bool
) -> RoleDecision:
    """Papel da subtarefa, na ordem do ADR 021 §2.

    Args:
        task: ``AgentTask`` ainda não concluída.
        plan_tasks: Subtarefas do plano (para as dependências).
        metric: Métrica principal M do Problema, ou ``None`` se não resolvida.
        resolved_ref: ``hypothesis_ref`` da subtarefa resolveu para uma hipótese aceita.

    Returns:
        ``RoleDecision``; ``referencia`` só vem da declaração.
    """
    declared = declared_role(getattr(task, "papel", ""))
    if declared in PAPEIS_EXPERIMENTO:
        return RoleDecision(declared, FONTE_DECLARADO)
    if resolved_ref:
        return RoleDecision(PAPEL_TESTE, FONTE_HYPOTHESIS_REF)
    if getattr(task, "task_type", None) in PREPARATORY_TASK_TYPES:
        return RoleDecision(PAPEL_PREPARACAO, FONTE_TASK_TYPE)
    approach = getattr(task, "approach", None)
    approach_signal = isinstance(approach, dict) and approach.get("tipo") == "algoritmo"
    if approach_signal or has_test_signal(list(getattr(task, "validation_criteria", None) or []), metric):
        return RoleDecision(PAPEL_TESTE, FONTE_SINAL_DE_TESTE)
    if has_dependents(task, plan_tasks):
        return RoleDecision(PAPEL_PREPARACAO, FONTE_ESTRUTURA_DAG)
    return RoleDecision(PAPEL_PREPARACAO, FONTE_RESIDUAL)
