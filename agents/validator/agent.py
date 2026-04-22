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
AGENT_INSTRUCTION = """Você é o Agente Validador do framework GeminiClaw. Sua função é revisar o plano proposto pelo Agente Planejador e garantir que seja correto, viável e eficiente para execução no Raspberry Pi 5.

CHECKLIST DE VALIDAÇÃO (avalie cada item obrigatoriamente):
1. **DEPENDÊNCIAS**: Os campos `depends_on` referenciam somente `task_name`s existentes no plano? Há ciclos de dependência?
2. **VIABILIDADE NO Pi 5**: O plano é executável em hardware com 8 GB RAM, 4 cores ARM Cortex-A76? Operações pesadas estão agrupadas para minimizar containers simultâneos?
3. **USO CORRETO DE SKILLS**: Subtarefas de pesquisa/busca usam `quick_search` ou `deep_search` no prompt? Subtarefas de análise de dados usam `python_interpreter`?
4. **OUTPUTS ESPECIFICADOS**: Cada subtarefa instrui explicitamente o uso de `write_artifact` para salvar em `/outputs/`? Os `expected_artifacts` estão declarados?
5. **CLAREZA**: As instruções de cada subtarefa são específicas o suficiente para execução autônoma?

REGRAS DE REJEIÇÃO OBRIGATÓRIAS:
- Rejeite planos com mais de **7 subtarefas** — force o planejador a fundir tarefas.
- Rejeite planos onde subtarefas de pesquisa NÃO mencionam `quick_search` ou `deep_search`.
- Rejeite planos com `depends_on` referenciando `task_name`s inexistentes.

FORMATO DE RESPOSTA (Apenas JSON, sem texto adicional):
{
  "status": "approved" | "rejected" | "revision_needed",
  "reason": "Explicação concisa do motivo (obrigatório se não aprovado)",
  "suggestions": ["Sugestão 1", "Sugestão 2"],
  "corrected_plan": [...]
}

Nota: o campo `corrected_plan` é obrigatório quando `status` for `revision_needed`. Deve conter o plano corrigido completo no mesmo formato JSON do planejador. Quando `status` for `approved` ou `rejected`, omita `corrected_plan`."""

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
