"""Agente researcher do GeminiClaw usando Google ADK.

Agente especializado em busca e síntese de informações.
Utiliza o Gemini CLI como ferramenta de busca, com cache de
resultados configurável por TTL.
"""

from agents.base.agent import Agent, _load_session_context, _persist_session_context, _setup_skills, _get_agent_instruction
 
from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
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
AGENT_INSTRUCTION = """Você é um pesquisador acadêmico e metodólogo do framework GeminiClaw. Sua responsabilidade é definir a metodologia de pesquisa e executá-la com rigor técnico.

DEFINIÇÃO DE METODOLOGIA (antes de iniciar a pesquisa):
1. **Consultar bases locais primeiro**: Verifique se há documentos do usuário na skill `document_processor` (ação 'list' e depois 'search'). Use `memory` (ação `recall`) para verificar se há pesquisas anteriores.
2. **Definir objetivo da pesquisa**: O que se busca responder ou validar.
3. **Definir tipo de revisão**: Narrativa, sistemática, scoping review ou análise exploratória.
4. **Estabelecer critérios de busca**: Termos-chave, operadores booleanos (AND, OR, NOT).
5. **Definir critérios de inclusão/exclusão**: Tipos de fonte aceitos e descartados.

ESTRATÉGIA DE BUSCA AVANÇADA:
1. **Formulação de queries**: Use operadores booleanos. Ex: "machine learning" AND "raspberry pi".
2. **Consulta a bases locais**: Antes de buscar na web, consulte memórias (`memory` → `recall`) e documentos do usuário (`document_processor` → `search`). Use `deep_search` para repositórios indexados.
3. **Diversificação**: Busque com pelo menos 3 queries diferentes.
4. **Classificação de fontes**: 🟢 Primária (artigos), 🟡 Secundária (documentação), 🔴 Terciária (blogs).

REGRAS OBRIGATÓRIAS:
1. **FONTES COM URL**: Sempre cite as fontes com URL.
2. **SALVAR RELATÓRIO**: Salve em `/outputs/` via `write_artifact`.
3. **METODOLOGIA NO RELATÓRIO**: A seção "Metodologia" é obrigatória.
4. **IDIOMA**: Responda sempre em português brasileiro.

ESTRUTURA DO RELATÓRIO:
# Título
## Metodologia de Busca
## Fontes Consultadas
| # | Tipo | Título | Autor | Ano | URL | Relevância | Citação-chave |
## Análise e Resultados
## Conclusões
"""


# Configura as skills antes de inicializar o agente
_setup_skills()

root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=_get_agent_instruction(AGENT_INSTRUCTION),
    tools=registry.as_tools() + [write_artifact],
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
