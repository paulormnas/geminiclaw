"""Loop de execução autônoma para agentes GeminiClaw.

Implementa a lógica de triage (simples vs complexo), 
decomposição de tarefas em subtarefas e loop de retentativas.
"""

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from src.agents.regimento import encerrar_sessao, iniciar_sessao, sessao_atual
from src.agents.subtask_contract import (
    build_developer_contract,
    dependency_files,
    oversized_fields,
    threshold_masked,
)
from src.artifacts.metrics_file import metrics_of
from src.artifacts.subtask_output import negative_result_feedback
from src.config import (
    CIRCUIT_BREAKER_STALL_CYCLES,
    LIMIT_GRACE_SECONDS,
    MAX_PLAN_RETRIES,
    MAX_SUBTASKS_PER_TASK,
    SESSION_MAX_TASK_RETRIES,
)
from src.egress.gate import role_tainted
from src.egress.persisted import resumed_text_tainted, resumo_marca, tags_tainted, with_taint_tag
from src.host.health import HealthMonitor
from src.knowledge.suggestions import SuggestionError
from src.logger import get_logger
from src.observability.telemetry import get_telemetry
from src.orchestration.dependency_artifacts import resolve_dependency_mounts
from src.orchestration.errors import PlanningStalled
from src.orchestration.exploration_contract import contract_applies
from src.orchestration.exploration_feedback import review_observations_feedback
from src.orchestration.exploration_linking import DROP_LONG_FIELD
from src.orchestration.loop_report import LoopReportMixin
from src.orchestration.subtask_ingestion import ingest_subtask, link_preparations
from src.orchestration.triage import TriageClassifier
from src.orchestration.usage import (
    StopReason,
    UsageBudget,
    UsageTracker,
    consume_replan,
    is_cancelled,
    mark_task_started,
)
from src.session.commands import MOTIVO_CANCELADA
from src.session.continuity import (
    ESTADO_FECHADO,
    ST_ABANDONADA,
    ST_CONCLUIDA,
    ST_FALHOU,
    CheckpointRecorder,
    list_task_artifacts,
    plan_entry,
    safe_task_name,
)
from src.skills.code.sandbox import dependency_target
from src.skills.memory.short_term import ShortTermMemory
from src.utils.egress_fragments import mark_artifact_names, mark_execution_output, taint_if
from src.utils.terminal import print_status

if TYPE_CHECKING:
    from src.agents.subtask_contract import SubtaskContract
    from src.orchestration.exploration import ExplorationSession, ExplorationStop
    from src.orchestration.orchestrator import AgentResult, AgentTask, Orchestrator, OrchestratorResult

logger = get_logger(__name__)

# Campos de ``AgentTask`` que não voltam ao Researcher no plano anterior (internos do orquestrador).
_PLAN_ECHO_EXCLUDED = frozenset(
    {"subtask_id", "created_at", "papel_fonte", "prepara_ids", "hypothesis_origin"}
)

# Roadmap V3 - Etapa V3: limite de chars para injeção de contexto (~2000 tokens)
_CONTEXT_MAX_CHARS = 8_000


@dataclass(frozen=True)
class CycleProgress:
    """Progresso de um ciclo de planejamento/execução, para o disjuntor de "zero progresso"."""

    succeeded: frozenset
    failure_signatures: frozenset
    # v18.7-exploration-limits §9.1: na exploração com projeto, o progresso é do grafo (``None`` = laço da V17).
    experiments: int | None = None
    results: int | None = None

    def advanced_from(self, previous: "CycleProgress") -> bool:
        """Há progresso se o grafo ganhou ``Experimento`` ou ``Resultado`` (exploração com projeto) ou, sem projeto,
        se surgiram sucessos novos; em ambos os casos, se a assinatura dos erros mudou."""
        if self.failure_signatures != previous.failure_signatures:
            return True
        if self.experiments is not None and previous.experiments is not None:
            return self.experiments > previous.experiments or (self.results or 0) > (previous.results or 0)
        return not self.succeeded <= previous.succeeded


DONE_STATUSES = ("success", "concluded_negative")  # estados do DAG que liberam as dependentes e contam como progresso


def succeeded_task_names(dag_state: Dict[str, Any]) -> List[str]:
    """Subtarefas que avançaram a pesquisa no ciclo: sucesso ou resultado negativo (``v18.6-hypothesis-closure``)."""
    return [t for t, state in dag_state.items() if state["status"] in DONE_STATUSES]


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


