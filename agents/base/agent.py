"""Agente base GeminiClaw usando Google ADK.

Este módulo define o root_agent que serve como agente mínimo funcional.
Integra-se ao SessionManager para carregar e persistir contexto,
e ao logger estruturado para rastreamento de operações.
"""

import os
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.genai import types as genai_types
from agents.base.tools import write_artifact
from src.logger import get_logger, setup_file_logging
from src.session import SessionManager
from src.config import DEFAULT_MODEL, SQLITE_DB_PATH
from src.skills import registry
from src.skills.memory.long_term import LongTermMemory

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_base"
AGENT_DESCRIPTION = (
    "Agente base do framework GeminiClaw. Capaz de processar solicitações "
    "genéricas, manter contexto de sessão e responder em português."
)
AGENT_INSTRUCTION = (
    "Você é um agente assistente do framework GeminiClaw, executando em um "
    "container Docker isolado em um Raspberry Pi 5. Suas responsabilidades são:\n"
    "1. Processar a solicitação recebida de forma clara e objetiva.\n"
    "2. Responder sempre em português brasileiro.\n"
    "3. Ser conciso e direto nas respostas.\n"
    "4. Reportar qualquer erro ou limitação encontrada.\n"
    "5. **MEMÓRIA E PERFIL DO USUÁRIO**: Utilize as ferramentas de memória para "
    "identificar informações sobre o perfil e preferências do usuário. "
    "Quando identificar algo relevante e duradouro, registre na memória de longo prazo.\n"
    "6. **FERRAMENTAS**: Você possui acesso a diversas skills (busca na web, execução de código, memória). "
    "Use-as conforme a necessidade para resolver as tarefas.\n"
    "7. **EXECUÇÃO DE CÓDIGO (CRÍTICO)**: Quando sua tarefa envolver criar um pipeline de ML ou qualquer script, "
    "você DEVE EXECUTAR o código usando a ferramenta 'python_interpreter' para validar os resultados e "
    "garantir que os arquivos de output (CSV, PNG, JSON, MD) sejam realmente gerados no disco.\n"
    "8. **IMPORTANTE**: Todos os artefatos finais devem ser salvos em `/outputs/` usando a ferramenta 'write_artifact'.\n"
    "Se não souber responder, diga claramente que não tem informação suficiente."
)


async def _load_session_context(callback_context: Any) -> None:
    """Callback executado antes do agente processar a solicitação.

    Carrega o payload da sessão do SQLite e injeta no state do agente.

    Args:
        callback_context: Contexto do callback ADK.
    """
    session_id = os.environ.get("SESSION_ID", "")
    agent_id = os.environ.get("AGENT_ID", "")

    if not session_id:
        logger.warning(
            "SESSION_ID não definido, pulando carregamento de sessão",
            extra={"agent_id": agent_id},
        )
        return

    try:
        db_path = os.environ.get("SQLITE_DB_PATH", SQLITE_DB_PATH)
        manager = SessionManager(db_path)
        session = manager.get(session_id)

        if session:
            # Injeta o payload da sessão no state do agente
            for key, value in session.payload.items():
                callback_context.state[key] = value

            logger.info(
                "Contexto da sessão carregado",
                extra={
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "payload_keys": list(session.payload.keys()),
                },
            )
        else:
            logger.warning(
                "Sessão não encontrada",
                extra={"session_id": session_id, "agent_id": agent_id},
            )

    except Exception as e:
        logger.error(
            "Erro ao carregar contexto da sessão",
            extra={
                "session_id": session_id,
                "agent_id": agent_id,
                "error": str(e),
            },
        )


async def _persist_session_context(callback_context: Any) -> None:
    """Callback executado após o agente processar a solicitação.

    Persiste o state do agente de volta na sessão do SQLite.

    Args:
        callback_context: Contexto do callback ADK.
    """
    session_id = os.environ.get("SESSION_ID", "")
    agent_id = os.environ.get("AGENT_ID", "")

    if not session_id:
        return

    try:
        db_path = os.environ.get("SQLITE_DB_PATH", SQLITE_DB_PATH)
        manager = SessionManager(db_path)

        # Converte o state para dict serializável
        state_data: dict[str, Any] = {}
        for key in callback_context.state:
            state_data[key] = callback_context.state[key]

        manager.update(session_id, payload=state_data)

        logger.info(
            "Contexto da sessão persistido",
            extra={
                "session_id": session_id,
                "agent_id": agent_id,
                "state_keys": list(state_data.keys()),
            },
        )

    except Exception as e:
        logger.error(
            "Erro ao persistir contexto da sessão",
            extra={
                "session_id": session_id,
                "agent_id": agent_id,
                "error": str(e),
            },
        )


def _setup_skills() -> None:
    """Configura e registra as skills habilitadas via variáveis de ambiente."""
    # Como as skills já tentam se registrar no __init__.py de src.skills,
    # aqui apenas garantimos que respeitamos os flags do .env
    
    # Se uma skill não estiver habilitada, removemos do registry se estiver lá
    if os.environ.get("SKILL_QUICK_SEARCH_ENABLED", "true").lower() != "true":
        registry._skills.pop("quick_search", None)
        
    if os.environ.get("SKILL_DEEP_SEARCH_ENABLED", "false").lower() != "true":
        registry._skills.pop("deep_search", None)
        
    if os.environ.get("SKILL_CODE_ENABLED", "true").lower() != "true":
        registry._skills.pop("python_interpreter", None)
        
    if os.environ.get("SKILL_MEMORY_ENABLED", "true").lower() != "true":
        registry._skills.pop("memory", None)

    logger.info(
        "Skills configuradas",
        extra={"available_skills": [s["name"] for s in registry.list_available()]}
    )


def _get_agent_instruction(base_instruction: str) -> str:
    """Gera a instrução do agente incluindo o resumo da memória de longo prazo."""
    instruction = base_instruction
    
    try:
        db_path = os.environ.get("LONG_TERM_MEMORY_DB", "./store/memory.db")
        ltm = LongTermMemory(db_path)
        summary = ltm.summarize_for_context(limit=5)
        
        if summary:
            instruction += f"\n\n**CONTEXTO HISTÓRICO (Memória de Longo Prazo)**:\n{summary}"
            logger.info("Resumo da memória de longo prazo injetado na instrução")
    except Exception as e:
        logger.warning(f"Não foi possível carregar memória de longo prazo: {e}")
        
    return instruction


# Configura as skills antes de inicializar o agente
_setup_skills()

# Define o root_agent — ponto de entrada obrigatório para o ADK
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=_get_agent_instruction(AGENT_INSTRUCTION),
    tools=registry.as_adk_tools() + [write_artifact],
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

logger.info(
    "Agente base inicializado",
    extra={
        "agent_name": AGENT_NAME,
        "model": DEFAULT_MODEL,
    },
)

if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop
    
    # Configura o logger raiz para escrever também no volume compartilhado
    # O diretório /logs/ já é garantido pelo OutputManager no host
    setup_file_logging("/logs/agent.log")
    
    # Inicia o loop de conexão IPC quando o container roda este módulo
    asyncio.run(run_ipc_loop(root_agent))
