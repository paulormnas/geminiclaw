"""Agente researcher do GeminiClaw usando Google ADK.

Agente especializado em busca e síntese de informações.
Utiliza o Gemini CLI como ferramenta de busca, com cache de
resultados configurável por TTL.
"""

from google.adk.agents import Agent

from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
from agents.base.agent import _load_session_context, _persist_session_context, _setup_skills, _get_agent_instruction
from agents.base.tools import write_artifact
from src.skills import registry

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_researcher"
AGENT_DESCRIPTION = (
    "Agente especializado em busca e síntese de informações. "
    "Capaz de pesquisar temas variados usando o Gemini CLI e "
    "consolidar os resultados em respostas estruturadas."
)
AGENT_INSTRUCTION = (
    "Você é um pesquisador especializado em revisão bibliográfica do framework GeminiClaw. "
    "Sua responsabilidade é levantar, analisar e sintetizar informações de fontes confiáveis "
    "para auxiliar em pesquisas acadêmicas e técnicas.\n\n"
    "ESTRATÉGIA DE PESQUISA:\n"
    "  1. Query inicial — formule uma busca específica sobre o tema central.\n"
    "  2. Refinamento — se os resultados forem insuficientes, reformule a query com termos mais precisos.\n"
    "  3. Síntese — consolide os resultados em um relatório estruturado em Markdown.\n\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "1. **FONTES COM URL**: Sempre cite as fontes utilizadas incluindo a URL completa. "
    "Nunca apresente informação sem indicar a origem.\n"
    "2. **SALVAR RELATÓRIO**: Salve o relatório final em Markdown estruturado via ferramenta `write_artifact` "
    "em `/outputs/<task_name>/relatorio.md`. Isso é obrigatório.\n"
    "3. **BUSCA WEB**: Use `quick_search` para buscas gerais na web. "
    "Use `deep_search` quando domínios indexados estiverem disponíveis e a busca exigir profundidade. "
    "Use `web_reader` para ler o conteúdo completo de páginas web específicas e extrair o texto.\n"
    "4. **MEMÓRIA**: Use a ferramenta `memory` (ação `recall`) para consultar pesquisas anteriores relevantes. "
    "Após descobertas importantes, use `memorize` para persistir para uso futuro.\n"
    "5. **IDIOMA**: Responda sempre em português brasileiro.\n\n"
    "ESTRUTURA DO RELATÓRIO MARKDOWN:\n"
    "```\n"
    "# Título da Pesquisa\n"
    "## Resumo\n"
    "## Fontes Consultadas\n"
    "- [Título da Fonte](URL)\n"
    "## Análise\n"
    "## Conclusões\n"
    "```"
)


# Configura as skills antes de inicializar o agente
_setup_skills()

# Define o root_agent — ponto de entrada obrigatório para o ADK
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=_get_agent_instruction(AGENT_INSTRUCTION),
    tools=registry.as_adk_tools() + [write_artifact],
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

logger.info(
    "Agente researcher inicializado",
    extra={
        "agent_name": AGENT_NAME,
        "model": DEFAULT_MODEL,
        "tools": ["search"],
    },
)

if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop
    
    # Configura o logger raiz para escrever também no volume compartilhado
    setup_file_logging("/logs/agent.log")
    
    # Inicia o loop de conexão IPC quando o container roda este módulo
    asyncio.run(run_ipc_loop(root_agent))
