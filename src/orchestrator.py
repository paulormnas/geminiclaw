"""Orquestrador principal do GeminiClaw.

Coordena a execução de múltiplos agentes no próprio processo (AgentRuntime),
gerenciando sessões e o tratamento de falhas parciais. O único uso de container é o
sandbox de código, acionado pela skill de código.
"""

import asyncio
import os
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from src.logger import get_logger
from src.config import (
    GEMINI_REQUESTS_PER_MINUTE,
    GEMINI_RATE_LIMIT_COOLDOWN_SECONDS,
    MAX_AGENT_RUNS_PER_SESSION,
    OLLAMA_ENABLE_THINKING,
    MAX_PLANNING_ITERATIONS,
    MAX_PLANNING_RUNS_PER_SESSION,
    PLAN_NORMALIZER_ENABLED,
    PLAN_REJECTION_STALL_LIMIT,
    SESSION_MAX_TASK_RETRIES,
)
from src.pipeline_errors import AgentRunLimitReached, PlanningStalled
from src.plan_normalizer import normalize_plan
from src.llm.session import SessionRouting, bind_session_routing, build_session_routing, get_session_routing
from src.session import SessionManager
from src.output_manager import OutputManager, generate_session_slug
from src.autonomous_loop import AutonomousLoop
from src.utils.json_parser import extract_json
from src.rate_limiter import AdaptiveRateLimiter
from src.llm.metering import bind_execution, bound_execution_id
from src.telemetry import get_telemetry
from src.agents.validator_agent import ValidatorAgent
from src.agent_runtime.context import AgentContext
from src.agent_runtime.runtime import AgentRuntime
from src.context_loader import ContextLoader, ContextBundle
from src.human_gate import HumanGate
from src.usage import UsageBudget, UsageTracker

if TYPE_CHECKING:
    from agents.curator.runner import Curator
    from src.knowledge.graph_store import GraphStore
    from src.knowledge.ingestion import FactIngestor
    from src.knowledge.semantic_runtime import SemanticRuntime

logger = get_logger(__name__)

# Papéis de agente que uma subtarefa pode pedir. As definições executáveis (instrução,
# ferramentas) ficam em src/agent_runtime/definitions.py.
AGENT_IDS: tuple[str, ...] = (
    "developer",
    "base",
    "researcher",
    "summarizer",
    "reviewer",
)

@dataclass
class AgentTask:
    """Definição de uma tarefa a ser executada por um agente.

    Args:
        agent_id: Identificador do agente.
        prompt: Prompt/solicitação a ser enviada ao agente.
        task_name: Identificador único da subtarefa no plano (snake_case).
        depends_on: Lista de task_names que devem concluir antes desta tarefa.
        expected_artifacts: Lista de artefatos esperados como output.
    """

    agent_id: str
    prompt: str
    task_name: str = ""
    depends_on: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    validation_criteria: list[str] = field(default_factory=list)
    preferred_model: str | None = None
    subtask_id: str | None = None  # V9: ID único para telemetria
    created_at: str | None = None  # V9: Timestamp de criação
    retry_attempt: int = 0  # V12.3.3: Número da tentativa atual (0-indexed)
    mode: str = ""  # V15.6/G10: SessionMode ("assisted" | "semi" | "auto")
    # V15.1/G1: metadados de epistemologia científica gerados pelo Researcher
    task_type: str | None = None  # "reproduction" | "eda" | "model_impl" | "validation" | "synthesis"
    hypothesis: str = ""  # o que esta subtarefa testa ou produz
    scientific_rationale: str = ""  # por que esta etapa é metodologicamente necessária
    # v17-structural-fact-ingestion: abordagem declarada pelo Researcher ({"nome", "tipo", "descricao"?}).
    approach: dict[str, str] | None = None


@dataclass
class AgentResult:
    """Resultado da execução de um agente.

    Args:
        agent_id: Identificador do agente.
        session_id: ID da sessão associada.
        status: Status da execução ("success", "error", "timeout").
        response: Payload da resposta do agente.
        error: Mensagem de erro, se houver.
        error_category: Categoria estruturada da falha de infraestrutura, se conhecida.
    """

    agent_id: str
    session_id: str
    status: str
    response: dict[str, Any]
    error: str | None = None
    # Categoria estruturada de falha de infraestrutura (``llm_connection``); ``None`` quando
    # desconhecida. Usada pela ingestão de fatos (v17-structural-fact-ingestion), sem heurística de texto.
    error_category: str | None = None


@dataclass
class OrchestratorResult:
    """Resultado consolidado da orquestração.

    Args:
        results: Lista de resultados individuais dos agentes.
        total: Total de agentes executados.
        succeeded: Quantidade que finalizou com sucesso.
        failed: Quantidade que falhou.
    """

    results: list[AgentResult]
    total: int
    succeeded: int
    failed: int
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    plan_json: str | None = None
    session_id: str | None = None  # V15.5/G9: id da sessão mestra (usado para input_snapshot/)


