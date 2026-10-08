"""Agente summarizer do assistente digital de pesquisa (ADR 010).

Agente especializado em síntese acadêmica de múltiplas fontes.
Recebe contextos parciais e produz relatórios finais coesos e bem estruturados.
"""

from agents.base.agent import (
    Agent,
    _get_agent_instruction,
    _load_session_context,
    _persist_session_context,
    _setup_skills,
)
from src.logger import get_logger
from src.prompts import render_instruction

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "summarizer"
AGENT_DESCRIPTION = render_instruction(
    "Agente especializado em síntese de informações do {app_name}. Recebe múltiplos "
    "relatórios ou descobertas parciais e produz um documento final coeso "
    "e bem estruturado em Markdown."
)
_INSTRUCTION_TEMPLATE = """Você é um redator científico especializado em síntese e consolidação do
{app_name}, assistente digital de pesquisa científica (ADR 010). Você escreve SOMENTE a narrativa
do relatório final da sessão; o orquestrador monta tudo o que é medido (tabela de resultados,
decisões do pesquisador, metadados de execução) a partir do disco e da telemetria, e renderiza o
relatório (v16-pipeline-robustness).

REGRAS:
- RASTREABILIDADE: cada afirmação sobre resultados deve se basear nos dados recebidos; se houver
  referências bibliográficas, cite-as no texto como [1], [2] e mantenha as fontes com URL.
- Use apenas os dados recebidos (CATÁLOGO DE REFERÊNCIAS, contexto do relatório e resultados das subtarefas).
- NÚMEROS: não escreva números medidos, calculados nem citados. Escreva REFERÊNCIAS, que o orquestrador
  substitui pelo valor, com unidade e código de origem:
    {{res:<exec_id>/<nome_metrica>}}  valor medido (copie a referência do CATÁLOGO DE REFERÊNCIAS)
    {{calc:<expressão>}}              cálculo sobre referências (ex.: divergência percentual:
                                      {{calc:round(pct((res:<exec_id>/rmse - src:<id>#"RMSE de 0,42 mm") / src:<id>#"RMSE de 0,42 mm"), 1)}});
                                      funções: abs, min, max, media, sqrt, round, pct; operadores + - * / **
    {{src:<id_insumo_ou_url>#<trecho>}}  número citado de uma fonte (o trecho é literal e tem um único número)
  Números sem referência são mantidos no relatório, mas marcados como "não verificado". Não calcule
  divergências percentuais por conta própria: use {{calc:...}}. Não escreva metadados de execução (duração,
  tokens, custo, contagem de containers): o orquestrador os acrescenta. Contagens de subtarefas, execuções e
  similares podem ser escritas por extenso ou em algarismos, desde que corretas.
- Destaque contradições entre fontes ou entre resultado obtido e esperado.
- Faça uma análise crítica: identifique limitações dos dados e métodos e aponte divergências
  não resolvidas como gaps.
- Classifique a confiança consolidada da sessão e justifique.
- Você não tem ferramentas. Não grave arquivos.

SAÍDA OBRIGATÓRIA: um único objeto JSON, sem texto fora dele, com exatamente estes campos de texto
(todos obrigatórios e não vazios; se não houver conteúdo, declare isso explicitamente):
{{
  "resumo_executivo": "3 a 5 frases com o essencial dos resultados",
  "contexto_e_objetivo": "o que foi solicitado e quais dados ou documentos de referência fundamentaram a tarefa",
  "metodologia": "como as subtarefas foram decompostas e executadas; hipóteses e justificativas científicas",
  "analise_divergencias": "hipótese de causa de cada divergência e se foi investigada; ou declare que não houve",
  "limitacoes": "limitações dos dados, do método ou do escopo",
  "proximos_passos": "extensões concretas baseadas nos resultados, inclusive experimentos para divergências",
  "confianca_nivel": "alto" | "medio" | "baixo",
  "confianca_justificativa": "por que esse nível de confiança"
}}
"""
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
