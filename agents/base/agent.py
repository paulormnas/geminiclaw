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

from src.logger import get_logger
from src.session import SessionManager
from src.config import DEFAULT_MODEL, SQLITE_DB_PATH

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
    "5. **IMPORTANTE**: Todos os artefatos (código, documentos, imagens) que você produzir devem ser salvos em `/outputs/<task_name>/` dentro do container.\n"
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


# Define o root_agent — ponto de entrada obrigatório para o ADK
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=AGENT_INSTRUCTION,
    tools=[write_artifact],
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
    
    # Inicia o loop de conexão IPC quando o container roda este módulo
    asyncio.run(run_ipc_loop(root_agent))