class AutonomousLoop(LoopReportMixin):
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
        self._health_monitor = HealthMonitor()
        # Roadmap V15.6 / Spec G10 — modo de operação da sessão corrente
        self._session_mode: str = ""
        # V18/usage-limits — orçamento e contabilização de uso da sessão corrente.
        # Definidos em `run()`, quando o budget efetivo (defaults de config + overrides
        # de CLI) é conhecido.
        self._usage_tracker: "UsageTracker | None" = None
        # v18.5-claim-verification: afirmações pendentes de sessões anteriores verificadas nesta execução.
        self._claims_previous: list[Any] = []
        # v18.5-operation-metrics: cadência e contagem dos avisos periódicos do modo sem limite.
        self._notice_schedule: Any = None
        self._unlimited_notices = 0
        # (sessão, subtarefa, tentativa) -> hash do contrato da tentativa, para conferir a revisão (ADR 022 §7)
        self._attempt_hashes: Dict[tuple[str, str, int], Optional[str]] = {}


    @staticmethod
    def _pending_model_stop(master_session_id: str | None = None) -> "StopReason | None":
        """Parada pedida fora do orçamento: interrupção do pesquisador, cota do provedor esgotada (v18.7), em
        ``strict`` a versão do modelo (v18.5) e, por último, a ausência do terminal numa sessão ``assisted`` (v18.7)."""
        from src.llm.quota import quota_stop_for
        from src.orchestration.usage import interrupt_requested, suspension_requested

        if interrupt_requested():
            return StopReason.INTERRUPTED
        if master_session_id is not None and quota_stop_for(master_session_id) is not None:
            return StopReason.PROVIDER_QUOTA
        from src.llm.session import current_session_routing
        from src.llm.versions import STOP_VERSION

        routing = current_session_routing()
        if routing is not None and routing.versions.parada_pendente == STOP_VERSION:
            return StopReason.MODEL_VERSION
        if suspension_requested():  # por último: um limite atingido no mesmo ponto prevalece (design §1.4)
            return StopReason.SUSPENDED
        from src.orchestration.usage import pause_requested

        if pause_requested():  # ``pausar`` do pesquisador (v18.7-session-events-terminal)
            return StopReason.PAUSED
        return None

    def _usage_fraction(self) -> float:
        """Maior fração consumida entre os limites ativos (tokens, tempo, custo); 0 no modo sem limite (design §7)."""
        tracker = self._usage_tracker
        if tracker is None:
            return 0.0
        status = tracker.check()
        return max((p for p in (status.tokens_pct, status.minutes_pct, status.cost_pct) if p is not None), default=0.0)

    def _pending_stop(self, master_session_id: str) -> "StopReason | None":
        """Ponto de verificação de limites: trata a mudança de versão do modelo (política ``retomar``) e consulta as
        paradas pendentes. Falha ao tratar a versão nunca interrompe a pesquisa."""
        try:
            self._apply_model_version_policy(master_session_id)
        except Exception:  # noqa: BLE001 — a política de versão nunca derruba a verificação de limites
            logger.warning("Falha ao tratar a mudança de versão do modelo", exc_info=True)
        return self._pending_model_stop(master_session_id)

    def _apply_model_version_policy(self, master_session_id: str) -> None:
        """``ON_MODEL_VERSION_CHANGE=retomar`` em ``strict``: checkpoint e continuação, ou troca do modelo do papel.

        Versão nova informada: o evento ``versao_modelo_alterada`` já foi gravado e a sessão continua com o mesmo
        modelo. Versão desconhecida: cada papel que usa o modelo passa ao próximo elegível da ``preferencia`` (evento
        ``modelo_substituido``); sem elegível, a sessão fecha com ``versao_modelo`` e continua retomável.
        """
        from src.llm.session import current_session_routing

        routing = current_session_routing()
        if routing is None or not routing.versions.strict:
            return
        actions = routing.versions.drain_actions()
        if not actions:
            return
        from src.llm.allocation import build_allocation_profile
        from src.llm.model_substitution import REASON_UNKNOWN_VERSION, find_substitute, replace_role_model
        from src.llm.versions import ACTION_UNKNOWN, EVENT_MODEL_REPLACED

        replaced = False
        for action in actions:
            if action["tipo"] != ACTION_UNKNOWN:
                logger.warning("Versão do modelo mudou; a sessão continua com o mesmo modelo", extra=action)
                continue
            roles = action["papeis"] or [r for r, res in routing.papeis.items() if res.id == action["provedor_modelo"]]
            for role in roles:
                old_id = routing.papeis[role].id
                new_id = find_substitute(routing, role)
                if new_id is None:
                    logger.warning(
                        "Sem modelo elegível para substituir: a sessão fecha por versao_modelo",
                        extra={"papel": role, "modelo": old_id},
                    )
                    routing.versions.request_stop()
                    continue
                replace_role_model(routing, role, new_id, REASON_UNKNOWN_VERSION)
                routing.versions.emit_event({
                    "tipo": EVENT_MODEL_REPLACED, "papel": role, "anterior": old_id, "novo": new_id,
                    "motivo": REASON_UNKNOWN_VERSION,
                })
                replaced = True
        session_manager = self.orchestrator.session_manager
        if replaced:
            session = session_manager.get(master_session_id)
            payload = dict(session.payload) if session is not None else {}
            payload["llm_routing"] = routing.payload()
            payload["allocation_profile"] = build_allocation_profile(routing)
            session_manager.update(master_session_id, payload=payload)
        recorder = self._recorder(master_session_id)
        if recorder is not None:
            recorder.set_usage()  # grava o checkpoint (o estado das subtarefas já está nele) antes de continuar

    @staticmethod
    async def _refresh_model_versions() -> None:
        """Relê o digest dos modelos Ollama da sessão (a cada checkpoint); falha nunca interrompe a pesquisa."""
        from src.llm.allocation import refresh_ollama_versions

        try:
            await refresh_ollama_versions()
        except Exception:  # noqa: BLE001 — telemetria de versão
            logger.warning("Não foi possível reler as versões dos modelos Ollama", exc_info=True)

    def _recorder(self, master_session_id: str) -> "CheckpointRecorder | None":
        """Gravador de checkpoint da sessão, ou ``None`` (sem checkpoint a pesquisa continua)."""
        getter = getattr(self.orchestrator, "get_checkpoint", None)
        if not callable(getter):
            return None
        rec = getter(master_session_id)
        return rec if isinstance(rec, CheckpointRecorder) else None

    def _resume(self, master_session_id: str) -> Any:
        """``ResumeState`` da sessão (retomada), ou ``None``."""
        from src.session.continuity import ResumeState

        getter = getattr(self.orchestrator, "get_resume", None)
        state = getter(master_session_id) if callable(getter) else None
        return state if isinstance(state, ResumeState) else None

    def _preload_resumed_results(self, master_session_id: str, resume: Any) -> None:
        """Entrega às dependentes o resultado das subtarefas concluídas na sessão anterior (sem reexecutá-las)."""
        from src.artifacts.subtask_output import SubtaskOutput
        from src.session.continuity import safe_artifact_path
        from src.utils.normalization import clean_free_text

        for name, state in resume.completed.items():
            # O checkpoint é dado não confiável: caminhos revalidados e resumo em uma linha, sem títulos forjados.
            artifacts = [
                {"name": rel.rsplit("/", 1)[-1], "path": f"{resume.source_session_id}/{rel}"}
                for rel in state.artefatos
                if safe_artifact_path(rel)
            ]
            summary = clean_free_text(state.resultado_resumo).replace("#", "")[:1000]
            # v18.5-egress-gate — a marca gravada na produção vale na retomada, mesmo com outro catálogo; texto sem
            # marca (legado) segue a regra do perfil da sessão que o produziu (design §7).
            output = SubtaskOutput(
                task_name=name,
                agent_id=clean_free_text(state.agent_id)[:64] or "developer",
                status="success",
                text_summary=f"[dado da sessão {resume.source_session_id}, concluída] {summary}".strip(),
                artifacts=artifacts,
                tainted=resumed_text_tainted(state, resume.source_session_id, self.orchestrator.session_manager),
            )
            self._short_term_memory.write(
                session_id=master_session_id,
                key=f"result:{name}",
                value=output.to_json(),
                source=output.agent_id,
                tags=with_taint_tag(["subtask_result", name, "structured", "resumed"], output.tainted is not False),
            )

    async def run(
        self,
        prompt: str,
        master_session_id: str,
        mode: str = "",
        budget: "UsageBudget | None" = None,
    ) -> "OrchestratorResult":
        """Executa a tarefa utilizando o loop autônomo (ver ``_run_session``).

        Marca a sessão como ativa para que o 1º Ctrl+C a feche com checkpoint (v18.5-operation-metrics §2.6).
        """
        from src.llm.quota import clear_quota_stop
        from src.orchestration.usage import clear_interrupt, set_session_active

        clear_interrupt()
        clear_quota_stop(master_session_id)  # v18.7: a parada por cota de uma sessão anterior não vale para esta
        set_session_active(True)
        regimento_token = None
        try:
            regimento_token, adendo_pendente = self._iniciar_regimento(master_session_id, mode)
            if adendo_pendente is not None:
                return await self._suspend_session(
                    master_session_id, [], [],
                    f"Sessão aguarda o pesquisador: ativação do adendo do regimento (`ativar_adendo_regimento`, "
                    f"sha256 {adendo_pendente}).",
                )
            return await self._run_session(prompt, master_session_id, mode, budget)
        finally:
            if regimento_token is not None:
                encerrar_sessao(regimento_token)
            set_session_active(False)

    def _iniciar_regimento(self, master_session_id: str, mode: str) -> tuple[Any, str | None]:
        """Carrega o regimento da pesquisa uma vez, registra a versão e o vincula à sessão (ADR 022 §4.4).

        Grava o evento ``regimento_sessao`` (início e cada recorte novo), o payload ``regimento`` da sessão e, na
        retomada com hash diferente do registrado, o evento ``regimento_alterado``. Regimento ou adendo inválido,
        e adendo não aprovado no ``auto``, falham a sessão antes de qualquer chamada de modelo.

        Returns:
            O token do vínculo e, no ``assisted`` e no ``semi``, o sha256 do adendo que aguarda o pesquisador
            (``None`` sem adendo pendente); nesse caso a sessão não executa subtarefas.
        """
        from src.config import SESSION_DEFAULT_MODE

        modo = mode or SESSION_DEFAULT_MODE
        registro: dict[str, Any] = {"recortes": []}

        def registrar_recorte(rec: Any) -> None:
            registro["recortes"].append(
                {"tipo_objetivo": rec.tipo_objetivo, "modo": rec.modo, "recorte_sha256": rec.sha256}
            )
            self._emit_regimento(master_session_id, "regimento_sessao", {
                "versao": sessao.regimento.versao, "regimento_sha256": sessao.regimento.sha256, "adendo_sha256": "",
                "recorte_sha256": rec.sha256, "tipo_objetivo": rec.tipo_objetivo, "modo": rec.modo,
            })
            self._gravar_regimento_no_payload(master_session_id, registro)

        sessao, token = iniciar_sessao(modo, on_recorte=registrar_recorte)
        try:
            adendo, pendente = self._conferir_adendo(master_session_id, modo, sessao)
        except Exception:
            encerrar_sessao(token)
            self._fechar_por_erro(master_session_id)
            raise
        sessao.adendo = adendo
        adendo_sha = adendo.sha256 if adendo is not None else ""
        registro.update({"versao": sessao.regimento.versao, "regimento_sha256": sessao.regimento.sha256,
                         "adendo_sha256": adendo_sha})
        inicio = {"versao": sessao.regimento.versao, "regimento_sha256": sessao.regimento.sha256,
                  "adendo_sha256": adendo_sha}
        if pendente is not None:
            inicio["adendo_pendente_sha256"] = pendente
        self._emit_regimento(master_session_id, "regimento_sessao", inicio)
        self._gravar_regimento_no_payload(master_session_id, registro)
        self._conferir_regimento_retomado(master_session_id, sessao.regimento.sha256)
        return token, pendente

    def _fechar_por_erro(self, master_session_id: str) -> None:
        """Marca a sessão como fechada com ``motivo_parada = erro`` (a recusa antes de começar sai com o código 1)."""
        try:
            manager = self.orchestrator.session_manager
            session = manager.get(master_session_id)
            if session is not None:
                manager.update(
                    master_session_id, status="closed", payload={**session.payload, "motivo_parada": "erro"}
                )
        except Exception:  # noqa: BLE001
            logger.warning("Falha ao fechar a sessão recusada", exc_info=True)

    def _conferir_adendo(self, master_session_id: str, modo: str, sessao: Any) -> tuple[Any, str | None]:
        """Lê o adendo uma vez e confere a aprovação no gate persistente (design §5.5 a §5.7).

        Returns:
            ``(adendo aprovado ou None, sha256 do adendo pendente ou None)``.

        Raises:
            AdendoError: adendo inválido ou como link simbólico, ou pendente no ``auto`` (a sessão não começa).
        """
        from src import config
        from src.agents.regimento.adendo import AdendoError, aprovado, ler_adendo, registrar_pedido
        from src.gate.persistent_gate import session_gate

        diretorio = getattr(self.orchestrator, "_current_context_dir", None) or config.INPUT_CONTEXT_DIR
        adendo = ler_adendo(diretorio)
        if adendo is None:
            return None, None
        gate = session_gate()
        try:
            if aprovado(gate, adendo):
                return adendo, None
            project_id = None
            getter = getattr(self.orchestrator, "_session_project_id", None)
            if callable(getter):
                project_id = getter(master_session_id)
            registrar_pedido(
                gate, adendo, sessao.regimento.estrutura, session_id=master_session_id, project_id=project_id
            )
        except AdendoError:
            raise
        except Exception as exc:  # noqa: BLE001 - sem o gate não há como conferir a aprovação: falha fechada
            raise AdendoError(f"aprovação do adendo não conferida ({type(exc).__name__}).") from exc
        if modo == "auto":
            raise AdendoError(
                f"sessão recusada antes de começar: o adendo do regimento (sha256 {adendo.sha256}) não foi aprovado "
                "pelo pesquisador. Aprove o pedido `ativar_adendo_regimento` no terminal e inicie a sessão de novo."
            )
        return None, adendo.sha256

    def _emit_regimento(self, master_session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        try:
            get_telemetry().record_agent_event(
                execution_id=master_session_id, session_id=master_session_id, agent_id="autonomous_loop",
                event_type=event_type, payload=payload,
            )
        except Exception:  # noqa: BLE001 - o registro nunca interrompe a sessão
            logger.warning("Falha ao registrar %s", event_type, exc_info=True)

    def _gravar_regimento_no_payload(self, master_session_id: str, registro: dict[str, Any]) -> None:
        try:
            manager = self.orchestrator.session_manager
            session = manager.get(master_session_id)
            if session is None:
                return
            payload = dict(session.payload)
            payload["regimento"] = {**registro, "recortes": list(registro["recortes"])}
            manager.update(master_session_id, payload=payload)
        except Exception:  # noqa: BLE001
            logger.warning("Falha ao gravar o regimento no payload da sessão", exc_info=True)

    def _conferir_regimento_retomado(self, master_session_id: str, atual: str) -> None:
        """Na retomada, registra ``regimento_alterado`` se o hash do disco difere do da sessão de origem."""
        resume = self._resume(master_session_id)
        if resume is None:
            return
        try:
            origem = self.orchestrator.session_manager.get(resume.source_session_id)
            anterior = ((origem.payload if origem is not None else {}) or {}).get("regimento") or {}
            anterior_sha = anterior.get("regimento_sha256") if isinstance(anterior, dict) else None
        except Exception:  # noqa: BLE001
            return
        if anterior_sha and anterior_sha != atual:
            self._emit_regimento(master_session_id, "regimento_alterado", {
                "regimento_sha256_registrado": anterior_sha, "regimento_sha256_atual": atual,
                "sessao_origem": resume.source_session_id,
            })

    async def _sincronizar_objetivo_do_regimento(self, exploration: "ExplorationSession | None") -> None:
        """Atualiza o tipo de objetivo do recorte vigente a partir do ``Problema`` ativo (a cada ciclo)."""
        sessao = sessao_atual()
        if sessao is None:
            return
        tipo = await asyncio.to_thread(exploration.objective_type) if exploration is not None else None
        sessao.definir_objetivo(tipo)

    async def _run_session(
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
        # desta sessão (ver src/orchestration/orchestrator.py — exec_id e master_session.id coincidem).
        # `self.max_retries`, se ajustado explicitamente pelo chamador (ex: testes)
        # antes desta chamada, é respeitado como override de `max_task_retries` do
        # orçamento default — só é ignorado se `budget` for passado explicitamente.
        effective_budget = budget or UsageBudget.from_config(max_task_retries=self.max_retries)
        self._usage_tracker = UsageTracker(
            effective_budget,
            execution_id=master_session_id,
            pending_stop=lambda: self._pending_stop(master_session_id),
        )
        self.orchestrator.register_usage_tracker(master_session_id, self._usage_tracker)
        self.max_retries = effective_budget.max_task_retries
        self._notice_schedule = None  # v18.5-operation-metrics: cadência dos avisos reinicia a cada sessão
        self._unlimited_notices = 0

        logger.info(
            "Iniciando loop autônomo",
            extra={"prompt_preview": prompt[:100], "master_session_id": master_session_id, "mode": self._session_mode}
        )

        telemetry = get_telemetry()

        # v18-research-continuity — a retomada sempre segue o caminho complexo (há plano a continuar) e, antes de
        # replanejar, conclui o fechamento do Curator que ficou pendente na sessão anterior.
        resume = self._resume(master_session_id)
        if resume is not None:
            await self.orchestrator.resume_curator_pending(master_session_id)
            # v18.5-claim-verification (design §11): pendentes das sessões anteriores, antes do primeiro planejamento.
            self._claims_previous = await self.orchestrator.resume_claims_pending(master_session_id)

        # 1. Triage: Simples vs Complexo
        is_complex = True if resume is not None else await self._is_complex_triage(prompt, master_session_id)

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

    def _record_hardware_snapshot(self, master_session_id: str, task_name: str | None) -> None:
        """Grava o instantâneo de hardware após uma subtarefa (``HEALTH_CHECK_ENABLED``).

        Só valores lidos pelo ``HealthMonitor``: o que a plataforma não expõe vai como ``NULL``; ``is_throttled`` é a
        temperatura frente a ``TEMPERATURE_LIMIT`` (``NULL`` sem limite ou sem leitura). Falhas não
        interrompem a sessão.
        """
        from src.config import HEALTH_CHECK_ENABLED

        if not HEALTH_CHECK_ENABLED:
            return
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
                task_name=task_name,
                cpu_temp_c=temp,
                cpu_usage_pct=cpu,
                mem_total_mb=mem["total_mb"] if mem else None,
                mem_available_mb=mem["available_mb"] if mem else None,
                mem_usage_pct=mem["percent"] if mem else None,
                is_throttled=throttled,
            )
        except Exception as e:
            logger.debug("Falha ao coletar métricas de saúde", extra={"error": str(e)})

    async def _llm_triage_direct(self, prompt: str) -> bool:
        """Classifica usando o LLM configurado diretamente, sem container.

        Args:
            prompt: Solicitação original do usuário.

        Returns:
            True se COMPLEX, False se SIMPLE. Em caso de erro, retorna True.
        """
        try:
            from src.llm.factory import ProviderResolverError, get_provider
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
            from src.utils.egress_fragments import ContentOrigin, PromptFragment, labeled

            response = await provider.generate(
                messages=[labeled("user", PromptFragment(triage_prompt, ContentOrigin.INSTRUCAO, source="triagem"))],
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

        except ProviderResolverError:
            raise  # falha de composição (sem resolvedor ou sem filtro de egresso): nunca vira COMPLEX
        except Exception as e:
            logger.warning(
                "Falha no triage LLM direto, assumindo COMPLEX",
                extra={"error": str(e)},
            )

        return True  # padrão conservador


    async def _run_simple_path(self, prompt: str, master_session_id: str) -> "OrchestratorResult":
        """Executa a tarefa via caminho simplificado (apenas agente base)."""
        from src.orchestration.orchestrator import AgentTask, OrchestratorResult
        
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

    async def _check_operational_thresholds(self, master_session_id: str) -> None:
        """Monitora limites operacionais (tokens, duração) (Roadmap V15.3 / Spec G5).

        Nunca bloqueia, em nenhum modo: apenas registra o aviso no log. O processo da sessão não lê o terminal
        (v18.7-background-sessions §1.10); a pausa pelo pesquisador vem em ``v18.7-session-events-terminal``.
        """
        from src.config import OPERATIONAL_THRESHOLDS

        # v18.5-operation-metrics §6: percentuais do orçamento efetivo (inclui overrides da CLI); no modo sem
        # limite os avisos de tokens, tempo e custo não existem (os avisos periódicos os substituem).
        budget = self._usage_tracker.budget if self._usage_tracker is not None else UsageBudget.from_config()
        session_max_tokens = budget.max_tokens
        session_max_minutes = budget.max_minutes

        await self._maybe_unlimited_notice(master_session_id)

        telemetry = get_telemetry()
        token_summary = telemetry.get_token_summary(master_session_id)
        rows = token_summary.get("by_provider_model", [])
        total_tokens = sum(r.get("total_tokens") or 0 for r in rows)
        total_cost = sum(r.get("total_cost_usd") or 0 for r in rows)

        token_pct = (total_tokens / session_max_tokens) if session_max_tokens else 0.0
        duration_min = (time.time() - getattr(self, "_session_started_at", time.time())) / 60
        # V18/usage-limits — avisos da Spec G5 agora são percentuais dos limites reais
        # do UsageBudget (session_max_minutes), não mais minutos absolutos.
        duration_pct = (duration_min / session_max_minutes) if session_max_minutes else 0.0

        triggered: list[str] = []
        if not budget.unlimited and token_pct >= OPERATIONAL_THRESHOLDS["token_usage_pct"]:
            triggered.append(f"Uso de tokens: {token_pct*100:.0f}% do limite ({total_tokens}/{session_max_tokens})")
        cost_pct = (total_cost / budget.max_cost_usd) if budget.max_cost_usd else 0.0
        if not budget.unlimited and cost_pct >= OPERATIONAL_THRESHOLDS["cost_usage_pct"]:
            triggered.append(
                f"Custo estimado: {cost_pct*100:.0f}% do limite (US$ {total_cost:.2f}/US$ {budget.max_cost_usd:.2f})"
            )
        if not budget.unlimited and duration_pct >= OPERATIONAL_THRESHOLDS["session_duration_pct"]:
            triggered.append(
                f"Duração da sessão: {duration_pct*100:.0f}% do limite "
                f"({duration_min:.0f}min/{session_max_minutes:.0f}min)"
            )

        if not triggered:
            return

        logger.warning(
            "Limite(s) operacional(is) atingido(s)",
            extra={"triggered": triggered, "mode": self._session_mode, "master_session_id": master_session_id},
        )

    async def _maybe_unlimited_notice(self, master_session_id: str) -> None:
        """Aviso periódico de consumo do modo sem limite (v18.5-operation-metrics §2.5).

        Registrado em log e na saída da sessão quando passa o intervalo de tempo ou de tokens (o que ocorrer
        primeiro), em todos os modos, sem nunca bloquear.
        """
        tracker = self._usage_tracker
        if tracker is None or not tracker.budget.unlimited:
            return
        if self._notice_schedule is None:
            from src import config
            from src.orchestration.unlimited_mode import NoticeSchedule

            self._notice_schedule = NoticeSchedule(
                config.UNLIMITED_NOTICE_INTERVAL_MINUTES,
                config.UNLIMITED_NOTICE_TOKEN_STEP,
                started_minutes=tracker.elapsed_minutes(),
            )
        status = tracker.check()
        if not self._notice_schedule.due(status.minutes_elapsed, status.tokens_used):
            return

        from src.utils.terminal import BOLD, RESET, YELLOW

        rows = get_telemetry().get_token_summary(master_session_id).get("by_provider_model", [])
        costs = [r.get("total_cost_usd") for r in rows if r.get("total_cost_usd") is not None]
        cost = f"US$ {sum(costs):.2f}" if costs else "não informado"
        line = (
            f"Modo sem limite: {status.minutes_elapsed:.0f} min │ {status.tokens_used:,} tokens │ custo {cost} │ "
            f"egresso {status.egress_bytes:,} bytes"
        )
        print(f"\n{YELLOW}{BOLD}⚠ {line}{RESET}")
        logger.warning(
            "Aviso periódico do modo sem limite",
            extra={"master_session_id": master_session_id, "tokens_used": status.tokens_used},
        )
        self._unlimited_notices += 1
        get_telemetry().record_agent_event(
            execution_id=master_session_id,
            session_id=master_session_id,
            agent_id="autonomous_loop",
            event_type="unlimited_notice",
            payload={
                "minutes_elapsed": round(status.minutes_elapsed, 2),
                "tokens_used": status.tokens_used,
                "egress_bytes": status.egress_bytes,
                "numero": self._unlimited_notices,
            },
        )

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
            from src.utils.terminal import BOLD, CYAN, RESET, YELLOW

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

    def _build_context_prefix(
        self, master_session_id: str, depends_on: list[str], mounted: Optional[Dict[str, str]] = None
    ) -> str:
        """Constrói o prefixo de contexto das subtarefas anteriores das quais esta depende.

        Lê os resultados já completados da ShortTermMemory e monta um bloco de
        texto estruturado para ser injetado antes do prompt da subtarefa atual.
        O texto é truncado em `_CONTEXT_MAX_CHARS` caracteres para não exceder
        o limite de tokens do modelo (~2000 tokens).

        Args:
            master_session_id: ID da sessão mestra (chave da ShortTermMemory).
            depends_on: Lista de task_names cujos resultados devem ser incluídos.
            mounted: ``task_name`` -> caminho no container (``/deps_out/...``) das dependências montadas; o contexto
                mostra esse caminho em vez do caminho do host.

        Returns:
            String com o bloco de contexto pronta para prefilar o prompt,
            ou string vazia se não houver contexto disponível.
        """
        if not depends_on:
            return ""

        parts: list[str] = []
        from src.artifacts.subtask_output import SubtaskOutput
        for task_name in depends_on:
            entry = self._short_term_memory.read(master_session_id, f"result:{task_name}")
            if entry:
                try:
                    output = SubtaskOutput.from_json(entry.value)
                    parts.append(output.to_context_string(mounted_at=(mounted or {}).get(task_name)))
                except Exception:
                    # Fallback para texto bruto se não for JSON válido (compatibilidade)
                    parts.append(f"### Resultado de `{task_name}`\n{taint_if(entry.value, tags_tainted(entry.tags))}")
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
        - outros papéis conhecidos (AGENT_IDS) são preservados
        - papel desconhecido -> palavras-chave do prompt (subtarefas criadas fora do normalizador)
        """
        from src.orchestration.orchestrator import AGENT_IDS
        raw_agent = (task.agent_id or "developer").lower()
        if raw_agent in AGENT_IDS:
            agent_id = raw_agent
        else:
            p_lower = (task.prompt or "").lower()
            if any(k in p_lower for k in ("pesquis", "search", "artigo", "buscar", "document")):
                agent_id = "researcher"
            else:
                agent_id = "developer"

        # v18.7-subtask-contract: preserva todos os campos da tarefa (task_type, hipótese, papel, contrato...).
        return replace(task, agent_id=agent_id)

    def _record_attempt_event(
        self, task: "AgentTask", contract: "SubtaskContract | None", attempt_number: int, master_session_id: str
    ) -> None:
        """Evento ``subtask_attempt``: uma vez por tentativa, com o hash e o custo estimado do contrato.

        Só hash, tamanhos e marcas (nunca o texto do contrato, que pode ter dado do Researcher contaminado). Sem
        contrato (subtarefa do Researcher), ``contrato_sha256 = null``. Guarda o hash para conferir a revisão
        (``contrato_divergente``, ADR 022 §7). ``v18.7-exploration-metrics`` lê estes eventos.
        """
        try:  # observabilidade nunca derruba a execução
            sha = contract.sha256() if contract is not None else None
            chars = tokens = None
            if contract is not None:
                from src.llm.context_compression import estimate_tokens
                from src.utils.egress_fragments import plain_text

                text = plain_text(contract.fragments())
                chars, tokens = len(text), estimate_tokens(text)
            self._attempt_hashes[(master_session_id, task.task_name or "", attempt_number)] = sha
            get_telemetry().record_agent_event(
                execution_id=master_session_id,
                session_id=master_session_id,
                agent_id=task.agent_id,
                event_type="subtask_attempt",
                task_name=task.task_name or None,
                payload={
                    "task_name": task.task_name,
                    "attempt": attempt_number,
                    "contrato_sha256": sha,
                    "contrato_chars": chars,
                    "contrato_tokens_estimados": tokens,
                    "tarefa_original_truncada": bool(contract and contract.original_task_truncated_from),
                    "recorte_sha256": getattr(task, "recorte_sha256", None) or self._recorte_sha256_vigente(),
                    "limiar_mascarado": (
                        threshold_masked(contract, role_tainted("developer")) if contract is not None else False
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao registrar subtask_attempt", extra={"error": str(exc)})

    @staticmethod
    def _validated_metric(task: Any, review: Any, session_out_dir: Any, exploration: Any) -> dict[str, Any]:
        """Métrica principal do Problema, só quando a revisão a validou (para o resumo do evento da subtarefa).

        Vazio sem exploração, sem métrica no ``metrics.json`` ou sem revisão aprovada e verificada.
        """
        try:
            if exploration is None or review is None or not review.is_approved or not getattr(review, "verified", True):
                return {}
            objective = exploration.problem_objective()
            if objective is None or not safe_task_name(task.task_name or ""):
                return {}
            path = Path(session_out_dir) / task.task_name / "metrics.json"
            if not path.is_file():
                return {}
            values = metrics_of(json.loads(path.read_text(encoding="utf-8")))
            for key, value in values.items():
                if key == objective.metric or key.endswith(f".{objective.metric}"):
                    return {"metrica_validada": objective.metric, "valor_validado": float(value)}
        except Exception:  # noqa: BLE001 - o resumo do evento nunca atrapalha a subtarefa
            logger.debug("Métrica validada indisponível para o evento", exc_info=True)
        return {}

    @staticmethod
    def _recorte_sha256_vigente() -> str | None:
        """Hash do recorte do regimento vigente na sessão; ``None`` sem regimento vinculado."""
        sessao = sessao_atual()
        return sessao.recorte_atual().sha256 if sessao is not None else None

    def _check_contract_divergence(
        self, task: "AgentTask", attempt: int, review_sha: str, master_session_id: str
    ) -> None:
        """Compara o hash da revisão com o da tentativa; diferentes: evento ``contrato_divergente`` (não reprova)."""
        attempt_sha = self._attempt_hashes.get((master_session_id, task.task_name or "", attempt))
        if not review_sha or not attempt_sha or review_sha == attempt_sha:
            return
        logger.warning("Contrato divergente entre a execução e a revisão", extra={"task_name": task.task_name})
        try:
            get_telemetry().record_agent_event(
                execution_id=master_session_id,
                session_id=master_session_id,
                agent_id="autonomous_loop",
                event_type="contrato_divergente",
                task_name=task.task_name or None,
                payload={
                    "task_name": task.task_name, "attempt": attempt,
                    "hash_tentativa": attempt_sha, "hash_revisao": review_sha,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao registrar contrato_divergente", extra={"error": str(exc)})

    def _dependency_mounts(
        self, task: "AgentTask", plan: List["AgentTask"], resumed_deps: Dict[str, List[str]],
        dag_state: Dict[str, Any], resume: Any, master_session_id: str,
    ) -> tuple[Any, ...]:
        """Saídas das dependências concluídas da subtarefa, para a montagem somente leitura no sandbox (ADR 022 §9)."""
        depends: Dict[str, List[str]] = {t.task_name: [*t.depends_on, *resumed_deps.get(t.task_name, [])] for t in plan}
        concluded: Dict[str, str] = {
            name: master_session_id for name, state in dag_state.items() if state.get("status") in DONE_STATUSES
        }
        if resume is not None:
            for name, state in resume.completed.items():
                concluded.setdefault(name, resume.source_session_id)
                depends.setdefault(name, list(getattr(state, "depends_on", []) or []))
        return resolve_dependency_mounts(
            task.task_name, depends, concluded, self.orchestrator.output_manager.base_dir
        )

    def _dependency_listing(
        self, mounts: tuple[Any, ...], plan: List["AgentTask"], master_session_id: str, project_id: Optional[str]
    ) -> list[tuple[str, str, tuple[str, ...], int]]:
        """Item 10 do contrato: caminho montado e arquivos de cada dependência (nome real quando há alias)."""
        from src.artifacts.subtask_output import SubtaskOutput

        listing = []
        for mount in mounts:
            expected = next((t.expected_artifacts for t in plan if t.task_name == mount.task_name), [])
            aliases: Dict[str, str] = {}
            entry = self._short_term_memory.read(master_session_id, f"result:{mount.task_name}")
            if entry:
                try:
                    aliases = dict(SubtaskOutput.from_json(entry.value).artifact_aliases or {})
                except Exception:  # noqa: BLE001 - sem alias a listagem usa os nomes presentes
                    aliases = {}
            files, extra = dependency_files(mount.source, expected, aliases)
            listing.append((mount.task_name, dependency_target(project_id, mount.task_name) + "/", files, extra))
        return listing

    async def _attempt_contract(
        self, task: "AgentTask", plan: List["AgentTask"], original_task: str, master_session_id: str,
        mounts: tuple[Any, ...] = (), project_id: Optional[str] = None,
    ) -> "SubtaskContract":
        """Contrato da tentativa do Developer, a partir do plano vigente (ADR 022 §2)."""
        listing = await asyncio.to_thread(self._dependency_listing, mounts, plan, master_session_id, project_id)
        exploration = self._exploration(master_session_id)
        if exploration is not None:
            return await asyncio.to_thread(
                exploration.build_contract, task, plan, original_task, dependency_artifacts=listing
            )
        return build_developer_contract(task, plan, None, original_task, dependency_artifacts=listing)

    def _exploration(self, master_session_id: str) -> "ExplorationSession | None":
        """Exploração ativa da sessão (v18-hypothesis-loop); ``None`` mantém o laço de ciclo único da V17."""
        from src.orchestration.exploration import ExplorationSession

        getter = getattr(self.orchestrator, "get_exploration", None)
        found = getter(master_session_id) if callable(getter) else None
        return found if isinstance(found, ExplorationSession) else None

    async def _suspend_session(
        self, master_session_id: str, tasks: List["AgentTask"], final_results: List["AgentResult"], text: str
    ) -> "OrchestratorResult":
        """Pausa (retomável) a sessão que só tem pedidos ao pesquisador pela frente: ``aguarda_pesquisador``.

        O processo da sessão não espera: grava o checkpoint e sai com o código 4 (v18.7-background-sessions §1.5).
        """
        from src.orchestration.orchestrator import AgentResult, OrchestratorResult
        from src.session.states import MOTIVO_AGUARDA_PESQUISADOR, STATUS_AWAITING_RESEARCHER

        current = self.orchestrator.session_manager.get(master_session_id)
        payload = dict(current.payload) if current is not None else {}
        payload["motivo_parada"] = MOTIVO_AGUARDA_PESQUISADOR
        self.orchestrator.session_manager.update(master_session_id, status=STATUS_AWAITING_RESEARCHER, payload=payload)
        logger.warning("Sessão aguarda o pesquisador", extra={"master_session_id": master_session_id})
        final_results.append(
            AgentResult(
                agent_id="orchestrator", session_id=master_session_id, status="success", response={"text": text}
            )
        )
        self._short_term_memory.clear(master_session_id)
        succeeded = sum(1 for r in final_results if r.status == "success")
        return OrchestratorResult(
            results=final_results,
            total=len(tasks),
            succeeded=succeeded,
            failed=len(final_results) - succeeded,
            artifacts=self.orchestrator.output_manager.list_artifacts(master_session_id),
        )

    async def _wait_for_researcher(self, master_session_id: str, decisoes: tuple[str, ...]) -> str:
        """`assisted`: espera o pesquisador responder um pedido de ``decisoes`` (consulta o gate a cada
        ``GATE_POLL_SECONDS``). Não conta como ciclo ocioso nem como estagnação.

        Returns:
            ``"respondido"`` se há resposta nova ainda não vista; ``"parar"`` se um limite, a interrupção ou a ausência
            do terminal pede o fechamento (``_close_for_pending_stop``).
        """
        from src.config import GATE_POLL_SECONDS
        from src.session.chain import chain_session_ids

        gate = self.orchestrator.human_gate
        chain = chain_session_ids(self.orchestrator.session_manager, master_session_id)
        seen: set[int] = self.__dict__.setdefault("_gate_seen", set())
        while True:
            if self._pending_stop(master_session_id) is not None or self._usage_tracker.check().should_close:
                return "parar"
            answered = await asyncio.to_thread(gate.answered_unconsumed, chain)
            fresh = [r for r in answered if r.decisao in decisoes and r.id not in seen]
            if fresh:
                seen.update(r.id for r in fresh)
                return "respondido"
            await asyncio.sleep(max(float(GATE_POLL_SECONDS), 0.01))

    async def _close_for_pending_stop(
        self, master_session_id: str, prompt: str, tasks: List["AgentTask"], dag_state: Dict[str, Any],
        final_results: List["AgentResult"],
    ) -> "OrchestratorResult":
        """Fecha a sessão pelo motivo que interrompeu a espera pelo pesquisador (limite, interrupção ou ausência)."""
        reason = self._pending_stop(master_session_id) or self._usage_tracker.check().stop_reason
        return await self._close_session(
            reason or StopReason.INTERRUPTED, master_session_id, prompt, tasks, dag_state, final_results
        )

    async def _close_on_suggestion_failure(
        self,
        exc: Exception,
        master_session_id: str,
        prompt: str,
        tasks: List["AgentTask"],
        dag_state: Dict[str, Any],
        final_results: List["AgentResult"],
    ) -> "OrchestratorResult":
        """Falha ao sugerir caminhos: fecha com ``erro`` (nunca como ``sem_caminhos_promissores``; AGENTS.md §1.6)."""
        from src.orchestration.exploration import ExplorationStop

        logger.error(
            "Falha ao sugerir caminhos; sessão fechada com motivo_parada=erro. Verifique o grafo e o diretório de "
            "saída da sessão e retome a pesquisa.",
            extra={"error": type(exc).__name__, "detalhe": str(exc)[:200]},
        )
        return await self._close_exploration(
            ExplorationStop.ERROR, master_session_id, prompt, tasks, dag_state, final_results
        )

    async def _check_metric_available(self, exploration: Any, master_session_id: str) -> Optional[Tuple[str, str]]:
        """Confere a ``Metrica`` do ``Problema`` antes do primeiro planejamento (``v18.6-hypothesis-closure`` §4).

        Returns:
            ``(mensagem de aviso, motivo)`` se a métrica do critério não pode ser medida; senão ``None``.
        """
        try:
            found = await asyncio.to_thread(exploration.metric_availability)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - sem leitura do grafo não há como afirmar que a métrica existe
            found = (f"falha ao conferir a métrica do Problema ({type(exc).__name__})", "verifique o grafo")
        if found is None:
            return None
        reason, fix = found
        message = f"Métrica indisponível: {reason}. Correção: {fix}."
        if self._session_mode == "auto":
            message += " No modo auto, o Researcher definirá a métrica no plano e o Validator a validará."
        logger.warning(message, extra={"master_session_id": master_session_id})
        print_status("warning", message)
        get_telemetry().record_agent_event(
            execution_id=master_session_id,
            session_id=master_session_id,
            agent_id="autonomous_loop",
            event_type="metrica_indisponivel",
            payload={"motivo": reason[:300], "correcao": fix, "modo": self._session_mode},
        )
        return message, reason

    async def _close_untested_hypotheses(
        self,
        untested: List[Tuple[str, str]],
        idle_cycles: int,
        master_session_id: str,
        prompt: str,
        tasks: List["AgentTask"],
        dag_state: Dict[str, Any],
        final_results: List["AgentResult"],
    ) -> "OrchestratorResult":
        """Ciclos ociosos esgotados com hipótese sem tentativa: fecha com ``hipoteses_nao_testadas``.

        É uma parada de pesquisa, não uma falha: não acrescenta resultado de erro
        (``v18.6-auto-metrics-and-stop-reasons``).
        """
        from src.orchestration.exploration import ExplorationStop

        message = f"hipóteses sem tentativa após {idle_cycles} ciclos ociosos: " + ", ".join(h for h, _ in untested)
        logger.warning(message, extra={"hipoteses_sem_tentativa": [h for h, _ in untested]})
        print_status("warning", message)
        get_telemetry().record_agent_event(
            execution_id=master_session_id,
            session_id=master_session_id,
            agent_id="autonomous_loop",
            event_type="hipoteses_sem_tentativa",
            payload={
                "motivo_parada": ExplorationStop.UNTESTED_HYPOTHESES.value,
                "hipoteses": [h for h, _ in untested][:50],
                "ciclos_ociosos": idle_cycles,
                "mensagem": message,
            },
        )
        return await self._close_exploration(
            ExplorationStop.UNTESTED_HYPOTHESES, master_session_id, prompt, tasks, dag_state, final_results
        )

    async def _close_exploration(
        self,
        stop: Any,
        master_session_id: str,
        prompt: str,
        tasks: List["AgentTask"],
        dag_state: Dict[str, Any],
        final_results: List["AgentResult"],
    ) -> "OrchestratorResult":
        """Fechamento da exploração por critério próprio (solução, sem caminhos, teto de ciclos ou erro).

        Nas paradas normais (solução e sem caminhos) promove as descobertas da sessão antes de fechar; em todas grava
        o checkpoint e consolida pelo fechamento comum (``_close_session``). A falha da promoção nunca impede o
        fechamento.
        """
        if getattr(stop, "value", "") in ("solucao_encontrada", "sem_caminhos_promissores") and any(
            r.status == "success" for r in final_results
        ):
            try:
                await self._promote_findings(prompt, master_session_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a promoção é complementar
                logger.warning("Promoção de descobertas falhou", extra={"error": type(exc).__name__})
        get_telemetry().record_agent_event(
            execution_id=master_session_id,
            session_id=master_session_id,
            agent_id="autonomous_loop",
            event_type="exploration_stop",
            payload={"motivo_parada": getattr(stop, "value", str(stop))},
        )
        ok_before = sum(1 for r in final_results if r.status == "success")
        failed_before = len(final_results) - ok_before
        result = await self._close_session(stop, master_session_id, prompt, tasks, dag_state, final_results)
        if getattr(stop, "value", "") in ("solucao_encontrada", "sem_caminhos_promissores"):
            # Parada por critério da pesquisa (não por limite): o saldo reflete as subtarefas, sem contar o relatório
            # de síntese, como no fechamento de sucesso da V17.
            result.succeeded, result.failed, result.total = ok_before, failed_before, ok_before + failed_before
        return result

    async def _run_complex_path(self, prompt: str, master_session_id: str) -> "OrchestratorResult":
        """Executa a tarefa via caminho complexo (Planner -> Loop de Subtarefas em DAG)."""
        from src.orchestration.orchestrator import AgentResult, AgentTask, OrchestratorResult
        from src.orchestration.task_scheduler import TaskScheduler

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
                pending_stop=lambda: self._pending_stop(master_session_id),
            )
            self.orchestrator.register_usage_tracker(master_session_id, self._usage_tracker)

        resume = self._resume(master_session_id)
        if resume is not None:
            self._preload_resumed_results(master_session_id, resume)
        recorder = self._recorder(master_session_id)
        session_out_dir = self.orchestrator.output_manager.base_dir / master_session_id
        max_plan_retries = MAX_PLAN_RETRIES
        execution_feedback = ""
        final_results: List[AgentResult] = []
        tasks: List[AgentTask] = []
        current_plan_dicts: List[Dict[str, Any]] = []
        # V12.5.1 — Circuito de progresso zero: progresso do ciclo anterior (v16-pipeline-robustness §4)
        _previous_progress: CycleProgress | None = None
        _stalled_cycles = 0

        # v18-hypothesis-loop — exploração ativa (projeto com Problema confirmado): o laço repete planejar -> executar
        # -> consolidar -> sugerir até solução, falta de caminhos ou limite de uso. Sem ela, vale o laço de ciclo
        # único da V17 (e MAX_PLAN_RETRIES conta todos os ciclos). Com ela, MAX_PLAN_RETRIES conta só os planos
        # consecutivos rejeitados pelo Validator.
        exploration = self._exploration(master_session_id)
        exploring = exploration is not None
        if exploration is not None:
            unavailable = await self._check_metric_available(exploration, master_session_id)
            if unavailable is not None and self._session_mode == "auto":
                # v18.6-auto-metrics-and-stop-reasons: no modo auto o Researcher define a métrica no plano e o
                # Validator a valida; só depois ela vale para o registro de resultado. A sessão não deixa de iniciar.
                exploration.require_metric_definition(unavailable[1])
            exploration.set_usage_fraction(self._usage_fraction)
            if resume is not None:  # design §4.4: origem das hipóteses do sistema vinda do checkpoint
                exploration.restore_system_origin(resume.checkpoint.hipoteses_do_sistema)
                exploration.restore_objective(resume.checkpoint.exploracao_estado)
        cycle_no = 0
        rejected_plans = 0
        rejection_issues: List[str] = []
        legacy_attempt = 0
        explore_next = False
        done_results: Dict[str, AgentResult] = {}  # subtarefas concluídas na sessão (nunca reexecutadas)
        latest_results: Dict[str, AgentResult] = {}
        cumulative_tasks: Dict[str, AgentTask] = {}
        cumulative_dag: Dict[str, Dict[str, Any]] = {}
        if exploration is not None:
            try:
                await exploration.suggest()  # caminhos em aberto e oportunidades aprovadas, antes do primeiro plano
            except SuggestionError as exc:
                return await self._close_on_suggestion_failure(
                    exc, master_session_id, prompt, list(cumulative_tasks.values()), cumulative_dag, final_results
                )

        while True:
            if exploring:
                if rejected_plans >= max_plan_retries:
                    # v18.7-exploration-limits §9.3: com ``explorar`` (padrão) a rejeição em sequência aciona o
                    # Curator; com ``parar`` fecha no auto e pede ao pesquisador no assisted/semi.
                    from src import config
                    from src.orchestration.exploration import ExplorationStop

                    logger.error("Planos consecutivos rejeitados", extra={"n": rejected_plans})
                    stop_args = (master_session_id, prompt, list(cumulative_tasks.values()), cumulative_dag,
                                 final_results)
                    if config.ON_PLAN_REJECTIONS == "explorar":
                        try:
                            intervened = await exploration.intervene_on_plan_rejections(
                                rejection_issues, rejected_plans
                            )
                        except SuggestionError as exc:
                            return await self._close_on_suggestion_failure(exc, *stop_args)
                        if intervened:
                            execution_feedback += (
                                "\nOs últimos planos foram rejeitados repetidamente: proponha uma abordagem ou "
                                "variação diferente, respondendo às sugestões do Curator."
                            )
                            explore_next = True
                        rejected_plans = 0
                        continue
                    if self._session_mode == "auto":
                        return await self._close_exploration(ExplorationStop.REJECTED_PLANS, *stop_args)
                    await asyncio.to_thread(exploration.request_plan_rejections, rejection_issues, rejected_plans)
                    answer = await asyncio.to_thread(exploration.plan_rejection_answer)
                    while answer is None and self._session_mode == "assisted":
                        if await self._wait_for_researcher(master_session_id, ("decidir_continuidade",)) == "parar":
                            return await self._close_for_pending_stop(*stop_args)
                        answer = await asyncio.to_thread(exploration.plan_rejection_answer)
                    if answer == "parar":
                        return await self._close_exploration(ExplorationStop.REJECTED_PLANS, *stop_args)
                    if answer is None:
                        return await self._suspend_session(
                            master_session_id, list(cumulative_tasks.values()), final_results,
                            "Sessão aguarda o pesquisador: planos rejeitados em sequência.",
                        )
                    rejected_plans = 0
                plan_attempt = cycle_no
            else:
                if legacy_attempt >= max_plan_retries:
                    break
                plan_attempt = legacy_attempt
                legacy_attempt += 1
            logger.info(f"Iniciando ciclo de planejamento/recuperação {plan_attempt+1}/{max_plan_retries}")

            # V18/usage-limits — não inicia um novo ciclo de planejamento (que despacharia
            # novas chamadas de exploração) se o orçamento já foi esgotado por um ciclo
            # anterior (ex: retentativas de conexão atingidas durante o último gather).
            await self._refresh_model_versions()  # v18.5: digest do Ollama a cada ciclo (checkpoint)
            await self._sincronizar_objetivo_do_regimento(exploration)
            pre_cycle_status = self._usage_tracker.check()
            if pre_cycle_status.should_close:
                return await self._close_session(
                    pre_cycle_status.stop_reason, master_session_id, prompt, tasks, {}, final_results
                )

            # 1. Planejamento ou Recuperação Incremental
            try:
                planning_kwargs: Dict[str, Any] = {"explore": True} if (exploring and explore_next) else {}
                tasks = await self.orchestrator._run_planning_loop(
                    prompt=prompt,
                    master_session_id=master_session_id,
                    previous_plan=current_plan_dicts if current_plan_dicts else None,
                    execution_feedback=execution_feedback,
                    **planning_kwargs,
                )
            except PlanningStalled as stalled:
                logger.error("Planejamento encerrado por reprovação repetida", extra={"issues": stalled.issues})
                if exploring:
                    rejected_plans += 1
                    rejection_issues = [str(i) for i in stalled.issues]
                    issues_text = "; ".join(stalled.issues)[:500]
                    execution_feedback = f"O Validador reprovou o plano repetidamente: {issues_text}"
                    continue
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
                # v18.7-benchmark-fixes: cota ou teto de gasto esgotado no planejamento não é plano rejeitado nem
                # motivo de replanejar: a sessão fecha por ``limite_cota_provedor``.
                if self._usage_tracker.check().stop_reason == StopReason.PROVIDER_QUOTA:
                    return await self._close_session(
                        StopReason.PROVIDER_QUOTA, master_session_id, prompt, tasks, {}, final_results
                    )
                logger.error(f"Falha na tentativa {plan_attempt+1} de gerar/recuperar plano")
                execution_feedback = "O orquestrador falhou ao gerar um plano aprovado."
                if exploring:
                    rejected_plans += 1
                    last_issues = getattr(self.orchestrator, "last_plan_issues", {})
                    rejection_issues = list(last_issues.get(master_session_id, []))
                continue
            rejected_plans = 0

            # v18.7-dependency-artifacts: dependências concluídas na sessão anterior saem de ``depends_on`` abaixo, mas
            # o consumidor ainda lê as saídas delas (montagem em /deps_out); guardadas aqui antes da poda.
            resumed_deps: Dict[str, List[str]] = {}
            if resume is not None:
                # Dependências concluídas na sessão anterior têm o resultado pré-carregado: não exigem nó no plano.
                names = {t.task_name for t in tasks if t.task_name}
                for t in tasks:
                    resumed_deps[t.task_name] = [d for d in t.depends_on if d not in names and d in resume.completed]
                    t.depends_on = [d for d in t.depends_on if d in names or d not in resume.completed]
            try:
                # v18.7-hypothesis-linking §1: DAG inválido volta ao Researcher antes da governança (``prepare_cycle``
                # deriva ``PREPARA`` percorrendo o grafo de dependências e o pressupõe válido).
                TaskScheduler.validate_dag(tasks)
            except ValueError as e:
                execution_feedback = f"Grafo de dependências inválido: {e}"
                logger.error(execution_feedback)
                continue

            plan_tasks = tasks  # plano completo (inclusive o que a governança retirar), base do próximo replanejamento
            if exploration is not None:
                # v18-hypothesis-loop §2/§4: grava hipóteses/decisões/respostas e aplica a governança do SessionMode.
                plan_extras = self.orchestrator.take_plan_extras(master_session_id)

                async def _prepare_cycle(plan: List["AgentTask"] = tasks) -> Any:
                    return await asyncio.to_thread(
                        exploration.prepare_cycle, plan, plan_extras,
                        done=set(done_results),
                        done_tasks={n: cumulative_tasks[n] for n in done_results if n in cumulative_tasks},
                    )

                try:
                    outcome = await _prepare_cycle()
                    # v18.7-persistent-human-gate §1.5: no `assisted`, com o terminal presente, a sessão espera o
                    # pesquisador decidir as hipóteses pendentes (sem contar como ciclo ocioso nem estagnação).
                    while (
                        outcome.pending_approval and self._session_mode == "assisted"
                        and not [t for t in outcome.tasks if t.task_name not in done_results]
                    ):
                        if await self._wait_for_researcher(master_session_id, ("aprovar_hipotese",)) == "parar":
                            return await self._close_for_pending_stop(
                                master_session_id, prompt, list(cumulative_tasks.values()), cumulative_dag,
                                final_results,
                            )
                        outcome = await _prepare_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - o grafo não aceitou o plano: fecha com checkpoint
                    logger.error(
                        "Plano não gravado no grafo; exploração encerrada", extra={"error": type(exc).__name__}
                    )
                    from src.orchestration.exploration import ExplorationStop

                    return await self._close_exploration(
                        ExplorationStop.ERROR, master_session_id, prompt, list(cumulative_tasks.values()),
                        cumulative_dag, final_results,
                    )
                tasks = outcome.tasks
                await link_preparations(
                    self.orchestrator, outcome.preparation_links, cumulative_tasks, master_session_id
                )
                if outcome.dropped:
                    logger.info("Subtarefas retiradas pela governança", extra={"dropped": outcome.dropped})
                new_tasks = [t for t in tasks if t.task_name not in done_results]
                if not new_tasks:
                    # Ciclo ocioso: nada novo a executar.
                    if outcome.pending_approval:
                        return await self._suspend_session(
                            master_session_id, list(cumulative_tasks.values()), final_results,
                            "Sessão aguarda o pesquisador: há hipóteses aguardando a aprovação.",
                        )
                    exploration.idle_cycles += 1
                    cycle_no += 1
                    in_plan = {t.hypothesis_id for t in plan_tasks if t.hypothesis_id}
                    try:
                        has_open = exploration.idle_cycles < 2 and await asyncio.to_thread(
                            exploration.has_open_paths, in_plan
                        )
                        # v18.6-hypothesis-closure §5: hipótese em_teste sem tentativa nunca fecha como "sem caminhos".
                        untested = await asyncio.to_thread(exploration.untested_hypotheses)
                    except SuggestionError as exc:
                        return await self._close_on_suggestion_failure(
                            exc, master_session_id, prompt, list(cumulative_tasks.values()), cumulative_dag,
                            final_results,
                        )
                    if not has_open:
                        from src.orchestration.exploration import ExplorationStop

                        if untested:
                            return await self._close_untested_hypotheses(
                                untested, exploration.idle_cycles, master_session_id, prompt,
                                list(cumulative_tasks.values()), cumulative_dag, final_results,
                            )
                        return await self._close_exploration(
                            ExplorationStop.NO_PATHS, master_session_id, prompt, list(cumulative_tasks.values()),
                            cumulative_dag, final_results,
                        )
                    execution_feedback = (
                        "Nenhuma subtarefa nova no plano. Há hipóteses em teste ou sugestões do Curator ainda "
                        "abertas: inclua subtarefas que as testem, ou encerre sem hipótese nova."
                    )
                    if untested:
                        execution_feedback += "\nHipóteses ainda sem nenhuma tentativa: " + "; ".join(
                            f"{hid} ({text})" for hid, text in untested
                        ) + "."
                    explore_next = True
                    current_plan_dicts = [
                        {k: v for k, v in t.__dict__.items() if v is not None and k not in _PLAN_ECHO_EXCLUDED}
                        for t in plan_tasks
                    ]
                    continue
                exploration.idle_cycles = 0
                if len(new_tasks) > self.max_subtasks:
                    logger.warning(f"Número de subtarefas novas ({len(new_tasks)}) excede o limite {self.max_subtasks}")
                    keep = {t.task_name for t in new_tasks[: self.max_subtasks]}
                    tasks = [t for t in tasks if t.task_name in done_results or t.task_name in keep]

            # Atualiza o estado do plano atual (para a próxima iteração se falhar)
            current_plan_dicts = [
                {k: v for k, v in t.__dict__.items() if v is not None and k not in _PLAN_ECHO_EXCLUDED} 
                for t in plan_tasks
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
            await self._check_operational_thresholds(master_session_id)

            # V18/usage-limits — limites reais (não apenas avisos): tokens, tempo e
            # retentativas de conexão, checados no mesmo ponto do ciclo que os avisos
            # operacionais acima (uma vez por ciclo de planejamento).
            plan_usage_status = self._usage_tracker.check()
            if plan_usage_status.should_close:
                return await self._close_session(
                    plan_usage_status.stop_reason, master_session_id, prompt, tasks, {}, final_results
                )

            if not exploring and len(tasks) > self.max_subtasks:
                logger.warning(f"Número de subtarefas ({len(tasks)}) excede o limite {self.max_subtasks}")
                tasks = tasks[:self.max_subtasks]

            try:  # as retiradas levam junto o que depende delas: o subgrafo mantido continua válido (confirmação)
                TaskScheduler.validate_dag(tasks)
            except ValueError as e:
                execution_feedback = f"Grafo de dependências inválido: {e}"
                logger.error(execution_feedback)
                continue

            if recorder is not None:
                await asyncio.to_thread(recorder.set_plan, [plan_entry(t) for t in tasks])
                if exploration is not None:  # design §4.4: a origem das hipóteses do sistema sobrevive à retomada
                    await asyncio.to_thread(recorder.set_system_origin, exploration.system_origin_snapshot())

            final_results = []
            cycle_results: Dict[str, AgentResult] = {}  # resultado final de cada subtarefa executada NESTE ciclo
            cycle_negatives: Dict[str, Dict[str, Any]] = {}  # resultados negativos NESTE ciclo
            cycle_observations: List[Tuple[str, str]] = []  # (subtarefa, observação do revisor) NESTE ciclo
            
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
                        if dag_state[dep]["status"] not in DONE_STATUSES:
                            # Dependência falhou ou foi cancelada -> Cancelar esta tarefa
                            logger.warning(f"Subtarefa {task.task_name} cancelada porque a dependência '{dep}' falhou.")
                            if task.task_name:
                                dag_state[task.task_name]["status"] = "cancelled"
                                dag_state[task.task_name]["future"].set_result(None)
                            return

                # v18-research-continuity — subtarefa concluída na sessão anterior: nunca reexecutada; o resultado
                # (resumo e artefatos) já foi entregue às dependentes por `_preload_resumed_results`.
                if resume is not None and task.task_name in resume.completed:
                    done = resume.completed[task.task_name]
                    logger.info("Subtarefa já concluída na sessão anterior; não reexecutada",
                                extra={"task_name": task.task_name, "source": resume.source_session_id})
                    resumed_result = AgentResult(
                        agent_id=done.agent_id or task.agent_id,
                        session_id=master_session_id,
                        status="success",
                        response={"text": done.resultado_resumo, "resumed_from": resume.source_session_id},
                    )
                    final_results.append(resumed_result)
                    cycle_results[task.task_name] = resumed_result
                    dag_state[task.task_name]["status"] = "success"
                    dag_state[task.task_name]["future"].set_result(None)
                    return

                # v18-hypothesis-loop — subtarefa concluída em ciclo anterior desta sessão: nunca reexecutada (o plano
                # replanejado a repete inalterada para manter as dependências); o resultado segue na memória curta.
                if task.task_name and task.task_name in done_results:
                    dag_state[task.task_name]["status"] = "success"
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

                # v18.7-session-events-terminal — ``cancelar <apelido> <subtarefa>``: a subtarefa que ainda não começou
                # é retirada com o motivo ``cancelada_pesquisador`` (as dependentes ficam sem a dependência).
                if task.task_name and is_cancelled(task.task_name):
                    logger.info("Subtarefa cancelada pelo pesquisador", extra={"task_name": task.task_name})
                    dag_state[task.task_name]["status"] = "abandonada"
                    dag_state[task.task_name]["error"] = MOTIVO_CANCELADA
                    if recorder is not None:
                        await asyncio.to_thread(
                            recorder.subtask_finished,
                            task.task_name,
                            status=ST_ABANDONADA,
                            tentativas=0,
                            resumo="cancelada pelo pesquisador antes de começar",
                            causa_falha=MOTIVO_CANCELADA,
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

                logger.info(
                    f"Iniciando subtarefa {index+1}/{len(tasks)}: {task.agent_id} [{task.task_name or 'sem nome'}]"
                )

                # V2: Constrói prefixo de contexto
                project_id = self.orchestrator._session_project_id(master_session_id)
                first_mounts = self._dependency_mounts(task, tasks, resumed_deps, dag_state, resume, master_session_id)
                context_prefix = self._build_context_prefix(
                    master_session_id,
                    task.depends_on,
                    {m.task_name: dependency_target(project_id, m.task_name) for m in first_mounts},
                )
                # v18.5-egress-gate — prompt escrito por modelo que aceita dados brutos leva a marca de contaminação.
                own_prompt = taint_if(task.prompt, task.prompt_tainted)
                task_prompt = context_prefix + own_prompt if context_prefix else own_prompt

                if context_prefix:
                    logger.info(
                        "Contexto de etapas anteriores injetado no prompt",
                        extra={
                            "task_name": task.task_name,
                            "depends_on": task.depends_on,
                            "context_chars": len(context_prefix),
                        },
                    )

                # ``prompt_tainted`` já foi aplicado em ``own_prompt``; os demais campos da tarefa seguem até o runtime.
                enriched_task = replace(task, prompt=task_prompt, mode=self._session_mode, prompt_tainted=False)

                enriched_task = self._enrich_task_prompt(enriched_task)
                enriched_task = self._dispatch_subtask(enriched_task)

                success = False
                last_result = None
                last_review: Dict[str, Any] | None = None  # parecer do Validator da última tentativa
                ambiguous = False  # revisão terminou em ``criterio_ambiguo`` (a falha não é do Developer)
                attempt_errors: List[str] = []  # V15.3/G5 — insumo do DivergenceReport
                # retry_key já calculada no início da coroutine (usada também pelo guard
                # de tarefa abandonada, acima).

                # Retry Loop — cada iteração conta como uma tentativa GLOBAL da tarefa
                # (SESSION_MAX_TASK_RETRIES), não apenas local a este dispatch.
                attempt = 0
                while True:
                    attempt_number = self._usage_tracker.record_task_attempt(retry_key)
                    attempt = attempt_number - 1  # índice 0-based, compatível com os logs abaixo
                    if recorder is not None and task.task_name:
                        await asyncio.to_thread(recorder.subtask_started, task.task_name, attempt_number)
                    logger.info(
                        f"Executando tentativa {attempt_number}/{self._usage_tracker.budget.max_task_retries} "
                        f"para {task.agent_id} [{task.task_name}]"
                    )

                    # V5.8 — Telemetria: subtask_start (apenas na primeira tentativa)
                    if attempt == 0:
                        if task.task_name:
                            mark_task_started(task.task_name)
                        telemetry = get_telemetry()
                        telemetry.record_agent_event(
                            execution_id=master_session_id,
                            session_id=master_session_id,
                            agent_id=task.agent_id,
                            event_type="subtask_start",
                            task_name=task.task_name or None,
                            payload={"depends_on": task.depends_on},
                        )

                    mounts = self._dependency_mounts(task, tasks, resumed_deps, dag_state, resume, master_session_id)
                    enriched_task = replace(enriched_task, dependency_mounts=mounts)
                    if contract_applies(enriched_task):
                        # v18.7-subtask-contract: reconstruído do plano vigente a cada tentativa (design §4).
                        contract = await self._attempt_contract(
                            task, tasks, prompt, master_session_id, enriched_task.dependency_mounts, project_id
                        )
                        long_fields = oversized_fields(contract)
                        if long_fields:
                            # Plano aprovado com avisos não despacha campo acima do teto (design §8.1 item 9).
                            logger.warning(
                                "Subtarefa retirada: campo do contrato acima do teto",
                                extra={"task_name": task.task_name, "campos": long_fields,
                                       "motivo": DROP_LONG_FIELD},
                            )
                            if task.task_name:
                                dag_state[task.task_name]["status"] = "cancelled"
                                dag_state[task.task_name]["error"] = f"{DROP_LONG_FIELD}: {', '.join(long_fields)}"
                                dag_state[task.task_name]["future"].set_result(None)
                            return
                        enriched_task = replace(enriched_task, contract=contract)
                        logger.info(
                            "Contrato da subtarefa montado",
                            extra={"task_name": task.task_name, "attempt": attempt_number,
                                   "contract_sha256": contract.sha256()},
                        )

                    self._record_attempt_event(task, enriched_task.contract, attempt_number, master_session_id)
                    result = await self.orchestrator._execute_agent(enriched_task, master_session_id)
                    last_result = result
                    last_review = None

                    if result.status == "success":
                        success = True
                        # V6.3: executa a revisão da subtarefa se habilitado e houver critérios
                        review = None
                        from src.config import REVIEW_ENABLED, REVIEW_MODE
                        if REVIEW_ENABLED and REVIEW_MODE == "per_subtask" and task.validation_criteria:
                            logger.info(f"Iniciando revisão da subtarefa {task.task_name}")
                            review = await self._review_subtask(
                                task, result, master_session_id, attempt_number,
                                **({"contract": enriched_task.contract} if enriched_task.contract is not None else {}),
                            )
                            last_review = review
                            for note in review.get("observacoes") or []:
                                cycle_observations.append((task.task_name or "", str(note)))
                            if review.get("status") == "fail" and review.get("outcome") == "resultado_negativo":
                                # v18.6-hypothesis-closure: hipótese refutada por limiar é conclusão, não falha.
                                result.response["outcome"] = "resultado_negativo"
                                cycle_negatives[task.task_name or ""] = {
                                    "hypothesis": task.hypothesis_ref or task.hypothesis_id or "",
                                    "findings": review.get("negative_findings") or [],
                                }
                                logger.info(f"Subtarefa {task.task_name} concluída com resultado negativo")
                            elif review.get("outcome") == "criterio_ambiguo":
                                # v18.7-subtask-contract (ADR 022 §2.7): sem a chave sem qualificador o critério não
                                # decide; o resultado fica não validado e o caso volta ao Researcher.
                                success, ambiguous = False, True
                                result.status = "error"
                                result.error = f"Critério ambíguo: {', '.join(review.get('issues', []))}"
                                for line in review.get("issues") or []:
                                    cycle_observations.append((task.task_name or "", f"{line}; indique a chave ou "
                                                               "grave a chave sem qualificador"))
                                logger.warning(f"Subtarefa {task.task_name} com critério ambíguo")
                            elif review.get("status") == "fail":
                                success = False
                                result.status = "error"
                                result.error = f"Falha na revisão: {', '.join(review.get('issues', []))}"
                                logger.warning(
                                    f"Subtarefa {task.task_name} reprovada na revisão",
                                    extra={"issues": review.get("issues")},
                                )
                            else:
                                logger.info(f"Subtarefa {task.task_name} aprovada na revisão")

                        if success and task.task_name:
                            # V6.4: Cria output estruturado
                            from src.artifacts.subtask_output import SubtaskOutput
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
                                tags=with_taint_tag(
                                    ["subtask_result", task.task_name, "structured"], output.tainted is not False
                                ),
                            )
                            
                            if task.agent_id == "code":
                                await self._extract_code_patterns(result, master_session_id)
                        break
                    else:
                        logger.warning(
                            f"Tentativa {attempt+1} de {task.task_name} falhou", extra={"error": result.error}
                        )
                        attempt_errors.append(result.error or "Erro desconhecido")

                        # v18.7-benchmark-fixes: cota ou teto de gasto esgotado no provedor não se resolve com nova
                        # tentativa; a sessão fecha por ``limite_cota_provedor`` no próximo ponto de verificação.
                        if result.error_category == "cota_provedor":
                            break

                        # V13.5.1: Orquestrador lista artefatos reais antes de cada retry.
                        artifacts_on_disk = self.orchestrator.output_manager.list_artifacts(master_session_id)
                        artifact_context = ""
                        if artifacts_on_disk:
                            artifact_context = (
                                "\n\n[ARTEFATOS PARCIAIS EXISTENTES EM DISCO]\n"
                                + mark_artifact_names("\n".join(f"  - {a}" for a in artifacts_on_disk))
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
                                value=json.dumps(memory_context),
                                tainted=True,  # previous_error é saída de execução: nunca stderr cru sem marca
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
                            f"Erro: {mark_execution_output(str(result.error or 'Erro desconhecido'), 'tentativa')}\n"
                            f"Instrução: Tente uma abordagem diferente para resolver o problema.\n"
                        )
                        enriched_task = replace(
                            enriched_task,
                            prompt=enriched_task.prompt + artifact_context + error_context,
                            retry_attempt=attempt + 1,  # V12.3.3: próxima tentativa
                            contract=None,  # reconstruído do plano vigente na próxima tentativa
                            dependency_mounts=(),  # recalculadas na próxima tentativa
                        )
                        await asyncio.sleep(1)

                if last_result:
                    final_results.append(last_result)
                    if task.task_name:
                        cycle_results[task.task_name] = last_result

                # v17-structural-fact-ingestion — fatos da subtarefa (revisada) no grafo, sem LLM.
                await ingest_subtask(self.orchestrator, task, last_result, last_review, master_session_id)

                # v18-research-continuity — checkpoint do fim da subtarefa (status, tentativas, artefatos, resumo).
                if recorder is not None and task.task_name:
                    if success:
                        cp_status = ST_CONCLUIDA
                    elif self._usage_tracker.task_retries_exhausted(retry_key):
                        cp_status = ST_ABANDONADA
                    else:
                        cp_status = ST_FALHOU
                    cp_text = ""
                    if last_result is not None:
                        cp_text = (
                            str(last_result.response.get("text") or "") if success else str(last_result.error or "")
                        )
                    await asyncio.to_thread(
                        recorder.subtask_finished,
                        task.task_name,
                        status=cp_status,
                        tentativas=self._usage_tracker.task_attempts(retry_key),
                        resumo=cp_text,
                        marca=resumo_marca(role_tainted(task.agent_id), task.agent_id),
                        artefatos=list_task_artifacts(session_out_dir, task.task_name),
                        causa_falha="ambigua" if ambiguous else (
                            "infraestrutura" if (not success and getattr(last_result, "error_category", None)) else None
                        ),
                    )

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
                    payload={
                        "success": success, "attempts": attempt + 1,
                        **self._validated_metric(task, last_review, session_out_dir, exploration),
                    },
                )

                # Fase 3 V5: Hardware snapshot + Monitoramento de Saúde
                self._record_hardware_snapshot(master_session_id, task.task_name or None)

                if task.task_name:
                    if success:
                        dag_state[task.task_name]["status"] = (
                            "concluded_negative" if task.task_name in cycle_negatives else "success"
                        )
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
            if self._usage_tracker.budget.max_minutes is None:  # modo sem limite: nenhum prazo de ciclo
                gather_timeout = None
            else:
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

            if exploration is not None:
                # Acumula o que o ciclo produziu (a sessão agora tem vários ciclos) e fecha o ciclo no grafo: status
                # das hipóteses e avaliação das decisões, só pela regra de réplicas.
                for t in tasks:
                    if t.task_name:
                        cumulative_tasks[t.task_name] = t
                for name, state in dag_state.items():
                    cumulative_dag[name] = {"status": state["status"], "error": state.get("error")}
                for name, result in cycle_results.items():
                    latest_results[name] = result
                    if dag_state.get(name, {}).get("status") in DONE_STATUSES:
                        done_results[name] = result
                final_results = list(latest_results.values())
                cycle_no += 1
                exploration.cycles = cycle_no
                try:
                    await asyncio.to_thread(
                        exploration.after_cycle,
                        [n for n, state in dag_state.items() if state["status"] == "abandonada"],
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - a avaliação é complementar: a pesquisa segue
                    logger.warning("Avaliação do ciclo falhou", extra={"error": type(exc).__name__})

            # v17-curator-agent — checkpoint de consolidação ao fim do ciclo de planejamento (falha isolada).
            try:
                await self.orchestrator.curator_consolidate(master_session_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a falha do Curator nunca derruba a sessão
                logger.warning("Checkpoint do Curator falhou", extra={"error": type(exc).__name__})
            if exploration is not None:
                try:
                    await exploration.suggest()  # o Curator sugere novos caminhos (determinístico)
                except SuggestionError as exc:
                    return await self._close_on_suggestion_failure(
                        exc, master_session_id, prompt, list(cumulative_tasks.values()), cumulative_dag, final_results
                    )
            try:  # v18-research-continuity — hipóteses, decisões e descobertas no checkpoint
                await asyncio.to_thread(self.orchestrator.refresh_graph_checkpoint, master_session_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Checkpoint sem estado do grafo", extra={"error": type(exc).__name__})

            if exploration is not None:
                # v18.7-exploration-limits §5 e §6: avalia o objetivo tipado do Problema e aplica a política
                # ao atingi-lo (parar, perguntar ou continuar). A contagem de réplicas da hipótese não decide; a
                # resposta do pesquisador vem do gate persistente, nunca do terminal da sessão.
                objective_state = None
                try:
                    objective_state = await asyncio.to_thread(exploration.evaluate_objective)
                    decision = await asyncio.to_thread(exploration.objective_decision)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - sem leitura do grafo não há como afirmar o objetivo
                    logger.warning("Critério do objetivo indisponível", extra={"error": type(exc).__name__})
                    decision = "seguir"
                if recorder is not None:
                    await asyncio.to_thread(recorder.set_exploration_state, exploration.objective_snapshot())
                if decision != "seguir":
                    from src.orchestration.exploration import ExplorationStop

                    stop_args = (master_session_id, prompt, list(cumulative_tasks.values()), cumulative_dag,
                                 final_results)
                    while decision == "aguardar" and self._session_mode == "assisted":
                        waited = await self._wait_for_researcher(master_session_id, ("decidir_objetivo_atingido",))
                        if waited == "parar":
                            return await self._close_for_pending_stop(*stop_args)
                        decision = await asyncio.to_thread(exploration.objective_decision)
                    if decision == "encerrar":
                        return await self._close_exploration(ExplorationStop.SOLUTION, *stop_args)
                    if decision == "aguardar" and self._session_mode == "assisted":
                        return await self._suspend_session(
                            master_session_id, list(cumulative_tasks.values()), final_results,
                            "Sessão aguarda o pesquisador: objetivo atingido, à espera da decisão.",
                        )
                    # semi/auto sem resposta: segue com o que não depende dela (o pedido continua pendente)
                else:
                    # v18.7-exploration-limits §7: estagnação (intervenção do Curator) e saturação; a sessão nunca
                    # fecha por estagnação, só por saturação confirmada no auto ou por ``parar`` do pesquisador.
                    from src.orchestration.exploration import ExplorationStop

                    try:
                        stall_stop = await exploration.manage_stagnation(objective_state)
                    except SuggestionError as exc:
                        return await self._close_on_suggestion_failure(
                            exc, master_session_id, prompt, list(cumulative_tasks.values()), cumulative_dag,
                            final_results,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - a estagnação nunca derruba a pesquisa
                        logger.warning("Estagnação não avaliada", extra={"error": type(exc).__name__})
                        stall_stop = None
                    if stall_stop is not None:
                        if recorder is not None:
                            await asyncio.to_thread(recorder.set_exploration_state, exploration.objective_snapshot())
                        return await self._close_exploration(
                            ExplorationStop(stall_stop), master_session_id, prompt, list(cumulative_tasks.values()),
                            cumulative_dag, final_results,
                        )
                    if recorder is not None:
                        await asyncio.to_thread(recorder.set_exploration_state, exploration.objective_snapshot())

            # Verifica se houve alguma falha
            failed_tasks = [t for t, state in dag_state.items() if state["status"] in ("failed", "cancelled")]
            abandoned_tasks = [t for t, state in dag_state.items() if state["status"] == "abandonada"]

            if not failed_tasks:
                # Sucesso total (possivelmente com tarefas abandonadas em ramificações
                # independentes do DAG — design §3, "Tarefa abandonada").
                succeeded = sum(1 for r in final_results if r.status == "success")
                failed = len(final_results) - succeeded
                cycle_succeeded = (
                    sum(1 for r in cycle_results.values() if r.status == "success") if exploring else succeeded
                )

                # V18/usage-limits — se TODAS as tarefas do ciclo foram abandonadas por
                # retentativas (nada teve sucesso), a sessão inteira fecha com
                # motivo_parada="limite_retentativas" (design §3, "Todas abandonadas").
                if abandoned_tasks and cycle_succeeded == 0 and self._usage_tracker.all_pending_abandoned(
                    list(dag_state.keys())
                ):
                    return await self._close_session(
                        StopReason.RETRIES, master_session_id, prompt,
                        list(cumulative_tasks.values()) if exploring else tasks,
                        cumulative_dag if exploring else dag_state, final_results,
                    )

                if exploring:
                    # v18-hypothesis-loop: sucesso do ciclo não encerra a pesquisa; replaneja em modo de exploração.
                    execution_feedback = self._exploration_feedback(cycle_no, cycle_results, abandoned_tasks)
                    if cycle_negatives:
                        execution_feedback += "\n" + negative_result_feedback(cycle_negatives)
                    observed = review_observations_feedback(cycle_observations)
                    if observed:
                        execution_feedback += "\n" + observed
                    objective_note = exploration.objective_feedback()
                    if objective_note:
                        execution_feedback += "\n" + objective_note
                    if consume_replan():  # ``replanejar`` já é o que o ciclo de exploração faz; registra o pedido
                        execution_feedback += "\nO pesquisador pediu um replanejamento neste ponto."
                    explore_next = True
                    continue

                if consume_replan() and plan_attempt + 1 < max_plan_retries:
                    # v18.7-session-events-terminal — ``replanejar``: depois das subtarefas em curso o Researcher
                    # replaneja (MODO: REPLAN) em vez de a pesquisa fechar com este plano.
                    execution_feedback = (
                        "O pesquisador pediu um replanejamento. Subtarefas concluídas não são repetidas; revise o "
                        "plano a partir dos resultados obtidos."
                    )
                    explore_next = False
                    continue

                if succeeded > 0:
                    await self._promote_findings(prompt, master_session_id)
                    # Etapa V6.7: Síntese final com o Summarizer
                    final_report = await self._synthesize_results(prompt, final_results, master_session_id)
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
            explore_next = False
            succeeded_tasks = succeeded_task_names(dag_state)
            logger.warning(f"O plano falhou nas tarefas: {failed_tasks}. Iniciando recuperação incremental...")

            # V12.5.1 — Circuit breaker: detecta progresso zero entre ciclos consecutivos
            # v16-pipeline-robustness §4 — progresso = mais sucessos OU mudança na assinatura dos
            # erros; dispara só após CIRCUIT_BREAKER_STALL_CYCLES ciclos consecutivos sem progresso.
            graph_counts = (None, None)
            if exploration is not None:
                try:
                    graph_counts = await asyncio.to_thread(exploration.session_progress)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - sem o grafo vale a regra por nomes
                    logger.warning("Progresso do grafo indisponível", extra={"error": type(exc).__name__})
            current_progress = CycleProgress(
                succeeded=frozenset(succeeded_tasks),
                failure_signatures=frozenset(
                    error_signature(t, dag_state[t].get("error")) for t in failed_tasks
                ),
                experiments=graph_counts[0],
                results=graph_counts[1],
            )
            if _previous_progress is not None and not current_progress.advanced_from(_previous_progress):
                _stalled_cycles += 1
            else:
                _stalled_cycles = 0
            if _stalled_cycles >= CIRCUIT_BREAKER_STALL_CYCLES:
                cb_msg = (
                    "Execução interrompida: nenhum progresso detectado entre ciclos consecutivos.\n"
                    f"Subtarefas falhas: {failed_tasks}.\n"
                    "Erros persistentes: "
                    f"{[dag_state[t]['error'] for t in failed_tasks if dag_state[t]['status'] == 'failed']}.\n"
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
                await self.record_operation_metrics(master_session_id, parcial=False)  # também na parada por erro
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
                from src.llm.cache import LLMResponseCache
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
                "Instrução: Crie um plano de recuperação focado em resolver as falhas e completar os "
                "objetivos restantes, "
                "sem refazer as tarefas que já tiveram sucesso."
            )
            if cycle_negatives:
                execution_feedback += "\n\n" + negative_result_feedback(cycle_negatives)
            observed = review_observations_feedback(cycle_observations)
            if observed:
                execution_feedback += "\n\n" + observed


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
            "Limite de tentativas de recuperação atingido. "
            f"A execução falhou com os seguintes erros:\n{execution_feedback}\n\n"
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

    @staticmethod
    def _exploration_feedback(cycle_no: int, cycle_results: Dict[str, Any], abandoned: List[str]) -> str:
        """Resumo do ciclo para o replanejamento de exploração: só nomes e estados (nenhum texto de saída)."""
        ok = sorted(n for n, r in cycle_results.items() if r.status == "success")
        lines = [
            f"Ciclo de exploração {cycle_no} concluído.",
            f"- Subtarefas concluídas neste ciclo: {', '.join(ok) if ok else 'nenhuma'}",
        ]
        if abandoned:
            lines.append(f"- Subtarefas abandonadas por retentativas: {', '.join(sorted(abandoned))}")
        lines.append(
            "- As contagens de réplicas e o estado das hipóteses estão no contexto de exploração; decida os próximos "
            "caminhos "
            "a partir deles e das sugestões do Curator."
        )
        return "\n".join(lines)

    async def _close_session(
        self,
        reason: "StopReason | ExplorationStop",
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
        (``openspec/changes/archive/v18-usage-limits/design.md`` §3) especifica o fechamento
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
        from src.orchestration.orchestrator import OrchestratorResult

        await self._refresh_model_versions()  # v18.5: digest do Ollama no checkpoint de fechamento
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

        if reason == StopReason.INTERRUPTED:  # v18.5-operation-metrics: conta como intervenção humana
            telemetry.record_agent_event(
                execution_id=master_session_id,
                session_id=master_session_id,
                agent_id="autonomous_loop",
                event_type="researcher_interruption",
                payload={"em": datetime.now(timezone.utc).isoformat()},
            )

        await self.record_operation_metrics(master_session_id, parcial=False)

        completed_tasks = [t for t, s in dag_state.items() if s.get("status") in DONE_STATUSES]
        abandoned_tasks = [t for t, s in dag_state.items() if s.get("status") == "abandonada"]
        pending_tasks = [
            t for t, s in dag_state.items() if s.get("status") not in (*DONE_STATUSES, "abandonada")
        ]

        # design §3 — "Reserva esgotada": se não sobrar orçamento nem para a reserva de
        # fechamento, pula a consolidação via LLM e apenas grava o checkpoint
        # determinístico; a consolidação fica pendente para a próxima execução.
        # v18.7-benchmark-fixes: com a cota do provedor esgotada o fechamento não chama LLM (nem Summarizer nem
        # Curator): o checkpoint determinístico é gravado e a consolidação fica para a retomada.
        from src.llm.quota import quota_stop_for

        quota = quota_stop_for(master_session_id) if reason == StopReason.PROVIDER_QUOTA else None
        # Sem o pesquisador a pesquisa não terminou: nada é consolidado (a consolidação fica para a retomada).
        suspending = reason in (StopReason.SUSPENDED, StopReason.PAUSED)
        tokens_available_for_closing = (
            quota is None and not suspending and not self._usage_tracker.tokens_hard_exhausted()
        )
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
        if quota is not None:
            checkpoint["cota_provedor"] = {
                "provedor": quota.provider, "modelo": quota.model, "status": quota.status_code,
            }

        # Checkpoint determinístico — sempre gravado, mesmo se a consolidação abaixo falhar.
        session = self.orchestrator.session_manager.get(master_session_id)
        payload = dict(session.payload) if session is not None else {}
        payload["motivo_parada"] = reason.value
        payload["checkpoint"] = checkpoint
        if suspending:
            from src.session.states import STATUS_SUSPENDED_LEGACY, STATUS_SUSPENDED_NO_RESEARCHER

            # ``pausar`` grava o estado retomável legado ``suspended`` (decisão do pesquisador, 2026-10-18).
            self.orchestrator.session_manager.update(
                master_session_id,
                status=STATUS_SUSPENDED_LEGACY if reason == StopReason.PAUSED else STATUS_SUSPENDED_NO_RESEARCHER,
                payload=payload,
            )
        else:
            self.orchestrator.session_manager.update(master_session_id, payload=payload)

        # v18-research-continuity — checkpoint.json atômico e versionado (substitui o dicionário ad hoc anterior).
        recorder = self._recorder(master_session_id)
        if recorder is not None:
            recorder.set_usage(
                consumo={
                    "tokens": usage_status.tokens_used,
                    "minutos": round(usage_status.minutes_elapsed, 2),
                    "retentativas_conexao": usage_status.connection_retries,
                }
            )
            for t_name in abandoned_tasks:
                state = recorder.snapshot().find(t_name)
                if state is not None and state.status != ST_ABANDONADA:
                    recorder.subtask_finished(
                        t_name, status=ST_ABANDONADA, tentativas=state.tentativas, resumo=state.resultado_resumo
                    )
            # O fechamento do Curator pendente da sessão anterior (set_curator_pending na retomada) não se perde.
            recorder.close(
                ESTADO_FECHADO, reason.value,
                curator_pendente=consolidation_pending or recorder.snapshot().curator_pendente,
            )

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
        elif suspending:
            logger.warning(
                "Sessão suspensa sem o pesquisador — consolidação final adiada (consolidation_pending)",
                extra={"master_session_id": master_session_id},
            )
        elif quota is not None:
            logger.warning(
                "Cota do provedor esgotada — consolidação final adiada (consolidation_pending)",
                extra={"master_session_id": master_session_id, "provedor": quota.provider, "modelo": quota.model},
            )
        elif not tokens_available_for_closing:
            logger.warning(
                "Reserva de tokens esgotada — consolidação final adiada (consolidation_pending)",
                extra={"master_session_id": master_session_id},
            )
        else:
            logger.info(
                "Nenhuma subtarefa concluída nem resultado a consolidar; consolidação final dispensada",
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
        from src.orchestration.orchestrator import AgentTask
        
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
                            injection = (
                                "\n\n[PADRÕES DE CÓDIGO CONHECIDOS PARA ESTE DOMÍNIO]\n" + "\n".join(lessons) + "\n"
                            )
                            task.prompt = task.prompt + injection
                            logger.info(
                                "Padrões de código injetados",
                                extra={"domain": inferred_domain, "count": len(lessons)},
                            )
                            
        return task

    async def _extract_code_patterns(self, result: "AgentResult", master_session_id: str) -> None:
        """Extrai padrões de código pós-conclusão de uma subtarefa (V13.6.1 e V13.6.2)."""
        if result.status != "success":
            return
            
        import hashlib
        import json
        import os
        
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
        # Vamos apenas injetar os últimos logs de execução ou o que houver no result
        # em vez de procurar o arquivo se for difícil.
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

        from src.orchestration.orchestrator import AgentTask
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
                        tags=["code_pattern", domain],
                        tainted=role_tainted(extraction_task.agent_id),
                    )
                    logger.info("Padrão de código extraído e salvo na memória", extra={"key": key})

    async def _review_subtask(
        self, task: "AgentTask", result: "AgentResult", master_session_id: str, attempt: int = 1,
        contract: "SubtaskContract | None" = None,
    ) -> Dict[str, Any]:
        """Invoca o Agente Revisor para avaliar o resultado de uma subtarefa.

        Args:
            task: A definição da tarefa com critérios de validação.
            result: O resultado produzido pelo agente executor.
            master_session_id: ID da sessão mestra.
            contract: Contrato da tentativa executada (v18.7-subtask-contract); o revisor julga pelo mesmo contrato.

        Returns:
            Dicionário com o status da revisão e feedback.
        """

        # V14.2: revisão de subtarefa executada via corrotina ValidatorAgent (sem container Docker)
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
            from src.agents.validator.agent import ValidatorAgent
            validator = ValidatorAgent()

        review = await validator.review_result(
            task=task,
            response_text=result.response.get("text", ""),
            artifacts_on_disk=artifacts_on_disk,
            output_dir=output_manager.base_dir / master_session_id,
            **({"contract": contract} if contract is not None else {}),
        )
        from src.llm.metering import bound_execution_id
        from src.observability.telemetry import get_telemetry

        self._check_contract_divergence(task, attempt, getattr(review, "contract_sha256", "") or "", master_session_id)
        refund_refused = False
        if getattr(review, "outcome", None) == "criterio_ambiguo" and task.task_name:
            # A falha não é do Developer: devolve a tentativa, no máximo uma vez por subtarefa na sessão (design §8.1).
            refund_refused = not self._usage_tracker.refund_task_attempt(task.task_name)

        try:  # observabilidade nunca derruba a revisão
            get_telemetry().record_agent_event(
                execution_id=bound_execution_id() or master_session_id,
                session_id=master_session_id,
                agent_id="validator",
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
                    "undecided_criteria": [
                        str(c)[:200] for c in (getattr(review, "undecided_criteria", None) or [])
                    ][:8],
                    "metric_qualifiers": dict(list((getattr(review, "metric_qualifiers", None) or {}).items())[:20]),
                    "outcome": getattr(review, "outcome", None) or ("aprovado" if review.is_approved else "reprovado"),
                    "motivos": [str(m)[:64] for m in (getattr(review, "motivos", None) or [])][:8],
                    "contrato_sha256": getattr(review, "contract_sha256", "") or None,
                    "observacoes": [str(o)[:200] for o in (getattr(review, "observations", None) or [])][:10],
                    "criterio_ambiguo": [
                        {"criterio": str(a.get("criterio", ""))[:16],
                         "chaves": [str(k)[:128] for k in a.get("chaves", [])]}
                        for a in (getattr(review, "ambiguities", None) or [])
                    ][:8],
                    "devolucao_recusada": refund_refused,
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
            "outcome": getattr(review, "outcome", None) or ("aprovado" if review.is_approved else "reprovado"),
            "negative_findings": list(getattr(review, "negative_findings", None) or []),
            "motivos": list(getattr(review, "motivos", None) or []),
            "predicoes": list(getattr(review, "predicoes", None) or []),
            "viola_restricao": getattr(review, "viola_restricao", None),
            "typed_issues": list(getattr(review, "typed_issues", None) or []),
            "observacoes": list(getattr(review, "observations", None) or []),
            "contrato_sha256": getattr(review, "contract_sha256", "") or "",
            "ambiguidades": list(getattr(review, "ambiguities", None) or []),
            "devolucao_recusada": refund_refused,
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
        from src.artifacts.subtask_output import SubtaskOutput
        from src.numeric_refs.catalog import report_context_without_numbers
        from src.orchestration.orchestrator import AgentTask
        from src.report.artifact_reader import ArtifactReader
        from src.report.report_model import (
            NarrativeError,
            parse_narrative,
            render_report_markdown,
            report_data_json,
            unavailable_narrative,
        )

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
                body = taint_if(str(res.response.get("text", "")), role_tainted(res.agent_id))
                context_parts.append(f"### Resultado do Agente {res.agent_id}\n{body}")

        session_dir = self.orchestrator.output_manager.base_dir / master_session_id
        data = await self._build_report_data(
            prompt, master_session_id, ArtifactReader(session_dir), stop_reason
        )

        # v18.5-numeric-references: o Summarizer recebe referências para copiar, não números.
        catalog = await self._build_reference_catalog(master_session_id, session_dir)
        base_prompt = (
            f"Escreva a narrativa do relatório da tarefa: '{prompt}'\n\n"
            "RESULTADOS DAS SUBTAREFAS:\n\n" + "\n\n".join(context_parts) + "\n\n"
            f"{mark_execution_output(catalog, 'catalogo_de_referencias')}\n\n"
            "CONTEXTO DO RELATÓRIO (JSON; os números de execução e a tabela de resultados são escritos pelo "
            "orquestrador):\n"
            f"{mark_execution_output(report_context_without_numbers(data.to_dict()), 'report_data')}\n\n"
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
        markdown = await self._append_provenance_section(markdown, master_session_id)
        markdown = await self._finalize_report(markdown, master_session_id, session_dir)
        markdown = await self._append_operation_metrics_section(markdown, master_session_id, session_dir, stop_reason)
        try:
            (session_dir / "report_data.json").write_text(report_data_json(data), encoding="utf-8")
        except OSError as exc:
            logger.error("Falha ao gravar o relatório final", extra={"error": str(exc)})

        # Falha da chamada ao agente continua sendo falha; narrativa indisponível não é.
        summary_result.response = {"text": markdown}
        return summary_result
