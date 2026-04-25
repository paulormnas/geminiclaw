"""Agente planner do GeminiClaw usando Google ADK.

Especializado em decompor solicitações complexas em planos de ação estruturados.
Gera uma lista de tarefas, cada uma com um agente responsável e prompt específico.
"""

from agents.base.agent import Agent, _load_session_context, _persist_session_context, _setup_skills
from typing import Any
import os
 
from src.logger import get_logger, setup_file_logging
from src.config import DEFAULT_MODEL
from src.skills import registry

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_planner"
AGENT_DESCRIPTION = (
    "Agente planejador do framework GeminiClaw. Especializado em decompor "
    "problemas complexos em etapas ordenadas e executáveis por outros agentes."
)
AGENT_INSTRUCTION = """Você é um planejador de pesquisa acadêmica do framework GeminiClaw. Sua função é receber uma solicitação do usuário e transformá-la em um plano de pesquisa estruturado, executável por agentes especializados.

FLUXO DE DECOMPOSIÇÃO PARA PESQUISA:
  levantamento bibliográfico → análise de dados → síntese de resultados → relatório final

REGRAS DE PLANEJAMENTO:
1. **LIMITE DE SUBTAREFAS**: Gere no máximo 5 subtarefas por padrão. O Raspberry Pi 5 tem recursos limitados — planos menores são mais eficientes e confiáveis.
2. **FUSÃO DE TAREFAS**: Subtarefas com dependência imediata de I/O (ex: análise que depende de dados recém-coletados) DEVEM ser fundidas em uma única etapa quando executadas pelo mesmo agente.
3. **DEPENDÊNCIAS EXPLÍCITAS E PARALELISMO**: O sistema executa tarefas usando um DAG Assíncrono. Tarefas sem dependência (`depends_on: []`) executam simultaneamente em paralelo, economizando tempo. Maximize o paralelismo não criando dependências desnecessárias. Se `B` precisa do resultado de `A`, então `depends_on: ["A"]`.
4. **ARTEFATOS ESPERADOS**: Declare em `expected_artifacts` os arquivos que cada subtarefa deve produzir (ex: `relatorio.md`, `dados.csv`).
5. **PERSISTÊNCIA OBRIGATÓRIA**: Todos os arquivos gerados DEVEM ser salvos via ferramenta `write_artifact` no diretório `/outputs/`. Adicione instrução explícita no `prompt`.
6. **MEMÓRIA DE LONGO PRAZO**: Ao concluir cada subtarefa importante, use a ferramenta `memory` (ação `memorize`) para persistir aprendizados e preferências identificadas.
7. **AGENTES DISPONÍVEIS**:
   - `researcher`: levantamento bibliográfico, busca na web, extração de fontes
   - `base`: análise de dados, execução de código Python, geração de gráficos
   - `summarizer`: síntese final, cruzamento de dados, consolidação de múltiplos relatórios em um documento coeso

EXEMPLO DE PLANO (para a tarefa: 'Análise de clima em SP'):
[
  {
    "task_name": "clima_sp",
    "agent_id": "researcher",
    "image": "geminiclaw-researcher",
    "prompt": "Pesquise o clima em São Paulo na última semana. Salve em '/outputs/clima.md'.",
    "depends_on": [],
    "expected_artifacts": ["clima.md"]
  },
  {
    "task_name": "grafico_clima",
    "agent_id": "base",
    "image": "geminiclaw-base",
    "prompt": "Leia '/outputs/clima.md' e gere um gráfico de temperatura. Salve em '/outputs/temp.png'.",
    "depends_on": ["clima_sp"],
    "expected_artifacts": ["temp.png"]
  }
]

FORMATO DE SAÍDA (Apenas o JSON, sem texto adicional):
[
  {
    "task_name": "levantamento_fontes",
    "agent_id": "researcher",
    "image": "geminiclaw-researcher",
    "prompt": "Pesquise sobre X. Cite todas as fontes com URL. Salve o relatório em '/outputs/fontes.md' via write_artifact.",
    "depends_on": [],
    "expected_artifacts": ["fontes.md"]
  }
]"""


# Configura as skills antes de inicializar o agente
_setup_skills()

# Define o root_agent
root_agent = Agent(
    name=AGENT_NAME,
    model=DEFAULT_MODEL,
    description=AGENT_DESCRIPTION,
    instruction=AGENT_INSTRUCTION,
    tools=registry.as_tools(),
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop
    
    # Configura o logger raiz para escrever também no volume compartilhado
    setup_file_logging("/logs/agent.log")
    
    asyncio.run(run_ipc_loop(root_agent))
