"""Relatório final e métricas de operação da sessão autônoma (parte do laço de ``AutonomousLoop``).

Divisão de ``autonomous_loop.py`` (ADR 024 §5): código movido sem mudança de comportamento.
"""

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src import config
from src.egress.gate import role_tainted
from src.egress.routing import ModelRouter
from src.logger import get_logger
from src.observability.telemetry import get_telemetry

logger = get_logger(__name__)


class LoopReportMixin:
    """Métodos de relatório e métricas usados por ``AutonomousLoop`` (``self.orchestrator`` etc.)."""

    def _session_payload(self, session_id: str) -> dict[str, Any]:
        session = self.orchestrator.session_manager.get(session_id)
        return dict(session.payload) if session is not None else {}

    async def record_operation_metrics(self, master_session_id: str, *, parcial: bool) -> dict[str, Any] | None:
        """Agrega as métricas de operação da sessão e grava em ``payload["operation_metrics"]`` (idempotente).

        Sem LLM. Uma falha nunca impede o fechamento nem o relatório: devolve ``None`` e registra em log
        (v18.5-operation-metrics §1.2–1.3).
        """
        from src.report.operation_metrics import aggregate_operation_metrics, default_readers, unlimited_block

        telemetry = get_telemetry()

        def on_error(group: str, message: str) -> None:
            telemetry.record_agent_event(
                execution_id=master_session_id,
                session_id=master_session_id,
                agent_id="autonomous_loop",
                event_type="operation_metrics_error",
                payload={"grupo": group, "mensagem": message[:300]},
            )

        try:
            await telemetry.flush()  # tokens e snapshots ainda em buffer entram na agregação
            payload = await asyncio.to_thread(self._session_payload, master_session_id)
            counts = {
                "planejamento": self.orchestrator._session_planning_run_counts.get(master_session_id, 0),
                "execucao": self.orchestrator._session_agent_run_counts.get(master_session_id, 0),
            }
            self.orchestrator.session_manager.update(
                master_session_id, payload={**payload, "execucoes_agente": counts}
            )
            metrics = await asyncio.to_thread(
                aggregate_operation_metrics,
                master_session_id,
                parcial=parcial,
                readers=default_readers(
                    self.orchestrator.output_manager.base_dir, payload_loader=self._session_payload
                ),
                unlimited=unlimited_block(payload.get("budget"), self._unlimited_notices),
                on_error=on_error,
            )
            self.orchestrator.session_manager.update(
                master_session_id,
                payload={**self._session_payload(master_session_id), "operation_metrics": metrics},
            )
            return metrics
        except Exception as exc:  # noqa: BLE001 - métricas nunca bloqueiam o fechamento
            logger.error(
                "Falha ao agregar as métricas de operação",
                extra={"error": type(exc).__name__, "detalhe": str(exc)[:300], "session_id": master_session_id},
            )
            return None

    def _continued_chain_metrics(self, session_id: str, current: dict[str, Any]) -> list[dict[str, Any]]:
        """Métricas gravadas das sessões que esta continua (``continues_session_id``) mais a atual, da mais antiga."""
        chain = [current]
        seen = {session_id}
        payload = self._session_payload(session_id)
        while len(chain) < 50:
            previous_id = payload.get("continues_session_id")
            if not previous_id or previous_id in seen:
                break
            seen.add(previous_id)
            payload = self._session_payload(previous_id)
            previous = payload.get("operation_metrics")
            if isinstance(previous, dict):
                chain.insert(0, previous)
        return chain

    async def _append_operation_metrics_section(
        self, markdown: str, master_session_id: str, session_dir: Path, stop_reason: Optional[str]
    ) -> str:
        """Acrescenta ao relatório a seção determinística "Métricas de operação" (orquestrador, sem LLM; design §5).

        Roda depois do pipeline do relatório: a verificação de números e de afirmações já produziu os seus dados, e a
        seção delimitada (``operation-metrics``) não passa pelo verificador de números.
        """
        from src.report.operation_metrics import render_operation_metrics_section

        metrics = await self.record_operation_metrics(master_session_id, parcial=False)
        if metrics is None:
            body = "## Métricas de operação\n\nNão foi possível agregar as métricas de operação desta sessão (ver log)."
            section = f"<!-- operation-metrics:begin -->\n{body}\n<!-- operation-metrics:end -->"
        else:
            section = render_operation_metrics_section(metrics, stop_reason=stop_reason)
            chain = await asyncio.to_thread(self._continued_chain_metrics, master_session_id, metrics)
            if len(chain) > 1:  # sessão continuada: soma informativa da cadeia (design §5)
                from src.report.operation_metrics import END_MARK, render_chain_line

                section = section.replace(END_MARK, f"{render_chain_line(chain)}\n{END_MARK}")
        markdown = f"{markdown.rstrip()}\n\n{section}\n"
        try:
            (session_dir / "relatorio_final.md").write_text(markdown, encoding="utf-8")
        except OSError as exc:
            logger.error("Falha ao gravar a seção de métricas de operação", extra={"error": str(exc)})
        return markdown

    async def _append_provenance_section(self, markdown: str, master_session_id: str) -> str:
        """Acrescenta ao relatório a seção determinística de proveniência (orquestrador, sem LLM; design §8).

        Também acrescenta à cadeia os términos pendentes e exporta o segmento da sessão. Nunca levanta.
        """
        from src.provenance.ledger import get_ledger
        from src.provenance.report import SECTION_TITLE, provenance_section

        try:
            divergences = list(getattr(self.orchestrator, "provenance_warnings", {}).get(master_session_id, []))
            body = await asyncio.to_thread(
                provenance_section,
                get_ledger(),
                master_session_id,
                self.orchestrator.output_manager.base_dir,
                divergences=divergences,
            )
        except Exception as exc:  # noqa: BLE001 - a seção nunca impede o relatório
            logger.warning("Seção de proveniência não gerada", extra={"error": type(exc).__name__})
            body = f"Não foi possível gerar a seção de proveniência ({type(exc).__name__})."
        block = f"<!-- provenance-chain:begin -->\n## {SECTION_TITLE}\n{body}\n<!-- provenance-chain:end -->"
        return f"{markdown.rstrip()}\n\n{block}\n"

    async def _build_reference_catalog(self, master_session_id: str, session_dir: Path) -> str:
        """Catálogo de referências numéricas da sessão (v18.5-numeric-references, design §7.1). Nunca levanta."""
        from src.numeric_refs.catalog import build_reference_catalog
        from src.provenance.ledger import get_ledger
        from src.report.artifact_reader import ArtifactReader

        try:
            return await asyncio.to_thread(
                build_reference_catalog,
                session_id=master_session_id,
                session_dir=session_dir,
                ledger=get_ledger(),
                metrics_by_task=ArtifactReader(session_dir).read_subtask_metrics(),
                graph=self._graph_for_report(),
                project_id=self.orchestrator._session_project_id(master_session_id),
                session_ids=self._report_session_ids(master_session_id),
            )
        except Exception as exc:  # noqa: BLE001 - sem catálogo o Summarizer segue; os números ficarão não verificados
            logger.warning("Catálogo de referências indisponível", extra={"error": type(exc).__name__})
            return "CATÁLOGO DE REFERÊNCIAS: indisponível nesta sessão."

    def _graph_for_report(self) -> Any:
        """Grafo para unidades e insumos citados no relatório, ou ``None`` (sem ele, ``src`` de insumo não resolve)."""
        try:
            return self.orchestrator._open_knowledge_store()
        except Exception:  # noqa: BLE001
            return None

    def _report_session_ids(self, master_session_id: str) -> list[str]:
        """Sessão atual e as da cadeia de continuidade (insumos e fontes de busca do projeto)."""
        resume = getattr(self.orchestrator, "_resumes", {}).get(master_session_id)
        previous = [Path(d).name for d in getattr(resume, "readable_dirs", ())] if resume is not None else []
        return [master_session_id, *previous]

    async def _finalize_report(self, source_markdown: str, master_session_id: str, session_dir: Path) -> str:
        """Grava ``relatorio_final.fonte.md`` e roda o pipeline (resolve, renderiza, verifica números, seções).

        Se o pipeline falhar, o erro é registrado e o relatório entregue é o texto fonte com um aviso explícito de que
        não passou pela verificação de números.
        """
        from src.numeric_refs.literal_metrics import read_literal_metrics
        from src.numeric_refs.resolver import ReferenceResolver
        from src.provenance.ledger import get_ledger
        from src.report.pipeline import SOURCE_FILE, ReportState

        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / SOURCE_FILE).write_text(source_markdown, encoding="utf-8")
        except OSError as exc:
            logger.error("Falha ao gravar o relatório fonte", extra={"error": str(exc)})
        try:
            resolver = ReferenceResolver(
                ledger=get_ledger(),
                output_dir=session_dir.parent,
                graph=self._graph_for_report(),
                session_ids=self._report_session_ids(master_session_id),
                literal_metrics=read_literal_metrics(session_dir),
            )
            counts = await asyncio.to_thread(self._report_counts, master_session_id, session_dir)
            source = source_markdown
            for cycle in range(config.CLAIM_REVISION_MAX_CYCLES + 1):
                state = ReportState(
                    session_id=master_session_id,
                    session_dir=session_dir,
                    source_text=source,
                    text=source,
                    resolver=resolver,
                    counts=dict(counts),
                )
                state.extras["claims_previous"] = list(self._claims_previous)
                await asyncio.to_thread(self._claims_pipeline(master_session_id).build, state)
                try:  # v18.6-hypothesis-closure §6.2: afirmacoes.json sempre existe quando há relatório final
                    from src.report.claims_report import ensure_claims_file

                    await asyncio.to_thread(
                        ensure_claims_file, state,
                        self.orchestrator.claim_runtime().budget_exhausted(master_session_id),
                    )
                except Exception as exc:  # noqa: BLE001 - complementar: nunca derruba o relatório
                    logger.warning("afirmacoes.json vazio não gravado", extra={"error": type(exc).__name__})
                revised = await self._revise_report_source(master_session_id, session_dir, state, source, cycle)
                if revised is None:
                    break
                source = revised
                try:
                    (session_dir / SOURCE_FILE).write_text(source, encoding="utf-8")
                except OSError as exc:
                    logger.error("Falha ao gravar o relatório fonte revisado", extra={"error": str(exc)})
            return (session_dir / "relatorio_final.md").read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - falha explícita, relatório fonte preservado
            logger.error("Pipeline do relatório falhou", extra={"error": type(exc).__name__, "detalhe": str(exc)[:300]})
            notice = (
                "> **Aviso:** o pipeline de verificação de números falhou "
                f"({type(exc).__name__}); este relatório NÃO foi verificado. O texto fonte está em "
                "`relatorio_final.fonte.md`.\n\n"
            )
            try:
                (session_dir / "relatorio_final.md").write_text(notice + source_markdown, encoding="utf-8")
            except OSError:
                pass
            return notice + source_markdown

    def _claims_pipeline(self, session_id: str) -> Any:
        """Pipeline do relatório com o estágio ``claims`` (v18.5-claim-verification), no laço de eventos atual."""
        from src.report.claims_report import ClaimsRunner, register_claims
        from src.report.pipeline import build_default_pipeline

        pipeline = build_default_pipeline()
        if config.CLAIM_VERIFY_ENABLED:
            runtime = self.orchestrator.claim_runtime()
            register_claims(
                pipeline,
                ClaimsRunner(
                    loop=asyncio.get_running_loop(),
                    make_service=lambda state: runtime.make_service(state.session_id),
                    session_results=runtime.session_results(session_id),
                ),
            )
        return pipeline

    async def _revise_report_source(
        self, master_session_id: str, session_dir: Path, state: Any, source: str, cycle: int
    ) -> Optional[str]:
        """Um ciclo de correção (design §8): devolve o texto fonte revisado, ou ``None`` se não há o que corrigir.

        Só ``refutada_deterministica`` e ``parcial`` voltam ao Summarizer; ``contestada`` vai ao pesquisador. Falha do
        Summarizer não interrompe o relatório: as afirmações seguem como estão, com o aviso no log.
        """
        data = state.extras.get("claims")
        if not config.CLAIM_VERIFY_ENABLED or not data or cycle >= config.CLAIM_REVISION_MAX_CYCLES:
            return None
        from src.claims.revision import apply_revisions, request_revisions, revision_targets
        from src.claims.store import ClaimStore

        store: ClaimStore = data["store"]
        sections = tuple(config.CLAIM_VERIFY_SECTIONS)
        items = revision_targets(store, source, sections)
        if not items or self.orchestrator.claim_runtime().budget_exhausted(master_session_id):
            return None
        try:
            provider = ModelRouter.get_provider("summarizer")
            replacements = await request_revisions(provider, items, role_tainted("summarizer"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - o relatório segue com as marcas, sem a correção
            logger.warning("Ciclo de correção do relatório falhou", extra={"error": type(exc).__name__})
            return None
        if not replacements:
            return None
        revised = apply_revisions(source, replacements, sections)
        if revised == source:
            return None
        fresh = ClaimStore.load(session_dir, master_session_id)
        for conclusao_id in replacements:
            entry = fresh.conclusoes.get(conclusao_id)
            if entry is not None:
                entry["ciclos"] = int(entry.get("ciclos") or 0) + 1
        fresh.save()
        return revised

    def _report_counts(self, master_session_id: str, session_dir: Path) -> dict[str, int]:
        """Contagens do orquestrador para a exclusão X8 do verificador (subtarefas, execuções, insumos...)."""
        from src.provenance.ledger import get_ledger
        from src.provenance.store import TIPO_INICIO, TIPO_TERMINO

        counts: dict[str, int] = {"sessao": 1}
        try:
            records = get_ledger().store.by_session(master_session_id)
            counts["execucao"] = sum(1 for r in records if r.tipo == TIPO_INICIO)
            counts["subtarefa"] = len({r.task_name for r in records if r.tipo == TIPO_TERMINO})
        except Exception:  # noqa: BLE001 - sem registro, as contagens ficam ausentes (números marcados)
            pass
        snapshot = session_dir / "input_snapshot"
        if snapshot.is_dir():
            counts["insumo"] = sum(1 for p in snapshot.iterdir() if p.is_file())
        return counts

    async def _build_report_data(
        self,
        prompt: str,
        master_session_id: str,
        artifact_reader: Any,
        stop_reason: Optional[str],
    ) -> Any:
        """Monta ``ReportData`` com disco e telemetria, sem LLM e sem nunca derrubar a síntese."""
        from src.llm.model_config import get_role_model_config, known_roles
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
            research_data=payload.get("research_data_markings", []),
        )
