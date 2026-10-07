"""Loop de execução autônoma para agentes GeminiClaw.

Implementa a lógica de triage (simples vs complexo), 
decomposição de tarefas em subtarefas e loop de retentativas.
"""

import os
import re
import json
import hashlib
import asyncio
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING, List, Dict, Optional
from src.logger import get_logger
from src.skills.memory.short_term import ShortTermMemory
from src.triage import TriageClassifier, TriageDecision
from src.health import PiHealthMonitor
from src.config import (
    CIRCUIT_BREAKER_STALL_CYCLES,
    LIMIT_GRACE_SECONDS,
    MAX_PLAN_RETRIES,
    MAX_SUBTASKS_PER_TASK,
    SESSION_MAX_TASK_RETRIES,
)
from src.telemetry import get_telemetry
from src.pipeline_errors import AgentRunLimitReached, PlanningStalled
from src.usage import UsageBudget, UsageTracker, StopReason

if TYPE_CHECKING:
    from src.orchestrator import Orchestrator, AgentTask, AgentResult, OrchestratorResult

logger = get_logger(__name__)

# Roadmap V3 - Etapa V3: limite de chars para injeção de contexto (~2000 tokens)
_CONTEXT_MAX_CHARS = 8_000


@dataclass(frozen=True)
class CycleProgress:
    """Progresso de um ciclo de planejamento/execução, para o disjuntor de "zero progresso"."""

    succeeded: frozenset
    failure_signatures: frozenset

    def advanced_from(self, previous: "CycleProgress") -> bool:
        """Há progresso se surgiram sucessos novos ou a assinatura dos erros mudou."""
        return not self.succeeded <= previous.succeeded or self.failure_signatures != previous.failure_signatures


_PATH_RE = re.compile(r"[\w.\-]*[/\\][\w./\\\-]*")


