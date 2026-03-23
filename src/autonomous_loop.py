"""Loop de execução autônoma para agentes GeminiClaw.

Implementa a lógica de triage (simples vs complexo), 
decomposição de tarefas em subtarefas e loop de retentativas.
"""

import os
import json
import asyncio
from typing import Any, TYPE_CHECKING, List, Dict
from src.logger import get_logger

if TYPE_CHECKING:
    from src.orchestrator import Orchestrator, AgentTask, AgentResult, OrchestratorResult

logger = get_logger(__name__)

class AutonomousLoop:
    """Implementa o ciclo de vida autônomo da execução de uma tarefa."""

    def __init__(self, orchestrator: "Orchestrator"):
        """Inicializa o loop com uma instância do orquestrador.
        
        Args:
            orchestrator: Orquestrador que fornece as capacidades de execução.
        """
        self.orchestrator = orchestrator
        self.max_retries = int(os.environ.get("MAX_RETRY_PER_SUBTASK", "3"))
        self.max_subtasks = int(os.environ.get("MAX_SUBTASKS_PER_TASK", "10"))

    async def run(self, prompt: str, master_session_id: str) -> "OrchestratorResult":
        """Executa a tarefa utilizando o loop autônomo.
        
        Args:
            prompt: Solicitação original do usuário.
            master_session_id: ID da sessão mestra para coordenação.
            
        Returns:
            OrchestratorResult consolidado.
        """
        logger.info(
            "Iniciando loop autônomo", 
            extra={"prompt_preview": prompt[:100], "master_session_id": master_session_id}
        )
        
        # 1. Triage: Simples vs Complexo
        is_complex = await self._is_complex_triage(prompt, master_session_id)
        
        if not is_complex:
            logger.info("Tarefa identificada como SIMPLES — Usando Agente Base diretamente")
            return await self._run_simple_path(prompt, master_session_id)
            
        logger.info("Tarefa identificada como COMPLEXA — Iniciando Planejamento e Decomposição")
        return await self._run_complex_path(prompt, master_session_id)

    async def _is_complex_triage(self, prompt: str, master_session_id: str) -> bool:
        """Avalia se a tarefa exige planejamento ou pode ser resolvida pelo agente base.
        
        Utiliza o Planner agent para tomar a decisão de triage.
        """
        # Importações locais para evitar recursão circular
        from src.orchestrator import AgentTask, AGENT_REGISTRY
        
        triage_prompt = (
            f"Analise a solicitação do usuário abaixo e determine se ela é 'SIMPLE' ou 'COMPLEX'.\n\n"
            f"**Critérios para SIMPLE**:\n"
            f"- Pode ser respondida diretamente com conhecimento geral.\n"
            f"- Exige apenas um passo ou uma pergunta simples.\n"
            f"- Não exige busca profunda, execução de código complexa ou múltiplos agentes.\n\n"
            f"**Critérios para COMPLEX**:\n"
            f"- Exige pesquisa em bibliografias ou internet (Researcher).\n"
            f"- Exige criação e execução de scripts Python para análise (Coder).\n"
            f"- Exige decomposição em múltiplos passos lógicos.\n"
            f"- Exige validação de resultados intermediários.\n\n"
            f"**SOLICITAÇÃO**: {prompt}\n\n"
            f"Responda APENAS 'SIMPLE' ou 'COMPLEX'."
        )
        
        task = AgentTask(
            agent_id="planner",
            image=AGENT_REGISTRY.get("planner", "geminiclaw-planner"),
            prompt=triage_prompt
        )
        
        # Executa o triage
        result = await self.orchestrator._execute_agent(task, master_session_id)
        
        if result.status == "success":
            response_text = result.response.get("text", "").upper()
            if "COMPLEX" in response_text:
                return True
            if "SIMPLE" in response_text:
                return False
                
        # Em caso de incerteza ou erro, tratamos como complexo (padrão conservador)
        logger.warning(
            "Falha ou ambiguidade no triage, assumindo COMPLEX", 
            extra={"status": result.status, "response": result.response.get("text", "")}
        )
        return True

    async def _run_simple_path(self, prompt: str, master_session_id: str) -> "OrchestratorResult":
        """Executa a tarefa via caminho simplificado (apenas agente base)."""
        from src.orchestrator import AgentTask, AGENT_REGISTRY, OrchestratorResult
        
        task = AgentTask(
            agent_id="base",
            image=AGENT_REGISTRY.get("base", "geminiclaw-base"),
            prompt=prompt
        )
        
        result = await self.orchestrator._execute_agent(task, master_session_id)
        
        succeeded = 1 if result.status == "success" else 0
        failed = 1 - succeeded
        
        return OrchestratorResult(
            results=[result],
            total=1,
            succeeded=succeeded,
            failed=failed,
            artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id)
        )

    async def _run_complex_path(self, prompt: str, master_session_id: str) -> "OrchestratorResult":
        """Executa a tarefa via caminho complexo (Planner -> Loop de Subtarefas)."""
        from src.orchestrator import AgentTask, OrchestratorResult, AGENT_REGISTRY, AgentResult
        
        # 1. Planejamento (S7.3): Decompõe a tarefa
        tasks = await self.orchestrator._run_planning_loop(prompt, master_session_id)
        
        if not tasks:
            logger.error("Falha ao gerar plano de execução")
            return OrchestratorResult(results=[], total=0, succeeded=0, failed=0)

        logger.info(f"Plano gerado com {len(tasks)} subtarefas")
        
        if len(tasks) > self.max_subtasks:
            logger.warning(f"Número de subtarefas ({len(tasks)}) excede o limite {self.max_subtasks}")
            tasks = tasks[:self.max_subtasks]

        final_results: List[AgentResult] = []
        
        # 2. Loop de Execução Autônoma (S7.4)
        for i, task in enumerate(tasks):
            logger.info(f"Processando subtarefa {i+1}/{len(tasks)}: {task.agent_id}")
            
            # TODO (Opcional): Consultar memória de curto prazo (S7.4.a) 
            # Isso já é feito parcialmente via master_session no orquestrador
            
            success = False
            last_result = None
            
            # Retry Loop (S7.4.d)
            for attempt in range(self.max_retries):
                logger.info(f"Executando tentativa {attempt+1}/{self.max_retries} para {task.agent_id}")
                
                # Executa a skill/agente
                result = await self.orchestrator._execute_agent(task, master_session_id)
                last_result = result
                
                # Avaliação do resultado (simplificada por enquanto)
                if result.status == "success":
                    # TODO: Futuramente injetar um passo de "Self-Correction" aqui
                    success = True
                    break
                else:
                    logger.warning(f"Tentativa {attempt+1} falhou", extra={"error": result.error})
                    # Delay básico de retry
                    await asyncio.sleep(1)
            
            if last_result:
                final_results.append(last_result)
            
            if not success:
                logger.error(f"Subtarefa {i+1} ({task.agent_id}) falhou após todas as tentativas")
                # Interrompe o loop se uma etapa crítica falhar?
                # Por agora, vamos continuar para tentar as demais etapas, 
                # mas o resultado final refletirá a falha.

        succeeded = sum(1 for r in final_results if r.status == "success")
        failed = len(final_results) - succeeded
        
        # 3. Finalização (S7.5): Promove descobertas importantes
        if succeeded > 0:
            await self._promote_findings(prompt, master_session_id)

        return OrchestratorResult(
            results=final_results,
            total=len(tasks),
            succeeded=succeeded,
            failed=failed,
            artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id)
        )

    async def _promote_findings(self, prompt: str, master_session_id: str) -> None:
        """Identifica e promove descobertas importantes para a memória de longo prazo (S7.5.a)."""
        from src.orchestrator import AgentTask, AGENT_REGISTRY
        
        logger.info("Promovendo descobertas importantes para memória de longo prazo")
        
        promotion_prompt = (
            f"A tarefa principal foi: '{prompt}'.\n"
            f"Analise o que foi realizado nesta sessão e identifique aprendizados, "
            f"preferências do usuário ou fatos importantes que devem ser persistidos "
            f"na memória de longo prazo para futuras interações.\n"
            f"Use a ferramenta 'memory' com a ação 'memorize' (ou 'remember_forever') "
            f"para registrar cada item relevante."
        )
        
        task = AgentTask(
            agent_id="planner", # O Planner é ideal para sintetizar e decidir o que é importante
            image=AGENT_REGISTRY.get("planner", "geminiclaw-planner"),
            prompt=promotion_prompt
        )
        
        # Executa sem esperar retorno detalhado, apenas para permitir que o agente memorize
        await self.orchestrator._execute_agent(task, master_session_id)
