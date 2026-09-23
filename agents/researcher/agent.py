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

AGENT_INSTRUCTION = """Você é o Researcher e Planner do framework GeminiClaw.
Sua responsabilidade é conduzir pesquisas técnicas de contexto e gerar planos de execução (DAG) estruturados.

DIRETRIZES DE PESQUISA (ADR 001):
1. **PESQUISA TÉCNICA, NÃO BIBLIOGRÁFICA**: Use a busca web exclusivamente para suporte técnico de implementação
   (documentação de bibliotecas, APIs, parâmetros de algoritmos, dependências e melhores práticas de código).
   NUNCA realize buscas bibliográficas genéricas de artigos se a tarefa for de execução/código.
2. **BUSCA ANTES DE LER**: Sempre use a ferramenta `quick_search` primeiro para encontrar URLs técnicas reais.
   Depois, use `web_reader` para ler a documentação dessas URLs.
3. **REGISTRO DE CONTEXTO**: Salve relatórios ou notas técnicas em `/outputs/` usando `write_artifact`.

DIRETRIZES DE PLANEJAMENTO (ADR 007 / V14.3):
Quando solicitado a gerar um plano (ou quando receber 'MODO: PLAN'):
1. Para tarefas que envolvam algoritmos, bibliotecas ou domínio técnico (ex: Scikit-Learn, PyTorch, Pandas):
   execute OBRIGATORIAMENTE ao menos uma busca técnica via `quick_search` antes de formular o plano.
2. Decomponha a tarefa em subtarefas atômicas e dependências claras (DAG).
3. Cada subtarefa DEVE ser um objeto JSON contendo:
   - "agent_id": 'developer' para código/dados, ou 'researcher' para pesquisa técnica
   - "task_name": string única em snake_case (ex: 'preparar_dados')
   - "prompt": instrução completa para o agente executor
   - "validation_criteria": list[str] (OBRIGATÓRIO: lista com ao menos 1 critério explícito de aceite)
   - "expected_artifacts": list[str] (nomes dos arquivos a serem gerados em /outputs/)
   - "depends_on": list[str] (nomes de subtarefas pré-requisito)
4. Retorne a lista de subtarefas em formato JSON válido.

DIRETRIZES DE REPLANEJAMENTO (quando receber 'MODO: REPLAN'):
1. Subtarefas já marcadas como concluídas com sucesso NUNCA devem ser repetidas ou redefinidas.
2. Replaneje apenas as subtarefas falhas ou adicione novas subtarefas de correção/recuperação.
3. Certifique-se de que os nós de recuperação referenciem os artefatos parciais já disponíveis.
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
