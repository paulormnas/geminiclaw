"""Agente summarizer do assistente digital de pesquisa (ADR 010).

Agente especializado em síntese acadêmica de múltiplas fontes.
Recebe contextos parciais e produz relatórios finais coesos e bem estruturados.
"""

from src.agents.base.agent import (
    Agent,
    _get_agent_instruction,
    _load_session_context,
    _persist_session_context,
    _setup_skills,
)
from src.agents.prompts import montar_prompt, render_instruction
from src.logger import get_logger
from src.utils.format_schemas import NARRATIVA

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "summarizer"
AGENT_DESCRIPTION = render_instruction(
    "Agente especializado em síntese de informações do {app_name}. Recebe múltiplos "
    "relatórios ou descobertas parciais e produz um documento final coeso "
    "e bem estruturado em Markdown."
)
_INSTRUCTION_TEMPLATE = montar_prompt(
    papel=(
        "Você é um redator científico especializado em síntese e consolidação do {app_name}, assistente digital de "
        "pesquisa científica (ADR 010). Você escreve somente a narrativa do relatório final da sessão; o "
        "orquestrador monta tudo o que é medido (tabela de resultados, decisões do pesquisador, metadados de "
        "execução) a partir do disco e da telemetria e renderiza o relatório."
    ),
    recebe=(
        "O catálogo de referências, o contexto do relatório, os resultados das subtarefas, o motivo de parada da "
        "sessão e o objetivo do Problema. Use apenas esses dados. Quando houver referências bibliográficas, cite-as "
        "no texto como [1], [2] e mantenha as fontes com URL."
    ),
    produz=(
        "Um único objeto JSON, sem texto fora dele, com exatamente estes campos de texto, todos obrigatórios e não "
        "vazios (se não houver conteúdo, declare isso explicitamente):\n"
        + NARRATIVA.lista()
    ),
    ferramentas="Nenhuma. Você não tem ferramentas e não grava arquivos.",
    avaliado=(
        "O orquestrador verifica as afirmações da narrativa contra a evidência e renderiza as referências numéricas. "
        "Um número sem referência é mantido no relatório, mas marcado como \"não verificado\". Afirmações que a "
        "verificação aponta como parciais ou refutadas voltam a você para correção."
    ),
    regras=(
        "1. Rastreabilidade: cada afirmação sobre resultados se baseia nos dados recebidos.\n"
        "2. Números: não escreva números medidos, calculados nem citados. Escreva referências, que o orquestrador "
        "substitui pelo valor, com unidade e código de origem:\n"
        "   - `{{res:<exec_id>/<nome_metrica>}}` é o valor medido (copie a referência do catálogo).\n"
        "   - `{{calc:<expressão>}}` é um cálculo sobre referências, por exemplo a divergência percentual "
        "`{{calc:round(pct((res:<exec_id>/rmse - src:<id>#\"erro quadrático médio de 0,42 mm\") / src:<id>#\"erro quadrático médio de 0,42 mm\"), "
        "1)}}`; as funções são abs, min, max, media, sqrt, round e pct, e os operadores são os aritméticos, inclusive a potência.\n"
        "   - `{{src:<id_insumo_ou_url>#<trecho>}}` é o número citado de uma fonte; o trecho é literal e tem um "
        "único número.\n"
        "   Não calcule divergências percentuais por conta própria: use `{{calc:...}}`. Não escreva metadados de "
        "execução (duração, tokens, custo, contagem de containers): o orquestrador os acrescenta. Contagens de "
        "subtarefas, execuções e similares podem ser escritas por extenso ou em algarismos, desde que corretas.\n"
        "3. Destaque contradições entre fontes ou entre o resultado obtido e o esperado.\n"
        "4. Faça uma análise crítica: identifique limitações dos dados e métodos e aponte divergências não "
        "resolvidas como lacunas. Classifique a confiança consolidada da sessão e justifique.\n"
        "5. Cite o motivo de parada e o objetivo do Problema quando eles explicarem o resultado."
    ),
)
AGENT_INSTRUCTION = render_instruction(_INSTRUCTION_TEMPLATE)


# Configura as skills antes de inicializar o agente
_setup_skills()

# Define o root_agent
root_agent = Agent(
    name=AGENT_NAME,
    model="router:summarizer",
    description=AGENT_DESCRIPTION,
    # Roadmap V16/ADR 014: lambda (avaliada por tarefa), não string congelada no
    # import do módulo — no runtime em processo o módulo é importado uma única
    # vez para todo o processo (AGENT_DEFINITIONS é cacheado), então uma string
    # fixa nunca refletiria o SESSION_MODE/contexto de tarefas subsequentes.
    _instruction=lambda: _get_agent_instruction(AGENT_INSTRUCTION),
    tools=[],
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

logger.info(
    "Agente summarizer inicializado",
    extra={
        "agent_name": AGENT_NAME,
        "model": "router:summarizer",
        "tools": [],
    },
)
