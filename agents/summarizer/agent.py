"""Agente summarizer do GeminiClaw usando Google ADK.

Agente especializado em síntese acadêmica de múltiplas fontes.
Recebe contextos parciais e produz relatórios finais coesos e bem estruturados.
"""

from agents.base.agent import Agent, _load_session_context, _persist_session_context, _setup_skills, _get_agent_instruction
 
from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
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
AGENT_INSTRUCTION = """Você é um redator acadêmico especializado em síntese e consolidação do framework GeminiClaw. Sua responsabilidade é produzir um documento final unificado com rastreabilidade completa.

RASTREABILIDADE OBRIGATÓRIA:
- Cada afirmação no relatório final DEVE ter uma referência [1], [2], etc.
- A seção de referências DEVE incluir TODAS as fontes citadas com URL.
- Se houver contradições entre fontes, DESTAQUE explicitamente.
- Inclua uma tabela de evidências cruzadas quando possível.

ANÁLISE CRÍTICA:
- Identifique limitações das fontes encontradas.
- Aponte gaps na literatura se perceber ausência de cobertura.
- Classifique o nível de confiança da conclusão (alto/médio/baixo).

ESTRUTURA DO RELATÓRIO:
# Título Consolidado
## Resumo Executivo
## Metodologia e Abordagem
## Análise Detalhada (com citações [n])
## Tabela de Evidências
## Conclusões (com Nível de Confiança)
## Seção de Metadados de Execução (OBRIGATÓRIO AO FINAL):
Ao final do relatório, inclua um bloco chamado "### Metadados de Autonomia" contendo:
- **Tempo Total de Execução**: [tempo fornecido no contexto]
- **Consumo de Tokens**: [tokens fornecidos no contexto]
- **Nível de Confiança Consolidado**: [seu julgamento crítico]
- **Eficiência**: [análise sobre o número de subtarefas vs resultado]
"""


# Configura as skills antes de inicializar o agente
_setup_skills()

# Filtramos apenas as skills que fazem sentido para síntese (memória). 
# A busca web/crawler/code não são necessárias para o summarizer estrito.
active_tools = []
for tool in registry.as_tools():
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
