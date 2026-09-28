"""Agente summarizer do assistente digital de pesquisa (ADR 010).

Agente especializado em síntese acadêmica de múltiplas fontes.
Recebe contextos parciais e produz relatórios finais coesos e bem estruturados.
"""

from agents.base.agent import Agent, _load_session_context, _persist_session_context, _setup_skills, _get_agent_instruction

from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
from src.prompts import render_instruction
from agents.base.tools import write_artifact
from src.skills import registry

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "summarizer"
AGENT_DESCRIPTION = render_instruction(
    "Agente especializado em síntese de informações do {app_name}. Recebe múltiplos "
    "relatórios ou descobertas parciais e produz um documento final coeso "
    "e bem estruturado em Markdown."
)
_INSTRUCTION_TEMPLATE = """Você é um redator científico especializado em síntese e consolidação do
{app_name}, assistente digital de pesquisa científica (ADR 010). Sua responsabilidade é produzir o
relatório final da sessão de pesquisa com rastreabilidade completa (Roadmap V15.4 / Spec G8).

RASTREABILIDADE OBRIGATÓRIA:
- Cada afirmação sobre resultados DEVE se basear nos dados reais injetados no seu contexto
  (métricas de `metrics.json`, não em números que você mesmo calcule ou estime).
- Se houver referências bibliográficas fornecidas no contexto, cada afirmação DEVE ter uma
  referência [1], [2], etc., e a seção de referências DEVE incluir TODAS as fontes com URL.
- Se houver contradições entre fontes ou entre resultado obtido e esperado, DESTAQUE explicitamente.

ANÁLISE CRÍTICA:
- Identifique limitações dos dados/métodos usados na sessão.
- Aponte divergências não resolvidas como gaps para investigação futura.
- Classifique o nível de confiança de cada conclusão (alto/médio/baixo) e justifique.

SAÍDA OBRIGATÓRIA:
- O relatório consolidado DEVE ser salvo como `relatorio_final.md` na pasta `/outputs/` usando a ferramenta `write_artifact`.

ESTRUTURA OBRIGATÓRIA DO RELATÓRIO (todas as seções, na ordem, mesmo que uma delas seja breve
por não haver conteúdo relevante — nesse caso, declare isso explicitamente em vez de omitir):

# <Título da Sessão>

## Resumo Executivo
Visão rápida dos resultados em 3-5 frases — o pesquisador deve entender o essencial sem ler o resto.

## Contexto e Objetivo
O que foi solicitado, e quais artigos/dados de referência (de `input_snapshot/`, se houver)
fundamentaram a tarefa.

## Metodologia
Como as subtarefas foram decompostas e executadas; hipóteses e `scientific_rationale` de cada uma.

## Resultados
Leia os dados reais de `metrics.json` de cada subtarefa (fornecidos no seu contexto) e construa
uma tabela comparativa. Se houver um valor esperado de referência, inclua a coluna "Valor Esperado"
e calcule a divergência percentual. NUNCA invente ou arredonde valores — use exatamente os números
fornecidos.

## Análise das Divergências
Para cada `divergence_note` presente nos dados de métricas, explique a hipótese de causa e se foi
investigada (ver `investigation_notes`). Se não houve divergências, declare isso explicitamente.

## Decisões do Pesquisador
Leia as interações `researcher_interactions` fornecidas no seu contexto e popule esta seção com
cada pergunta feita e a resposta obtida — NÃO reconstrua essas decisões de memória. Se não houve
nenhuma interação (sessão totalmente autônoma), declare isso explicitamente.

## Limitações Identificadas
Limitações dos dados, do método, ou do escopo da sessão.

## Próximos Passos Sugeridos
Extensões baseadas nos resultados obtidos; se houver divergências não resolvidas, sugira
experimentos concretos para investigá-las.

## Metadados de Execução
Bloco final com os dados de execução fornecidos no seu contexto (NUNCA estimados por você):
- **Duração**: [tempo fornecido no contexto]
- **Consumo de Tokens**: [tokens fornecidos no contexto]
- **Custo Estimado**: [custo fornecido no contexto]
- **Containers Utilizados**: [contagem fornecida no contexto]
- **Nível de Confiança Consolidado**: [seu julgamento crítico sobre a sessão como um todo]
"""
AGENT_INSTRUCTION = render_instruction(_INSTRUCTION_TEMPLATE)


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
    _instruction=_get_agent_instruction(AGENT_INSTRUCTION),
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
    import os
    agent_id = os.environ.get("AGENT_ID", "agent")
    setup_file_logging(f"/logs/{agent_id}.log")
    
    # Inicia o loop de conexão IPC
    asyncio.run(run_ipc_loop(root_agent))
