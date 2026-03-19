"""Agente researcher do GeminiClaw usando Google ADK.

Agente especializado em busca e síntese de informações.
Utiliza o Gemini CLI como ferramenta de busca, com cache de
resultados configurável por TTL.
"""

from google.adk.agents import Agent

from src.logger import get_logger
from src.config import DEFAULT_MODEL
from agents.base.agent import _load_session_context, _persist_session_context
from agents.researcher.tools import search

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
    "2. Usar a ferramenta 'search' para buscar informações relevantes.\n"
    "3. Sintetizar os resultados em uma resposta clara, organizada e objetiva.\n"
    "4. Citar fontes quando disponíveis.\n"
    "5. Responder sempre em português brasileiro.\n"
    "6. Se não encontrar informações suficientes, diga claramente o que "
    "foi encontrado e o que ficou faltando.\n\n"
    "Diretrizes de pesquisa:\n"
    "- Faça buscas específicas e focadas, evitando termos genéricos.\n"
    "- Se a primeira busca não retornar resultados satisfatórios, "
    "reformule a query e tente novamente.\n"
    "- Priorize informações recentes e de fontes confiáveis.\n"
    "- Organize a resposta com títulos e subtítulos quando apropriado."
)

# Define o root_agent — ponto de entrada obrigatório para o ADK
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=AGENT_INSTRUCTION,
    tools=[search],
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
