"""Cola da verificação de afirmações com o orquestrador (v18.5-claim-verification, design §3, §7 e §11).

Reúne o que o ``ClaimService`` precisa da sessão: orçamento (``UsageTracker``), grafo (métricas, evidência de
``Descoberta``, nós ``Afirmacao``), Validator e sinalizações ao Curator. Toda falha aqui é isolada: a sessão nunca para
por causa da verificação, e o que não foi verificado fica ``pendente`` com motivo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from src import config
from src.claims.decompose import conclusion_from_discovery
from src.claims.deterministic import CodeValue
from src.claims.evidence import (
    codes_from_payload,
    discovery_evidence_builder,
    report_evidence_builder,
    session_results_item,
)
from src.claims.graph import update_discovery_claim, write_discovery_claim
from src.claims.model import Afirmacao, Conclusao
from src.claims.service import ClaimService
from src.claims.store import FILENAME, ClaimStore
from src.logger import get_logger
from src.numeric_refs.provenance_file import FILE_NAME as NUMERIC_FILE
from src.utils.normalization import normalize_metric_name

logger = get_logger(__name__)

PENDING_CHECKPOINT_KEY = "afirmacoes_pendentes"
_MAX_METRICS = 1000


class MetricCatalog:
    """Métricas do grafo (``sentido``, sinônimos) por nome normalizado; carregado uma vez e tolerante a falha."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph
        self._by_name: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._by_name is None:
            self._by_name = {}
            if self._graph is not None:
                try:
                    after: str | None = None
                    while len(self._by_name) < _MAX_METRICS:
                        page = self._graph.list_nodes("Metrica", after_id=after, limit=200)
                        if not page:
                            break
                        for node in page:
                            props = node.properties
                            names = [props.get("nome"), *(props.get("sinonimos") or [])]
                            for name in names:
                                if name:
                                    self._by_name[normalize_metric_name(str(name))] = props
                        after = page[-1].id
                except Exception as exc:  # noqa: BLE001 - sem métricas, o determinístico de qualidade vai ao verificador
                    logger.warning("Catálogo de métricas indisponível", extra={"erro": type(exc).__name__})
        return self._by_name

    def sense_of(self, name: str) -> str | None:
        props = self._load().get(normalize_metric_name(name))
        return props.get("sentido") if props else None

    def known_metrics(self) -> list[str]:
        return sorted({str(p.get("nome")) for p in self._load().values() if p.get("nome")})

    def aliases_of(self, name: str) -> list[str]:
        props = self._load().get(normalize_metric_name(name))
        return [str(a) for a in (props.get("sinonimos") or [])] + ([str(props["nome"])] if props else [])


