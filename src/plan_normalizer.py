"""Normalizador determinístico de plano (V16 / ``v16-pipeline-robustness``).

Corrige, antes da validação, apenas o que é recuperável sem inventar conteúdo: envelopes de
lista, tipos de campo, nomes de subtarefa e sinônimos conhecidos de ``task_type`` e ``agent_id``.
Cada reparo é registrado. O que não é recuperável (prompt, critérios de aceite, ciclos, plano
vazio) fica em ``unrecoverable`` e segue para o Validator, que o reprova (AGENTS.md, princípio 6).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

_ENVELOPE_KEYS = ("tasks", "plan", "subtasks", "steps")
_LIST_FIELDS = ("depends_on", "validation_criteria", "expected_artifacts")
_SPLIT_FIELDS = ("depends_on", "expected_artifacts")  # strings separadas por vírgula ou linha

_TASK_TYPE_SYNONYMS: dict[str, str] = {
    "eda": "eda",
    "exploratory": "eda",
    "exploratory_data_analysis": "eda",
    "exploracao": "eda",
    "analise_exploratoria": "eda",
    "reproduction": "reproduction",
    "reproducao": "reproduction",
    "replication": "reproduction",
    "model_impl": "model_impl",
    "model_implementation": "model_impl",
    "modelimpl": "model_impl",
    "implementation": "model_impl",
    "modeling": "model_impl",
    "modelagem": "model_impl",
    "validation": "validation",
    "validacao": "validation",
    "synthesis": "synthesis",
    "sintese": "synthesis",
    "report": "synthesis",
}

_AGENT_SYNONYMS: dict[str, str] = {
    "developer": "developer",
    "dev": "developer",
    "desenvolvedor": "developer",
    "coder": "developer",
    "researcher": "researcher",
    "pesquisador": "researcher",
    "research": "researcher",
    "base": "base",
    "summarizer": "summarizer",
    "sumarizador": "summarizer",
    "reviewer": "reviewer",
    "revisor": "reviewer",
    "validator": "validator",
    "validador": "validator",
}


@dataclass(frozen=True)
class PlanRepair:
    """Reparo aplicado pelo normalizador (``task_name`` ``None`` = plano inteiro)."""

    task_name: str | None
    kind: str
    detail: str


@dataclass(frozen=True)
class NormalizedPlan:
    """Resultado da normalização."""

    tasks: list[dict[str, Any]]
    repairs: list[PlanRepair] = field(default_factory=list)
    unrecoverable: list[str] = field(default_factory=list)


def to_snake_case(name: str) -> str:
    """Converte um nome livre em snake_case ASCII (``"Carregar Dados"`` -> ``carregar_dados``)."""
    stripped = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", stripped.lower()).strip("_")


def _canonical_key(value: str) -> str:
    return re.sub(r"_+", "_", to_snake_case(value))


def _unwrap(raw: Any, repairs: list[PlanRepair]) -> Any:
    if isinstance(raw, dict):
        list_keys = [k for k, v in raw.items() if isinstance(v, list)]
        preferred = [k for k in list_keys if k in _ENVELOPE_KEYS]
        key = preferred[0] if preferred else (list_keys[0] if len(list_keys) == 1 and len(raw) == 1 else None)
        if key is not None:
            repairs.append(PlanRepair(None, "unwrap_envelope", f"lista extraída da chave '{key}'"))
            return raw[key]
    return raw


def _coerce_list(task: dict[str, Any], name: str, repairs: list[PlanRepair]) -> None:
    for key in _LIST_FIELDS:
        if key not in task:
            continue
        value = task[key]
        if isinstance(value, list):
            if all(isinstance(v, str) for v in value):
                continue
            task[key] = [v if isinstance(v, str) else str(v) for v in value]
            repairs.append(PlanRepair(name, "coerce_list", f"{key}: itens convertidos para texto"))
            continue
        if value is None:
            if key in _SPLIT_FIELDS:
                task[key] = []
                repairs.append(PlanRepair(name, "coerce_list", f"{key}: null virou lista vazia"))
            continue  # validation_criteria nulo segue para o Validator
        if isinstance(value, str):
            if key in _SPLIT_FIELDS:
                parts = [p.strip() for p in re.split(r"[,\n]", value) if p.strip()]
            else:
                parts = [value.strip()] if value.strip() else []
            task[key] = parts
            repairs.append(PlanRepair(name, "coerce_list", f"{key}: texto virou lista"))


_APPROACH_KEYS = ("nome", "tipo", "descricao")


def _coerce_approach(task: dict[str, Any], name: str, repairs: list[PlanRepair]) -> None:
    """Normaliza o campo opcional ``approach`` (v17-structural-fact-ingestion).

    Aceita ``{"nome", "tipo", "descricao"}``; texto solto vira ``{"nome": texto}``. Valores que
    não são texto, chaves desconhecidas e abordagens sem ``nome`` são descartados (o campo é opcional).
    """
    value = task.get("approach")
    if isinstance(value, str) and value.strip():
        task["approach"] = {"nome": value.strip()}
        repairs.append(PlanRepair(name or None, "coerce_approach", "approach: texto virou objeto"))
        return
    if isinstance(value, dict):
        clean = {k: v.strip() for k, v in value.items() if k in _APPROACH_KEYS and isinstance(v, str) and v.strip()}
        if "nome" in clean:
            if clean != value:
                repairs.append(PlanRepair(name or None, "coerce_approach", "approach: campos inválidos removidos"))
            task["approach"] = clean
            return
    del task["approach"]
    repairs.append(PlanRepair(name or None, "coerce_approach", "approach removido (sem 'nome' textual)"))


def normalize_plan(raw: Any) -> NormalizedPlan:
    """Normaliza o plano devolvido pelo planejador, sem I/O e sem LLM.

    Args:
        raw: Valor extraído do JSON do planejador (lista, ou dict com envelope).

    Returns:
        ``NormalizedPlan`` com as subtarefas normalizadas, os reparos e os problemas que o
        normalizador não corrige.
    """
    repairs: list[PlanRepair] = []
    unrecoverable: list[str] = []
    data = _unwrap(raw, repairs)
    if not isinstance(data, list) or not data:
        return NormalizedPlan([], repairs, ["Plano vazio ou em formato inválido."])

    tasks: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            unrecoverable.append(f"Subtarefa {idx + 1} não é um objeto JSON.")
            tasks.append(item)
            continue
        tasks.append(dict(item))

    # agent_id e task_type
    for task in tasks:
        if not isinstance(task, dict):
            continue
        label = str(task.get("task_name") or "")
        agent = task.get("agent_id")
        if isinstance(agent, str):
            canonical = _AGENT_SYNONYMS.get(_canonical_key(agent))
            if canonical and canonical != agent:
                task["agent_id"] = canonical
                repairs.append(PlanRepair(label or None, "normalize_agent_id", f"{agent} -> {canonical}"))
            elif canonical is None:
                unrecoverable.append(f"agent_id '{agent}' sem equivalente conhecido (subtarefa '{label}').")
        ttype = task.get("task_type")
        if isinstance(ttype, str):
            canonical = _TASK_TYPE_SYNONYMS.get(_canonical_key(ttype))
            if canonical is None:
                del task["task_type"]
                detail = f"'{ttype}' removido (sem equivalente)"
                repairs.append(PlanRepair(label or None, "normalize_task_type", detail))
            elif canonical != ttype:
                task["task_type"] = canonical
                repairs.append(PlanRepair(label or None, "normalize_task_type", f"{ttype} -> {canonical}"))
        for key in ("hypothesis", "scientific_rationale"):
            if key in task and task[key] is not None and not isinstance(task[key], str):
                task[key] = str(task[key])
                repairs.append(PlanRepair(label or None, "coerce_text", f"{key} convertido para texto"))

    # approach (opcional): texto vira {"nome": ...}; só chaves textuais conhecidas sobrevivem
    for task in tasks:
        if isinstance(task, dict) and "approach" in task:
            _coerce_approach(task, str(task.get("task_name") or ""), repairs)

    # nomes: derivar, snake_case e desduplicar (mapa antigo -> novo para depends_on)
    rename: dict[str, str] = {}
    used: set[str] = set()
    for n, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            continue
        original = task.get("task_name")
        if not isinstance(original, str) or not original.strip():
            agent = to_snake_case(str(task.get("agent_id") or "task")) or "task"
            new = f"{agent}_{n}"
            repairs.append(PlanRepair(new, "derive_task_name", "task_name ausente"))
        else:
            new = to_snake_case(original) or f"task_{n}"
            if new != original:
                repairs.append(PlanRepair(new, "snake_case_name", f"{original} -> {new}"))
        base, suffix = new, 2
        while new in used:
            new = f"{base}_{suffix}"
            suffix += 1
        if new != base:
            repairs.append(PlanRepair(new, "dedupe_name", f"{base} -> {new}"))
        used.add(new)
        task["task_name"] = new
        if isinstance(original, str) and original not in rename:
            rename[original] = new

    canonical_names = {_canonical_key(n): n for n in used}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        name = task["task_name"]
        _coerce_list(task, name, repairs)
        deps = task.get("depends_on")
        if not isinstance(deps, list):
            continue
        fixed: list[str] = []
        for dep in deps:
            target = rename.get(dep) or (dep if dep in used else canonical_names.get(_canonical_key(dep)))
            if target is None:
                unrecoverable.append(f"Subtarefa '{name}' depende de '{dep}', que não existe no plano.")
                fixed.append(dep)
                continue
            if target == name:
                repairs.append(PlanRepair(name, "break_self_dependency", f"dependência de si mesma ({dep}) removida"))
                continue
            if target != dep:
                repairs.append(PlanRepair(name, "fix_dependency_name", f"{dep} -> {target}"))
            if target not in fixed:
                fixed.append(target)
        task["depends_on"] = fixed

    cycle = _find_cycle(tasks)
    if cycle:
        unrecoverable.append("Dependência circular entre subtarefas: " + " -> ".join(cycle) + ".")
    return NormalizedPlan(tasks, repairs, unrecoverable)


def _find_cycle(tasks: list[Any]) -> list[str]:
    graph = {
        t["task_name"]: [d for d in t.get("depends_on", []) if isinstance(d, str)]
        for t in tasks
        if isinstance(t, dict)
    }
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> list[str]:
        state[node] = 1
        for dep in graph.get(node, []):
            if dep not in graph:
                continue
            if state.get(dep) == 1:
                return path[path.index(dep):] + [dep] if dep in path else [node, dep]
            if dep not in state:
                found = visit(dep, path + [dep])
                if found:
                    return found
        state[node] = 2
        return []

    for node in graph:
        if node not in state:
            found = visit(node, [node])
            if found:
                return found
    return []
