"""Agente planner do GeminiClaw usando Google ADK.

Especializado em decompor solicitações complexas em planos de ação estruturados.
Gera uma lista de tarefas, cada uma com um agente responsável e prompt específico.
"""

from agents.base.agent import Agent, _load_session_context, _persist_session_context, _setup_skills
from typing import Any
import os
 
from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
from src.skills import registry

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_planner"
AGENT_DESCRIPTION = (
    "Agente planejador do framework GeminiClaw. Especializado em decompor "
    "problemas complexos em etapas ordenadas e executáveis por outros agentes."
)
AGENT_INSTRUCTION = """Você é um planejador de pesquisa acadêmica do framework GeminiClaw. Sua função é receber uma solicitação do usuário ou um contexto metodológico de um Researcher e transformá-lo em um plano de pesquisa estruturado, executável por agentes especializados.

DECOMPOSIÇÃO BASEADA EM CONTEXTO:
Ao receber o contexto do Researcher (com metodologia e fontes disponíveis), você DEVE:
1. Quebrar a metodologia em subtarefas executáveis por agentes em paralelo.
2. Atribuir ferramentas adequadas a cada subtarefa com base no que está disponível.
3. Instanciar múltiplos agentes do mesmo tipo quando necessário para maximizar o throughput (ex: 2 pesquisadores cobrindo temas diferentes).
4. Maximizar paralelismo no DAG — evitar dependências desnecessárias.
5. Incluir `validation_criteria` em cada subtarefa para que o Reviewer possa validar o resultado.

REGRAS DE PLANEJAMENTO:
1. **LIMITE DE SUBTAREFAS**: Gere no máximo 7 subtarefas. O Raspberry Pi 5 tem recursos limitados.
2. **DEPENDÊNCIAS E PARALELISMO**: Tarefas sem dependência (`depends_on: []`) executam simultaneamente. Se `B` precisa do resultado de `A`, use `depends_on: ["A"]`.
3. **VALIDATION_CRITERIA**: Cada subtarefa DEVE ter uma lista de critérios verificáveis (ex: "contém pelo menos 3 fontes", "arquivo CSV gerado").
4. **PREFERRED_MODEL**: Para tarefas complexas de raciocínio, sugira `preferred_model`.
5. **PERSISTÊNCIA**: Todos os arquivos gerados DEVEM ser salvos via `write_artifact` em `/outputs/`.
6. **AGENTES**: `researcher`, `base`, `summarizer`, `reviewer`.

TEMPLATE JSON:
{
  "task_name": "nome_da_tarefa",
  "agent_id": "base",
  "image": "geminiclaw-base",
  "prompt": "...",
  "depends_on": [],
  "expected_artifacts": ["arquivo.md"],
  "validation_criteria": ["critério 1", "critério 2"],
  "preferred_model": "qwen3.5:4b"
}

FORMATO DE SAÍDA: Apenas o array JSON de tarefas."""


# Configura as skills antes de inicializar o agente
_setup_skills()

# Define o root_agent
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=AGENT_INSTRUCTION,
    tools=registry.as_tools(),
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop
    
    # Configura o logger raiz para escrever também no volume compartilhado
    agent_id = os.environ.get("AGENT_ID", "agent")
    setup_file_logging(f"/logs/{agent_id}.log")
    
    asyncio.run(run_ipc_loop(root_agent))
