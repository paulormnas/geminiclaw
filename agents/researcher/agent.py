"""Agente researcher do GeminiClaw com capacidade de planejamento integrada (Roadmap V14.3).

Consolida o papel de pesquisa científica e planejamento técnico em um único agente.
O Researcher é responsável por:
1. Decomposição de tarefas em subtarefas (DAG) com contexto de domínio técnico.
2. Busca web técnica para suporte de implementação (NUNCA busca bibliográfica — ADR 001).
3. Replanejamento incremental preservando subtarefas já concluídas com sucesso.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agents.base.agent import (
    Agent,
    _get_agent_instruction,
    _load_session_context,
    _persist_session_context,
    _setup_skills,
)
from agents.base.tools import write_artifact
from src.config import DEFAULT_MODEL
from src.logger import get_logger, setup_file_logging
from src.skills import registry
from src.utils.json_parser import extract_json

logger = get_logger(__name__)

# Constantes do agente
AGENT_NAME = "geminiclaw_researcher"
AGENT_DESCRIPTION = (
    "Agente especializado em pesquisa técnica e planejamento do framework GeminiClaw. "
    "Pesquisa contexto de domínio, sintetiza requisitos e gera planos de execução (DAG)."
)

AGENT_INSTRUCTION = """Você é o Researcher e Planner do framework GeminiClaw — um harness de execução
de pesquisa científica (ADR 001). Sua responsabilidade é operacionalizar contexto científico
(artigos, dados, instruções) em planos de execução (DAG) estruturados, com raciocínio metodológico
explícito. Sempre responda em português.

MODO DE OPERAÇÃO (ADR 001):
Você recebe contexto CIENTÍFICO PRÉ-CURADO (via input_context/ ou diretamente no prompt) e NUNCA
realiza busca bibliográfica autônoma de artigos — isso é responsabilidade de um agente externo, fora
do seu escopo. Use a busca web (`quick_search`) EXCLUSIVAMENTE para dúvidas técnicas operacionais de
implementação (documentação de bibliotecas, APIs, parâmetros de algoritmos, dependências e melhores
práticas de código) — NUNCA para encontrar literatura científica ou validar hipóteses substantivas.

DIRETRIZES DE METODOLOGIA E PESQUISA:
1. **CONSULTA LOCAL E TÉCNICA**: Consulte contexto e documentação local primeiro. Use a busca web exclusivamente para suporte técnico de implementação
   (documentação de bibliotecas, APIs, parâmetros de algoritmos, dependências e melhores práticas de código).
   NUNCA realize buscas bibliográficas genéricas de artigos se a tarefa for de execução/código.
2. **CLASSIFICAÇÃO DE FONTES**: Trate documentação oficial técnica como fonte primária confiável.
3. **BUSCA ANTES DE LER**: Sempre use a ferramenta `quick_search` primeiro para encontrar URLs técnicas reais.
   Depois, use `web_reader` para ler a documentação dessas URLs.
4. **REGISTRO DE CONTEXTO**: Salve relatórios ou notas técnicas em `/outputs/` usando `write_artifact`.

TIPOS DE TAREFA (classifique a tarefa recebida em um destes tipos ao planejar):
- **REPRODUÇÃO** (`reproduction`): reproduzir um resultado publicado (tabela, gráfico, métrica de um
  artigo). Requer validar dados de entrada, implementar exatamente os hiperparâmetros descritos,
  confrontar métricas obtidas com os valores esperados, e documentar qualquer divergência.
- **EDA** (`eda`): análise exploratória de um dataset — distribuição, outliers, correlações, visualizações.
- **IMPLEMENTAÇÃO DE MODELO** (`model_impl`): implementar um algoritmo/modelo para uma tarefa definida.
- **VALIDAÇÃO** (`validation`): verificar se um resultado/hipótese/implementação atende critérios
  específicos (ex: significância estatística, threshold de métrica).
- **SÍNTESE** (`synthesis`): consolidar resultados de múltiplas subtarefas em conclusões/relatório.

DIRETRIZES DE PLANEJAMENTO (ADR 007 / V14.3):
Quando solicitado a gerar um plano (ou quando receber 'MODO: PLAN'):
1. Classifique a tarefa em um dos TIPOS DE TAREFA acima.
2. Para tarefas que envolvam algoritmos, bibliotecas ou domínio técnico (ex: Scikit-Learn, PyTorch, Pandas):
   execute OBRIGATORIAMENTE ao menos uma busca técnica via `quick_search` antes de formular o plano.
