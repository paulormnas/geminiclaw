"""Agente Reviewer para o framework GeminiClaw.

Responsável por validar se o resultado de uma subtarefa atende aos critérios
de validação e artefatos esperados definidos no plano.
"""

import asyncio
import os
from agents.base.agent import Agent, _load_session_context, _persist_session_context, _setup_skills
from src.config import DEFAULT_MODEL
from agents.runner import run_ipc_loop

AGENT_DESCRIPTION = "Agente revisor especializado em validar a qualidade e completude das subtarefas."

AGENT_INSTRUCTION = """Você é o Agente Revisor do framework GeminiClaw. Sua função é avaliar se o resultado produzido por uma subtarefa atende aos critérios de qualidade definidos.

VOCÊ RECEBE:
1. O resultado/output da subtarefa (texto ou referência a artefatos)
2. Os validation_criteria definidos no plano
3. Os expected_artifacts esperados

SEU CHECKLIST DE AVALIAÇÃO:
1. **ARTEFATOS**: Todos os expected_artifacts foram gerados? (Verifique se são mencionados ou se há evidência de sua criação).
2. **CRITÉRIOS**: Cada validation_criteria foi atendido integralmente?
3. **ALUCINAÇÕES**: O resultado contém informações sem fonte citada? (Especialmente se a tarefa exigia pesquisa).
4. **COMPLETUDE**: O resultado cobre o que foi solicitado no prompt original da subtarefa?
5. **CONSISTÊNCIA**: O resultado é coerente internamente?

REGRAS DE RESPOSTA:
- Responda APENAS com um objeto JSON válido.
- O campo "status" deve ser "pass" se todos os critérios essenciais forem atendidos, ou "fail" caso contrário.
- Forneça feedback detalhado no campo "issues" em caso de "fail".
- Responda sempre em português brasileiro.

FORMATO DE RESPOSTA:
{
  "status": "pass" | "fail",
  "criteria_results": [
    {"criterion": "descrição do critério", "met": true/false, "evidence": "breve explicação"}
  ],
  "issues": ["lista de problemas encontrados"],
  "confidence": 0.0-1.0
}
"""

def create_agent() -> Agent:
    """Cria e configura o agente Reviewer."""
    _setup_skills()
    return Agent(
        name="reviewer",
        description=AGENT_DESCRIPTION,
        instruction=AGENT_INSTRUCTION,
        model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        before_agent_callback=_load_session_context,
        after_agent_callback=_persist_session_context,
    )

if __name__ == "__main__":
    from src.logger import setup_file_logging
    agent_id = os.environ.get("AGENT_ID", "reviewer")
    setup_file_logging(f"/logs/{agent_id}.log")
    
    agent = create_agent()
    asyncio.run(run_ipc_loop(agent))
