"""Ligação das subtarefas do plano às hipóteses (v18-hypothesis-loop §2 e §4; v18.7-hypothesis-linking §3 e §6).

Separado de ``exploration.py`` (tarefa 0.9 de v18.7-hypothesis-linking; ADR 024 §5): a resolução de ``hypothesis_ref``
para o ``id`` da hipótese, a preparação servida a cada hipótese, a retirada das subtarefas que só a decisão humana ou a
integridade impedem de executar e o fecho (até o ponto fixo) das que dependem delas. Funções puras sobre as subtarefas
do plano; ``ExplorationSession.prepare_cycle`` só as orquestra.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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


# Motivos que impedem a execução (ADR 021 §6).
DROP_REJECTED = "hipotese_rejeitada_pelo_pesquisador"
DROP_PENDING = "hipotese_aguarda_aprovacao"
DROP_ABANDONED = "hipotese_abandonada_pelo_pesquisador"
DROP_DEPENDS = "depende_de_subtarefa_retirada"
# Retiradas que mantêm a hipótese viva (pendente): não abandonam a hipótese do sistema (design §4.4).
DROP_PHYSICAL = "experimento_fisico"  # v18.7-exploration-limits: bancada ou equipamento fora do sandbox
KEEPS_HYPOTHESIS_ALIVE = frozenset({DROP_PENDING, DROP_PHYSICAL})
_FORMAT_REJECTIONS = ("id_inexistente", "sem_enunciado")  # falha de formato: vira hipótese do sistema


@dataclass
class RefResolution:
    """Resolução dos ``hypothesis_ref`` do plano.

    Attributes:
        resolved: ``task_name`` -> ``id`` da hipótese aceita a que o ``hypothesis_ref`` resolveu.
        dropped: ``task_name`` -> código das subtarefas cuja referência não pode executar (hipótese abandonada pelo
            pesquisador, equivalente a uma abandonada, oportunidade não aprovada).
        motivo: ``task_name`` -> motivo da hipótese do sistema quando a referência é inválida
            (``ref_id_inexistente`` ou ``ref_sem_enunciado``).
    """

    resolved: dict[str, str] = field(default_factory=dict)
    dropped: dict[str, str] = field(default_factory=dict)
    motivo: dict[str, str] = field(default_factory=dict)


def resolve_task_refs(
    book: HypothesisBook, tasks: list[Any], report: RecordReport
) -> RefResolution:
    """Resolve o ``hypothesis_ref`` de cada subtarefa; nada é retirado por falta ou erro de formato da referência."""
    out = RefResolution()
    for task in tasks:
        ref = getattr(task, "hypothesis_ref", "") or ""
        if not ref:
            continue
        hid = book.resolve_ref(ref, report)
        if hid is not None:
            out.resolved[task.task_name] = hid
        elif ref in report.rejeitadas:
            reason = report.rejeitadas[ref]
            if reason in _FORMAT_REJECTIONS:
                out.motivo[task.task_name] = f"ref_{reason}"
            else:
                out.dropped[task.task_name] = f"hipotese_{reason}"
        elif (node := book.referenced(ref)) is not None and book.abandoned_author(node) == "pesquisador":
            out.dropped[task.task_name] = "hipotese_hipotese_abandonada"
        else:
            out.motivo[task.task_name] = "ref_id_inexistente"
    return out


def is_test(task: Any) -> bool:
    return getattr(task, "papel_decidido", "") == "teste"


def transitive_dependents(name: str, tasks: list[Any]) -> set[str]:
    """Subtarefas que dependem de ``name``, direta ou transitivamente."""
    found: set[str] = set()
    frontier = {name}
    while frontier:
        nxt = {
            t.task_name for t in tasks
            if t.task_name and t.task_name not in found and any(d in frontier for d in t.depends_on)
        }
        found |= nxt
        frontier = nxt
    return found


def transitive_dependencies(name: str, tasks: list[Any]) -> set[str]:
    """Subtarefas das quais ``name`` depende, direta ou transitivamente."""
    by_name = {t.task_name: t for t in tasks if t.task_name}
    found: set[str] = set()
    frontier = [name]
    while frontier:
        task = by_name.get(frontier.pop())
        for dep in (task.depends_on if task is not None else []):
            if dep not in found and dep in by_name:
                found.add(dep)
                frontier.append(dep)
    return found


def served_hypotheses(prep: Any, tasks: list[Any], own: set[str]) -> list[str]:
    """Hipóteses que a preparação serve: as testadas por ``teste`` que dependem dela, e ``own`` (a que ela cita)."""
    dependents = transitive_dependents(prep.task_name, tasks)
    served = {t.hypothesis_id for t in tasks if t.task_name in dependents and is_test(t) and t.hypothesis_id}
    return sorted(served | own)


def governance_drops(tasks: list[Any], selection: Selection, dropped: dict[str, str], *, done: set[str]) -> None:
    """Acrescenta a ``dropped`` os testes cuja hipótese a governança não deixou executar."""
    runnable = set(selection.execute)
    for task in tasks:
        if task.task_name in dropped or task.task_name in done or not is_test(task):
            continue
        hid = task.hypothesis_id
        if not hid or hid in runnable:
            continue
        dropped[task.task_name] = hypothesis_drop_reason(hid, selection) or DROP_ABANDONED


def hypothesis_drop_reason(hid: str, selection: Selection) -> str | None:
    """Motivo pelo qual a governança retirou a hipótese do ciclo, ou ``None`` se ela executa."""
    if hid in selection.execute:
        return None
    if hid in selection.pending_approval:
        return DROP_PENDING
    if hid in selection.rejected:
        return DROP_REJECTED
    return DROP_ABANDONED


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


def cascade_drops(
    tasks: list[Any], dropped: dict[str, str], *, done: set[str], served: dict[str, list[str]],
    hypothesis_drops: dict[str, str],
) -> None:
    """Fecho das retiradas até o ponto fixo (ADR 021 §6).

    - subtarefa que depende de uma retirada sai com ``depende_de_subtarefa_retirada`` (a entrada não vai existir);
    - preparação sai quando **todas** as hipóteses que serve foram retiradas (com o motivo comum delas, se for um só);
      preparação ligada só ao ``Problema`` nunca sai por motivo de hipótese.

    Uma hipótese está retirada quando a governança a retirou (``hypothesis_drops``) ou quando todos os seus testes
    ainda não concluídos foram retirados.
    """
    changed = True
    while changed:
        changed = False
        for name in descendants_of(set(dropped), tasks, done) - set(dropped):
            dropped[name] = DROP_DEPENDS
            changed = True
        tests_of: dict[str, list[str]] = {}
        for task in tasks:
            if task.task_name not in done and is_test(task) and task.hypothesis_id:
                tests_of.setdefault(task.hypothesis_id, []).append(task.task_name)

        def retired(hid: str) -> str | None:
            if hid in hypothesis_drops:
                return hypothesis_drops[hid]
            names = tests_of.get(hid)
            if names and all(n in dropped for n in names):
                reasons = {dropped[n] for n in names}
                return reasons.pop() if len(reasons) == 1 else DROP_DEPENDS
            return None

        for task in tasks:
            name = task.task_name
            if name in done or name in dropped or getattr(task, "papel_decidido", "") != "preparacao":
                continue
            targets = served.get(name) or []
            reasons = [retired(h) for h in targets]
            if targets and all(reasons):
                common = set(reasons)
                dropped[name] = common.pop() if len(common) == 1 else DROP_DEPENDS  # type: ignore[arg-type]
                changed = True
