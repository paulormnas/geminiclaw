"""Dependências cujas saídas o sandbox monta somente leitura (v18.7-dependency-artifacts, ADR 022 §9, design §3).

Funções puras: recebem o grafo de dependências e as sessões onde cada subtarefa concluiu e devolvem os
``DependencyMount`` da tentativa. A validação das origens e o teto de montagens são do sandbox.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from src import config
from src.utils.agent_context import DependencyMount


def dependency_names(task_name: str, depends: Mapping[str, Sequence[str]], scope: str) -> list[str]:
    """Dependências de ``task_name``: as diretas, ou o fecho transitivo de ``depends`` (ordem estável, sem repetição).

    Args:
        task_name: Subtarefa consumidora.
        depends: ``task_name`` -> dependências diretas (do plano e do checkpoint da sessão anterior).
        scope: ``transitivas`` ou ``diretas`` (``DEPENDENCY_ARTIFACTS_SCOPE``).
    """
    direct = [d for d in depends.get(task_name, ()) if d and d != task_name]
    if scope == "diretas":
        return list(dict.fromkeys(direct))
    ordered: list[str] = []
    stack = list(reversed(direct))
    while stack:
        name = stack.pop()
        if name in ordered or name == task_name:
            continue
        ordered.append(name)
        stack.extend(reversed(list(depends.get(name, ()))))
    return ordered


def resolve_dependency_mounts(
    task_name: str,
    depends: Mapping[str, Sequence[str]],
    concluded: Mapping[str, str],
    output_root: Path,
    scope: str | None = None,
) -> tuple[DependencyMount, ...]:
    """Saídas das dependências concluídas de ``task_name`` a montar no sandbox.

    Args:
        task_name: Subtarefa consumidora.
        depends: ``task_name`` -> dependências diretas.
        concluded: ``task_name`` -> sessão onde concluiu (a atual, ou a de origem na retomada). Dependência fora daqui
            não concluiu e não é montada.
        output_root: Raiz de saída (``outputs/``).
        scope: Padrão ``DEPENDENCY_ARTIFACTS_SCOPE``.

    Returns:
        Montagens na ordem das dependências; sem pasta no host, a dependência não entra. Nunca é truncado: o teto
        ``DEPENDENCY_ARTIFACTS_MAX_MOUNTS`` é conferido pelo sandbox, que recusa a execução.
    """
    if not config.DEPENDENCY_ARTIFACTS_ENABLED:
        return ()
    mounts: list[DependencyMount] = []
    for name in dependency_names(task_name, depends, scope or config.DEPENDENCY_ARTIFACTS_SCOPE):
        session = concluded.get(name)
        if not session:
            continue
        folder = output_root / session / name
        if folder.is_dir():
            mounts.append(DependencyMount(task_name=name, source=folder, session_id=session))
    return tuple(mounts)
