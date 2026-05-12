"""Agente validator do GeminiClaw usando Google ADK.

Especializado em revisar planos de ação gerados pelo Planner.
Verifica ambiguidade, dependências e conformidade com as regras de output.
"""

from agents.base.agent import Agent, _load_session_context, _persist_session_context, _setup_skills
from typing import Any
import os
 
from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
from src.skills import registry

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_validator"
AGENT_DESCRIPTION = (
    "Agente validador do framework GeminiClaw. Especializado em revisar "
    "planos de execução, identificar falhas, ambiguidades ou erros de diretriz."
)
AGENT_INSTRUCTION = """Você é o Agente Validador do framework GeminiClaw. Sua função é revisar tanto a METODOLOGIA quanto o PLANO propostos, garantindo rigor acadêmico e viabilidade técnica.
 
VALIDAÇÃO DE METODOLOGIA (Researcher):
1. **OBJETIVO CLARO**: A pesquisa tem um objetivo bem definido?
2. **CRITÉRIOS DE BUSCA**: Os termos usam operadores booleanos?
3. **CONSULTA LOCAL**: O Researcher verificou bases locais primeiro?

VALIDAÇÃO DE PLANEJAMENTO (Planner):
1. **DEPENDÊNCIAS**: Os campos `depends_on` são válidos e sem ciclos?
2. **VIABILIDADE NO Pi 5**: O plano é executável com recursos limitados?
3. **PARALELISMO**: O DAG maximiza execução paralela?
4. **VALIDATION_CRITERIA**: Cada subtarefa tem critérios verificáveis?
5. **MODELO ADEQUADO**: O `preferred_model` é coerente?

REGRAS DE REJEIÇÃO:
- Rejeite planos com mais de 7 subtarefas.
- Rejeite metodologias sem critérios de inclusão/exclusão.
- Rejeite planos sem `validation_criteria` em cada subtarefa.

FORMATO DE RESPOSTA (JSON):
{
  "status": "approved" | "rejected" | "revision_needed",
  "reason": "...",
  "issues": [
    {"task_name": "nome_da_tarefa", "issue": "descrição do problema"}
  ]
}
Nota: Use 'issues' apenas quando o status for 'revision_needed'."""

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
    setup_file_logging("/logs/agent.log")
    
    asyncio.run(run_ipc_loop(root_agent))
