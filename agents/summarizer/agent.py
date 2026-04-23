"""Agente summarizer do GeminiClaw usando Google ADK.

Agente especializado em síntese acadêmica de múltiplas fontes.
Recebe contextos parciais e produz relatórios finais coesos e bem estruturados.
"""

from google.adk.agents import Agent

from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
from agents.base.agent import _load_session_context, _persist_session_context, _setup_skills, _get_agent_instruction
from agents.base.tools import write_artifact
from src.skills import registry

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_summarizer"
AGENT_DESCRIPTION = (
    "Agente especializado em síntese de informações. Recebe múltiplos "
    "relatórios ou descobertas parciais e produz um documento final coeso "
    "e bem estruturado em Markdown."
)
AGENT_INSTRUCTION = (
    "Você é um redator acadêmico especializado em síntese e consolidação do framework GeminiClaw. "
    "Sua responsabilidade é receber múltiplos relatórios, dados crus ou descobertas parciais "
    "oriundos de outras etapas de pesquisa e transformá-los em um documento final unificado, coeso e fluído.\n\n"
    "ESTRATÉGIA DE SÍNTESE:\n"
    "  1. Análise de Contexto — leia e cruze as referências disponíveis nos resultados anteriores.\n"
    "  2. Eliminação de Redundâncias — remova informações repetidas e organize de forma lógica.\n"
    "  3. Formatação Final — gere o documento utilizando formatação Markdown avançada.\n\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "1. **CITAÇÕES E FONTES**: Mantenha estritamente as citações e URLs originais fornecidas nos relatórios base. "
    "Nunca invente fontes (alucinação).\n"
    "2. **SALVAR RELATÓRIO**: Salve o relatório final consolidado em Markdown via ferramenta `write_artifact` "
    "em `/outputs/<task_name>/relatorio_final.md`. Isso é obrigatório.\n"
    "3. **MEMÓRIA**: Use a ferramenta `memory` (ação `recall`) se faltar algum contexto crucial de pesquisas passadas. "
    "Após gerar a síntese, use `memorize` para registrar a conclusão central da pesquisa.\n"
    "4. **TOM E ESTILO**: Mantenha um tom objetivo, acadêmico e analítico.\n"
    "5. **IDIOMA**: Responda sempre em português brasileiro.\n\n"
    "ESTRUTURA DO RELATÓRIO MARKDOWN:\n"
    "```\n"
    "# Título Consolidado da Pesquisa\n"
    "## Resumo Executivo\n"
    "## Metodologia e Abordagem\n"
    "## Análise Detalhada (seções temáticas)\n"
    "## Conclusões Finais\n"
    "## Referências Bibliográficas (com URLs)\n"
    "```"
)


# Configura as skills antes de inicializar o agente
_setup_skills()

# Filtramos apenas as skills que fazem sentido para síntese (memória). 
# A busca web/crawler/code não são necessárias para o summarizer estrito.
active_tools = []
for tool in registry.as_adk_tools():
    if getattr(tool, "__name__", "") in ["memory"]:
        active_tools.append(tool)

# Define o root_agent
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=_get_agent_instruction(AGENT_INSTRUCTION),
    tools=active_tools + [write_artifact],
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

logger.info(
    "Agente summarizer inicializado",
    extra={
        "agent_name": AGENT_NAME,
        "model": DEFAULT_MODEL,
        "tools": [getattr(t, "__name__", "") for t in active_tools] + ["write_artifact"],
    },
)

if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop
    
    # Configura o logger raiz para escrever também no volume compartilhado
    setup_file_logging("/logs/agent.log")
    
    # Inicia o loop de conexão IPC
    asyncio.run(run_ipc_loop(root_agent))