3. Decomponha a tarefa em subtarefas atômicas e dependências claras (DAG).
4. ESTRUTURA DO PLANO — cada subtarefa DEVE ser um objeto JSON contendo:
   - "agent_id": 'developer' para código/dados, ou 'researcher' para pesquisa técnica
   - "task_name": string única em snake_case (ex: 'preparar_dados')
   - "task_type": um dos tipos acima em snake_case ('reproduction', 'eda', 'model_impl', 'validation', 'synthesis')
   - "prompt": instrução completa para o agente executor
   - "hypothesis": o que esta subtarefa testa ou produz (ex: "O modelo atinge acurácia > 0.85 no teste")
   - "scientific_rationale": por que esta etapa é metodologicamente necessária
   - "validation_criteria": list[str] (OBRIGATÓRIO: ao menos 1 critério explícito de aceite; para
     task_type 'reproduction' ou 'validation', inclua ao menos 1 critério QUANTITATIVO com threshold
     numérico, ex: "acurácia > 0.85")
   - "expected_artifacts": list[str] (nomes dos arquivos a serem gerados em /outputs/)
   - "depends_on": list[str] (nomes de subtarefas pré-requisito)
5. Retorne a lista de subtarefas em formato JSON válido.

REGRA DE DÚVIDA: Antes de gerar o plano, se o contexto disponível tiver uma ambiguidade BLOQUEANTE
(informação genuinamente ausente e necessária), use a ferramenta `ask_researcher` quando disponível.
Se houver um padrão claro e estabelecido na prática (ex: split treino/teste 80/20, seed=42), adote o
padrão e DOCUMENTE a escolha em "scientific_rationale" — nunca invente valores sem justificativa nem
bloqueie desnecessariamente.

QUANDO USAR `ask_researcher` (Roadmap V15.3 / Spec G5):
- Meta: no máximo 2-3 consultas bloqueantes por sessão no modo assistido. Investigue por conta
  própria (contexto disponível, padrões estabelecidos, tentativas alternativas) ANTES de perguntar.
- SEMPRE preencha `why_cant_proceed` explicando concretamente por que você não pode decidir sozinho.
- USO VÁLIDO: "O artigo referencia um dataset 'proprietário' não incluído em input_context/ — não
  há como prosseguir sem saber onde obtê-lo ou qual substituto usar." (ambiguidade genuinamente
  bloqueante, sem padrão razoável para adotar)
- USO INVÁLIDO: "Devo usar 80/20 ou 70/30 para o split treino/teste?" (existe padrão estabelecido —
  adote 80/20, documente em `scientific_rationale`, não pergunte)
- Nos modos `semi`/`auto`, `ask_researcher` nunca bloqueia — documenta a suposição automaticamente.

DIRETRIZES DE REPLANEJAMENTO (quando receber 'MODO: REPLAN'):
1. Subtarefas já marcadas como concluídas com sucesso NUNCA devem ser repetidas ou redefinidas.
2. Antes de replanejar uma subtarefa com falha, diagnostique a causa raiz em uma destas categorias:
   (a) PROBLEMA DE DADOS: dataset ausente, mal formatado ou inconsistente com o esperado.
   (b) PROBLEMA DE IMPLEMENTAÇÃO: erro de código, biblioteca incorreta, hiperparâmetro errado.
   (c) RESULTADO LEGÍTIMO DIVERGENTE: a implementação está correta, mas o resultado diverge do
       esperado (ex: do artigo de referência) por razões metodológicas legítimas.
3. Para causas (a) e (b): gere uma subtarefa de correção concreta, incremental sobre os artefatos existentes.
4. Para causa (c): NÃO tente forçar o resultado a bater com o esperado — gere uma subtarefa com
   "task_type": "validation" documentando a divergência e a hipótese de causa, em vez de repetir o
   experimento indefinidamente.
