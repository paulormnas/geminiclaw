"""Base do toolkit do Curator: estado da sessão, validação de entradas, auditoria e revisão de duplicatas."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import config
from src.knowledge.curator_common import (
    _ID_RE,
    _MAX_AUDIT_REASON,
    _MAX_IDS,
    _NUMERIC_TEXT_FIELDS,
    AUDIT_FILENAME,
    CuratorLimits,
    CuratorStats,
    CuratorToolError,
    _clip,
    _Review,
)
from src.knowledge.curator_flags import (
    FlagStore,
)
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.normalization import clean_free_text
from src.knowledge.provenance import Actor
from src.knowledge.semantic_index import IGNORED_STATUSES, SemanticIndex, canonical_text
from src.knowledge.service import KnowledgeService
from src.knowledge.similarity_queue import QueueItem, SimilarityQueue
from src.knowledge.validation import REJECTED_STATUSES
from src.logger import get_logger

logger = get_logger(__name__)


class CuratorBase:
    def __init__(
        self,
        store: GraphStore,
        *,
        project_id: str,
        session_id: str,
        session_dir: Path | None = None,
        index: SemanticIndex | None = None,
        queue: SimilarityQueue | None = None,
        model: str | None = None,
        limits: CuratorLimits | None = None,
        service: KnowledgeService | None = None,
    ) -> None:
        """Inicializa o toolkit.

        Args:
            store: Porta única do grafo (de produção, o store indexado; escritas passam pelo gancho do índice).
            project_id: Projeto da sessão: todas as escritas ficam nele.
            session_id: Sessão de proveniência (``sessao_id`` dos nós criados).
            session_dir: ``outputs/<sessão>/`` (sinalizações e trilha de auditoria); ``None`` desliga ambos.
            index: Índice semântico. **Sem ele a criação de nós é recusada** (a revisão de duplicatas é
                obrigatória e falha fechada).
            queue: Fila de similaridade (revisão de pares).
            model: Modelo do Curator (proveniência do ator).
            limits: Orçamento e tamanhos (padrão: ``src/config.py``).
            service: Serviço determinístico de veredito (padrão: ``KnowledgeService(store)``).
        """
        self.store = store
        self.project_id = project_id
        self.session_id = session_id
        self.session_dir = Path(session_dir) if session_dir is not None else None
        self.index = index
        self.queue = queue
        self.limits = limits or CuratorLimits.from_config()
        self.service = service or KnowledgeService(store)
        self.actor = Actor(kind="agente", role="curator", model=model)
        self.stats = CuratorStats()
        self._flags = FlagStore(self.session_dir) if self.session_dir is not None else None
        self._batch: dict[int, QueueItem] = {}
        self._served: set[int] = set()
        self._created: set[str] = set()  # nós criados nesta execução (não servem de base para substituir/contestar)
        # v18.5-claim-verification: descobertas criadas ou reforçadas nesta execução (as que o orquestrador verifica).
        self.touched_discoveries: list[str] = []
        self._started = datetime.now(timezone.utc).isoformat()
        # v18.5-numeric-references: resolvedor das referências {{res|calc|src}} do texto escrito (injetável em testes).
        self.numeric_resolver: Any = None
        self._numeric_warnings: list[str] = []

    # ------------------------------------------------------------------ utilitários

    def _text(self, name: str, value: Any, *, required: bool = True, max_chars: int | None = None) -> str:
        if value is None and not required:
            return ""
        if not isinstance(value, str):
            raise CuratorToolError(f"'{name}' deve ser texto.")
        cleaned = clean_free_text(value)
        if required and not cleaned:
            raise CuratorToolError(f"'{name}' não pode ser vazio.")
        limit = max_chars or self.limits.max_text_chars
        if len(cleaned) > limit:
            raise CuratorToolError(f"'{name}' longo demais (máximo {limit} caracteres); resuma.")
        if name in _NUMERIC_TEXT_FIELDS:
            self._check_numeric_refs(name, cleaned)
        return cleaned

    def _resolver(self) -> Any:
        """Resolvedor de referências numéricas (padrão: registro de execuções, grafo e sessões do projeto)."""
        if self.numeric_resolver is None:
            from src.numeric_refs.resolver import ReferenceResolver
            from src.provenance.ledger import get_ledger

            self.numeric_resolver = ReferenceResolver(
                ledger=get_ledger(),
                output_dir=Path(config.OUTPUT_BASE_DIR),
                graph=self.store,
                session_ids=[self.session_id],
            )
        return self.numeric_resolver

    def _check_numeric_refs(self, name: str, text: str) -> None:
        """Referência malformada ou que não resolve é recusada; número sem referência é aceito com aviso.

        Raises:
            CuratorToolError: Lista as referências com problema e o motivo (o grafo só guarda referências resolvíveis).
        """
        from src.numeric_refs.syntax import find_malformed, find_references
        from src.numeric_refs.verifier import verify_numbers

        problems = [f"{i.trecho[:60]!r} ({i.motivo})" for i in find_malformed(text)]
        refs = find_references(text)
        if refs:
            resolver = self._resolver()
            for ref in refs:
                resolved = resolver.resolve(ref)
                if not resolved.ok:
                    problems.append(f"{ref.raw[:80]!r} não resolve: {resolved.motivo}")
        if problems:
            raise CuratorToolError(
                f"'{name}' tem referências numéricas inválidas: " + "; ".join(problems[:5])
                + ". Corrija a referência ou remova o número."
            )
        outcome = verify_numbers(text, protected_spans=[r.span for r in refs])
        if outcome.nao_verificados:
            shown = ", ".join(repr(u.texto) for u in outcome.nao_verificados[:5])
            self._numeric_warnings.append(
                f"'{name}': números sem referência serão exibidos como [não verificado]: {shown}. "
                "Prefira {{res:<exec_id>/<métrica>}}, {{calc:...}} ou {{src:...}}."
            )

    def _take_warnings(self) -> dict[str, Any]:
        """Avisos de números sem referência da chamada corrente (vazio se não houver)."""
        warnings, self._numeric_warnings = self._numeric_warnings, []
        return {"avisos": warnings} if warnings else {}

    @staticmethod
    def _id(name: str, value: Any) -> str:
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise CuratorToolError(f"'{name}' deve ser um ID de nó válido.")
        return value

    def _ids(self, name: str, value: Any, *, required: bool = False) -> list[str]:
        if value is None:
            value = []
        if not isinstance(value, list) or len(value) > _MAX_IDS:
            raise CuratorToolError(f"'{name}' deve ser uma lista de até {_MAX_IDS} IDs.")
        ids = list(dict.fromkeys(self._id(name, v) for v in value))
        if required and not ids:
            raise CuratorToolError(f"'{name}' não pode ser vazio.")
        return ids

    def _visible(self, node: Node) -> bool:
        return (
            node.properties.get("projeto_id") == self.project_id
            or node.properties.get("visibilidade") == "compartilhavel"
        )

    def _node(self, name: str, node_id: str, labels: tuple[str, ...] | None = None, *, own: bool = False) -> Node:
        node = self.store.get_node(self._id(name, node_id))
        if node is None:
            raise CuratorToolError(f"'{name}': nó inexistente.")
        if labels is not None and node.label not in labels:
            raise CuratorToolError(f"'{name}': esperado {'/'.join(labels)}, recebido {node.label}.")
        if own and node.properties.get("projeto_id") != self.project_id:
            raise CuratorToolError(f"'{name}': o Curator só escreve em nós do projeto da sessão.")
        if not own and not self._visible(node):
            raise CuratorToolError(f"'{name}': nó de outro projeto, não compartilhável.")
        return node

    def _mutable(self, name: str, node_id: str, labels: tuple[str, ...]) -> Node:
        node = self._node(name, node_id, labels, own=True)
        if node.properties.get("status") in REJECTED_STATUSES:
            raise CuratorToolError(f"'{name}': nó rejeitado pelo pesquisador não pode ser alterado.")
        return node

    def _spend_write(self) -> None:
        if self.stats.escritas >= self.limits.max_writes:
            raise CuratorToolError(
                f"orçamento de escritas da execução esgotado ({self.limits.max_writes}); "
                "o restante fica para a próxima."
            )
        self.stats.escritas += 1

    def _refuse(self, motivo: str, **extra: Any) -> dict[str, Any]:
        self.stats.recusas += 1
        return {"ok": False, "motivo": motivo, **extra}

    def _audit(self, tool: str, **fields: Any) -> None:
        """Trilha local de decisões (``curator_audit.jsonl``): ferramenta, IDs e motivo curto; best effort."""
        if self.session_dir is None:
            return
        record = {"em": datetime.now(timezone.utc).isoformat(), "ferramenta": tool, "sessao": self.session_id}
        record.update({k: _clip(v, _MAX_AUDIT_REASON) for k, v in fields.items()})
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(
                self.session_dir / AUDIT_FILENAME, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "ab") as handle:
                handle.write((json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
        except OSError as exc:
            logger.warning("Trilha de auditoria do Curator indisponível", extra={"extra": {"erro": type(exc).__name__}})

    def _base_props(self) -> dict[str, Any]:
        # `tainted`: o texto do nó é produto de um modelo que aceita dados brutos (v18.5-egress-gate, design §7).
        from src.egress.gate import role_tainted

        return {"projeto_id": self.project_id, "sessao_id": self.session_id, "tainted": role_tainted("curator")}

    def _edge(self, src: str, rel: str, dst: str, evidencias: list[str] | None = None, **props: Any) -> None:
        self.store.create_edge(
            src, rel, dst, {"origem": "afirmado", "evidencias": evidencias or [], **props}, actor=self.actor
        )

    def _has_edge(self, src: str, rel: str, dst: str) -> bool:
        sub = self.store.neighbors(src, [rel], direction="out", depth=1)
        return any(e.src_id == src and e.rel_type == rel and e.dst_id == dst for e in sub.edges)

    # ------------------------------------------------------------- revisão de duplicatas

    def _review(
        self, label: str, props: dict[str, Any], *, sobre: list[str], extra_consulted: list[str]
    ) -> _Review:
        """Revisão **obrigatória** antes de criar (ADR 015 §10): busca semântica + estrutural + faixas.

        Raises:
            CuratorToolError: Índice semântico indisponível (falha fechada: nada é criado sem revisar).
        """
        if self.index is None:
            raise CuratorToolError(
                "revisão de duplicatas indisponível (índice semântico desligado ou fora do ar): nada foi criado."
            )
        text = canonical_text(label, props)
        if not text:
            raise CuratorToolError("texto insuficiente para a revisão de duplicatas.")
        try:
            hits = self.index.similar(
                text=text,
                labels=[label],
                filters={"projeto_id": self.project_id},
                min_score=config.SIM_RELATED_MIN_SAME_DOMAIN,
                limit=10,
            )
        except Exception as exc:  # noqa: BLE001 - Qdrant/embedding fora do ar: falha fechada
            logger.warning("Revisão semântica falhou", extra={"extra": {"erro": type(exc).__name__}})
            raise CuratorToolError("revisão de duplicatas indisponível (índice semântico): nada foi criado.") from exc
        review = _Review()
        seen: set[str] = set()
        for hit in hits:
            node = self.store.get_node(hit.node_id)
            if node is None or node.properties.get("status") in IGNORED_STATUSES:
                continue
            seen.add(hit.node_id)
            review.consultados.append(hit.node_id)
            if hit.score >= config.SIM_DUPLICATE_MIN:
                review.duplicatas.append((hit.node_id, hit.score))
            else:
                review.relacionados.append((hit.node_id, hit.score))
        if label == "Descoberta":
            for target in sobre:
                sub = self.store.neighbors(target, ["SOBRE"], direction="in", depth=1)
                for node in sub.nodes:
                    if (
                        node.label == "Descoberta"
                        and node.id not in seen
                        and node.properties.get("projeto_id") == self.project_id
                        and node.properties.get("status") == "ativa"
                    ):
                        seen.add(node.id)
                        review.consultados.append(node.id)
                        if node.properties.get("tipo") == props.get("tipo"):
                            review.relacionados.append((node.id, None))  # mesmo escopo e tipo: dúvida = relacionado
        review.consultados.extend(i for i in [*sobre, *extra_consulted] if i not in review.consultados)
        return review

    def _check_duplicates(
        self, review: _Review, variacao_de: str | None, diferenca: str, kind: str
    ) -> dict[str, Any] | None:
        """Aplica as faixas: duplicata recusa; relacionado exige ``variacao_de`` + ``diferenca``."""
        if review.duplicatas:
            existing, score = review.duplicatas[0]
            return self._refuse(
                f"duplicata de {kind} existente (similaridade {score:.2f}); não crie: reforce o existente.",
                id_existente=existing,
                orientacao="Use reinforce_discovery(id=<id_existente>, evidencia_ids=[...])"
                if kind == "Descoberta"
                else "Reaproveite a oportunidade existente.",
            )
        if review.relacionados:
            ids = [i for i, _ in review.relacionados]
            if not (variacao_de and diferenca):
                return self._refuse(
                    f"existe {kind} relacionada; para criar, informe 'variacao_de' (um dos IDs relacionados) e "
                    "'diferenca' (o que muda: outra condição, domínio, configuração ou resultado oposto). "
                    "Na dúvida entre duplicata e variação, não crie.",
                    relacionados=ids,
                )
            if variacao_de not in ids:
                return self._refuse("'variacao_de' deve ser um dos IDs relacionados encontrados.", relacionados=ids)
        return None

    def _link_related(self, new_id: str, review: _Review, variacao_de: str | None) -> list[str]:
        """Liga a nova descoberta às relacionadas por ``SEMELHANTE_A`` (``score``, ``modelo``, ``versao``)."""
        linked: list[str] = []
        info = self.index.embedding_info if self.index is not None else None
        for other_id, score in review.relacionados:
            if variacao_de and other_id != variacao_de and score is None:
                continue
            props = {
                "score": float(score) if score is not None else float(config.SIM_RELATED_MIN_SAME_DOMAIN),
                "modelo": getattr(info, "model", "desconhecido"),
                "versao": str(getattr(info, "version", "0")),
            }
            try:
                self._edge(new_id, "SEMELHANTE_A", other_id, **props)
                linked.append(other_id)
            except GraphStoreError as exc:
                logger.warning("Ligação SEMELHANTE_A recusada", extra={"extra": {"erro": type(exc).__name__}})
        return linked

    # ------------------------------------------------------------------ leitura

