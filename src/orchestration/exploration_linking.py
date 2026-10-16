"""Ligação das subtarefas do plano às hipóteses (v18-hypothesis-loop, design §2 e §4).

Movido de ``exploration.py`` sem alterar o comportamento (v18.7-hypothesis-linking, tarefa 0.9; ADR 024 §5): a
resolução de ``hypothesis_ref`` para o ``id`` da hipótese, a retirada das subtarefas que a governança não deixa
executar e o fecho das que dependem delas. ``ExplorationSession.prepare_cycle`` só orquestra estas funções.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.knowledge.hypotheses import HypothesisBook, PlanExtras, RecordReport, legacy_hypotheses
from src.knowledge.hypothesis_cycle import Selection
from src.utils.normalization import normalize_domain_term

# Subtarefas que preparam ou sintetizam não testam hipótese; as demais de um plano no formato novo precisam de uma.
PREPARATORY_TASK_TYPES = frozenset({"eda", "synthesis"})


def bind_legacy_refs(tasks: list[Any], extras: PlanExtras) -> tuple[PlanExtras, bool]:
    """Formato antigo: promove o campo ``hypothesis`` das subtarefas a hipóteses formais e preenche ``hypothesis_ref``.

    Returns:
        ``(extras, legado)``: ``legado`` é verdadeiro quando alguma hipótese foi promovida.
    """
    if extras.novo_formato:
        return extras, False
    declared = legacy_hypotheses(
        [{"hypothesis": t.hypothesis, "scientific_rationale": t.scientific_rationale, "approach": t.approach}
         for t in tasks]
    )
    if not declared:
        return extras, False
    by_text = {normalize_domain_term(d.enunciado): d.ref for d in declared}
    for task in tasks:
        if not getattr(task, "hypothesis_ref", "") and task.hypothesis:
            task.hypothesis_ref = by_text.get(normalize_domain_term(task.hypothesis), "")
    return replace(extras, hipoteses=declared), True


def is_bound(task: Any) -> bool:
    """Subtarefa que testa hipótese (precisa de ``hypothesis_ref`` resolvível no formato novo).

    Tipos preparatórios (``eda``, ``synthesis``) nunca testam hipótese, mesmo que o modelo preencha ``approach``:
    o Gemini 3.8 flash o preenche em todas as subtarefas, e exigir hipótese da EDA retirava o plano inteiro (tudo
    depende dela), fechando a sessão como ``sem_caminhos_promissores`` sem executar nada.
    """
    if getattr(task, "task_type", None) in PREPARATORY_TASK_TYPES:
        return False
    if getattr(task, "approach", None):
        return True
    return getattr(task, "agent_id", "") == "developer" and getattr(task, "task_type", None) not in (
        PREPARATORY_TASK_TYPES
    )


def resolve_task_refs(
    book: HypothesisBook, tasks: list[Any], report: RecordReport, *, novo_formato: bool, done: set[str]
) -> dict[str, str]:
    """Preenche ``hypothesis_id`` de cada subtarefa e devolve ``task_name -> motivo`` das que não podem executar."""
    dropped: dict[str, str] = {}
    for task in tasks:
        ref = getattr(task, "hypothesis_ref", "") or ""
        hid = book.resolve_ref(ref, report) if ref else None
        task.hypothesis_id = hid or ""
        if ref and hid is None and ref in report.rejeitadas:
            dropped[task.task_name] = f"hipotese_{report.rejeitadas[ref]}"
        elif novo_formato and hid is None and is_bound(task) and task.task_name not in done:
            dropped[task.task_name] = "sem_hipotese"
    return dropped


def governance_drops(
    tasks: list[Any], selection: Selection, dropped: dict[str, str], *, done: set[str]
) -> None:
    """Acrescenta a ``dropped`` as subtarefas cuja hipótese a governança não deixou executar."""
    runnable = set(selection.execute)
    for task in tasks:
        if task.task_name in dropped or task.task_name in done:
            continue
        if task.hypothesis_id and task.hypothesis_id not in runnable:
            if task.hypothesis_id in selection.pending_approval:
                dropped[task.task_name] = "hipotese_aguarda_aprovacao"
            elif task.hypothesis_id in selection.rejected:
                dropped[task.task_name] = "hipotese_rejeitada_pelo_pesquisador"
            elif task.hypothesis_id in selection.deferred:
                dropped[task.task_name] = "hipotese_adiada_por_prioridade"
            else:
                dropped[task.task_name] = "hipotese_ja_concluida_ou_abandonada"


def descendants_of(dropped: set[str], tasks: list[Any], keep: set[str]) -> set[str]:
    """Fecho transitivo das subtarefas que dependem de uma retirada (as já concluídas em ``keep`` ficam)."""
    out = set(dropped)
    changed = True
    while changed:
        changed = False
        for task in tasks:
            name = getattr(task, "task_name", "")
            if name and name not in out and name not in keep and any(d in out for d in task.depends_on):
                out.add(name)
                changed = True
    return out
