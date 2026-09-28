"""Registro de definições de agente para o runtime em processo (Roadmap V16).

Equivalente, para o modo ``AGENT_RUNTIME=inprocess``, ao ``AGENT_REGISTRY``
(papel → imagem Docker) usado pelo modo container: mapeia cada papel de
agente à sua instrução, ferramentas e callbacks — reaproveitando os objetos
``Agent`` já definidos em ``agents/*/agent.py`` para não duplicar o conteúdo
dos prompts (fonte única de verdade continua nos módulos de agente).

A construção é preguiçosa (``get_agent_definitions``) porque importar
``agents/*/agent.py`` executa efeitos colaterais de inicialização (setup de
skills, logging) — só queremos pagar esse custo quando o runtime em processo
é efetivamente usado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentDefinition:
    """Definição de um papel de agente executável em processo.

    Args:
        agent_id: Papel do agente (chave em ``AGENT_DEFINITIONS``).
        role: Papel usado para resolução de provedor/modelo via
            ``ModelRouter``/``RoleModelConfig`` (normalmente igual a
            ``agent_id``).
        instruction: Função que retorna a instrução (system prompt) atual do
            agente — pode ser dinâmica (ex.: injeta contexto do workspace).
        tools: Lista de ferramentas (funções Python) disponíveis ao agente.
        before_callback: Callback executado antes do loop do agente.
        after_callback: Callback executado após o loop do agente.
    """

    agent_id: str
    role: str
    instruction: Callable[[], str]
    tools: List[Callable[..., Any]]
    before_callback: Optional[Callable[[Any], Awaitable[None]]] = None
    after_callback: Optional[Callable[[Any], Awaitable[None]]] = None


def _build_definitions() -> Dict[str, AgentDefinition]:
    """Importa os módulos de agente e monta o registro ``AGENT_DEFINITIONS``.

    Returns:
        Dicionário papel → ``AgentDefinition``.
    """
    from agents.base.agent import root_agent as base_agent
    from agents.developer.agent import root_agent as developer_agent
    from agents.researcher.agent import root_agent as researcher_agent
    from agents.reviewer.agent import create_agent as create_reviewer_agent
    from agents.summarizer.agent import root_agent as summarizer_agent

    reviewer_agent = create_reviewer_agent()

    role_to_agent = {
        "base": base_agent,
        "developer": developer_agent,
        "researcher": researcher_agent,
        "summarizer": summarizer_agent,
        "reviewer": reviewer_agent,
    }

    definitions: Dict[str, AgentDefinition] = {}
    for role, agent in role_to_agent.items():
        definitions[role] = AgentDefinition(
            agent_id=role,
            role=role,
            instruction=(lambda bound_agent=agent: bound_agent.instruction),
            tools=list(agent.tools),
            before_callback=agent.before_agent_callback,
            after_callback=agent.after_agent_callback,
        )

    logger.info(
        "AGENT_DEFINITIONS construído para o runtime em processo",
        extra={"roles": sorted(definitions.keys())},
    )
    return definitions


_definitions_cache: Optional[Dict[str, AgentDefinition]] = None


def get_agent_definitions() -> Dict[str, AgentDefinition]:
    """Retorna o registro completo de definições de agente (construção preguiçosa).

    Returns:
        Dicionário papel → ``AgentDefinition``, cacheado após a primeira chamada.
    """
    global _definitions_cache
    if _definitions_cache is None:
        _definitions_cache = _build_definitions()
    return _definitions_cache


def get_agent_definition(agent_id: str) -> AgentDefinition:
    """Resolve a definição de um papel de agente específico.

    Args:
        agent_id: Papel do agente a resolver (ex.: ``"developer"``).

    Returns:
        A ``AgentDefinition`` correspondente.

    Raises:
        ValueError: Se ``agent_id`` não corresponder a nenhum papel registrado.
    """
    definitions = get_agent_definitions()
    definition = definitions.get(agent_id)
    if definition is None:
        valid = ", ".join(sorted(definitions.keys()))
        raise ValueError(
            f"Papel de agente desconhecido para o runtime em processo: '{agent_id}'. "
            f"Papéis disponíveis: {valid}."
        )
    return definition


def reset_definitions_cache() -> None:
    """Limpa o cache de definições (uso em testes)."""
    global _definitions_cache
    _definitions_cache = None