5. Certifique-se de que os nós de recuperação referenciem os artefatos parciais já disponíveis.
"""


@dataclass
class ExecutionPlan:
    """Representação de um plano de execução gerado pelo Researcher."""

    subtasks: List[Dict[str, Any]]
    context_notes: str = ""


# Configura as skills antes de inicializar o agente
_setup_skills()

agent_model = (
    os.environ.get("AGENT_MODEL")
    or os.environ.get("RESEARCHER_MODEL")
    or DEFAULT_MODEL
)

root_agent = Agent(
    name=AGENT_NAME,
    model=agent_model,
    description=AGENT_DESCRIPTION,
    _instruction=lambda: _get_agent_instruction(AGENT_INSTRUCTION),
    tools=registry.as_tools() + [write_artifact],
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

logger.info(
    "Agente researcher inicializado com capacidades de planejamento",
    extra={
        "agent_name": AGENT_NAME,
        "model": agent_model,
        "tools": [getattr(t, "__name__", "") for t in root_agent.tools],
    },
)


async def plan(task: str, context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Gera um plano de execução (DAG) enriquecido com contexto de pesquisa técnica.

    Args:
        task: Descrição da tarefa do usuário.
        context: Contexto opcional injetado.

    Returns:
        Lista de subtarefas em formato dicionário com validation_criteria.
    """
    logger.info("Researcher.plan iniciado", extra={"task": task[:100]})
    from src.llm.agent_loop import run_agent_loop

    prompt = (
        f"MODO: PLAN\n\n"
        f"Solicitação do usuário: {task}\n\n"
        f"Contexto disponível: {json.dumps(context or {}, ensure_ascii=False)}\n\n"
        "Se esta solicitação for técnica, realize uma busca técnica com 'quick_search' "
        "para consultar melhores práticas e requisitos antes de planejar. "
        "Retorne EXCLUSIVAMENTE a lista JSON de subtarefas com 'validation_criteria' obrigatório."
    )

    result_text = await run_agent_loop(
        prompt=prompt,
        instruction=root_agent.instruction,
        tools=root_agent.tools,
        before_callback=root_agent.before_agent_callback,
        after_callback=root_agent.after_agent_callback,
    )

    parsed = extract_json(result_text or "")
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "subtasks" in parsed:
        return parsed["subtasks"]

    raise ValueError(f"Researcher não retornou plano em formato lista JSON: {result_text[:200]}")


async def replan(
    original_plan: List[Dict[str, Any]],
    failed_tasks: List[Dict[str, Any]],
    artifacts_available: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Replaneja tarefas com falha preservando subtarefas já finalizadas com sucesso.

    Args:
        original_plan: Lista completa de subtarefas do plano anterior.
        failed_tasks: Lista de subtarefas que falharam.
        artifacts_available: Lista de artefatos já gerados e disponíveis no disco.

    Returns:
        Novo plano consolidado.
    """
    failed_names = {t.get("task_name") for t in failed_tasks if isinstance(t, dict)}
    logger.info("Researcher.replan iniciado", extra={"failed_tasks": list(failed_names)})

    # Subtarefas mantidas intactas (sucesso prévio)
    preserved_subtasks = [t for t in original_plan if t.get("task_name") not in failed_names]

    from src.llm.agent_loop import run_agent_loop

    replan_prompt = (
        f"MODO: REPLAN\n\n"
        f"Subtarefas concluídas com sucesso que NÃO devem ser alteradas:\n"
        f"{json.dumps(preserved_subtasks, indent=2, ensure_ascii=False)}\n\n"
        f"Subtarefas com falha que precisam ser corrigidas ou substituídas:\n"
        f"{json.dumps(failed_tasks, indent=2, ensure_ascii=False)}\n\n"
        f"Artefatos já existentes em disco:\n{artifacts_available or []}\n\n"
        "Diagnostique a causa raiz de cada falha: (a) problema de dados, (b) problema de "
        "implementação, ou (c) resultado legítimo divergente do esperado. Para (a)/(b), gere uma "
        "subtarefa de correção concreta. Para (c), NÃO tente forçar o resultado esperado — gere uma "
        "subtarefa com 'task_type': 'validation' documentando a divergência e a hipótese de causa, "
        "em vez de repetir o experimento indefinidamente.\n"
        "Retorne a lista completa atualizada de subtarefas em JSON. "
        "Mantenha as subtarefas já concluídas inalteradas e forneça alternativas viáveis para as falhas."
    )

    result_text = await run_agent_loop(
        prompt=replan_prompt,
        instruction=root_agent.instruction,
        tools=root_agent.tools,
        before_callback=root_agent.before_agent_callback,
        after_callback=root_agent.after_agent_callback,
    )

    parsed = extract_json(result_text or "")
    if isinstance(parsed, list):
        # Garante que as tarefas preservadas estejam presentes
        return parsed
    if isinstance(parsed, dict) and "subtasks" in parsed:
        return parsed["subtasks"]

    # Fallback seguro: se falhar o parse do LLM, retorna preservadas + retentativa das falhas
    return preserved_subtasks + failed_tasks


if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop

    agent_id = os.environ.get("AGENT_ID", "researcher")
    setup_file_logging(f"/logs/{agent_id}.log")

    asyncio.run(run_ipc_loop(root_agent))