class ClaimRuntime:
    """Serviços de verificação de uma sessão mestra.

    Args:
        output_dir: Raiz de ``outputs/``.
        graph_getter: Devolve o grafo ou levanta (sem grafo, só o relatório é verificado).
        tracker_getter: Devolve o ``UsageTracker`` da sessão, ou ``None``.
        validator: ``ValidatorAgent`` (porta ``ClaimVerifierPort``).
        project_getter: Devolve o ``projeto_id`` da sessão, ou ``None``.
    """

    def __init__(
        self,
        output_dir: Path | str,
        *,
        graph_getter: Callable[[], Any],
        tracker_getter: Callable[[str], Any],
        validator: Any,
        project_getter: Callable[[str], str | None] = lambda _sid: None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self._graph_getter = graph_getter
        self._tracker_getter = tracker_getter
        self._validator = validator
        self._project_getter = project_getter

    # --- peças ----------------------------------------------------------------------------------------------------

    def graph(self) -> Any:
        try:
            return self._graph_getter()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Grafo indisponível para a verificação", extra={"erro": type(exc).__name__})
            return None

    def session_results(self, session_id: str) -> Callable[[], Any]:
        """Provedor da tabela de resultados validados da sessão (evidência de frases sem código de referência)."""
        return lambda: session_results_item(self.graph(), session_id)

    def budget_exhausted(self, session_id: str) -> bool:
        """Limite de tokens ou de tempo atingido (a sessão segue; as afirmações restantes ficam ``pendente``)."""
        tracker = self._tracker_getter(session_id)
        if tracker is None:
            return False
        try:
            return bool(tracker.tokens_hard_exhausted() or tracker.check().time_exhausted)
        except Exception:  # noqa: BLE001 - sem leitura do consumo, não bloqueia
            return False

    def make_service(self, session_id: str, store: ClaimStore | None = None) -> ClaimService:
        session_dir = self.output_dir / session_id
        catalog = MetricCatalog(self.graph())
        return ClaimService(
            store=store or ClaimStore.load(session_dir, session_id),
            verifier=self._validator,
            budget_exhausted=lambda: self.budget_exhausted(session_id),
            sense_of=catalog.sense_of,
            known_metrics=catalog.known_metrics,
            aliases_of=catalog.aliases_of,
            flag_sink=lambda conclusao, claim: self._flag(session_dir, conclusao, claim),
        )

    @staticmethod
    def _flag(session_dir: Path, conclusao: Conclusao, claim: Afirmacao) -> None:
        """Refutação determinística de ``Descoberta`` → ``falha_relevante`` para o Curator revisar o enunciado."""
        from src.knowledge.curator_flags import record_flag

        values = "; ".join(f"{k}={v.get('valor')}" for k, v in claim.valores_registrados.items() if isinstance(v, dict))
        text = f"Afirmação refutada pelos valores registrados ({values}): {claim.texto}"
        record_flag(
            session_dir,
            agente="orquestrador",
            subtarefa="claim_verification",
            tipo="falha_relevante",
            texto=text[: config.CURATOR_FLAG_MAX_CHARS],
            refs=[conclusao.conclusao_id.removeprefix("desc:")],
        )

    # --- Descoberta -------------------------------------------------------------------------------------------------

    async def verify_discoveries(self, session_id: str, discovery_ids: Iterable[str]) -> list[Afirmacao]:
        """Verifica as descobertas criadas ou reforçadas e grava os nós ``Afirmacao`` (nunca levanta)."""
        if not config.CLAIM_VERIFY_ENABLED:
            return []
        ids = list(dict.fromkeys(discovery_ids))
        graph = self.graph()
        if not ids or graph is None:
            return []
        try:
            conclusions: list[Conclusao] = []
            for node_id in ids:
                node = graph.get_node(node_id)
                if node is None or node.label != "Descoberta":
                    continue
                conclusions.append(
                    conclusion_from_discovery(node_id, str(node.properties.get("enunciado") or ""),
                                              node.properties.get("condicoes"))
                )
            if not conclusions:
                return []
            service = self.make_service(session_id)
            await service.verify_conclusions(conclusions, {}, discovery_evidence_builder(graph))
            claims = [c for con in conclusions for c in service.store.for_conclusion(con.conclusao_id)]
            self._sync_graph(graph, service.store, claims, session_id)
            service.store.save()
            return claims
        except Exception as exc:  # noqa: BLE001 - a verificação nunca derruba a sessão
            logger.warning("Verificação de descobertas falhou", extra={"erro": type(exc).__name__})
            return []

    def _sync_graph(self, graph: Any, store: ClaimStore, claims: list[Afirmacao], session_id: str) -> None:
        project_id = self._project_getter(session_id)
        if not project_id:
            return
        for claim in claims:
            try:
                if claim.no_grafo is None:
                    claim.no_grafo = write_discovery_claim(graph, claim, project_id=project_id, session_id=session_id)
                else:
                    update_discovery_claim(graph, claim.no_grafo, claim)
            except Exception as exc:  # noqa: BLE001 - o arquivo da sessão continua sendo a fonte
                logger.warning("Nó Afirmacao não gravado", extra={"erro": type(exc).__name__})

    # --- pendentes (retomada) ----------------------------------------------------------------------------------

    def pending_for_checkpoint(self, session_id: str) -> list[dict[str, str]]:
        """Chave ``afirmacoes_pendentes`` do ``checkpoint.json`` (design §11)."""
        try:
            store = ClaimStore.load(self.output_dir / session_id, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pendências de afirmações ilegíveis", extra={"erro": type(exc).__name__})
            return []
        return [
            {"afirmacao_id": c.afirmacao_id, "session_id": session_id, "conclusao_id": c.conclusao_id}
            for c in store.pending()
        ]

    async def verify_previous_pending(self, session_id: str, pending: Iterable[dict[str, str]]) -> list[Afirmacao]:
        """Verifica as pendentes das sessões anteriores antes do primeiro planejamento.

        O resultado entra no histórico da afirmação (arquivo da sessão original, por acréscimo, e nó ``Afirmacao``) e
        é devolvido para a subseção do relatório da sessão nova. Nenhum efeito sobre hipóteses; nunca levanta.
        """
        if not config.CLAIM_VERIFY_ENABLED:
            return []
        by_session: dict[str, list[str]] = {}
        for item in pending:
            by_session.setdefault(str(item.get("session_id")), []).append(str(item.get("afirmacao_id")))
        verified: list[Afirmacao] = []
        graph = self.graph()
        for old_session, claim_ids in by_session.items():
            try:
                store = ClaimStore.load(self.output_dir / old_session, old_session)
                claims = [c for c in (store.get(i) for i in claim_ids) if c is not None]
                codes, evidence = self._previous_context(old_session, graph)
                service = self.make_service(session_id, store=store)
                done = await service.reverify_pending(
                    claims,
                    lambda cid, st=store: (st.conclusoes.get(cid) or {}).get("texto"),
                    codes,
                    evidence,
                    session_id=session_id,
                )
                if graph is not None:
                    self._sync_graph(graph, store, [c for c in done if c.conclusao_id.startswith("desc:")], old_session)
                store.save()
                verified.extend(done)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Reverificação de pendentes falhou", extra={"sessao": old_session, "erro": type(exc).__name__}
                )
        return verified

    def _previous_context(self, old_session: str, graph: Any) -> tuple[dict[str, CodeValue], Callable[..., list]]:
        codes: dict[str, CodeValue] = {}
        codigos: list[dict[str, Any]] = []
        try:
            data = json.loads((self.output_dir / old_session / NUMERIC_FILE).read_text(encoding="utf-8"))
            codigos = data.get("codigos") or []
            codes = codes_from_payload(codigos)
        except (OSError, ValueError):
            pass
        report_builder = report_evidence_builder(codigos, self.output_dir)
        discovery_builder = discovery_evidence_builder(graph) if graph is not None else (lambda _c, _s: [])

        def evidence(conclusao: Conclusao, sentences: list) -> list:
            builder = discovery_builder if conclusao.conclusao_id.startswith("desc:") else report_builder
            return builder(conclusao, sentences)

        return codes, evidence


def claims_file_exists(output_dir: Path | str, session_id: str) -> bool:
    return (Path(output_dir) / session_id / FILENAME).is_file()
