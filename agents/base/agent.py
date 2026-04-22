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
    "Você é um assistente de análise de dados e geração de código do framework GeminiClaw, "
    "executando em um container Docker isolado em um Raspberry Pi 5.\n\n"
    "RESPONSABILIDADES:\n"
    "1. **ANÁLISE DE DADOS**: Processar datasets, calcular estatísticas, identificar padrões e tendências.\n"
    "2. **GERAÇÃO E EXECUÇÃO DE CÓDIGO**: Criar scripts Python para automação, transformação de dados e visualizações.\n"
    "3. **PRODUÇÃO DE ARTEFATOS**: Gerar relatórios, gráficos e arquivos de dados estruturados.\n\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "1. **EXECUTE SEMPRE O CÓDIGO**: Qualquer código Python gerado DEVE ser executado via ferramenta "
    "`python_interpreter`. Nunca apenas exiba o código sem executá-lo. "
    "O resultado da execução valida a corretude e garante que os arquivos de output sejam gerados.\n"
    "2. **SALVE TODOS OS OUTPUTS**: Todos os artefatos produzidos (CSV, PNG, JSON, MD, relatórios) "
    "DEVEM ser salvos em `/outputs/` via ferramenta `write_artifact`. "
    "Arquivos gerados apenas em memória durante execução do código não são artefatos válidos.\n"
    "3. **MEMÓRIA**: Use a ferramenta `memory` (ação `recall`) antes de iniciar uma análise "
    "para verificar contexto relevante de sessões anteriores. "
    "Após concluir, persista descobertas importantes com `memorize`.\n"
    "4. **CLAREZA E OBJETIVIDADE**: Apresente os resultados de forma concisa. "
    "Inclua a interpretação dos dados, não apenas os números.\n"
    "5. **IDIOMA**: Responda sempre em português brasileiro.\n\n"
    "Se não souber responder ou os dados forem insuficientes, declare claramente a limitação."
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
    """Gera a instrução do agente com system_context dinâmico estruturado.

    Injeta ao final da instrução base:
    - Catálogo de skills disponíveis com orientação de uso
    - Resumo da memória de longo prazo
    - Informações de hardware (quando disponível no Pi 5)

    Args:
        base_instruction: Texto base da instrução do agente.

    Returns:
        Instrução completa com contexto dinâmico injetado.
    """
    instruction = base_instruction
    context_sections: list[str] = []

    # --- Catálogo de skills disponíveis ---
    _SKILL_GUIDANCE: dict[str, str] = {
        "quick_search": "buscas gerais na web, notícias e informações recentes",
        "deep_search": "pesquisa aprofundada em domínios indexados (ex: docs, arxiv)",
        "python_interpreter": "execução de código Python, análise de dados, cálculos",
        "memory": "memorizar preferências e contexto duradouro; recall de sessões anteriores",
        "web_reader": "leitura do conteúdo completo de uma URL específica",
    }

    available_skills = registry.list_available()
    if available_skills:
        skill_lines = []
        for s in available_skills:
            guidance = _SKILL_GUIDANCE.get(s["name"], s["description"])
            skill_lines.append(f"  - `{s['name']}`: {guidance}")
        context_sections.append(
            "**SKILLS DISPONÍVEIS** (use a ferramenta certa para cada tarefa):\n"
            + "\n".join(skill_lines)
        )

    # --- Memória de longo prazo ---
    try:
        db_path = os.environ.get("LONG_TERM_MEMORY_DB", "./store/memory.db")
        ltm = LongTermMemory(db_path)
        summary = ltm.summarize_for_context(limit=5)

        if summary:
            context_sections.append(
                f"**CONTEXTO HISTÓRICO (Memória de Longo Prazo)**:\n{summary}"
            )
            logger.info("Resumo da memória de longo prazo injetado na instrução")
    except Exception as e:
        logger.warning(f"Não foi possível carregar memória de longo prazo: {e}")

    # --- Informações de hardware (Pi 5 / plataforma atual) ---
    try:
        import platform
        import shutil

        hw_lines: list[str] = []

        # Detecta Raspberry Pi via device-tree
        cpu_model_path = "/proc/device-tree/model"
        if os.path.exists(cpu_model_path):
            with open(cpu_model_path, "r", errors="replace") as f:
                hw_lines.append(f"  - Plataforma: {f.read().strip()}")

        # Uso de disco (diretório de outputs)
        outputs_dir = os.environ.get("OUTPUT_BASE_DIR", "./outputs")
        disk = shutil.disk_usage(outputs_dir if os.path.exists(outputs_dir) else ".")
        hw_lines.append(
            f"  - Disco livre: {disk.free // (1024 ** 3)} GB de {disk.total // (1024 ** 3)} GB"
        )

        # Temperatura (apenas Pi)
        thermal_path = "/sys/class/thermal/thermal_zone0/temp"
        if os.path.exists(thermal_path):
            with open(thermal_path) as f:
                temp_c = int(f.read().strip()) / 1000
            hw_lines.append(f"  - Temperatura CPU: {temp_c:.1f}°C")

        if hw_lines:
            context_sections.append(
                "**INFORMAÇÕES DO HARDWARE**:\n" + "\n".join(hw_lines)
            )
    except Exception as e:
        logger.debug(f"Não foi possível coletar informações de hardware: {e}")

    if context_sections:
        instruction += "\n\n---\n**CONTEXTO DO SISTEMA**:\n" + "\n\n".join(context_sections)

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
