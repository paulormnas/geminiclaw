"""Contexto de execução por tarefa para o runtime de agentes em processo.

Quando vários agentes rodam em paralelo dentro do mesmo processo do
orquestrador, variáveis de ambiente (``os.environ``) não servem para carregar
estado por tarefa: são globais ao processo. Este módulo usa ``contextvars``
para isolar o estado de cada execução de agente (Roadmap V16 / ADR 014,
Design §1).

``asyncio`` copia o ``contextvars.Context`` corrente ao criar uma nova
``Task`` (via ``asyncio.create_task``/``asyncio.ensure_future``). Definir a
variável de contexto dentro da corrotina de uma tarefa, portanto, isola essa
tarefa das demais que rodam concorrentemente — desde que cada execução de
agente seja disparada em sua própria ``Task`` (ver ``AgentRuntime.run``).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

AskResearcherCallback = Callable[[str, str, str, list[str]], Awaitable[str]]
# (pergunta, contexto, why_cant_proceed, opções, decisao_reservada) -> texto para o agente.
ConsultResearcherCallback = Callable[[str, str, str, list[str], Optional[str]], Awaitable[str]]


@dataclass(frozen=True)
class AgentContext:
    """Estado de execução de uma única tarefa de agente.

    Substitui, no runtime em processo, as variáveis de ambiente por tarefa
    lidas anteriormente de dentro do container (``SESSION_ID``, ``AGENT_ID``,
    ``SESSION_MODE``, ``OUTPUT_BASE_DIR``, ``AGENT_MODEL`` etc.).

    Args:
        session_id: ID da sessão mestra (compartilhada por todas as subtarefas
            de uma mesma execução orquestrada).
        agent_session_id: ID da sessão específica deste agente/subtarefa.
        agent_id: Papel do agente (``researcher``, ``developer``,
            ``summarizer``, ``reviewer``, ``base``, ...).
        task_name: Nome da subtarefa no plano (snake_case), quando houver.
        mode: Modo de operação da sessão (``SessionMode``: assisted|semi|auto).
        output_dir: Diretório absoluto e resolvido de outputs da sessão
            (``outputs/<session_id>/``). Toda escrita de artefato desta tarefa
            deve ser confinada a este diretório.
        model: Modelo LLM efetivo resolvido para esta execução.
        enable_thinking: Se o modo de raciocínio estendido (thinking) do
            provedor deve ser habilitado.
        execution_id: ID da execução (histórico/telemetria); usa
            ``session_id`` quando não houver um execution_id dedicado.
        readable_dirs: Diretórios de outputs de sessões anteriores da cadeia (mesmo projeto), **somente leitura**
            (v18-research-continuity); a escrita continua confinada a ``output_dir``.
        ask_researcher: Callback opcional para round-trip com o pesquisador
            humano (Spec G5), ligado a ``Orchestrator._handle_ask_researcher``
            sem passar por IPC. ``None`` quando a skill deve usar o caminho
            IPC (modo container) ou quando não há researcher disponível.
        consult_researcher: Callback opcional do Researcher consultor (V18 / Spec
            `researcher-consult`), usado por ``ask_researcher`` nos modos ``semi``/``auto``,
            ligado a ``Orchestrator._consult_researcher_core``. ``None`` mantém a suposição
            documentada.
        project_id: Projeto de pesquisa da sessão (v17-input-document-index); restringe por padrão a busca e a
            lista de documentos. ``None`` fora de sessões de projeto.
        extra: Metadados adicionais não cobertos pelos campos acima (``project_meta``: ``ProjectMeta`` do projeto,
            usado no cabeçalho enriquecido da ingestão de artefatos).
    """

    session_id: str
    agent_session_id: str
    agent_id: str
    mode: str
    output_dir: Path
    model: str
    task_name: str = ""
    enable_thinking: bool = False
    execution_id: str = ""
    readable_dirs: tuple[Path, ...] = ()
    ask_researcher: Optional[AskResearcherCallback] = None
    consult_researcher: Optional[ConsultResearcherCallback] = None
    project_id: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


current_context: ContextVar[Optional[AgentContext]] = ContextVar(
    "geminiclaw_agent_context", default=None
)


def get_agent_context() -> AgentContext:
    """Retorna o ``AgentContext`` da tarefa em execução.

    Returns:
        O ``AgentContext`` vinculado à ``Task`` asyncio corrente.

    Raises:
        RuntimeError: Se chamado fora do escopo de execução de um agente
            (nenhum contexto foi vinculado nesta ``Task``).
    """
    ctx = current_context.get()
    if ctx is None:
        raise RuntimeError(
            "get_agent_context() chamado fora de uma execução de agente em "
            "processo — nenhum AgentContext está vinculado à Task asyncio atual."
        )
    return ctx


def get_agent_context_optional() -> Optional[AgentContext]:
    """Retorna o ``AgentContext`` corrente, ou ``None`` se não houver um.

    Usado por código que precisa funcionar tanto no runtime em processo
    quanto no modo container legado (onde não há ``AgentContext`` e o estado
    por tarefa continua vindo de ``os.environ``).

    Returns:
        O ``AgentContext`` vinculado à ``Task`` atual, ou ``None``.
    """
    return current_context.get()


def bind_agent_context(ctx: AgentContext) -> Any:
    """Vincula ``ctx`` como o ``AgentContext`` da ``Task`` asyncio corrente.

    Deve ser chamado como a primeira ação dentro da corrotina que representa
    a execução isolada de um agente (idealmente logo após
    ``asyncio.create_task``), para que o isolamento por ``Task`` do
    ``contextvars`` entre em vigor.

    Args:
        ctx: Contexto a vincular.

    Returns:
        Token opaco retornável a ``current_context.reset()`` para desfazer a
        vinculação (uso tipicamente desnecessário quando a ``Task`` é
        descartada ao final da execução, mas exposto para testes).
    """
    return current_context.set(ctx)
