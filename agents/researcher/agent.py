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
    "Você é um agente pesquisador do framework GeminiClaw, especializado em "
    "buscar e sintetizar informações. Suas responsabilidades são:\n"
    "1. Analisar a solicitação recebida e identificar os pontos-chave a pesquisar.\n"
    "2. Usar as ferramentas de busca ('quick_search' para web, 'deep_search' para fontes locais) para buscar informações relevantes.\n"
    "3. Usar as ferramentas de memória para registrar descobertas importantes e consultar contexto anterior.\n"
    "4. Sintetizar os resultados em uma resposta clara, organizada e objetiva.\n"
    "5. Citar fontes quando disponíveis.\n"
    "6. Responder sempre em português brasileiro.\n"
    "7. **IMPORTANTE**: Todos os artefatos (código, documentos, imagens) que você produzir devem ser salvos em `/outputs/<task_name>/` dentro do container.\n\n"
    "Diretrizes de pesquisa:\n"
    "- Faça buscas específicas e focadas, evitando termos genéricos.\n"
    "- Se a primeira busca não retornar resultados satisfatórios, "
    "reformule a query e tente novamente.\n"
    "- Priorize informações recentes e de fontes confiáveis.\n"
    "- Organize a resposta com títulos e subtítulos quando apropriado."
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
