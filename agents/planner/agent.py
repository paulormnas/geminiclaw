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
AGENT_INSTRUCTION = """Você é o Agente Planejador do framework GeminiClaw. Sua função é receber uma solicitação do usuário e transformá-la em um plano de execução estruturado.

DIRETRIZES DE PLANEJAMENTO:
1. Decompunha o problema em etapas lógicas.
2. **IMPORTANTE**: Atualmente, todos os agentes no plano são executados em PARALELO e NÃO compartilham memória ou estado em tempo real. Portanto, se uma tarefa depende do resultado de outra, elas devem ser MERGULHADAS em uma única tarefa para um único agente capaz de fazer ambas (ex: 'researcher' pode pesquisar e salvar o resumo).
3. Evite criar múltiplas tarefas para uma solicitação simples que pode ser resolvida por um único agente especializado.
4. Para cada etapa, identifique o agente mais adequado (ex: 'researcher' para busca, 'base' para processamento geral).
5. Cada tarefa deve ter: 'agent_id', 'image', 'prompt' e 'task_name' (identificador único da etapa, use snake_case).
6. O plano deve ser retornado EXCLUSIVAMENTE em formato JSON.

EXEMPLO DE SAÍDA (Apenas o JSON):
[
  {
    "agent_id": "researcher",
    "image": "geminiclaw-researcher",
    "task_name": "pesquisa_raspberry_pi",
    "prompt": "Pesquise sobre a história do Raspberry Pi e salve um resumo detalhado em 'resumo_pi.md' usando a ferramenta write_artifact."
  }
]"""


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
