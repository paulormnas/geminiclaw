"""Agente validator do GeminiClaw usando Google ADK.

Especializado em revisar planos de ação gerados pelo Planner.
Verifica ambiguidade, dependências e conformidade com as regras de output.
"""

from google.adk.agents import Agent
from typing import Any
import os

from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
from agents.base.agent import _load_session_context, _persist_session_context, _setup_skills
from src.skills import registry

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_validator"
AGENT_DESCRIPTION = (
    "Agente validador do framework GeminiClaw. Especializado em revisar "
    "planos de execução, identificar falhas, ambiguidades ou erros de diretriz."
)
AGENT_INSTRUCTION = (
    "Você é o Agente Validador do framework GeminiClaw. Sua função é revisar o plano "
    "proposto pelo Agente Planejador para uma solicitação do usuário.\n\n"
    "CRITÉRIOS DE VALIDAÇÃO (CRÍTICO):\n"
    "1. **Paralelismo**: Verifique se o plano faz uso correto da 'memory' para persistência entre agentes, mas mantenha a regra de que tarefas com dependência imediata de I/O devem ser fundidas.\n"
    "2. **Uso de Skills**: O plano utiliza as ferramentas corretas para cada tarefa? (ex: 'quick_search' para web, 'python_interpreter' para cálculos complexos).\n"
    "3. **Ambiguidade**: As instruções de cada tarefa são claras o suficiente para um agente executar?\n"
    "4. **Outputs**: Cada tarefa especifica explicitamente o uso da ferramenta write_artifact para salvar em `/outputs/`?\n"
    "5. **Viabilidade**: O plano é realizável com os agentes disponíveis (base, researcher, planner, validator)?\n\n"
    "FORMATO DE RESPOSTA (Apenas JSON):\n"
    "{\n"
    "  \"status\": \"approved\" | \"rejected\" | \"revision_needed\",\n"
    "  \"reason\": \"Explicação curta do motivo (obrigatório se não aprovado)\",\n"
    "  \"suggestions\": [\"Lista de melhorias sugeridas se revision_needed\"]\n"
    "}"
)

# Configura as skills antes de inicializar o agente
_setup_skills()

# Define o root_agent
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=AGENT_INSTRUCTION,
    tools=registry.as_adk_tools(),
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop
    
    # Configura o logger raiz para escrever também no volume compartilhado
    setup_file_logging("/logs/agent.log")
    
    asyncio.run(run_ipc_loop(root_agent))