def error_signature(task_name: str, error: Any) -> str:
    """Assinatura do erro de uma subtarefa: tipo normalizado, sem números nem caminhos.

    Reprovações do revisor viram ``review:<texto>``; demais falhas, ``agent:<texto>``.
    """
    text = str(error or "desconhecido").lower()
    kind = "review" if text.startswith("falha na revisão") else "agent"
    text = _PATH_RE.sub("<path>", text)
    text = re.sub(r"\d+(?:[.,]\d+)?", "#", text)
    text = re.sub(r"\s+", " ", text).strip()[:200]
    digest = hashlib.sha1(f"{kind}:{text}".encode("utf-8")).hexdigest()[:10]
    return f"{task_name}:{kind}:{digest}"


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
        # V18/usage-limits — CORRIGIDO: antes lia MAX_RETRY_PER_SUBTASK/MAX_SUBTASKS_PER_TASK
        # diretamente de os.environ (defaults 10/15, divergentes de src/config.py). Agora lê
        # exclusivamente de src/config.py (fonte única de limites — Spec usage-limits,
        # requisito "Fonte única de limites"). self.max_retries é o valor efetivo do
        # orçamento da sessão corrente; é reatribuído em `run()` a partir do UsageBudget
        # (que pode ter sido ajustado via CLI), mas usa o default de config até lá.
        self.max_retries = SESSION_MAX_TASK_RETRIES
        self.max_subtasks = MAX_SUBTASKS_PER_TASK
        # Roadmap V3 - Etapa V3: classificador local de triage (sem container)
        self._triage_classifier = TriageClassifier(
            confidence_threshold=float(os.environ.get("TRIAGE_CONFIDENCE_THRESHOLD", "0.7"))
        )
        self._health_monitor = PiHealthMonitor()
        # Roadmap V15.6 / Spec G10 — modo de operação da sessão corrente
        self._session_mode: str = ""
        # V18/usage-limits — orçamento e contabilização de uso da sessão corrente.
        # Definidos em `run()`, quando o budget efetivo (defaults de config + overrides
        # de CLI) é conhecido.
        self._usage_tracker: "UsageTracker | None" = None


    async def run(
        self,
        prompt: str,
        master_session_id: str,
        mode: str = "",
        budget: "UsageBudget | None" = None,
    ) -> "OrchestratorResult":
        """Executa a tarefa utilizando o loop autônomo.

        Args:
            prompt: Solicitação original do usuário.
            master_session_id: ID da sessão mestra para coordenação.
            mode: Nível de autonomia da sessão (SessionMode). Se omitido, usa
                ``SESSION_DEFAULT_MODE``.
            budget: Orçamento de uso da sessão (Roadmap V18 / Spec
                `usage-limits`). Se omitido, usa os defaults de `src/config.py`.

        Returns:
            OrchestratorResult consolidado.
        """
        from src.config import SESSION_DEFAULT_MODE
        self._session_mode = mode or SESSION_DEFAULT_MODE
        # Roadmap V15.3 / Spec G5 — usado para calcular session_duration_min
        self._session_started_at = time.time()

        # V18/usage-limits — orçamento efetivo da sessão (CLI > config) e tracker de
        # consumo. execution_id=master_session_id: mesmo ID usado em toda a telemetria
        # desta sessão (ver src/orchestrator.py — exec_id e master_session.id coincidem).
        # `self.max_retries`, se ajustado explicitamente pelo chamador (ex: testes)
        # antes desta chamada, é respeitado como override de `max_task_retries` do
        # orçamento default — só é ignorado se `budget` for passado explicitamente.
        effective_budget = budget or UsageBudget.from_config(max_task_retries=self.max_retries)
        self._usage_tracker = UsageTracker(effective_budget, execution_id=master_session_id)
        self.orchestrator.register_usage_tracker(master_session_id, self._usage_tracker)
        self.max_retries = effective_budget.max_task_retries

        logger.info(
            "Iniciando loop autônomo",
            extra={"prompt_preview": prompt[:100], "master_session_id": master_session_id, "mode": self._session_mode}
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
        """Classifica usando o LLM configurado diretamente, sem container.

        Args:
            prompt: Solicitação original do usuário.

        Returns:
            True se COMPLEX, False se SIMPLE. Em caso de erro, retorna True.
        """
        try:
            from src.llm.factory import get_provider
            provider = get_provider()

            triage_prompt = (
                "Analise a solicitação abaixo e responda APENAS com 'SIMPLE' ou 'COMPLEX'.\n"
                "SIMPLE: pode ser respondida diretamente, sem pesquisa ou código complexo.\n"
                "COMPLEX: exige pesquisa, código, múltiplos passos ou validação.\n"
                f"SOLICITAÇÃO: {prompt}\n"
                "Resposta:"
            )

            import time as _time
            from src.llm.metering import record_llm_call

            _t0 = _time.monotonic()
            response = await provider.generate(
                messages=[{"role": "user", "content": triage_prompt}],
                max_tokens=10
            )
            record_llm_call(provider, response, int((_time.monotonic() - _t0) * 1000), "triage")
            text = (response.text or "").strip().upper()

            logger.info(
                "Triage via LLM direto concluído",
                extra={"response": text[:50], "provider": provider.model_name},
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
        from src.orchestrator import AgentTask, OrchestratorResult
        
        now_iso = datetime.now(timezone.utc).isoformat()
        subtask_id = uuid.uuid4().hex
        
        task = AgentTask(
            agent_id="developer",
            prompt=prompt,
            task_name="simple_task",
            subtask_id=subtask_id,
            created_at=now_iso,
            mode=self._session_mode,
        )
        
        # Registra estado inicial
        telemetry = get_telemetry()
        telemetry.record_subtask_metrics(
            subtask_id=subtask_id,
            execution_id=master_session_id,
            task_name="simple_task",
            agent_id="developer",
            status="pending",
            created_at=now_iso
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

    async def _check_operational_thresholds(self, master_session_id: str) -> bool:
        """Monitora limites operacionais (tokens, custo, duração, containers) e, no modo
        `assisted`, oferece ao pesquisador a opção de suspender a sessão (Roadmap V15.3 / Spec G5).

        Não-bloqueante por padrão: apenas registra em log nos modos `semi`/`auto`. No modo
        `assisted`, exibe um aviso e aguarda `OPERATIONAL_THRESHOLD_WAIT_SECONDS` por uma
        resposta; se o pesquisador digitar 's', a sessão é marcada como suspensa.

        Returns:
            True se o pesquisador optou por suspender a sessão; False caso contrário.
        """
        from src.config import (
            OPERATIONAL_THRESHOLDS,
            SESSION_MAX_TOKENS,
            SESSION_MAX_MINUTES,
            MAX_AGENT_RUNS_PER_SESSION,
            OPERATIONAL_THRESHOLD_WAIT_SECONDS,
        )

        telemetry = get_telemetry()
        token_summary = telemetry.get_token_summary(master_session_id)
        rows = token_summary.get("by_provider_model", [])
        total_tokens = sum(r.get("total_tokens") or 0 for r in rows)
        total_cost = sum(r.get("total_cost_usd") or 0 for r in rows)

        token_pct = (total_tokens / SESSION_MAX_TOKENS) if SESSION_MAX_TOKENS else 0.0
        run_counts = getattr(self.orchestrator, "_session_agent_run_counts", None)
        agent_runs = run_counts.get(master_session_id, 0) if isinstance(run_counts, dict) else 0
        run_limit = MAX_AGENT_RUNS_PER_SESSION
        limit_fn = getattr(self.orchestrator, "effective_run_limit", None)
        if callable(limit_fn):
            effective = limit_fn(master_session_id)
            run_limit = effective if isinstance(effective, int) else run_limit
        agent_runs_pct = (agent_runs / run_limit) if run_limit else 0.0
        duration_min = (time.time() - getattr(self, "_session_started_at", time.time())) / 60
        # V18/usage-limits — avisos da Spec G5 agora são percentuais dos limites reais
        # do UsageBudget (SESSION_MAX_MINUTES), não mais minutos absolutos.
        duration_pct = (duration_min / SESSION_MAX_MINUTES) if SESSION_MAX_MINUTES else 0.0

        triggered: list[str] = []
        if token_pct >= OPERATIONAL_THRESHOLDS["token_usage_pct"]:
            triggered.append(f"Uso de tokens: {token_pct*100:.0f}% do limite ({total_tokens}/{SESSION_MAX_TOKENS})")
        if total_cost >= OPERATIONAL_THRESHOLDS["cost_usd"]:
            triggered.append(f"Custo estimado: ${total_cost:.2f} (limite ${OPERATIONAL_THRESHOLDS['cost_usd']:.2f})")
        if duration_pct >= OPERATIONAL_THRESHOLDS["session_duration_pct"]:
            triggered.append(
                f"Duração da sessão: {duration_pct*100:.0f}% do limite ({duration_min:.0f}min/{SESSION_MAX_MINUTES:.0f}min)"
            )
        planning_counts = getattr(self.orchestrator, "_session_planning_run_counts", None)
        planning_runs = planning_counts.get(master_session_id, 0) if isinstance(planning_counts, dict) else 0
        if agent_runs_pct >= OPERATIONAL_THRESHOLDS["agent_runs_pct"]:
            triggered.append(
                f"Execuções de agente: {agent_runs_pct*100:.0f}% do limite ({agent_runs}/{run_limit}); "
                f"execuções de planejamento: {planning_runs}"
            )

        if not triggered:
            return False

        logger.warning(
            "Limite(s) operacional(is) atingido(s)",
            extra={"triggered": triggered, "mode": self._session_mode, "master_session_id": master_session_id},
        )

        if self._session_mode != "assisted":
            # Nos modos semi/auto, apenas registra em log — nunca bloqueia (Spec G5).
            return False

        from src.utils.terminal import RESET, BOLD, YELLOW

        print(f"\n{YELLOW}{BOLD}⚠ Limite(s) operacional(is) atingido(s):{RESET}")
        for item in triggered:
            print(f"  {YELLOW}•{RESET} {item}")

        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(input, "  Digite 's' para suspender a sessão, ou aguarde para continuar: "),
                timeout=OPERATIONAL_THRESHOLD_WAIT_SECONDS,
            )
        except asyncio.TimeoutError:
            answer = None

        if answer and answer.strip().lower() in ("s", "sim"):
            self.orchestrator.session_manager.update(master_session_id, status="suspended")
            logger.info("Sessão suspensa pelo pesquisador", extra={"master_session_id": master_session_id})
            return True

        return False

    async def _report_divergence(
        self, task: "AgentTask", attempt_errors: List[str], master_session_id: str
    ) -> None:
        """Gera e registra um DivergenceReport quando uma subtarefa esgota todas as
        tentativas de retry (Roadmap V15.3 / Spec G5): esperado, obtido em cada
        tentativa, hipótese de causa e opções concretas para o pesquisador.

        Apenas exibe/registra — NUNCA bloqueia diretamente aqui. Se o Researcher, ao
        replanejar com este feedback (via `execution_feedback`), decidir que a
        ambiguidade é genuinamente bloqueante, ele consulta o pesquisador através da
        ferramenta `ask_researcher` (que já tem semântica de bloqueio, deduplicação e
        orçamento de consultas por sessão corretas — ver src/skills/human_feedback).
        No modo `assisted`, o relatório é exibido no terminal; nos modos `semi`/`auto`,
        apenas registrado em log e no payload da sessão.
        """
        options = [
            "Aceitar o resultado divergente e documentar (recomendado)",
            "Tentar novamente com uma abordagem diferente na próxima iteração de replanejamento",
            "Abortar esta subtarefa e prosseguir sem ela",
        ]
        expected = task.hypothesis or (task.validation_criteria[0] if task.validation_criteria else "não especificado")
        report: Dict[str, Any] = {
            "task_name": task.task_name,
            "expected": expected,
            "obtained_per_attempt": attempt_errors,
            "hypothesis_of_cause": (
                "Falha recorrente após múltiplas tentativas — revisar dados/implementação "
                "ou considerar divergência legítima do resultado esperado."
            ),
            "options": options,
        }

        if self._session_mode == "assisted":
            from src.utils.terminal import RESET, BOLD, YELLOW, CYAN

            print(
                f"\n{YELLOW}{BOLD}⚠ DivergenceReport — subtarefa '{task.task_name}' falhou "
                f"após {len(attempt_errors)} tentativas{RESET}"
            )
            print(f"  {BOLD}Esperado:{RESET} {expected}")
            print(f"  {BOLD}Obtido em cada tentativa:{RESET}")
            for i, err in enumerate(attempt_errors, start=1):
                print(f"    [{i}] {err}")
            print(f"  {BOLD}Hipótese de causa:{RESET} {report['hypothesis_of_cause']}")
            print(f"  {CYAN}Opções consideradas no replanejamento:{RESET}")
            for i, opt in enumerate(options, start=1):
                print(f"    [{i}] {opt}")
        else:
            logger.info(
                "DivergenceReport gerado (modo não-assistido, apenas registrado)",
                extra={"task_name": task.task_name, "mode": self._session_mode},
            )

        session = self.orchestrator.session_manager.get(master_session_id)
        payload = dict(session.payload) if session is not None else {}
        reports = list(payload.get("divergence_reports", []))
        reports.append(report)
        payload["divergence_reports"] = reports
        self.orchestrator.session_manager.update(master_session_id, payload=payload)

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
        from src.subtask_output import SubtaskOutput
        for task_name in depends_on:
            entry = self._short_term_memory.read(master_session_id, f"result:{task_name}")
            if entry:
                try:
                    output = SubtaskOutput.from_json(entry.value)
                    parts.append(output.to_context_string())
                except Exception:
                    # Fallback para texto bruto se não for JSON válido (compatibilidade)
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

    def _dispatch_subtask(self, task: "AgentTask") -> "AgentTask":
        """Roteia a subtarefa para o agente adequado (Roadmap V14.4).

        Roteia com base em `task.agent_id`:
        - 'developer' (ou código/dados) -> developer
        - 'researcher' (pesquisa/planejamento) -> researcher
        - 'base' legado -> redirecionado para 'developer'
        - outros papéis conhecidos (AGENT_IDS) são preservados
        """
        from src.orchestrator import AGENT_IDS, AgentTask
        raw_agent = (task.agent_id or "developer").lower()
        if raw_agent == "base":
            agent_id = "developer"
        elif raw_agent in AGENT_IDS:
            agent_id = raw_agent
        else:
            p_lower = (task.prompt or "").lower()
            if any(k in p_lower for k in ("pesquis", "search", "artigo", "buscar", "document")):
                agent_id = "researcher"
            else:
                agent_id = "developer"

        return AgentTask(
            agent_id=agent_id,
            prompt=task.prompt,
            task_name=task.task_name,
            depends_on=task.depends_on,
            expected_artifacts=task.expected_artifacts,
            validation_criteria=task.validation_criteria,
            preferred_model=task.preferred_model,
            subtask_id=task.subtask_id,
            created_at=task.created_at,
            retry_attempt=task.retry_attempt,
        )

    async def _run_complex_path(self, prompt: str, master_session_id: str) -> "OrchestratorResult":
        """Executa a tarefa via caminho complexo (Planner -> Loop de Subtarefas em DAG)."""
        from src.orchestrator import AgentTask, OrchestratorResult, AgentResult
        from src.task_scheduler import TaskScheduler

        # V18/usage-limits — rede de segurança: `_run_complex_path` é chamado
        # normalmente via `run()`, que inicializa `self._usage_tracker` a partir do
        # orçamento efetivo da sessão. Chamadas diretas (ex: testes que exercitam o
        # caminho complexo isoladamente) não passam por `run()`; nesse caso, cria um
        # tracker com os defaults de `src/config.py` para não quebrar com
        # AttributeError. `self.max_retries`, se tiver sido ajustado explicitamente
        # pelo chamador (ex: testes) antes desta chamada, é respeitado como override
        # de `max_task_retries` do orçamento default.
        if self._usage_tracker is None:
            self._usage_tracker = UsageTracker(
                UsageBudget.from_config(max_task_retries=self.max_retries),
                execution_id=master_session_id,
            )
            self.orchestrator.register_usage_tracker(master_session_id, self._usage_tracker)

        max_plan_retries = MAX_PLAN_RETRIES
        execution_feedback = ""
        final_results: List[AgentResult] = []
        tasks: List[AgentTask] = []
        current_plan_dicts: List[Dict[str, Any]] = []
        # V12.5.1 — Circuit breaker: progresso do ciclo anterior (v16-pipeline-robustness §4)
        _previous_progress: CycleProgress | None = None
        _stalled_cycles = 0
        

        for plan_attempt in range(max_plan_retries):
            logger.info(f"Iniciando ciclo de planejamento/recuperação {plan_attempt+1}/{max_plan_retries}")

            # V18/usage-limits — não inicia um novo ciclo de planejamento (que despacharia
            # novas chamadas de exploração) se o orçamento já foi esgotado por um ciclo
            # anterior (ex: retentativas de conexão atingidas durante o último gather).
            pre_cycle_status = self._usage_tracker.check()
            if pre_cycle_status.should_close:
                return await self._close_session(
                    pre_cycle_status.stop_reason, master_session_id, prompt, tasks, {}, final_results
                )

            # 1. Planejamento ou Recuperação Incremental
            try:
                tasks = await self.orchestrator._run_planning_loop(
                    prompt=prompt,
                    master_session_id=master_session_id,
                    previous_plan=current_plan_dicts if current_plan_dicts else None,
                    execution_feedback=execution_feedback
                )
            except AgentRunLimitReached as limit_exc:
                self._record_run_limit(master_session_id, limit_exc)
                return await self._close_session(
                    StopReason.RUNS, master_session_id, prompt, tasks, {}, final_results
                )
            except PlanningStalled as stalled:
                logger.error("Planejamento encerrado por reprovação repetida", extra={"issues": stalled.issues})
                self._short_term_memory.clear(master_session_id)
                final_results.append(AgentResult(
                    agent_id="orchestrator",
                    session_id=master_session_id,
                    status="error",
                    response={"text": str(stalled)},
                    error="Planejamento encerrado: reprovação determinística repetida.",
                ))
                return OrchestratorResult(
                    results=final_results, total=0, succeeded=0, failed=len(final_results),
                    artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
                )
            
            if not tasks:
                logger.error(f"Falha na tentativa {plan_attempt+1} de gerar/recuperar plano")
                execution_feedback = "O orquestrador falhou ao gerar um plano aprovado."
                continue

            # Atualiza o estado do plano atual (para a próxima iteração se falhar)
            current_plan_dicts = [
                {k: v for k, v in t.__dict__.items() if v is not None and k not in ("subtask_id", "created_at")} 
                for t in tasks
            ]
            
            logger.info(f"Plano ativo com {len(tasks)} subtarefas")

            # V5.8 — Telemetria: plan_generated
            telemetry = get_telemetry()
            now_iso = datetime.now(timezone.utc).isoformat()
            
            # V9: Atribui IDs e timestamps iniciais às tarefas
            for t in tasks:
                t.subtask_id = uuid.uuid4().hex
                t.created_at = now_iso
                # Registra o estado inicial (pending) na tabela subtask_metrics
                telemetry.record_subtask_metrics(
                    subtask_id=t.subtask_id,
                    execution_id=master_session_id,
                    task_name=t.task_name or "unnamed",
                    agent_id=t.agent_id,
                    status="pending",
                    created_at=t.created_at
                )

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

            # Roadmap V15.3 / Spec G5 — monitoramento de limites operacionais, checado uma
            # vez por ciclo de planejamento (não por subtarefa, para evitar corridas entre
            # subtarefas concorrentes do mesmo ciclo).
            if await self._check_operational_thresholds(master_session_id):
                suspend_result = AgentResult(
                    agent_id="orchestrator",
                    session_id=master_session_id,
                    status="success",
                    response={"text": "Sessão suspensa pelo pesquisador após aviso de limite operacional."},
                )
                final_results.append(suspend_result)
                self._short_term_memory.clear(master_session_id)
                succeeded = sum(1 for r in final_results if r.status == "success")
                return OrchestratorResult(
                    results=final_results,
                    total=len(tasks),
                    succeeded=succeeded,
                    failed=len(final_results) - succeeded,
                    artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
                )

            # V18/usage-limits — limites reais (não apenas avisos): tokens, tempo e
            # retentativas de conexão, checados no mesmo ponto do ciclo que os avisos
            # operacionais acima (uma vez por ciclo de planejamento).
            plan_usage_status = self._usage_tracker.check()
            if plan_usage_status.should_close:
                return await self._close_session(
                    plan_usage_status.stop_reason, master_session_id, prompt, tasks, {}, final_results
                )

            if len(tasks) > self.max_subtasks:
                logger.warning(f"Número de subtarefas ({len(tasks)}) excede o limite {self.max_subtasks}")
                tasks = tasks[:self.max_subtasks]

            try:
                TaskScheduler.validate_dag(tasks)
            except ValueError as e:
                execution_feedback = f"Grafo de dependências inválido: {e}"
                logger.error(execution_feedback)
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

            limit_hits: List[AgentRunLimitReached] = []

            async def _execute_task_in_dag(task: AgentTask, index: int):
                # V18/usage-limits — chave de contabilização de retentativas da MESMA
                # tarefa (design §2): conta cumulativamente entre ciclos de replanejamento
                # que preservam o task_name, via UsageTracker (não mais um range() local).
                # Calculada aqui (antes de aguardar dependências) para poder ser usada
                # também no guard de tarefa já abandonada, logo abaixo.
                retry_key = task.task_name or f"_unnamed_{task.subtask_id or index}"

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

                # V18/usage-limits — não redespacha uma tarefa já ABANDONADA por
                # esgotamento de retentativas em um ciclo de replanejamento anterior. O
                # mesmo task_name pode reaparecer em planos incrementais gerados por
                # `_run_planning_loop`; sem este guard, o retry loop abaixo recomeçaria a
                # contagem de tentativas locais do zero, mas `record_task_attempt` já
                # opera cumulativamente por task_name — o risco real é o dispatch em si
                # (chamada ao agente) ocorrer de novo para uma tarefa cujo orçamento de
                # retentativas já foi esgotado. Tratada como "abandonada" (não "cancelled")
                # para manter a mesma semântica de `dag_state` usada linhas abaixo, quando
                # o esgotamento é detectado dentro do próprio retry loop.
                if self._usage_tracker.is_task_abandoned(retry_key):
                    logger.info(
                        "Despacho suspenso: tarefa já abandonada por esgotamento de "
                        "retentativas em ciclo de replanejamento anterior",
                        extra={"task_name": task.task_name, "retry_key": retry_key},
                    )
                    if task.task_name:
                        dag_state[task.task_name]["status"] = "abandonada"
                        dag_state[task.task_name]["error"] = (
                            "Tarefa já abandonada em ciclo de replanejamento anterior "
                            "(retentativas esgotadas)"
                        )
                        dag_state[task.task_name]["future"].set_result(None)
                    return

                # V18/usage-limits — não despacha uma NOVA subtarefa se o orçamento já foi
                # esgotado (dependências já concluídas antes deste ponto continuam intactas;
                # apenas o despacho desta subtarefa ainda não iniciada é suspenso).
                dispatch_status = self._usage_tracker.check()
                if dispatch_status.should_close:
                    logger.info(
                        "Despacho suspenso: limite de orçamento atingido",
                        extra={
                            "task_name": task.task_name,
                            "stop_reason": dispatch_status.stop_reason.value if dispatch_status.stop_reason else None,
                        },
                    )
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
                    prompt=task_prompt,
                    task_name=task.task_name,
                    depends_on=task.depends_on,
                    expected_artifacts=task.expected_artifacts,
                    validation_criteria=task.validation_criteria,
                    preferred_model=task.preferred_model,
                    subtask_id=task.subtask_id,
                    created_at=task.created_at,
                    mode=self._session_mode,
                )
                
                enriched_task = self._enrich_task_prompt(enriched_task)
                enriched_task = self._dispatch_subtask(enriched_task)

                success = False
                last_result = None
                last_review: Dict[str, Any] | None = None  # parecer do Validator da última tentativa
                attempt_errors: List[str] = []  # V15.3/G5 — insumo do DivergenceReport
                # retry_key já calculada no início da coroutine (usada também pelo guard
                # de tarefa abandonada, acima).

                # Retry Loop — cada iteração conta como uma tentativa GLOBAL da tarefa
                # (SESSION_MAX_TASK_RETRIES), não apenas local a este dispatch.
                attempt = 0
                while True:
                    attempt_number = self._usage_tracker.record_task_attempt(retry_key)
                    attempt = attempt_number - 1  # índice 0-based, compatível com os logs abaixo
                    logger.info(
                        f"Executando tentativa {attempt_number}/{self._usage_tracker.budget.max_task_retries} "
                        f"para {task.agent_id} [{task.task_name}]"
                    )

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

                    try:
                        result = await self.orchestrator._execute_agent(enriched_task, master_session_id)
                    except AgentRunLimitReached as limit_exc:
                        limit_hits.append(limit_exc)
                        if task.task_name:
                            dag_state[task.task_name]["status"] = "cancelled"
                            dag_state[task.task_name]["future"].set_result(None)
                        return
                    last_result = result
                    last_review = None

                    if result.status == "success":
                        success = True
                        # V6.3: Executa Reviewer se habilitado e houver critérios
                        review = None
                        from src.config import REVIEW_ENABLED, REVIEW_MODE
                        if REVIEW_ENABLED and REVIEW_MODE == "per_subtask" and task.validation_criteria:
                            logger.info(f"Iniciando revisão da subtarefa {task.task_name}")
                            review = await self._review_subtask(task, result, master_session_id, attempt_number)
                            last_review = review
                            if review.get("status") == "fail":
                                success = False
                                result.status = "error"
                                result.error = f"Falha na revisão: {', '.join(review.get('issues', []))}"
                                logger.warning(f"Subtarefa {task.task_name} reprovada na revisão", extra={"issues": review.get("issues")})
                            else:
                                logger.info(f"Subtarefa {task.task_name} aprovada na revisão")

                        if success and task.task_name:
                            # V6.4: Cria output estruturado
                            from src.subtask_output import SubtaskOutput
                            output = SubtaskOutput.from_agent_result(
                                task_name=task.task_name,
                                agent_id=task.agent_id,
                                result=result,
                                review_data=review
                            )
                            
                            self._short_term_memory.write(
                                session_id=master_session_id,
                                key=f"result:{task.task_name}",
                                value=output.to_json(),
                                source=task.agent_id,
                                tags=["subtask_result", task.task_name, "structured"],
                            )
                            
                            if task.agent_id == "code":
                                await self._extract_code_patterns(result, master_session_id)
                        break
                    else:
                        logger.warning(f"Tentativa {attempt+1} de {task.task_name} falhou", extra={"error": result.error})
                        attempt_errors.append(result.error or "Erro desconhecido")

                        # V13.5.1: Orquestrador lista artefatos reais antes de cada retry.
                        artifacts_on_disk = self.orchestrator.output_manager.list_artifacts(master_session_id)
                        artifact_context = ""
                        if artifacts_on_disk:
                            artifact_context = (
                                f"\n\n[ARTEFATOS PARCIAIS EXISTENTES EM DISCO]\n"
                                + "\n".join(f"  - {a}" for a in artifacts_on_disk)
                                + "\nEsses artefatos são válidos. Não os recrie. Continue a partir deles.\n"
                            )

                        # V13.5.2: Orquestrador popula memória de curto prazo antes do retry.
                        from src.skills.__init__ import registry
                        memory_skill = registry.get("memory")
                        if memory_skill:
                            memory_context = {
                                "type": "retry_context",
                                "task": task.task_name,
                                "attempt": attempt + 1,
                                "previous_error": result.error,
                                "artifacts_available": artifacts_on_disk,
                                "manifest_path": f"outputs/{master_session_id}/manifest.json"
                            }
                            await memory_skill.run(
                                action="remember",
                                session_id=master_session_id,
                                key=f"retry_context_{task.task_name}_{attempt + 1}",
                                value=json.dumps(memory_context)
                            )

                        # V18/usage-limits — retentativas da MESMA tarefa (task_name) são
                        # limitadas por SESSION_MAX_TASK_RETRIES, contadas cumulativamente
                        # pelo UsageTracker (inclusive entre ciclos de replanejamento). Ao
                        # esgotar, a tarefa é ABANDONADA (não mais recomeça o loop) — o
                        # restante do DAG e a sessão continuam (design §3).
                        if self._usage_tracker.task_retries_exhausted(retry_key):
                            break

                        # V12.1.1 — Cache-busting por injeção de contexto de erro.
                        # O bloco abaixo altera o prompt da próxima tentativa, garantindo
                        # que o cache faça MISS e o agente receba um novo contexto.
                        error_context = (
                            f"\n\n[TENTATIVA ANTERIOR FALHOU]\n"
                            f"Tentativa: {attempt_number}/{self._usage_tracker.budget.max_task_retries}\n"
                            f"Erro: {result.error or 'Erro desconhecido'}\n"
                            f"Instrução: Tente uma abordagem diferente para resolver o problema.\n"
                        )
                        enriched_task = AgentTask(
                            agent_id=enriched_task.agent_id,
                            prompt=enriched_task.prompt + artifact_context + error_context,
                            task_name=enriched_task.task_name,
                            depends_on=enriched_task.depends_on,
                            expected_artifacts=enriched_task.expected_artifacts,
                            validation_criteria=enriched_task.validation_criteria,
                            preferred_model=enriched_task.preferred_model,
                            subtask_id=enriched_task.subtask_id,
                            created_at=enriched_task.created_at,
                            retry_attempt=attempt + 1,  # V12.3.3: próxima tentativa
                            mode=enriched_task.mode,
                        )
                        await asyncio.sleep(1)

                if last_result:
                    final_results.append(last_result)

                # v17-structural-fact-ingestion — fatos da subtarefa (revisada) no grafo, sem LLM.
                await self._ingest_subtask(task, last_result, last_review, master_session_id)

                # Roadmap V15.3 / Spec G5 — DivergenceReport quando a subtarefa esgota
                # todas as tentativas (padrão de falha recorrente detectado).
                if not success and self._usage_tracker.task_retries_exhausted(retry_key):
                    await self._report_divergence(task, attempt_errors, master_session_id)

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
                    elif self._usage_tracker.task_retries_exhausted(retry_key):
                        # V18/usage-limits — retentativas da MESMA tarefa esgotadas: a
                        # tarefa é ABANDONADA, não "failed". Isso a exclui de
                        # `failed_tasks` abaixo — NÃO dispara um novo ciclo de
                        # replanejamento; apenas esta tarefa (e seus dependentes) fica
                        # sem conclusão, e o restante do DAG e a sessão continuam
                        # (design §3 — "Retentativas abandonam a tarefa, não a sessão").
                        self._usage_tracker.mark_task_abandoned(retry_key)
                        dag_state[task.task_name]["status"] = "abandonada"
                        dag_state[task.task_name]["error"] = last_result.error if last_result else "Unknown error"
                    else:
                        dag_state[task.task_name]["status"] = "failed"
                        dag_state[task.task_name]["error"] = last_result.error if last_result else "Unknown error"

                    dag_state[task.task_name]["future"].set_result(None)

            # Executa todas as tarefas simultaneamente (o DAG coordena a ordem real).
            # V18/usage-limits — limitado pelo tempo restante do orçamento + carência
            # (LIMIT_GRACE_SECONDS): subtarefas em andamento têm até esse prazo para
            # terminar; se estourar, as demais são canceladas e a sessão fecha por
            # limite de tempo (design §3).
            coroutines = [_execute_task_in_dag(t, i) for i, t in enumerate(tasks)]
            remaining_seconds = max(
                0.0, (self._usage_tracker.budget.max_minutes * 60) - (self._usage_tracker.elapsed_minutes() * 60)
            )
            gather_timeout = remaining_seconds + LIMIT_GRACE_SECONDS
            try:
                await asyncio.wait_for(asyncio.gather(*coroutines), timeout=gather_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Limite de tempo atingido durante a execução do ciclo — cancelando "
                    "subtarefas restantes após a carência",
                    extra={"master_session_id": master_session_id, "grace_seconds": LIMIT_GRACE_SECONDS},
                )
                for t_name, state in dag_state.items():
                    if state["status"] == "pending":
                        state["status"] = "cancelled"
                        if not state["future"].done():
                            state["future"].set_result(None)
                return await self._close_session(
                    StopReason.TIME, master_session_id, prompt, tasks, dag_state, final_results
                )

            if limit_hits:
                self._record_run_limit(master_session_id, limit_hits[0])
                return await self._close_session(
                    StopReason.RUNS, master_session_id, prompt, tasks, dag_state, final_results
                )

            # v17-curator-agent — checkpoint de consolidação ao fim do ciclo de planejamento (falha isolada).
            await self.orchestrator.curator_consolidate(master_session_id)

            # Verifica se houve alguma falha
            failed_tasks = [t for t, state in dag_state.items() if state["status"] in ("failed", "cancelled")]
            abandoned_tasks = [t for t, state in dag_state.items() if state["status"] == "abandonada"]

            if not failed_tasks:
                # Sucesso total (possivelmente com tarefas abandonadas em ramificações
                # independentes do DAG — design §3, "Tarefa abandonada").
                succeeded = sum(1 for r in final_results if r.status == "success")
                failed = len(final_results) - succeeded

                # V18/usage-limits — se TODAS as tarefas do ciclo foram abandonadas por
                # retentativas (nada teve sucesso), a sessão inteira fecha com
                # motivo_parada="limite_retentativas" (design §3, "Todas abandonadas").
                if abandoned_tasks and succeeded == 0 and self._usage_tracker.all_pending_abandoned(
                    list(dag_state.keys())
                ):
                    return await self._close_session(
                        StopReason.RETRIES, master_session_id, prompt, tasks, dag_state, final_results
                    )

                if succeeded > 0:
                    await self._promote_findings(prompt, master_session_id)
                    # Etapa V6.7: Síntese final com o Summarizer
                    try:
                        final_report = await self._synthesize_results(prompt, final_results, master_session_id)
                    except AgentRunLimitReached as limit_exc:
                        self._record_run_limit(master_session_id, limit_exc)
                        final_report = None
                    if final_report:
                        # Adiciona o relatório final aos resultados
                        final_results.append(final_report)

                self._short_term_memory.clear(master_session_id)

                return OrchestratorResult(
                    results=final_results,
                    total=len(tasks),
                    succeeded=succeeded,
                    failed=failed,
                    artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
                    plan_json=json.dumps([t.__dict__ for t in tasks])
                )
            
            # Se falhou, preparamos o feedback para a próxima tentativa de plano (Recuperação Incremental)
            succeeded_tasks = [t for t, state in dag_state.items() if state["status"] == "success"]
            logger.warning(f"O plano falhou nas tarefas: {failed_tasks}. Iniciando recuperação incremental...")

            # V12.5.1 — Circuit breaker: detecta progresso zero entre ciclos consecutivos
            # v16-pipeline-robustness §4 — progresso = mais sucessos OU mudança na assinatura dos
            # erros; dispara só após CIRCUIT_BREAKER_STALL_CYCLES ciclos consecutivos sem progresso.
            current_progress = CycleProgress(
                succeeded=frozenset(succeeded_tasks),
                failure_signatures=frozenset(
                    error_signature(t, dag_state[t].get("error")) for t in failed_tasks
                ),
            )
            if _previous_progress is not None and not current_progress.advanced_from(_previous_progress):
                _stalled_cycles += 1
            else:
                _stalled_cycles = 0
            if _stalled_cycles >= CIRCUIT_BREAKER_STALL_CYCLES:
                cb_msg = (
                    "Execução interrompida: nenhum progresso detectado entre ciclos consecutivos.\n"
                    f"Subtarefas falhas: {failed_tasks}.\n"
                    f"Erros persistentes: {[dag_state[t]['error'] for t in failed_tasks if dag_state[t]['status'] == 'failed']}.\n"
                    "Considere revisar o prompt ou as dependências do ambiente."
                )
                logger.warning(
                    "V12.5.1 Circuit Breaker ativado: zero progresso em ciclos consecutivos",
                    extra={"succeeded_tasks": succeeded_tasks, "failed_tasks": failed_tasks},
                )
                telemetry = get_telemetry()
                telemetry.record_agent_event(
                    execution_id=master_session_id,
                    session_id=master_session_id,
                    agent_id="autonomous_loop",
                    event_type="circuit_breaker",
                    payload={
                        "reason": "zero_progress",
                        "succeeded_tasks": succeeded_tasks,
                        "failed_tasks": failed_tasks,
                        "stalled_cycles": _stalled_cycles,
                        "failure_signatures": sorted(current_progress.failure_signatures),
                    },
                )
                cb_result = AgentResult(
                    agent_id="orchestrator",
                    session_id=master_session_id,
                    status="error",
                    response={"text": cb_msg},
                    error="Circuit breaker: zero progresso.",
                )
                final_results.append(cb_result)
                self._short_term_memory.clear(master_session_id)
                succeeded = sum(1 for r in final_results if r.status == "success")
                failed_count = len(final_results) - succeeded
                return OrchestratorResult(
                    results=final_results,
                    total=len(tasks),
                    succeeded=succeeded,
                    failed=failed_count,
                    artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
                )
            _previous_progress = current_progress

            errors = []
            for t in failed_tasks:
                if dag_state[t]["status"] == "failed":
                    errors.append(f"Tarefa '{t}' falhou com erro: {dag_state[t]['error']}")

            # V12.1.3 — Invalidar prompts das subtarefas falhas no cache LLM antes de replanear.
            # Isso garante que o próximo ciclo de planejamento não re-use respostas cacheadas
            # que originaram as falhas.
            try:
                from src.llm_cache import LLMResponseCache
                from src.llm.session import get_session_routing
                _model = get_session_routing().resolution("researcher").id
                _cache = LLMResponseCache()
                for failed_task_obj in tasks:
                    if failed_task_obj.task_name in failed_tasks:
                        _cache.invalidate(failed_task_obj.prompt, _model)
                        logger.debug(
                            "Cache invalidado para subtarefa falha",
                            extra={"task_name": failed_task_obj.task_name},
                        )
            except Exception as _inv_err:
                logger.warning(
                    "Falha ao invalidar cache de subtarefas — replan prossegue mesmo assim",
                    extra={"error": str(_inv_err)},
                )

            execution_feedback = (
                f"STATUS DA EXECUÇÃO ANTERIOR:\n"
                f"- Tarefas concluídas com sucesso: {', '.join(succeeded_tasks) if succeeded_tasks else 'Nenhuma'}\n"
                f"- Falhas encontradas:\n" + "\n".join(errors) + "\n\n"
                f"Instrução: Crie um plano de recuperação focado em resolver as falhas e completar os objetivos restantes, "
                f"sem refazer as tarefas que já tiveram sucesso."
            )


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
            f"Limite de tentativas de recuperação atingido. A execução falhou com os seguintes erros:\n{execution_feedback}\n\n"
            f"Por favor, revise a solicitação ou forneça orientações adicionais."
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

    async def _ingest_subtask(
        self,
        task: "AgentTask",
        result: Optional["AgentResult"],
        review: Optional[Dict[str, Any]],
        master_session_id: str,
    ) -> None:
        """Ingere os fatos estruturais de uma subtarefa concluída (v17-structural-fact-ingestion).

        Nunca interrompe a sessão: sem projeto/grafo a ingestão é omitida; falhas do grafo viram
        eventos em ``knowledge_pending.jsonl`` (tratados pelo ``FactIngestor``).
        """
        from src.knowledge.ingestion import FactIngestor, SubtaskInput

        ingestor = self.orchestrator.get_ingestor(master_session_id)
        if not isinstance(ingestor, FactIngestor) or result is None or not task.task_name:
            return
        try:

            sub = SubtaskInput(
                task_name=task.task_name,
                subtask_id=task.subtask_id,
                agent_id=task.agent_id,
                task_type=task.task_type,
                hypothesis=task.hypothesis or "",
                scientific_rationale=task.scientific_rationale or "",
                approach=task.approach if isinstance(task.approach, dict) else None,
                agent_status=result.status,
                agent_error_category=getattr(result, "error_category", None),
                review_status=(review or {}).get("status"),
                review_verified=bool((review or {}).get("verified", False)),
                validation_criteria=[c for c in (task.validation_criteria or []) if isinstance(c, str)],
            )
            if await asyncio.to_thread(ingestor.subtask, sub):
                # v17-curator-agent: recálculo determinístico do veredito após cada subtarefa ingerida.
                subtarefa_id = sub.subtask_id or f"{master_session_id}:{sub.task_name}"
                await asyncio.to_thread(self.orchestrator.knowledge_after_subtask, master_session_id, subtarefa_id)
        except Exception as exc:  # noqa: BLE001 - a ingestão nunca derruba a subtarefa
            logger.warning("Falha ao ingerir fatos da subtarefa", extra={"error": type(exc).__name__})

    def _record_run_limit(self, master_session_id: str, exc: AgentRunLimitReached) -> None:
        """Registra o evento ``limit_reached`` do limite de execuções (observabilidade segura)."""
        logger.warning(
            "Limite de execuções de agente atingido",
            extra={"kind": exc.kind, "count": exc.count, "limit": exc.limit},
        )
        try:
            get_telemetry().record_agent_event(
                execution_id=master_session_id,
                session_id=master_session_id,
                agent_id="autonomous_loop",
                event_type="limit_reached",
                payload={"limit": "agent_runs", "kind": exc.kind, "count": exc.count, "max": exc.limit},
            )
        except Exception as err:
            logger.warning("Falha ao registrar limit_reached", extra={"error": str(err)})

    async def _close_session(
        self,
        reason: "StopReason",
        master_session_id: str,
        prompt: str,
        tasks: List["AgentTask"],
        dag_state: Dict[str, Any],
        final_results: List["AgentResult"],
    ) -> "OrchestratorResult":
        """Executa o fechamento gracioso da sessão (Roadmap V18 / Spec `usage-limits`).

        Grava sempre um checkpoint determinístico (sem LLM — design §3, "Fechamento
        sempre registra o avanço") no payload da sessão e em ``checkpoint.json``, com
        o motivo de parada e o estado de cada tarefa. Se ainda houver orçamento na
        reserva de fechamento, tenta também uma consolidação final via Summarizer.

        Nota de integração (spec ambiguity, ver relatório da mudança): o design
        (``openspec/changes/v18-usage-limits/design.md`` §3) especifica o fechamento
        como "checkpoint (v18-research-continuity) + curator.close_session". Nem o
        checkpoint de ``v18-research-continuity`` nem o agente Curator (ADR 012)
        existem neste codebase — são mudanças paralelas/futuras que ainda não foram
        implementadas. Esta implementação usa o Summarizer já existente
        (`_synthesize_results`) como consolidação final e um checkpoint determinístico
        próprio como substituto temporário; quando `v18-research-continuity`/Curator
        forem implementados, este método deve passar a delegar a eles.

        Args:
            reason: Motivo de parada (`StopReason`).
            master_session_id: ID da sessão mestra (== execution_id).
            prompt: Solicitação original do usuário.
            tasks: Plano ativo no momento do fechamento (pode ser vazio).
            dag_state: Estado do DAG no momento do fechamento (pode ser vazio).
            final_results: Resultados já acumulados na sessão.

        Returns:
            `OrchestratorResult` final da sessão, com o checkpoint e (se possível)
            a consolidação final incluídos.
        """
        from src.orchestrator import OrchestratorResult

        usage_status = self._usage_tracker.check()

        logger.warning(
            "Sessão em fechamento gracioso",
            extra={
                "master_session_id": master_session_id,
                "motivo_parada": reason.value,
                "tokens_used": usage_status.tokens_used,
                "minutes_elapsed": usage_status.minutes_elapsed,
                "connection_retries": usage_status.connection_retries,
            },
        )

        telemetry = get_telemetry()
        telemetry.record_agent_event(
            execution_id=master_session_id,
            session_id=master_session_id,
            agent_id="autonomous_loop",
            event_type="session_closing",
            payload={
                "motivo_parada": reason.value,
                "tokens_used": usage_status.tokens_used,
                "minutes_elapsed": usage_status.minutes_elapsed,
                "connection_retries": usage_status.connection_retries,
                "abandoned_tasks": sorted(self._usage_tracker.abandoned_tasks),
            },
        )

        completed_tasks = [t for t, s in dag_state.items() if s.get("status") == "success"]
        abandoned_tasks = [t for t, s in dag_state.items() if s.get("status") == "abandonada"]
        pending_tasks = [
            t for t, s in dag_state.items() if s.get("status") not in ("success", "abandonada")
        ]

        # design §3 — "Reserva esgotada": se não sobrar orçamento nem para a reserva de
        # fechamento, pula a consolidação via LLM e apenas grava o checkpoint
        # determinístico; a consolidação fica pendente para a próxima execução.
        tokens_available_for_closing = not self._usage_tracker.tokens_hard_exhausted()
        consolidation_pending = not tokens_available_for_closing

        checkpoint = {
            "motivo_parada": reason.value,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "completed_tasks": completed_tasks,
            "abandoned_tasks": abandoned_tasks,
            "pending_tasks": pending_tasks,
            "tokens_used": usage_status.tokens_used,
            "minutes_elapsed": usage_status.minutes_elapsed,
            "connection_retries": usage_status.connection_retries,
            "consolidation_pending": consolidation_pending,
        }

        # Checkpoint determinístico — sempre gravado, mesmo se a consolidação abaixo falhar.
        session = self.orchestrator.session_manager.get(master_session_id)
        payload = dict(session.payload) if session is not None else {}
        payload["motivo_parada"] = reason.value
        payload["checkpoint"] = checkpoint
        self.orchestrator.session_manager.update(master_session_id, payload=payload)

        try:
            session_dir = self.orchestrator.output_manager.base_dir / master_session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "checkpoint.json").write_text(
                json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Falha ao gravar checkpoint.json", extra={"error": str(e)})

        # Consolidação final (equivalente ao Curator — ver nota de integração acima),
        # usando a reserva de tokens quando disponível.
        if tokens_available_for_closing and (completed_tasks or final_results):
            try:
                final_report = await self._synthesize_results(
                    prompt, final_results, master_session_id, reason.value
                )
                if final_report:
                    final_results.append(final_report)
            except Exception as e:
                logger.warning(
                    "Falha na consolidação final durante o fechamento — checkpoint "
                    "determinístico preservado",
                    extra={"error": str(e)},
                )
                consolidation_pending = True
        else:
            logger.warning(
                "Reserva de tokens esgotada — consolidação final adiada (consolidation_pending)",
                extra={"master_session_id": master_session_id},
            )

        self._short_term_memory.clear(master_session_id)

        succeeded = sum(1 for r in final_results if r.status == "success")
        failed = len(final_results) - succeeded

        return OrchestratorResult(
            results=final_results,
            total=len(tasks) if tasks else len(dag_state),
            succeeded=succeeded,
            failed=failed,
            artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
            plan_json=json.dumps([t.__dict__ for t in tasks]) if tasks else None,
        )

    async def _promote_findings(self, prompt: str, master_session_id: str) -> None:
        """Identifica e promove descobertas importantes para a memória de longo prazo (S7.5.a)."""
        from src.orchestrator import AgentTask
        
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
            agent_id="base",  # o papel 'planner' não existe no runtime em processo; 'base' tem a skill de memória
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

    def _enrich_task_prompt(self, task: "AgentTask") -> "AgentTask":
        """Injeta lições relevantes no contexto inicial da subtarefa (V13.6.3)."""
        if task.agent_id == "code":
            from src.skills.__init__ import registry
            memory_skill = registry.get("memory")
            if memory_skill:
                inferred_domain = "unknown"
                prompt_lower = task.prompt.lower()
                # Tenta inferir o domínio a partir do prompt
                for d in ["pandas", "sklearn", "matplotlib", "seaborn", "numpy", "tensorflow", "pytorch", "fastapi"]:
                    if d in prompt_lower:
                        inferred_domain = d
                        break
                        
                if inferred_domain != "unknown":
                    # Usamos long_term.search() pois memory_skill.retrieve não suporta buscas abertas/prefixos
                    patterns = memory_skill.long_term.search(tags=[inferred_domain], limit=3)
                    if patterns:
                        lessons = []
                        for p in patterns:
                            try:
                                data = json.loads(p.value)
                                lesson = f"- Padrão: {data.get('pattern')}"
                                if data.get("pitfall"):
                                    lesson += f" | Armadilha: {data.get('pitfall')}"
                                if data.get("fix"):
                                    lesson += f" | Correção: {data.get('fix')}"
                                lessons.append(lesson)
                            except Exception:
                                pass
                                
                        if lessons:
                            injection = "\n\n[PADRÕES DE CÓDIGO CONHECIDOS PARA ESTE DOMÍNIO]\n" + "\n".join(lessons) + "\n"
                            task.prompt = task.prompt + injection
                            logger.info("Padrões de código injetados", extra={"domain": inferred_domain, "count": len(lessons)})
                            
        return task

    async def _extract_code_patterns(self, result: "AgentResult", master_session_id: str) -> None:
        """Extrai padrões de código pós-conclusão de uma subtarefa (V13.6.1 e V13.6.2)."""
        if result.status != "success":
            return
            
        import os
        import json
        import hashlib
        
        # O manifest.json no novo formato (V13.3) fica em outputs/<session_id>/manifest.json
        # Aqui <session_id> de fato do container code costuma ser master_session_id + "_" + task_name
        # Mas vamos procurar o manifest associado à session atual (master_session_id, ou a pasta da task_name)
        # Assumiremos master_session_id como path base, ou obter de config
        output_dir = os.environ.get("OUTPUT_DIR", "outputs")
        # Para ser seguro e capturar o manifest correto que foi preenchido:
        # A task V13.1.2 usa master_session_id_task_name
        # Mas para a extração não temos acesso fácil ao task_name aqui além de result.task_name (se existir)
        # O result não tem task_name nativo, mas podemos obter da short term memory
        # ou tentar ler o manifest global (V13.3) que talvez seja persistido no diretório da task.
        task_name = getattr(result, "task_name", None)
        if not task_name:
            # Em nossa implementação anterior `task.task_name` estava disponível via escopo
            # Mas `result` só tem session_id (que é master_session_id)
            # Vamos inferir do short term memory ou usar o fallback 
            pass
            
        # O manifest costuma estar em outputs/<master_session_id>_task_name/manifest.json 
        # Vamos apenas injetar os últimos logs de execução ou o que houver no result em vez de procurar o arquivo se for difícil.
        # Mas V13.6.1 exige "Histórico: {manifest_steps}".
        # O V13.5.2 usava outputs/{master_session_id}/manifest.json. Vou usar esse.
        manifest_path = os.path.join(output_dir, master_session_id, "manifest.json")
        manifest_steps = []
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r") as f:
                    manifest_data = json.load(f)
                    manifest_steps = manifest_data.get("steps", [])
            except Exception as e:
                logger.warning(f"Falha ao ler manifest.json: {e}")
                
        # Se não há passos, falhamos silenciosamente pois é apenas extração de padrões
        if not manifest_steps:
            return

        extraction_prompt = (
            f"Dado o histórico de execução desta subtarefa, extraia lições reutilizáveis no formato JSON:\n"
            f"{{\n"
            f'  "domain": "nome do domínio (ex: sklearn, pandas, matplotlib)",\n'
            f'  "pattern": "descrição do padrão que funcionou",\n'
            f'  "pitfall": "descrição da armadilha encontrada (se houver)",\n'
            f'  "fix": "como foi resolvida"\n'
            f"}}\n"
            f"Histórico:\n{json.dumps(manifest_steps)}\n"
            f"Responda APENAS com o JSON."
        )

        from src.orchestrator import AgentTask
        extraction_task = AgentTask(
            agent_id="base",
            prompt=extraction_prompt,
            task_name="extract_patterns"
        )

        extraction_result = await self.orchestrator._execute_agent(extraction_task, master_session_id)
        if extraction_result.status == "success":
            raw_text = extraction_result.response.get("text", "")
            from src.utils.json_parser import extract_json
            extracted = extract_json(raw_text)
            
            if extracted and isinstance(extracted, dict) and "domain" in extracted and "pattern" in extracted:
                domain = str(extracted["domain"]).lower().strip()
                hash_curto = hashlib.md5(str(extracted["pattern"]).encode()).hexdigest()[:6]
                key = f"code_pattern:{domain}:{hash_curto}"
                
                from src.skills.__init__ import registry
                memory_skill = registry.get("memory")
                if memory_skill:
                    await memory_skill.run(
                        action="memorize",
                        session_id=master_session_id,
                        key=key,
                        value=json.dumps(extracted),
                        tags=["code_pattern", domain]
                    )
                    logger.info("Padrão de código extraído e salvo na memória", extra={"key": key})

    async def _review_subtask(
        self, task: "AgentTask", result: "AgentResult", master_session_id: str, attempt: int = 1
    ) -> Dict[str, Any]:
        """Invoca o Agente Revisor para avaliar o resultado de uma subtarefa.

        Args:
            task: A definição da tarefa com critérios de validação.
            result: O resultado produzido pelo agente executor.
            master_session_id: ID da sessão mestra.

        Returns:
            Dicionário com o status da revisão e feedback.
        """
        from src.orchestrator import AgentTask
        from src.utils.json_parser import extract_json

        # V14.2: Reviewer executado via corrotina ValidatorAgent (sem container Docker)
        output_manager = self.orchestrator.output_manager
        # `list_artifacts` devolve dicts só de `artifacts/`; os scripts gravam em `<subtarefa>/`. O
        # revisor recebe nomes e caminhos e varre a pasta inteira da sessão (`output_dir`).
        artifacts_on_disk = [
            value
            for a in output_manager.list_artifacts(master_session_id)
            for value in ((a["name"], a["path"]) if isinstance(a, dict) else (a,))
        ]
        validator = getattr(self.orchestrator, "validator", None)
        if validator is None:
            from src.agents.validator_agent import ValidatorAgent
            validator = ValidatorAgent()

        review = await validator.review_result(
            task=task,
            response_text=result.response.get("text", ""),
            artifacts_on_disk=artifacts_on_disk,
            output_dir=output_manager.base_dir / master_session_id,
        )
        from src.llm.metering import bound_execution_id
        from src.telemetry import get_telemetry

        try:  # observabilidade nunca derruba a revisão
            get_telemetry().record_agent_event(
                execution_id=bound_execution_id() or master_session_id,
                session_id=master_session_id,
                agent_id="reviewer",
                event_type="subtask_review",
                target_agent_id=task.agent_id,
                task_name=task.task_name or None,
                payload={
                    "status": review.status,
                    "approved": review.status in ("pass", "divergent_but_documented"),
                    "feedback": (review.feedback or "")[:400],
                    "issues": [str(i)[:200] for i in (review.issues or [])][:8],
                    "attempt": attempt,
                    "signature": review.signature,
                    "resolved_artifacts": dict(list((review.resolved_artifacts or {}).items())[:12]),
                    "name_mismatch": bool(review.name_mismatch),
                    "verified": bool(getattr(review, "verified", True)),
                },
            )
        except Exception as exc:
            logger.warning("Falha ao registrar subtask_review", extra={"error": str(exc)})
        return {
            "status": review.status,
            "issues": review.issues,
            "feedback": review.feedback,
            "resolved_artifacts": review.resolved_artifacts,
            "verified": bool(getattr(review, "verified", True)),
        }

    async def _synthesize_results(
        self,
        prompt: str,
        results: List["AgentResult"],
        master_session_id: str,
        stop_reason: Optional[str] = None,
    ) -> Optional["AgentResult"]:
        """Consolida os resultados em ``relatorio_final.md`` a partir de dados estruturados.

        O orquestrador monta ``ReportData`` (disco e telemetria, sem LLM) e renderiza o Markdown;
        o Summarizer só devolve a narrativa em JSON (v16-pipeline-robustness §6).

        Args:
            prompt: Prompt original do usuário.
            results: Lista de resultados das subtarefas.
            master_session_id: ID da sessão.
            stop_reason: ``motivo_parada`` quando a sessão fecha por limite.

        Returns:
            AgentResult do Summarizer com o relatório renderizado em ``response["text"]``.
        """
        from src.orchestrator import AgentTask
        from src.report.artifact_reader import ArtifactReader
        from src.report.report_model import (
            NarrativeError,
            parse_narrative,
            render_report_markdown,
            report_data_json,
            unavailable_narrative,
        )
        from src.subtask_output import SubtaskOutput

        logger.info("Iniciando síntese final dos resultados")

        context_parts = []
        for task_name in [r.task_name for r in results if hasattr(r, "task_name") and r.task_name]:
            entry = self._short_term_memory.read(master_session_id, f"result:{task_name}")
            if entry:
                try:
                    context_parts.append(SubtaskOutput.from_json(entry.value).to_context_string())
                except Exception:
                    pass
        if not context_parts:
            for res in results:
                context_parts.append(f"### Resultado do Agente {res.agent_id}\n{res.response.get('text', '')}")

        session_dir = self.orchestrator.output_manager.base_dir / master_session_id
        data = await self._build_report_data(
            prompt, master_session_id, ArtifactReader(session_dir), stop_reason
        )

        base_prompt = (
            f"Escreva a narrativa do relatório da tarefa: '{prompt}'\n\n"
            "RESULTADOS DAS SUBTAREFAS:\n\n" + "\n\n".join(context_parts) + "\n\n"
            "DADOS DO RELATÓRIO (JSON, medidos pelo orquestrador; copie os números daqui):\n"
            f"{report_data_json(data)}\n\n"
            "Responda SOMENTE com o JSON de narrativa descrito nas suas instruções."
        )
        summary_result = None
        narrative = None
        error = "sem resposta"
        for attempt in range(2):  # uma tentativa de reparo (design §6.2)
            suffix = "" if attempt == 0 else (
                f"\n\nA resposta anterior foi recusada: {error}. Reenvie SOMENTE o JSON válido de narrativa."
            )
            task = AgentTask(agent_id="summarizer", prompt=base_prompt + suffix, task_name="final_synthesis")
            summary_result = await self.orchestrator._execute_agent(task, master_session_id)
            try:
                narrative = parse_narrative(summary_result.response.get("text", "") or "")
                break
            except NarrativeError as exc:
                error = str(exc)

        if narrative is None:
            logger.warning("Narrativa do Summarizer indisponível", extra={"error": error})
            narrative = unavailable_narrative(error)
            data = replace(data, narrativa_indisponivel=True)

        markdown = render_report_markdown(data, narrative)
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "relatorio_final.md").write_text(markdown, encoding="utf-8")
            (session_dir / "report_data.json").write_text(report_data_json(data), encoding="utf-8")
        except OSError as exc:
            logger.error("Falha ao gravar o relatório final", extra={"error": str(exc)})

        # Falha da chamada ao agente continua sendo falha; narrativa indisponível não é.
        summary_result.response = {"text": markdown}
        return summary_result

    async def _build_report_data(
        self,
        prompt: str,
        master_session_id: str,
        artifact_reader: Any,
        stop_reason: Optional[str],
    ) -> Any:
        """Monta ``ReportData`` com disco e telemetria, sem LLM e sem nunca derrubar a síntese."""
        from src.model_config import get_role_model_config, known_roles
        from src.report.report_model import ReportMetadata, build_report_data

        telemetry = get_telemetry()
        tokens_in = tokens_out = 0
        cost = 0.0
        replans = 0
        agent_runs: Dict[str, int] = {}
        sandbox_runs = 0
        try:
            await telemetry.flush()  # garante que os dados estão no banco
            rows = telemetry.get_token_summary(master_session_id).get("by_provider_model", [])
            tokens_in = sum(int(r.get("total_prompt_tokens") or 0) for r in rows)
            tokens_out = sum(int(r.get("total_completion_tokens") or 0) for r in rows)
            cost = sum(float(r.get("total_cost_usd") or 0) for r in rows)
            replans = int(telemetry.get_derived_metrics(master_session_id).get("replans") or 0)
            counts = telemetry.get_event_counts(master_session_id, ("spawn", "sandbox_run"))
            agent_runs = dict(counts.get("spawn", {}))
            sandbox_runs = sum(counts.get("sandbox_run", {}).values())
        except Exception as exc:
            logger.warning("Falha ao coletar a telemetria do relatório", extra={"error": str(exc)})

        models_by_role: Dict[str, str] = {}
        for role in known_roles():
            cfg = get_role_model_config(role)
            models_by_role[role] = f"{cfg.provider}/{cfg.model}"

        session = self.orchestrator.session_manager.get(master_session_id)
        payload = getattr(session, "payload", None)
        payload = payload if isinstance(payload, dict) else {}
        artifacts = [
            str(a.get("path", a.get("name", ""))) if isinstance(a, dict) else str(a)
            for a in self.orchestrator.output_manager.list_artifacts(master_session_id)
        ]
        metadata = ReportMetadata(
            duration_s=time.time() - getattr(self, "_session_started_at", time.time()),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            agent_runs=agent_runs,
            sandbox_runs=sandbox_runs,
            models_by_role=models_by_role,
            stop_reason=stop_reason,
            replans=replans,
        )
        first_line = (prompt.strip().splitlines() or [""])[0][:80]
        return build_report_data(
            title=f"Relatório: {first_line}" if first_line else "Relatório da Sessão",
            request=prompt,
            metrics_by_task=artifact_reader.read_subtask_metrics(),
            metadata=metadata,
            interactions=payload.get("researcher_interactions", []),
            divergence_reports=payload.get("divergence_reports", []),
            artifacts=artifacts,
        )