class Orchestrator:
    """Orquestrador principal que coordena os agentes em processo.

    Recebe uma solicitação, planeja as subtarefas, executa os agentes pelo
    ``AgentRuntime`` e consolida os resultados.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        output_manager: OutputManager | None = None,
        agent_runtime: AgentRuntime | None = None,
        knowledge_store_factory: "Callable[[], GraphStore] | None" = None,
        knowledge_runtime_factory: "Callable[[], SemanticRuntime] | None" = None,
    ) -> None:
        """Inicializa o orquestrador com dependências injetadas.

        Args:
            session_manager: Gerenciador de sessões.
            output_manager: Gerenciador de outputs (opcional).
            agent_runtime: Runtime de agentes em processo (Roadmap V16/ADR 014).
                Se omitido, uma instância padrão é criada.
            knowledge_store_factory: Abre o grafo de conhecimento para a ingestão de fatos
                (v17-structural-fact-ingestion). Se omitido, usa ``open_graph_store``; o grafo só
                é aberto em sessões com projeto.
            knowledge_runtime_factory: Abre o grafo **com** o índice semântico e a fila de similaridade
                (``SemanticRuntime``), usados pelo Curator (v17-curator-agent) e pela reconciliação do
                índice no início da sessão. Se omitido (e sem ``knowledge_store_factory``), usa
                ``factory.open_knowledge_runtime``.
        """
        self.session_manager = session_manager
        self.output_manager = output_manager or OutputManager()
        self.rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=GEMINI_REQUESTS_PER_MINUTE,
            cooldown_seconds=GEMINI_RATE_LIMIT_COOLDOWN_SECONDS,
        )
        self.validator = ValidatorAgent()
        # Roadmap V16/ADR 014 — Rastreia execuções de agente por master_session_id
        self._session_agent_run_counts: dict[str, int] = {}
        self._session_planning_run_counts: dict[str, int] = {}
        self._session_plan_size: dict[str, int] = {}
        # V18/researcher-consult — resumo do plano aprovado, rastreadores de uso e contagem de
        # consultas por sessão mestra; provedor e skills do consultor são injetáveis (testes).
        self._session_plan_summary: dict[str, str] = {}
        self._usage_trackers: dict[str, UsageTracker] = {}
        self._session_consult_counts: dict[str, int] = {}
        self.consult_provider: Any = None
        self.consult_search_skill: Any = None
        self.consult_reader_skill: Any = None
        # Modo efetivo por sessão mestra: tarefas criadas sem `mode` (ex.: o planejamento do Researcher)
        # herdam o modo da sessão em vez do padrão global (que é `assisted` e bloquearia em stdin).
        self._session_modes: dict[str, str] = {}
        # V15.5/G9 — Bloco de texto do ContextBundle ativo, injetado no plano inicial do Researcher
        self._current_context_block: str = ""
        # Bloco do Problema por sessão mestra (evita vazar entre requisições concorrentes).
        self._project_blocks: dict[str, str] = {}
        self.agent_runtime = agent_runtime or AgentRuntime()
        # v17-structural-fact-ingestion — ingestor de fatos por sessão mestra e grafo compartilhado.
        self._knowledge_store_factory = knowledge_store_factory
        self._knowledge_runtime_factory = knowledge_runtime_factory
        self._knowledge_store: GraphStore | None = None
        self._knowledge_runtime: SemanticRuntime | None = None
        self._ingestors: dict[str, FactIngestor] = {}
        # v17-curator-agent — Curator por sessão mestra; provedor injetável (testes); gate de decisões reservadas.
        self._curators: dict[str, Curator] = {}
        self.curator_provider: Any = None
        self.human_gate = HumanGate()

    def _open_knowledge_store(self) -> "GraphStore":
        """Abre (uma vez) o grafo para a ingestão; falhas propagam e o ``FactIngestor`` as enfileira.

        Sem fábrica de ``GraphStore`` injetada, abre o ``SemanticRuntime`` (store **indexado**, fila de similaridade
        e índice) por ``factory.open_knowledge_runtime``; com o índice desligado, o store cru.
        """
        if self._knowledge_store is None:
            factory = self._knowledge_store_factory
            if factory is not None:
                self._knowledge_store = factory()
            else:
                runtime_factory = self._knowledge_runtime_factory
                if runtime_factory is None:
                    from src.knowledge.factory import open_knowledge_runtime as runtime_factory
                runtime = runtime_factory()
                if runtime is None:
                    from src.knowledge.factory import open_raw_graph_store

                    self._knowledge_store = open_raw_graph_store()
                else:
                    self._knowledge_runtime = runtime
                    self._knowledge_store = runtime.store
        return self._knowledge_store

    def _reconcile_knowledge_index(self) -> None:
        """Reconciliação do índice semântico no início da sessão, antes de qualquer consulta ao grafo.

        Nunca levanta: sem grafo ou com o índice fora do ar, a sessão segue (o grafo é a fonte da verdade e a
        próxima reconciliação corrige).
        """
        try:
            self._open_knowledge_store()
            runtime = self._knowledge_runtime
            if runtime is not None:
                from src.knowledge.semantic_runtime import reconcile_on_session_start

                reconcile_on_session_start(runtime)
        except Exception as exc:  # noqa: BLE001 - a sessão não depende do índice para começar
            logger.warning("Reconciliação do índice não executada", extra={"error": type(exc).__name__})

    # -- v17-curator-agent ----------------------------------------------------------------------------------

    def get_curator(self, session_id: str) -> "Curator | None":
        """Curator da sessão mestra (``None`` sem projeto, com o Curator desligado ou sem grafo)."""
        from src import config as cfg

        if not cfg.CURATOR_ENABLED:
            return None
        existing = self._curators.get(session_id)
        if existing is not None:
            return existing
        ingestor = self._ingestors.get(session_id)
        if ingestor is None:
            return None
        try:
            from agents.curator.runner import Curator

            store = self._open_knowledge_store()
            runtime = self._knowledge_runtime
            provider = self.curator_provider

            def _provider() -> Any:
                if provider is not None:
                    return provider
                from src.model_router import ModelRouter

                return ModelRouter.get_provider("curator")

            def _telemetry(event_type: str, payload: dict[str, Any]) -> None:
                get_telemetry().record_agent_event(
                    execution_id=session_id,
                    session_id=session_id,
                    agent_id="curator",
                    event_type=event_type,
                    payload=payload,
                    duration_ms=payload.get("duration_ms"),
                )

            curator = Curator(
                store,
                project_id=ingestor.ctx.project_id,
                session_id=session_id,
                session_dir=self.output_manager.base_dir / session_id,
                provider_factory=_provider,
                index=runtime.index if runtime is not None else None,
                queue=runtime.queue if runtime is not None else None,
                telemetry=_telemetry,
            )
        except Exception as exc:  # noqa: BLE001 - sem Curator a sessão continua
            logger.warning("Curator indisponível nesta sessão", extra={"error": type(exc).__name__})
            return None
        self._curators[session_id] = curator
        return curator

    def _curator_budget_left(self, session_id: str, *, closing: bool) -> bool:
        """O Curator só roda com orçamento: no meio da sessão, fora do fechamento; no fim, com a reserva de tokens."""
        tracker = self._usage_trackers.get(session_id)
        if tracker is None:
            return True
        try:
            return not (tracker.tokens_hard_exhausted() if closing else tracker.check().should_close)
        except Exception:  # noqa: BLE001 - sem leitura de consumo, segue (o orçamento do Curator é próprio)
            return True

    async def curator_consolidate(self, session_id: str) -> None:
        """Checkpoint de consolidação (fim de cada ciclo de planejamento). Nunca levanta."""
        curator = self.get_curator(session_id)
        if curator is None or not self._curator_budget_left(session_id, closing=False):
            return
        try:
            await curator.consolidate()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a falha do Curator nunca derruba a sessão
            logger.warning("Consolidação do Curator falhou", extra={"error": type(exc).__name__})

    async def curator_close(self, session_id: str) -> None:
        """Fechamento da sessão pelo Curator (fila de similaridade e caminhos sem conclusão). Nunca levanta."""
        curator = self.get_curator(session_id)
        try:
            if curator is None or not self._curator_budget_left(session_id, closing=True):
                return
            session = self.session_manager.get(session_id)
            reason = (session.payload if session is not None else {}).get("motivo_parada")
            await curator.close_session(reason if isinstance(reason, str) else None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fechamento do Curator falhou", extra={"error": type(exc).__name__})
        finally:
            self._curators.pop(session_id, None)

    def knowledge_after_subtask(self, session_id: str, subtarefa_id: str) -> None:
        """Recálculo determinístico (sem LLM) após uma subtarefa ingerida (v17-curator-agent task 2.5).

        Síncrono (chamado via ``asyncio.to_thread``). Nunca levanta: sem grafo, a ingestão já enfileirou os fatos e
        o recálculo acontece quando eles forem aplicados.
        """
        ingestor = self._ingestors.get(session_id)
        if ingestor is None:
            return
        try:
            from src.knowledge.service import KnowledgeService

            report = KnowledgeService(self._open_knowledge_store()).after_subtask(ingestor.ctx.project_id, subtarefa_id)
            get_telemetry().record_agent_event(
                execution_id=session_id,
                session_id=session_id,
                agent_id="orchestrator",
                event_type="knowledge_recompute",
                payload={
                    "hipoteses": report.hipoteses,
                    "descobertas": report.descobertas,
                    "promovidas": len(report.promovidas),
                    "ignoradas": report.ignoradas,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Recálculo do veredito não executado", extra={"error": type(exc).__name__})

    def _register_reserved(self, decisao: str | None, task: "AgentTask") -> None:
        """Registra no gate a decisão reservada como pendente para o pesquisador (a resposta do consultor não vale)."""
        if not decisao:
            return
        try:
            self.human_gate.request(decisao, task.task_name or "")
        except ValueError:
            logger.warning("Decisão reservada desconhecida; tratada como pendente sem registro no gate")

    @staticmethod
    async def _safe_ingest(fn: "Callable[[], Any]") -> None:
        """Roda uma etapa de ingestão fora do event loop; nenhuma falha de conhecimento derruba a sessão."""
        try:
            await asyncio.to_thread(fn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ingestão de fatos falhou", extra={"error": type(exc).__name__})

    def get_ingestor(self, session_id: str) -> "FactIngestor | None":
        """Ingestor de fatos da sessão mestra (``None`` em sessões sem projeto)."""
        return self._ingestors.get(session_id)

    def _start_ingestor(
        self, session_id: str, project_id: str | None, mode: str, start_date: str, continues: object
    ) -> "FactIngestor | None":
        """Cria o ingestor de fatos da sessão; sem projeto (``sem_grafo``/bypass) não há ingestão."""
        if not project_id:
            return None
        from src.config import NODE_ID
        from src.knowledge.ingestion import FactIngestor, SessionContext

        ctx = SessionContext(
            project_id=project_id,
            session_id=session_id,
            modo=mode,
            inicio=start_date,
            no_execucao=NODE_ID,
            continues_session_id=continues if isinstance(continues, str) else None,
        )

        def _telemetry(kind: str, info: dict[str, Any], duration_ms: int) -> None:
            get_telemetry().record_agent_event(
                execution_id=session_id,
                session_id=session_id,
                agent_id="orchestrator",
                event_type="knowledge_ingestion",
                payload={"kind": kind, **info},
                duration_ms=duration_ms,
            )

        self.output_manager.init_session(session_id)
        ingestor = FactIngestor(
            self._open_knowledge_store, ctx, self.output_manager.base_dir / session_id, telemetry=_telemetry
        )
        self._ingestors[session_id] = ingestor
        return ingestor

    def _end_ingestion(
        self, ingestor: "FactIngestor | None", session_id: str, status: str, exc: BaseException | None
    ) -> None:
        """Fim da sessão no grafo: ``fim``, ``motivo_parada`` e ``consumo`` (síncrono, sem LLM).

        Com ``exc`` (caminho de exceção/Ctrl+C) o evento só é enfileirado, sem acessar o grafo. Nunca
        levanta: a sessão não para por falha de conhecimento.
        """
        if ingestor is None:
            return
        try:
            self._end_ingestion_unsafe(ingestor, session_id, status, exc)
        except Exception as err:  # noqa: BLE001
            logger.warning("Fim da sessão não registrado no grafo", extra={"error": type(err).__name__})
        finally:
            self._ingestors.pop(session_id, None)

    def _end_ingestion_unsafe(
        self, ingestor: "FactIngestor", session_id: str, status: str, exc: BaseException | None
    ) -> None:
        from datetime import datetime, timezone

        from src.knowledge.ingestion import MOTIVOS_PARADA

        session = self.session_manager.get(session_id)
        payload = session.payload if session is not None else {}
        reason = payload.get("motivo_parada")
        if exc is not None:
            reason = "interrompida" if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)) else "erro"
        elif reason not in MOTIVOS_PARADA:
            reason = "solucao_encontrada" if status == "success" else "erro"
        consumo: dict[str, Any] = {}
        tracker = self._usage_trackers.get(session_id)
        if tracker is not None:
            try:
                usage = tracker.check()
                consumo = {
                    "tokens": usage.tokens_used,
                    "minutos": round(usage.minutes_elapsed, 2),
                    "retentativas_conexao": usage.connection_retries,
                }
            except Exception as err:  # noqa: BLE001 - o consumo é complementar; nunca derruba o fim da sessão
                logger.warning("Consumo da sessão indisponível para a ingestão", extra={"error": type(err).__name__})
        ingestor.session_end(
            fim=datetime.now(timezone.utc).isoformat(),
            motivo_parada=reason,
            consumo=consumo,
            offline=exc is not None,
        )

    @staticmethod
    def get_available_agents() -> tuple[str, ...]:
        """Retorna os papéis de agente que uma subtarefa pode pedir.

        Returns:
            Tupla com os identificadores de papel (ex.: ``"researcher"``).
        """
        return AGENT_IDS

    async def handle_request(
        self,
        prompt: str,
        agent_tasks: list[AgentTask] | None = None,
        mode: str | None = None,
        context_bundle: ContextBundle | None = None,
        budget: UsageBudget | None = None,
        llm_routing: SessionRouting | None = None,
        project_id: str | None = None,
        project_context: str | None = None,
        project_mode: str | None = None,
    ) -> OrchestratorResult:
        """Processa a solicitação do usuário, executando o ciclo de vida completo.

        Args:
            prompt: O prompt ou tarefa solicitada.
            agent_tasks: Lista de tarefas (opcional) para bypassar o autonomous loop.
            mode: Nível de autonomia da sessão (SessionMode). Se omitido, usa
                ``SESSION_DEFAULT_MODE`` (Roadmap V15.6 / Spec G10).
            context_bundle: Contexto pré-carregado de ``input_context/`` (Spec G9).
                Se omitido, é carregado internamente via ``ContextLoader``.
            budget: Orçamento de uso da sessão (Roadmap V18 / Spec `usage-limits`).
                Se omitido, usa os defaults de ``src/config.py`` via
                ``UsageBudget.from_config()``.
            llm_routing: Mapa resolvido de modelos por papel (ADR 017), normalmente resolvido
                pela CLI antes do banner. Se omitido, é resolvido aqui, antes de qualquer
                chamada de LLM; sem modelo elegível, levanta ``RoutingError`` e a sessão
                não começa.
            project_id: Projeto de pesquisa da sessão (v17-research-project); gravado em
                ``payload["project_id"]``.
            project_context: Bloco com título, resumo e critério do ``Problema`` confirmado,
                injetado no planejamento do Researcher junto ao contexto de ``input_context/``.
            project_mode: ``"sem_grafo"`` quando o grafo estava fora do ar e o contorno explícito
                está ligado; gravado em ``payload["project_mode"]``.

        Returns:
            O resultado final da orquestração.
        """
        import time
        import json
        from src.history import ExecutionHistory
        from datetime import datetime
        from src.config import SESSION_DEFAULT_MODE

        started_at = time.time()
        start_date = datetime.utcnow().isoformat() + "Z"

        effective_mode = mode or SESSION_DEFAULT_MODE
        if project_id:
            from src.knowledge.projects import validate_project_id

            project_id = validate_project_id(project_id)  # UUID; falha explícita antes de criar a sessão

        # ADR 017 — resolve o modelo de cada papel uma única vez, antes da sessão e de qualquer
        # chamada de LLM; o mapa vale até o fim da sessão (sem troca no meio).
        routing = llm_routing or await build_session_routing()
        bind_session_routing(routing)

        logger.info(
            "Nova requisição recebida no orquestrador",
            extra={"prompt_preview": prompt[:50], "mode": effective_mode},
        )

        # Gera slug legível para a sessão (V10.2)
        session_slug = generate_session_slug(prompt)

        master_session = self.session_manager.create("orchestrator", session_id=session_slug)

        # V18/usage-limits — orçamento efetivo da sessão (CLI > config), gravado no
        # payload da sessão para consulta/depuração e exibição no início da sessão.
        effective_budget = budget or UsageBudget.from_config()

        # V15.6/G10 — Persiste o modo de operação no payload da sessão mestra
        self.session_manager.update(
            master_session.id,
            payload={
                **master_session.payload,
                "mode": effective_mode,
                "prompt": prompt,
                "budget": effective_budget.to_payload(),
                "llm_routing": routing.payload(),
                **({"project_id": project_id} if project_id else {}),
                **({"project_mode": project_mode} if project_mode else {}),
            },
        )

        # v17-structural-fact-ingestion — fatos da sessão no grafo (só com projeto), sem LLM.
        ingestor = self._start_ingestor(
            master_session.id,
            project_id,
            effective_mode,
            start_date,
            master_session.payload.get("continues_session_id"),
        )
        if ingestor is not None:
            # v17-knowledge-semantic-index: reconcilia o índice antes de qualquer consulta ao grafo da sessão.
            await asyncio.to_thread(self._reconcile_knowledge_index)
            await self._safe_ingest(ingestor.session_start)

        # V15.5/G9 — Carrega (ou reutiliza) o contexto de input_context/ e o disponibiliza
        # para o Researcher no primeiro ciclo de planejamento; salva snapshot imutável.
        # O carregamento automático só ocorre no caminho real de uso (loop autônomo):
        # `agent_tasks` é um bypass de compatibilidade para chamadores programáticos que
        # montam seu próprio plano (sem Researcher), logo não há prompt de planejamento
        # para injetar contexto — evitamos o custo (e o I/O) quando não é utilizável.
        bundle = context_bundle
        if bundle is None and not agent_tasks:
            bundle = ContextLoader().load()
        if bundle is not None:
            self._current_context_block = bundle.to_prompt_context()
            self.output_manager.init_session(master_session.id)
            self._snapshot_input_context(bundle, master_session.id)
            if ingestor is not None:
                await self._safe_ingest(ingestor.inputs)
        # v17-research-project — o problema do projeto vai em todo planejamento (plano e replans).
        self._project_blocks[master_session.id] = project_context or ""

        # V5.6 — Telemetria: evento de início de execução
        telemetry = get_telemetry()
        history = ExecutionHistory()
        exec_id = history.start(prompt, start_date, exec_id=session_slug)
        bind_execution(exec_id or master_session.id, master_session.id)
        self._session_modes[master_session.id] = effective_mode
        telemetry.record_agent_event(
            execution_id=exec_id or master_session.id,
            session_id=master_session.id,
            agent_id="orchestrator",
            event_type="session_start",
            payload={
                "catalog_hash": routing.catalogo.hash,
                "catalog_version": routing.catalogo.versao,
                "llm_data_policy": routing.politica,
                "llm_routing": routing.modo,
            },
        )

        logger.info("Nova requisição registrada", extra={"execution_id": exec_id, "prompt_preview": prompt[:50]})

        try:
            # Se tarefas explícitas forem fornecidas, executa sequencialmente (compatibilidade)
            if agent_tasks:
                logger.info("Executando tarefas explícitas fornecidas (bypass autonomous loop)")
                results = []
                for task in agent_tasks:
                    task.mode = task.mode or effective_mode
                    result = await self._execute_agent(task, master_session.id)
                    results.append(result)

                succeeded = sum(1 for r in results if r.status == "success")
                failed = len(results) - succeeded
                all_artifacts = self.output_manager.list_artifacts(master_session.id)

                result = OrchestratorResult(
                    results=results,
                    total=len(results),
                    succeeded=succeeded,
                    failed=failed,
                    artifacts=all_artifacts,
                    plan_json=json.dumps([t.__dict__ for t in agent_tasks])
                )
            else:
                # Caso contrário, usa o loop autônomo (Etapa S7)
                loop = AutonomousLoop(self)
                result = await loop.run(
                    prompt, exec_id or master_session.id, mode=effective_mode, budget=effective_budget
                )
        except BaseException as run_exc:  # noqa: BLE001 - registra o fim da sessão no grafo e repropaga
            self._end_ingestion(ingestor, master_session.id, "failed", run_exc)
            raise

        # Atualiza a sessão mestra com o resultado consolidado.
        # V18/usage-limits — o payload é mesclado (não substituído) para preservar
        # campos gravados durante a execução (budget, motivo_parada,
        # researcher_interactions, divergence_reports).
        final_status = "success" if result.succeeded == result.total and result.total > 0 else "failed"
        pre_final_session = self.session_manager.get(master_session.id)
        pre_final_payload = pre_final_session.payload if pre_final_session is not None else {}
        self.session_manager.update(
            master_session.id,
            status=final_status,
            payload={
                **pre_final_payload,
                "prompt": prompt,
                "mode": effective_mode,
                "summary": {
                    "total": result.total,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "artifacts_count": len(result.artifacts)
                }
            }
        )
        if ingestor is not None:
            # v17-curator-agent: o Curator fecha a sessão (fila de similaridade, caminhos sem conclusão) antes de
            # o fim da sessão ir ao grafo; qualquer falha dele é isolada.
            await self.curator_close(master_session.id)
            await asyncio.to_thread(self._end_ingestion, ingestor, master_session.id, final_status, None)
        self.session_manager.close(master_session.id)
        
        # Etapa V14: Salva no histórico de execuções
        finished_at = time.time()
        duration = finished_at - started_at
        end_date = datetime.utcnow().isoformat() + "Z"
        
        if exec_id:
            history.finish(
                exec_id=exec_id,
                status=final_status,
                finished_at=end_date,
                duration_seconds=duration,
                plan_json=result.plan_json,
                results_json=json.dumps([r.__dict__ for r in result.results]),
                artifacts_json=json.dumps(result.artifacts),
                total_subtasks=result.total,
                succeeded=result.succeeded,
                failed=result.failed
            )
            logger.info("Execução finalizada no histórico", extra={"execution_id": exec_id})

        # V5.6 — Telemetria: evento de fim de execução
        if exec_id:
            telemetry.record_agent_event(
                execution_id=exec_id,
                session_id=master_session.id,
                agent_id="orchestrator",
                event_type="complete",
                payload={
                    "status": final_status,
                    "total": result.total,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "duration_ms": int(duration * 1000),
                },
                duration_ms=int(duration * 1000),
            )
            await telemetry.flush()
        
        # V10.2: Salva plano e resultados no diretório da sessão para facilitar consulta manual
        try:
            session_dir = self.output_manager.base_dir / master_session.id
            if result.plan_json:
                (session_dir / "plan.json").write_text(result.plan_json, encoding="utf-8")

            # Converte resultados para formato serializável
            serializable_results = [r.__dict__ for r in result.results]
            (session_dir / "results.json").write_text(json.dumps(serializable_results, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Falha ao salvar artefatos de metadados na sessão: {e}")

        # Roadmap V15.4 / Spec G8 — session_metadata.json: registro definitivo da
        # execução (interações, métricas, custo) para consulta e para os conversores
        # de formato (geminiclaw convert).
        try:
            final_session = self.session_manager.get(master_session.id)
            final_payload = final_session.payload if final_session is not None else master_session.payload
            token_summary = telemetry.get_token_summary(exec_id or master_session.id)
            token_rows = token_summary.get("by_provider_model", [])
            total_tokens = sum(r.get("total_tokens") or 0 for r in token_rows)
            total_cost = sum(r.get("total_cost_usd") or 0 for r in token_rows)

            session_metadata = {
                "session_id": master_session.id,
                "task": prompt,
                "mode": effective_mode,
                "started_at": start_date,
                "ended_at": end_date,
                "duration_seconds": duration,
                "subtasks": [r.__dict__ for r in result.results],
                "researcher_interactions": final_payload.get("researcher_interactions", []),
                "divergence_reports": final_payload.get("divergence_reports", []),
                "token_usage": {"total_tokens": total_tokens, "by_provider_model": token_rows},
                "cost_usd": total_cost,
                "agent_runs": self._session_agent_run_counts.get(master_session.id, 0),
                "planning_runs": self._session_planning_run_counts.get(master_session.id, 0),
                "report_path": "relatorio_final.md",
            }
            (session_dir / "session_metadata.json").write_text(
                json.dumps(session_metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Falha ao salvar session_metadata.json: {e}")

        result.session_id = master_session.id
        return result

    def _snapshot_input_context(self, bundle: ContextBundle, session_id: str) -> None:
        """Copia os arquivos de ``input_context/`` usados para ``outputs/<session_id>/input_snapshot/``
        (Roadmap V15.5 / Spec G9), garantindo rastreabilidade imutável da sessão.
        """
        if bundle.total_files == 0:
            return

        import shutil

        snapshot_dir = self.output_manager.base_dir / session_id / "input_snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        source_paths = (
            [d.source_path for d in bundle.text_documents]
            + [d.source_path for d in bundle.structured_data]
            + [d.source_path for d in bundle.images]
            + bundle.raw_files
        )
        for src_path in source_paths:
            try:
                shutil.copy2(src_path, snapshot_dir / src_path.name)
            except Exception as e:
                logger.warning(
                    "Falha ao copiar arquivo para input_snapshot/",
                    extra={"path": str(src_path), "error": str(e)},
                )

        logger.info(
            "input_snapshot/ salvo",
            extra={"session_id": session_id, "files": len(source_paths)},
        )

    async def _ask_researcher_core(
        self,
        question: str,
        context: str,
        why_cant_proceed: str,
        options: list[str],
        task: AgentTask,
        master_session_id: str | None,
    ) -> str:
        """Núcleo de ``ask_researcher``, chamado pelo callback do ``AgentContext`` (Roadmap
        V16/ADR 014): reutiliza uma resposta anterior similar se houver, ou exibe a pergunta
        e bloqueia aguardando a resposta do pesquisador via stdin.

        Args:
            question: Pergunta objetiva para o pesquisador.
            context: Contexto relevante para a decisão.
            why_cant_proceed: Por que o agente não pode decidir sozinho.
            options: Opções sugeridas ao pesquisador.
            task: Tarefa em execução no momento da pergunta.
            master_session_id: ID da sessão mestra, usado para persistência/dedup.

        Returns:
            A resposta do pesquisador (ou reaproveitada de uma pergunta similar anterior).
        """
        import asyncio as _asyncio
        from src.utils.terminal import RESET, BOLD, YELLOW, CYAN, DIM

        session_key = master_session_id or task.task_name or "unknown"

        cached_answer = self._find_similar_researcher_answer(session_key, question)
        if cached_answer is not None:
            logger.info(
                "ask_researcher: pergunta similar já respondida nesta sessão — reutilizando resposta",
                extra={"question": question[:100], "session_id": session_key},
            )
            return cached_answer

        print(f"\n{YELLOW}{BOLD}❓ O agente '{task.agent_id}' está bloqueado e precisa da sua ajuda:{RESET}")
        print(f"  {BOLD}Pergunta:{RESET} {question}")
        if context:
            print(f"  {DIM}Contexto: {context}{RESET}")
        if why_cant_proceed:
            print(f"  {DIM}Por que não pode prosseguir sozinho: {why_cant_proceed}{RESET}")
        if options:
            print(f"  {CYAN}Opções:{RESET}")
            for i, opt in enumerate(options, start=1):
                print(f"    [{i}] {opt}")

        answer = await _asyncio.to_thread(input, f"  {BOLD}Sua resposta:{RESET} ")

        self._record_researcher_interaction(session_key, question, why_cant_proceed, options, answer, task)
        return answer

    def _find_similar_researcher_answer(self, session_key: str, question: str) -> str | None:
        """Procura, nas interações já registradas na sessão, uma pergunta textualmente
        similar (Roadmap V15.3 / Spec G5) — evita perguntar a mesma dúvida duas vezes.

        Usa ``difflib.SequenceMatcher`` como heurística de similaridade textual (sem
        dependência de embeddings/Qdrant, suficiente para o caso de uso: perguntas quase
        idênticas repetidas na mesma sessão). Só interações que tiveram resposta real
        (do pesquisador ou do consultor) são reaproveitadas; suposições e pendências não.
        """
        import difflib
        from src.config import ASK_RESEARCHER_DEDUP_SIMILARITY
        from src.research_consult import RESPONDIDO_PESQUISADOR, RESPONDIDO_RESEARCHER

        session = self.session_manager.get(session_key)
        if session is None:
            return None
        interactions = session.payload.get("researcher_interactions", []) or []
        for interaction in interactions:
            # Registros anteriores à V18 não têm `respondido_por`: eram respostas do pesquisador.
            if interaction.get("respondido_por", RESPONDIDO_PESQUISADOR) not in (
                RESPONDIDO_PESQUISADOR,
                RESPONDIDO_RESEARCHER,
            ):
                continue
            prior_question = interaction.get("question", "")
            ratio = difflib.SequenceMatcher(None, question.lower(), prior_question.lower()).ratio()
            if ratio >= ASK_RESEARCHER_DEDUP_SIMILARITY:
                return interaction.get("researcher_response")
        return None

    def _record_researcher_interaction(
        self,
        session_key: str,
        question: str,
        why_cant_proceed: str,
        options: list[str],
        answer: str,
        task: AgentTask,
        *,
        respondido_por: str = "pesquisador",
        context: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persiste uma interação ask_researcher no payload da sessão (Roadmap V15.3 / Spec G5;
        campos de auditoria da V18, design §6).

        Returns:
            O registro gravado.
        """
        from datetime import datetime, timezone

        session = self.session_manager.get(session_key)
        payload = dict(session.payload) if session is not None else {}
        interactions = list(payload.get("researcher_interactions", []))
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "respondido_por": respondido_por,
            "agente": task.agent_id,
            "subtask_name": task.task_name,
            "execution_id": session_key,
            "question": question,
            "context": context,
            "why_cant_proceed": why_cant_proceed,
            "options": options,
            "researcher_response": answer,
            **(extra or {}),
        }
        interactions.append(record)
        payload["researcher_interactions"] = interactions
        self.session_manager.update(session_key, payload=payload)
        logger.info(
            "Interação ask_researcher persistida",
            extra={"session_id": session_key, "subtask_name": task.task_name, "respondido_por": respondido_por},
        )
        return record

    def register_usage_tracker(self, master_session_id: str, tracker: UsageTracker) -> None:
        """Registra o ``UsageTracker`` da sessão (criado pelo ``AutonomousLoop``), para que o
        consultor respeite o orçamento de tokens/tempo (V18 / Spec `researcher-consult`)."""
        self._usage_trackers[master_session_id] = tracker

    def _consult_provider(self) -> Any:
        if self.consult_provider is not None:
            return self.consult_provider
        from src.model_router import ModelRouter

        return ModelRouter.get_provider("researcher")

    async def _consult_researcher_core(
        self,
        question: str,
        context: str,
        why_cant_proceed: str,
        options: list[str],
        decisao_reservada: str | None,
        task: AgentTask,
        master_session_id: str | None,
    ) -> str:
        """Núcleo de ``ask_researcher`` nos modos ``semi``/``auto`` (V18 / Spec
        `researcher-consult`, design §1): decisão reservada, deduplicação, limites, Researcher
        consultor, registro e telemetria. Nunca lê o terminal e nunca propaga falha do consultor:
        qualquer impedimento vira a suposição documentada, com ``motivo_fallback`` registrado.

        Returns:
            O texto devolvido ao agente que perguntou.
        """
        import asyncio as _asyncio

        from agents.researcher.consult import format_answer, run_consult
        from src import config as cfg
        from src.research_consult import (
            PENDENTE_PESQUISADOR,
            RESERVED_MESSAGE,
            RESPONDIDO_RESEARCHER,
            RESPONDIDO_SUPOSICAO,
            assumption_text,
            classify_reserved,
        )
        from src.research_consult.query_guard import protected_file_names

        session_key = master_session_id or task.task_name or "unknown"
        mode = task.mode or self._session_modes.get(session_key, "") or "auto"

        def _finish(
            respondido_por: str,
            answer: str,
            motivo: str | None,
            consulta: dict[str, Any] | None = None,
            reutilizada: bool = False,
        ) -> str:
            extra: dict[str, Any] = {"motivo_fallback": motivo}
            if reutilizada:
                extra["reutilizada"] = True
            if consulta:
                extra["consulta"] = consulta
            record = self._record_researcher_interaction(
                session_key, question, why_cant_proceed, options, answer, task,
                respondido_por=respondido_por, context=context, extra=extra,
            )
            try:
                get_telemetry().record_agent_event(
                    execution_id=session_key,
                    session_id=session_key,
                    agent_id=task.agent_id,
                    event_type="researcher_consult",
                    task_name=task.task_name or None,
                    payload={
                        k: record[k]
                        for k in ("respondido_por", "agente", "subtask_name", "question", "motivo_fallback")
                    }
                    | ({"consulta": consulta} if consulta else {}),
                )
            except Exception as exc:  # telemetria nunca derruba a pergunta do agente
                logger.warning("Falha ao gravar evento researcher_consult", extra={"error": str(exc)})
            return answer

        # 1. Decisão reservada ao humano: nunca responder (valor desconhecido também é reservado).
        # Além da autodeclaração do agente, classifica a pergunta por palavras-chave (fail-closed).
        decisao_reservada = decisao_reservada or classify_reserved(question)
        if decisao_reservada:
            self._register_reserved(decisao_reservada, task)
            return _finish(PENDENTE_PESQUISADOR, RESERVED_MESSAGE, None, {"decisao_reservada": decisao_reservada})

        # 2. Consultor desligado.
        if not cfg.RESEARCHER_CONSULT_ENABLED:
            return _finish(RESPONDIDO_SUPOSICAO, assumption_text(mode, question), "desligado")

        # 3. Pergunta similar já respondida.
        cached_answer = self._find_similar_researcher_answer(session_key, question)
        if cached_answer is not None:
            logger.info(
                "ask_researcher: pergunta similar já respondida nesta sessão — reutilizando resposta",
                extra={"question": question[:100], "session_id": session_key},
            )
            return _finish(RESPONDIDO_RESEARCHER, cached_answer, None, reutilizada=True)

        # 4. Limite de consultas e orçamento.
        if self._session_consult_counts.get(session_key, 0) >= cfg.RESEARCHER_CONSULT_MAX_PER_SESSION:
            return _finish(
                RESPONDIDO_SUPOSICAO, assumption_text(mode, question, "limite_consultas"), "limite_consultas"
            )
        tracker = self._usage_trackers.get(session_key)
        if tracker is None:
            logger.warning(
                "Consulta ao Researcher sem UsageTracker: orçamento de tokens/tempo não é verificado",
                extra={"session_id": session_key},
            )
        elif tracker.check().should_close:
            return _finish(RESPONDIDO_SUPOSICAO, assumption_text(mode, question, "orcamento"), "orcamento")
        # A vaga é reservada antes do await: consultas concorrentes não furam o limite.
        self._session_consult_counts[session_key] = self._session_consult_counts.get(session_key, 0) + 1

        # 5. Consultor, com timeout.
        web = cfg.RESEARCHER_CONSULT_WEB_ENABLED
        try:
            if web:
                if self.consult_search_skill is None:
                    from src.skills.search_quick.skill import QuickSearchSkill

                    self.consult_search_skill = QuickSearchSkill()
                if self.consult_reader_skill is None:
                    from src.skills.web_reader.skill import WebReaderSkill

                    self.consult_reader_skill = WebReaderSkill()
            outcome = await _asyncio.wait_for(
                run_consult(
                    self._consult_provider(),
                    question=question,
                    context=context,
                    why_cant_proceed=why_cant_proceed,
                    options=options,
                    agent_role=task.agent_id,
                    subtask_name=task.task_name,
                    plan_summary=self._session_plan_summary.get(session_key, ""),
                    protected_names=protected_file_names(self.output_manager.base_dir / session_key),
                    web_enabled=web,
                    search_skill=self.consult_search_skill,
                    reader_skill=self.consult_reader_skill,
                    max_searches=cfg.RESEARCHER_CONSULT_MAX_SEARCHES,
                    max_reads=cfg.RESEARCHER_CONSULT_MAX_READS,
                    query_max_chars=cfg.RESEARCHER_CONSULT_QUERY_MAX_CHARS,
                    allowed_hosts=cfg.RESEARCHER_CONSULT_ALLOWED_HOSTS,
                    restrict_reads_to_searched_hosts=cfg.RESEARCHER_CONSULT_READ_ONLY_SEARCHED_HOSTS,
                ),
                timeout=cfg.RESEARCHER_CONSULT_TIMEOUT_SECONDS,
            )
        except _asyncio.TimeoutError:
            logger.warning("Consulta ao Researcher excedeu o timeout", extra={"session_id": session_key})
            return _finish(RESPONDIDO_SUPOSICAO, assumption_text(mode, question, "timeout"), "timeout")
        except Exception as exc:
            logger.warning("Consulta ao Researcher falhou", extra={"session_id": session_key, "error": str(exc)})
            return _finish(
                RESPONDIDO_SUPOSICAO, assumption_text(mode, question, "erro"), "erro", {"erro": str(exc)[:100]}
            )

        consulta = {
            "resposta": outcome.resposta,
            "buscas_realizadas": outcome.buscas_realizadas,
            "leituras": outcome.leituras,
            "recusas": outcome.recusas,
            "modelo": outcome.modelo,
            "tokens": outcome.tokens,
            "duracao_s": outcome.duracao_s,
        }
        # 6. Classificação pelo próprio consultor: decisão reservada.
        if outcome.reservada:
            self._register_reserved(decisao_reservada or classify_reserved(question), task)
            return _finish(PENDENTE_PESQUISADOR, RESERVED_MESSAGE, None, consulta | {"reservada": True})
        return _finish(RESPONDIDO_RESEARCHER, format_answer(outcome.resposta), None, consulta)

    def effective_run_limit(self, master_session_id: str, kind: str = "execution") -> int:
        """Limite efetivo de execuções de agente da sessão (v16-pipeline-robustness §5.1).

        O de subtarefas tem como piso ``MAX_AGENT_RUNS_PER_SESSION`` e cresce com o plano
        aprovado: ``n * (1 + SESSION_MAX_TASK_RETRIES) + 2``.
        """
        if kind == "planning":
            return MAX_PLANNING_RUNS_PER_SESSION
        n = self._session_plan_size.get(master_session_id, 0)
        return max(MAX_AGENT_RUNS_PER_SESSION, n * (1 + SESSION_MAX_TASK_RETRIES) + 2 if n else 0)

    async def _execute_agent(
        self, task: AgentTask, master_session_id: str | None = None, run_kind: str = "execution"
    ) -> AgentResult:
        """Executa um agente em processo via ``AgentRuntime`` (Roadmap V16/ADR 014).

        Faz uma chamada direta e supervisionada dentro do processo do orquestrador, com
        telemetria, circuit breaker de execuções por sessão e persistência da sessão do agente.

        Args:
            task: Definição da tarefa do agente.
            master_session_id: ID da sessão mestra para compartilhamento de estado.

        Returns:
            Resultado da execução do agente.
        """
        # Rate limiting adaptativo (Roadmap V3 - Etapa V8)
        await self.rate_limiter.acquire()

        # Roadmap V16/ADR 014 — Circuit breaker: limite de execuções de agente por sessão,
        # com contadores separados para planejamento e execução (v16-pipeline-robustness §5).
        if master_session_id:
            counts = self._session_planning_run_counts if run_kind == "planning" else self._session_agent_run_counts
            count = counts.get(master_session_id, 0)
            limit = self.effective_run_limit(master_session_id, run_kind)
            if count >= limit:
                raise AgentRunLimitReached(run_kind, count, limit, master_session_id)
            counts[master_session_id] = count + 1

        telemetry = get_telemetry()
        _exec_id = master_session_id or "unknown"

        from datetime import datetime, timezone
        started_at_iso = datetime.now(timezone.utc).isoformat()
        if task.subtask_id:
            telemetry.record_subtask_metrics(
                subtask_id=task.subtask_id,
                execution_id=_exec_id,
                task_name=task.task_name or "unnamed",
                agent_id=task.agent_id,
                status="running",
                created_at=task.created_at or started_at_iso,
                started_at=started_at_iso,
            )

        session = self.session_manager.create(task.agent_id)
        effective_session_id = master_session_id or session.id
        self.output_manager.init_session(effective_session_id)
        session_dir = (self.output_manager.base_dir / effective_session_id).resolve()

        logger.info(
            "Executando agente em processo",
            extra={"agent_id": task.agent_id, "session_id": session.id, "runtime": "inprocess"},
        )
        telemetry.record_agent_event(
            execution_id=_exec_id,
            session_id=session.id,
            agent_id=task.agent_id,
            event_type="spawn",
            task_name=task.task_name or None,
            payload={"runtime": "inprocess"},
        )

        # ADR 017 §7: a dica preferred_model do plano só vale como provedor/modelo validado pelo
        # roteador; caso contrário o papel usa o modelo resolvido da sessão.
        try:
            model = get_session_routing().apply_hint(task.agent_id, task.preferred_model)
        except ValueError:
            model = ""  # papel fora do catálogo: o runtime recusa com mensagem própria
        enable_thinking = OLLAMA_ENABLE_THINKING if task.agent_id not in ("planner", "validator") else True

        async def _ask_researcher_callback(
            question: str, context: str, why_cant_proceed: str, options: list[str]
        ) -> str:
            return await self._ask_researcher_core(
                question=question,
                context=context,
                why_cant_proceed=why_cant_proceed,
                options=options,
                task=task,
                master_session_id=master_session_id,
            )

        async def _consult_researcher_callback(
            question: str,
            context: str,
            why_cant_proceed: str,
            options: list[str],
            decisao_reservada: str | None = None,
        ) -> str:
            return await self._consult_researcher_core(
                question=question,
                context=context,
                why_cant_proceed=why_cant_proceed,
                options=options,
                decisao_reservada=decisao_reservada,
                task=task,
                master_session_id=master_session_id,
            )

        ctx = AgentContext(
            session_id=effective_session_id,
            agent_session_id=session.id,
            agent_id=task.agent_id,
            task_name=task.task_name,
            mode=task.mode or self._session_modes.get(effective_session_id, ""),
            output_dir=session_dir,
            model=model,
            enable_thinking=enable_thinking,
            execution_id=_exec_id,
            ask_researcher=_ask_researcher_callback,
            consult_researcher=_consult_researcher_callback,
        )

        result = await self.agent_runtime.run(task, ctx)

        self.session_manager.update(session.id, payload=result.response)

        if result.status == "success":
            await self.rate_limiter.report_success()
        else:
            error_msg = str(result.error or "")
            if "429" in error_msg or "Too Many Requests" in error_msg:
                await self.rate_limiter.report_429()
            else:
                await self.rate_limiter.report_success()

        telemetry.record_agent_event(
            execution_id=_exec_id,
            session_id=session.id,
            agent_id=task.agent_id,
            event_type="complete" if result.status == "success" else "error",
            task_name=task.task_name or None,
            payload={"status": result.status, "runtime": "inprocess"},
        )

        try:
            self.session_manager.close(session.id)
        except Exception as e:
            logger.error(f"Erro ao fechar sessão {session.id}: {e}")

        if task.subtask_id:
            finished_at_iso = datetime.now(timezone.utc).isoformat()
            duration_ms = int(
                (datetime.now(timezone.utc) - datetime.fromisoformat(started_at_iso)).total_seconds() * 1000
            )
            telemetry.record_subtask_metrics(
                subtask_id=task.subtask_id,
                execution_id=_exec_id,
                task_name=task.task_name or "unnamed",
                agent_id=task.agent_id,
                status=result.status,
                created_at=task.created_at or started_at_iso,
                started_at=started_at_iso,
                finished_at=finished_at_iso,
                duration_total_ms=duration_ms,
                duration_active_ms=duration_ms,
                retry_count=task.retry_attempt,
                error_type=result.error[:100] if result.error else None,
            )

        return result

    def _record_plan_normalized(self, master_session_id: str, iteration: int, normalized: Any) -> None:
        """Registra os reparos do normalizador (observabilidade nunca derruba o planejamento)."""
        try:
            get_telemetry().record_agent_event(
                execution_id=bound_execution_id() or master_session_id,
                session_id=master_session_id,
                agent_id="planner",
                event_type="plan_normalized",
                payload={
                    "iteration": iteration,
                    "repairs": [{"kind": r.kind, "task_name": r.task_name} for r in normalized.repairs][:20],
                    "unrecoverable": len(normalized.unrecoverable),
                },
            )
        except Exception as exc:
            logger.warning("Falha ao registrar plan_normalized", extra={"error": str(exc)})

    async def _run_planning_loop(
        self, 
        prompt: str, 
        master_session_id: str, 
        previous_plan: list[dict[str, Any]] | None = None,
        execution_feedback: str | None = None
    ) -> list[AgentTask]:
        """Executa o ciclo de planejamento (Planner -> Validator).

        Args:
            prompt: Solicitação original do usuário.
            master_session_id: ID da sessão mestra para logs.
            previous_plan: Plano gerado anteriormente para refinamento incremental.
            execution_feedback: Feedback de erro de execução para recuperação.

        Returns:
            Lista de AgentTask aprovadas.
        """
        logger.info(
            "Iniciando ciclo de planejamento", 
            extra={
                "prompt": prompt, 
                "master_session_id": master_session_id, 
                "is_incremental": previous_plan is not None
            }
        )
        
        feedback = execution_feedback or ""
        current_plan_data = previous_plan
        last_signature, repeats = "", 0
        
        _pctx = self._project_blocks.get(master_session_id, "")
        project_block = f"\n{_pctx}\n\n" if _pctx else ""

        for iteration in range(MAX_PLANNING_ITERATIONS):
            # 1. Executa o Researcher (que absorve o Planner na V14.3)
            if current_plan_data:
                last_plan_str = json.dumps(current_plan_data, indent=2, ensure_ascii=False)
                planner_prompt = (
                    f"MODO: REPLAN\n\n"
                    f"Tarefa original: {prompt}\n\n"
                    f"Este é o plano atual:\n{last_plan_str}\n\n"
                    f"{project_block}"
                    f"PROBLEMAS ENCONTRADOS:\n{feedback}\n\n"
                    "Instrução: Diagnostique a causa raiz de cada falha em uma das três categorias "
                    "(problema de dados, problema de implementação, ou resultado legítimo divergente) "
                    "antes de decidir a subtarefa de recuperação — ver DIRETRIZES DE REPLANEJAMENTO. "
                    "Replaneje apenas as subtarefas com falha ou adicione tarefas de recuperação. "
                    "NUNCA redefina ou repita subtarefas que já foram concluídas com sucesso. "
                    "Se a causa for um resultado legítimo divergente, NÃO tente forçar o resultado esperado: "
                    "gere uma subtarefa com 'task_type': 'validation' documentando a divergência. "
                    "Cada subtarefa DEVE conter 'validation_criteria' obrigatório. "
                    "Retorne o plano COMPLETO atualizado em JSON."
                )
            else:
                # V15.5/G9 — Injeta o contexto pré-curado de input_context/ apenas no
                # plano inicial (nunca em replans, para não repetir payload grande).
                context_block = f"\n\n{self._current_context_block}\n" if self._current_context_block else ""
                planner_prompt = (
                    f"MODO: PLAN\n\n"
                    f"Crie um plano de execução (DAG) para a seguinte tarefa:\n{prompt}\n"
                    f"{project_block}"
                    f"{context_block}\n"
                    "INSTRUÇÃO OBRIGATÓRIA: Se a tarefa envolver domínio técnico ou bibliotecas, "
                    "execute uma busca com 'quick_search' para verificar contexto antes de formular as subtarefas. "
                    "Cada subtarefa no plano DEVE conter 'validation_criteria' com ao menos um critério explícito. "
                    "Retorne a lista de subtarefas em formato JSON."
                )
                if feedback:
                    planner_prompt += f"\n\nPROBLEMAS ANTERIORES:\n{feedback}"

            planner_task = AgentTask(
                agent_id="researcher",
                prompt=planner_prompt,
            )

            planner_result = await self._execute_agent(planner_task, master_session_id, run_kind="planning")
            if planner_result.status != "success" or "error" in planner_result.response:
                err = planner_result.error or planner_result.response.get("error", "Erro desconhecido")
                logger.error(f"Falha no Agente Researcher (Planner): {err}", extra={"error": err})
                return []
            
            # Tenta extrair JSON da resposta
            raw_plan = planner_result.response.get("text", "")
            plan_data = extract_json(raw_plan)
            if PLAN_NORMALIZER_ENABLED and plan_data is not None:
                normalized = normalize_plan(plan_data)
                if normalized.repairs:
                    self._record_plan_normalized(master_session_id, iteration + 1, normalized)
                if normalized.tasks:
                    plan_data = normalized.tasks
            if plan_data is None or not isinstance(plan_data, list):
                logger.error(
                    "Erro ao parsear plano do Planner",
                    extra={"text_preview": raw_plan[:200]},
                )
                feedback = "Sua resposta anterior não era JSON válido. Responda APENAS com o JSON da lista de tarefas."
                continue
            
            current_plan_data = plan_data
            last_plan_str = json.dumps(current_plan_data, indent=2)

            # 2. Executa o Validator como corrotina assíncrona (V14.2 - sem Docker)
            val_result = await self.validator.validate_plan(
                plan=current_plan_data,
                prompt=prompt,
            )

            # v16-pipeline-robustness §1.3 — reprovação repetida: a determinística encerra o
            # planejamento; a do Validator LLM vira consultiva (aprova com avisos).
            if val_result.is_valid or not val_result.signature:
                last_signature, repeats = "", 0
            else:
                repeats = repeats + 1 if val_result.signature == last_signature else 1
                last_signature = val_result.signature
                if repeats >= PLAN_REJECTION_STALL_LIMIT and not val_result.deterministic:
                    val_result.is_valid = True
                    val_result.status = "approved"
                    val_result.approved_with_warnings = True

            try:  # observabilidade nunca derruba o planejamento
                get_telemetry().record_agent_event(
                    execution_id=bound_execution_id() or master_session_id,
                    session_id=master_session_id,
                    agent_id="validator",
                    event_type="plan_validation",
                    target_agent_id="researcher",
                    payload={
                        "iteration": iteration + 1,
                        "approved": bool(val_result.is_valid),
                        "approved_with_warnings": bool(val_result.approved_with_warnings),
                        "deterministic": bool(val_result.deterministic),
                        "signature": val_result.signature,
                        "reason": str(val_result.reason or "")[:300],
                        "issues": [str(i)[:200] for i in (val_result.issues or [])][:8],
                        "plan_tasks": len(current_plan_data),
                    },
                )
            except Exception as exc:
                logger.warning("Falha ao registrar plan_validation", extra={"error": str(exc)})

            if not val_result.is_valid and val_result.deterministic and repeats >= PLAN_REJECTION_STALL_LIMIT:
                raise PlanningStalled(
                    f"Planejamento encerrado: a mesma reprovação determinística se repetiu {repeats} vezes. "
                    + "; ".join(val_result.issues),
                    val_result.issues,
                )

            if val_result.is_valid:
                logger.info("Plano aprovado pelo Validador", extra={"iteration": iteration + 1})
                self._session_plan_size[master_session_id] = len(current_plan_data)
                self._session_plan_summary[master_session_id] = "\n".join(
                    f"- {t.get('task_name', '?')} ({t.get('agent_id', 'base')}): "
                    f"{str(t.get('description') or t.get('prompt') or '')[:160]}"
                    for t in current_plan_data
                )[:3000]
                tasks = []
                from datetime import datetime, timezone
                import uuid
                now_iso = datetime.now(timezone.utc).isoformat()
                for t in current_plan_data:
                    tasks.append(AgentTask(
                        agent_id=t.get("agent_id", "base"),
                        prompt=t.get("prompt", prompt),
                        task_name=t.get("task_name", ""),
                        depends_on=t.get("depends_on", []),
                        expected_artifacts=t.get("expected_artifacts", []),
                        validation_criteria=t.get("validation_criteria", []),
                        preferred_model=t.get("preferred_model"),
                        subtask_id=uuid.uuid4().hex,
                        created_at=now_iso,
                        task_type=t.get("task_type"),
                        hypothesis=t.get("hypothesis", ""),
                        scientific_rationale=t.get("scientific_rationale", ""),
                        approach=t.get("approach") if isinstance(t.get("approach"), dict) else None,
                    ))
                return tasks
            else:
                issues_str = "\n".join(f"- {i}" for i in val_result.issues) if val_result.issues else val_result.reason
                feedback = f"O Validador identificou os seguintes problemas:\n{issues_str}"
                logger.info("Solicitando revisão do plano", extra={"iteration": iteration + 1, "reason": feedback})

        logger.error("Máximo de iterações de planejamento atingido")
        return []
