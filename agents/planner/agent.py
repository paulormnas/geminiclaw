"""Agente planner do GeminiClaw usando Google ADK.

Especializado em decompor solicitações complexas em planos de ação estruturados.
Gera uma lista de tarefas, cada uma com um agente responsável e prompt específico.
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
AGENT_NAME = "geminiclaw_planner"
AGENT_DESCRIPTION = (
    "Agente planejador do framework GeminiClaw. Especializado em decompor "
    "problemas complexos em etapas ordenadas e executáveis por outros agentes."
)
AGENT_INSTRUCTION = """Você é o Agente Planejador do framework GeminiClaw. Sua função é receber uma solicitação do usuário e transformá-la em um plano de execução estruturado.

DIRETRIZES DE PLANEJAMENTO:
1. Decompunha o problema em etapas lógicas e ordenadas.
3. **FUSÃO DE TAREFAS (IMPORTANTE)**: Tarefas que possuem dependência imediata de I/O (ex: treinamento que depende de dados recém-processados) e que serão executadas pelo mesmo agente DEVEM ser fundidas em uma única etapa para otimizar o fluxo.
4. **PERSISTÊNCIA OBRIGATÓRIA**: Todos os arquivos gerados (relatórios, código, dados, gráficos) DEVEM ser salvos usando a ferramenta 'write_artifact' no diretório '/outputs/'. Isso é fundamental para que outros agentes e o usuário acessem os resultados.
5. **MEMÓRIA DE LONGO PRAZO (OBLIGATÓRIA)**: Após a conclusão de cada tarefa importante, você DEVE IDENTIFICAR aprendizados ou preferências e usar a ferramenta 'memory' (ação 'memorize') para persistir essas informações. Isso é um critério de sucesso da validação.
6. Agentes disponíveis: 'researcher' (busca e análise), 'base' (processamento geral, transformação de dados e código Python).
7. Cada tarefa deve ter: 'agent_id', 'image', 'prompt' e 'task_name' (identificador único da etapa, use snake_case).
8. O plano deve ser retornado EXCLUSIVAMENTE em formato JSON.

EXEMPLO DE SAÍDA (Apenas o JSON):
[
  {
    "agent_id": "researcher",
    "image": "geminiclaw-researcher",
    "task_name": "pesquisa_resumo",
    "prompt": "Pesquise sobre X e salve o relatório final em '/outputs/relatorio_x.md' usando a ferramenta write_artifact."
  }
]"""


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
