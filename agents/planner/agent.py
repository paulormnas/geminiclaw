"""Agente planner do GeminiClaw usando Google ADK.

Especializado em decompor solicitações complexas em planos de ação estruturados.
Gera uma lista de tarefas, cada uma com um agente responsável e prompt específico.
"""

from google.adk.agents import Agent
from typing import Any
import os

from src.logger import get_logger
from src.config import DEFAULT_MODEL
from agents.base.agent import _load_session_context, _persist_session_context

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_planner"
AGENT_DESCRIPTION = (
    "Agente planejador do framework GeminiClaw. Especializado em decompor "
    "problemas complexos em etapas ordenadas e executáveis por outros agentes."
)
AGENT_INSTRUCTION = (
    "Você é o Agente Planejador do framework GeminiClaw. Sua função é receber uma "
    "solicitação do usuário e transformá-la em um plano de execução estruturado.\n\n"
    "DIRETRIZES DE PLANEJAMENTO:\n"
    "1. Decompunha o problema em etapas lógicas e independentes quando possível.\n"
    "2. Para cada etapa, identifique o agente mais adequado (ex: 'researcher' para busca, 'base' para processamento geral).\n"
    "3. IMPORTANTE: Cada tarefa deve especificar onde salvar seus artefatos em `/outputs/<task_name>/`.\n"
    "4. O plano deve ser retornado em formato JSON, contendo uma lista de tarefas.\n"
    "5. Cada tarefa deve ter: 'agent_id' (tipo do agente), 'image' (imagem docker), 'prompt' (instrução específica para aquela etapa) e 'task_name' (identificador único da etapa).\n\n"
    "EXEMPLO DE SAÍDA (Apenas o JSON):\n"
    "[\n"
    "  {\n"
    "    \"agent_id\": \"researcher\",\n"
    "    \"image\": \"geminiclaw-researcher\",\n"
    "    \"task_name\": \"collect_info\",\n"
    "    \"prompt\": \"Pesquise sobre X e salve o resumo em /outputs/collect_info/summary.md\"\n"
    "  }\n"
    "]"
)

# Define o root_agent
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=AGENT_INSTRUCTION,
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop
    
    asyncio.run(run_ipc_loop(root_agent))
