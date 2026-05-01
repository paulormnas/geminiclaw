"""Loop de execução autônoma para agentes GeminiClaw.

Implementa a lógica de triage (simples vs complexo), 
decomposição de tarefas em subtarefas e loop de retentativas.
"""

import os
import json
import asyncio
from typing import Any, TYPE_CHECKING, List, Dict
from src.logger import get_logger
from src.skills.memory.short_term import ShortTermMemory
from src.triage import TriageClassifier, TriageDecision
from src.health import PiHealthMonitor
from src.telemetry import get_telemetry

if TYPE_CHECKING:
    from src.orchestrator import Orchestrator, AgentTask, AgentResult, OrchestratorResult

logger = get_logger(__name__)

# Roadmap V3 - Etapa V3: limite de chars para injeção de contexto (~2000 tokens)
_CONTEXT_MAX_CHARS = 8_000


class AutonomousLoop:
    """Implementa o ciclo de vida autônomo da execução de uma tarefa."""

    # Roadmap V3 - Etapa V2: memória de curto prazo compartilhada entre instâncias (escopo de processo)
    _short_term_memory: ShortTermMemory = ShortTermMemory()

    def __init__(self, orchestrator: "Orchestrator"):
        """Inicializa o loop com uma instância do orquestrador.
        
        Args:
            orchestrator: Orquestrador que fornece as capacidades de execução.
        """
        self.orchestrator = orchestrator
        self.max_retries = int(os.environ.get("MAX_RETRY_PER_SUBTASK", "3"))
        self.max_subtasks = int(os.environ.get("MAX_SUBTASKS_PER_TASK", "10"))
        # Roadmap V3 - Etapa V3: classificador local de triage (sem container)
        self._triage_classifier = TriageClassifier(
            confidence_threshold=float(os.environ.get("TRIAGE_CONFIDENCE_THRESHOLD", "0.7"))
        )
        self._health_monitor = PiHealthMonitor()


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
        
        telemetry = get_telemetry()

        # 1. Triage: Simples vs Complexo
        is_complex = await self._is_complex_triage(prompt, master_session_id)

        # V5.8 — Telemetria: triage_decision
        telemetry.record_agent_event(
            execution_id=master_session_id,
            session_id=master_session_id,
            agent_id="autonomous_loop",
            event_type="triage_decision",
            payload={"is_complex": is_complex, "mode": os.environ.get("TRIAGE_MODE", "hybrid")},
        )
        
        if not is_complex:
            logger.info("Tarefa identificada como SIMPLES — Usando Agente Base diretamente")
            return await self._run_simple_path(prompt, master_session_id)
            
        logger.info("Tarefa identificada como COMPLEXA — Iniciando Planejamento e Decomposição")
        return await self._run_complex_path(prompt, master_session_id)

    async def _is_complex_triage(self, prompt: str, master_session_id: str) -> bool:
        """Classifica se a tarefa é SIMPLE ou COMPLEX sem spawnar container.

        Roadmap V3 - Etapa V3: substitui o agente Planner em container por
        um classificador local com três modos de operação via TRIAGE_MODE:
        - heuristic : apenas heurísticas (sem API, sem rede, sem container)
        - llm       : chamada direta à API Gemini (sem container)
        - hybrid    : heurísticas primeiro; fallback LLM quando confiança < threshold

        Args:
            prompt: Solicitação original do usuário.
            master_session_id: ID da sessão mestra (usado apenas no modo LLM).

        Returns:
            True se COMPLEX, False se SIMPLE.
        """
        mode = os.environ.get("TRIAGE_MODE", "hybrid").lower()

        if mode == "heuristic":
            decision, confidence = self._triage_classifier.classify(prompt)
            logger.info(
                "Triage heurístico (modo heuristic)",
                extra={"decision": decision, "confidence": confidence},
            )
            return decision == "COMPLEX"

        if mode == "hybrid":
            decision, confidence = self._triage_classifier.classify(prompt)
            logger.info(
                "Triage heurístico (modo hybrid)",
                extra={"decision": decision, "confidence": confidence},
            )
            if confidence >= self._triage_classifier.confidence_threshold:
                return decision == "COMPLEX"
            logger.info(
                "Confiança abaixo do limiar — acionando LLM direto (sem container)",
                extra={"confidence": confidence, "threshold": self._triage_classifier.confidence_threshold},
            )
            return await self._llm_triage_direct(prompt)

        # modo 'llm': sempre usa LLM direto (sem container)
        return await self._llm_triage_direct(prompt)

    async def _llm_triage_direct(self, prompt: str) -> bool:
        """Classifica usando a API Gemini diretamente, sem container.

        Roadmap V3 - Etapa V3: fallback LLM para triage de baixa confiança.
        Usada nos modos 'llm' e 'hybrid' (quando confiança heurística é baixa).

        Args:
            prompt: Solicitação original do usuário.

        Returns:
            True se COMPLEX, False se SIMPLE. Em caso de erro, retorna True
            (padrão conservador).
        """
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
            from src.config import GEMINI_API_KEY, DEFAULT_MODEL

            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(DEFAULT_MODEL)

            triage_prompt = (
                f"Analise a solicitação abaixo e responda APENAS com 'SIMPLE' ou 'COMPLEX'.\n"
                f"SIMPLE: pode ser respondida diretamente, sem pesquisa ou código complexo.\n"
                f"COMPLEX: exige pesquisa, código, múltiplos passos ou validação.\n"
                f"SOLICITAÇÃO: {prompt}\n"
                f"Resposta:"
            )

            response = await asyncio.to_thread(model.generate_content, triage_prompt)
            text = (response.text or "").strip().upper()

            logger.info(
                "Triage via LLM direto concluído",
                extra={"response": text[:50]},
            )

            if "COMPLEX" in text:
                return True
            if "SIMPLE" in text:
                return False

        except Exception as e:
            logger.warning(
                "Falha no triage LLM direto, assumindo COMPLEX",
                extra={"error": str(e)},
            )

        return True  # padrão conservador


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
            artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
        )

    def _build_context_prefix(self, master_session_id: str, depends_on: list[str]) -> str:
        """Constrói o prefixo de contexto das subtarefas anteriores das quais esta depende.

        Lê os resultados já completados da ShortTermMemory e monta um bloco de
        texto estruturado para ser injetado antes do prompt da subtarefa atual.
        O texto é truncado em `_CONTEXT_MAX_CHARS` caracteres para não exceder
        o limite de tokens do modelo (~2000 tokens).

        Args:
            master_session_id: ID da sessão mestra (chave da ShortTermMemory).
            depends_on: Lista de task_names cujos resultados devem ser incluídos.

        Returns:
            String com o bloco de contexto pronta para prefilar o prompt,
            ou string vazia se não houver contexto disponível.
        """
        if not depends_on:
            return ""

        parts: list[str] = []
        for task_name in depends_on:
            entry = self._short_term_memory.read(master_session_id, f"result:{task_name}")
            if entry:
                parts.append(f"### Resultado de `{task_name}`\n{entry.value}")
            else:
                logger.debug(
                    "Contexto não encontrado na memória de curto prazo",
                    extra={"task_name": task_name, "master_session_id": master_session_id},
                )

        if not parts:
            return ""

        context = "\n\n".join(parts)

        # Trunca se necessário
        if len(context) > _CONTEXT_MAX_CHARS:
            context = context[:_CONTEXT_MAX_CHARS]
            logger.warning(
                "Contexto de subtarefas anteriores truncado",
                extra={
                    "max_chars": _CONTEXT_MAX_CHARS,
                    "master_session_id": master_session_id,
                    "depends_on": depends_on,
                },
            )

        return f"Contexto das etapas anteriores:\n{context}\n\n"

    async def _run_complex_path(self, prompt: str, master_session_id: str) -> "OrchestratorResult":
        """Executa a tarefa via caminho complexo (Planner -> Loop de Subtarefas em DAG)."""
        from src.orchestrator import AgentTask, OrchestratorResult, AGENT_REGISTRY, AgentResult
        from src.task_scheduler import TaskScheduler
        
        max_plan_retries = 3
        plan_feedback = ""
        final_results: List[AgentResult] = []
        tasks: List[AgentTask] = []
        
        for plan_attempt in range(max_plan_retries):
            logger.info(f"Iniciando tentativa de planejamento {plan_attempt+1}/{max_plan_retries}")
            # 1. Planejamento (S7.3): Decompõe a tarefa
            effective_prompt = prompt
            if plan_feedback:
                effective_prompt = f"{prompt}\n\nATENÇÃO: O plano anterior falhou com os seguintes erros:\n{plan_feedback}\nPor favor, elabore um plano alternativo corrigindo essas falhas."
                
            tasks = await self.orchestrator._run_planning_loop(effective_prompt, master_session_id)
            
            if not tasks:
                logger.error("Falha ao gerar plano de execução")
                return OrchestratorResult(results=[], total=0, succeeded=0, failed=0)

            logger.info(f"Plano gerado com {len(tasks)} subtarefas")

            # V5.8 — Telemetria: plan_generated
            telemetry = get_telemetry()
            telemetry.record_agent_event(
                execution_id=master_session_id,
                session_id=master_session_id,
                agent_id="planner",
                event_type="plan_generated",
                payload={
                    "num_subtasks": len(tasks),
                    "attempt": plan_attempt + 1,
                    "task_names": [t.task_name for t in tasks],
                },
            )
            
            if len(tasks) > self.max_subtasks:
                logger.warning(f"Número de subtarefas ({len(tasks)}) excede o limite {self.max_subtasks}")
                tasks = tasks[:self.max_subtasks]

            try:
                TaskScheduler.validate_dag(tasks)
            except ValueError as e:
                plan_feedback = f"Grafo de dependências inválido: {e}"
                logger.error(plan_feedback)
                continue

            final_results = []
            
            # Futures para cada tarefa (para sincronização do DAG)
            dag_state = {}
            for t in tasks:
                if t.task_name:
                    dag_state[t.task_name] = {
                        "future": asyncio.Future(),
                        "status": "pending",
                        "error": None
                    }

            async def _execute_task_in_dag(task: AgentTask, index: int):
                # Aguarda as dependências
                for dep in task.depends_on:
                    if dep in dag_state:
                        await dag_state[dep]["future"]
                        if dag_state[dep]["status"] != "success":
                            # Dependência falhou ou foi cancelada -> Cancelar esta tarefa
                            logger.warning(f"Subtarefa {task.task_name} cancelada porque a dependência '{dep}' falhou.")
                            if task.task_name:
                                dag_state[task.task_name]["status"] = "cancelled"
                                dag_state[task.task_name]["future"].set_result(None)
                            return

                logger.info(f"Iniciando subtarefa {index+1}/{len(tasks)}: {task.agent_id} [{task.task_name or 'sem nome'}]")

                # V2: Constrói prefixo de contexto
                context_prefix = self._build_context_prefix(master_session_id, task.depends_on)
                task_prompt = context_prefix + task.prompt if context_prefix else task.prompt

                if context_prefix:
                    logger.info(
                        "Contexto de etapas anteriores injetado no prompt",
                        extra={
                            "task_name": task.task_name,
                            "depends_on": task.depends_on,
                            "context_chars": len(context_prefix),
                        },
                    )

                enriched_task = AgentTask(
                    agent_id=task.agent_id,
                    image=task.image,
                    prompt=task_prompt,
                    task_name=task.task_name,
                    depends_on=task.depends_on,
                    expected_artifacts=task.expected_artifacts,
                    validation_criteria=task.validation_criteria,
                    preferred_model=task.preferred_model,
                )

                success = False
                last_result = None
                
                # Retry Loop
                for attempt in range(self.max_retries):
                    logger.info(f"Executando tentativa {attempt+1}/{self.max_retries} para {task.agent_id} [{task.task_name}]")

                    # V5.8 — Telemetria: subtask_start (apenas na primeira tentativa)
                    if attempt == 0:
                        telemetry = get_telemetry()
                        telemetry.record_agent_event(
                            execution_id=master_session_id,
                            session_id=master_session_id,
                            agent_id=task.agent_id,
                            event_type="subtask_start",
                            task_name=task.task_name or None,
                            payload={"depends_on": task.depends_on},
                        )

                    result = await self.orchestrator._execute_agent(enriched_task, master_session_id)
                    last_result = result
                    
                    if result.status == "success":
                        success = True
                        if task.task_name:
                            response_text = result.response.get("text", "")
                            self._short_term_memory.write(
                                session_id=master_session_id,
                                key=f"result:{task.task_name}",
                                value=response_text,
                                source=task.agent_id,
                                tags=["subtask_result", task.task_name],
                            )
                        break
                    else:
                        logger.warning(f"Tentativa {attempt+1} de {task.task_name} falhou", extra={"error": result.error})
                        await asyncio.sleep(1)

                if last_result:
                    final_results.append(last_result)

                # V5.8 — Telemetria: subtask_end
                telemetry = get_telemetry()
                telemetry.record_agent_event(
                    execution_id=master_session_id,
                    session_id=master_session_id,
                    agent_id=task.agent_id,
                    event_type="subtask_end",
                    task_name=task.task_name or None,
                    payload={"success": success, "attempts": attempt + 1},
                )

                # Fase 3 V5: Hardware snapshot + Monitoramento de Saúde
                from src.config import HEALTH_CHECK_ENABLED
                if HEALTH_CHECK_ENABLED:
                    try:
                        temp = self._health_monitor.get_temperature()
                        mem = self._health_monitor.get_memory_usage()
                        cpu = self._health_monitor.get_cpu_usage()
                        throttled = self._health_monitor.is_throttled()
                        
                        health_data = {
                            "temp": temp,
                            "mem_avail_mb": mem["available_mb"] if mem else None,
                            "cpu_pct": cpu
                        }
                        logger.info("Métricas de saúde do sistema após subtarefa", extra=health_data)

                        # V5 — Telemetria: hardware_snapshot após subtarefa
                        telemetry = get_telemetry()
                        telemetry.record_hardware_snapshot(
                            execution_id=master_session_id,
                            task_name=task.task_name or None,
                            cpu_temp_c=temp,
                            cpu_usage_pct=cpu,
                            mem_total_mb=mem["total_mb"] if mem else None,
                            mem_available_mb=mem["available_mb"] if mem else None,
                            mem_usage_pct=mem["percent"] if mem else None,
                            is_throttled=throttled,
                        )
                    except Exception as e:
                        logger.debug("Falha ao coletar métricas de saúde", extra={"error": str(e)})

                if task.task_name:
                    if success:
                        dag_state[task.task_name]["status"] = "success"
                    else:
                        dag_state[task.task_name]["status"] = "failed"
                        dag_state[task.task_name]["error"] = last_result.error if last_result else "Unknown error"
                    
                    dag_state[task.task_name]["future"].set_result(None)

            # Executa todas as tarefas simultaneamente (o DAG coordena a ordem real)
            coroutines = [_execute_task_in_dag(t, i) for i, t in enumerate(tasks)]
            await asyncio.gather(*coroutines)

            # Verifica se houve alguma falha
            failed_tasks = [t for t, state in dag_state.items() if state["status"] in ("failed", "cancelled")]
            if not failed_tasks:
                # Sucesso total
                succeeded = sum(1 for r in final_results if r.status == "success")
                failed = len(final_results) - succeeded
                
                if succeeded > 0:
                    await self._promote_findings(prompt, master_session_id)

                self._short_term_memory.clear(master_session_id)

                return OrchestratorResult(
                    results=final_results,
                    total=len(tasks),
                    succeeded=succeeded,
                    failed=failed,
                    artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
                    plan_json=json.dumps([t.__dict__ for t in tasks])
                )
            
            # Se falhou, preparamos o feedback para a próxima tentativa de plano
            logger.warning(f"O plano falhou nas tarefas: {failed_tasks}. Re-planejando...")
            errors = []
            for t in failed_tasks:
                if dag_state[t]["status"] == "failed":
                    errors.append(f"Tarefa '{t}' falhou com erro: {dag_state[t]['error']}")
            plan_feedback = "\n".join(errors)

            # V5.8 — Telemetria: replan_triggered
            telemetry = get_telemetry()
            telemetry.record_agent_event(
                execution_id=master_session_id,
                session_id=master_session_id,
                agent_id="autonomous_loop",
                event_type="replan_triggered",
                payload={"failed_tasks": failed_tasks, "attempt": plan_attempt + 1, "errors": errors},
            )

        # Se esgotou todas as tentativas de plano e ainda falhou
        logger.error("Limite de re-planejamentos atingido. Interrompendo execução.")
        self._short_term_memory.clear(master_session_id)
        
        help_msg = (
            f"Limite de tentativas atingido. O plano falhou sucessivamente nas seguintes etapas:\n{plan_feedback}\n\n"
            f"Por favor, responda se deseja tentar novamente e forneça orientações adicionais para contornar este problema."
        )
        
        help_result = AgentResult(
            agent_id="orchestrator",
            session_id=master_session_id,
            status="error",
            response={"text": help_msg},
            error="Limite de re-planejamentos atingido."
        )
        final_results.append(help_result)
        
        succeeded = sum(1 for r in final_results if r.status == "success")
        failed = len(final_results) - succeeded

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

        # V5.8 — Telemetria: memory_promotion
        telemetry = get_telemetry()
        telemetry.record_agent_event(
            execution_id=master_session_id,
            session_id=master_session_id,
            agent_id="planner",
            event_type="memory_promotion",
            payload={"source": "session_findings"},
        )
