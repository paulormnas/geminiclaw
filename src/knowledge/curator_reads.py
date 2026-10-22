"""Ferramentas de leitura do Curator (nós, vizinhança, similaridade, consulta livre, fila)."""

from __future__ import annotations

from typing import Any

from src.knowledge import schema
from src.knowledge.curator_common import (
    _FILTER_KEYS,
    _LIMIT_RE,
    _MAX_DATASET_FILTER,
    _MAX_FILTER_VALUE_CHARS,
    _MAX_ROWS,
    _QUEUE_OVERFETCH,
    _TEXT_ORACLE_RE,
    EVIDENCE_LABELS,
    CuratorToolError,
    _only_ids_and_numbers,
    _safe_param,
    _short_text,
    node_view,
)
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import Node
from src.logger import get_logger

logger = get_logger(__name__)


class CuratorReads:
    def get_node(self, node_id: str) -> dict[str, Any]:
        """Um nó do projeto (ou compartilhável) com as suas propriedades."""
        return {"ok": True, "no": node_view(self._node("node_id", node_id))}

    def neighbors(
        self, node_id: str, rels: list[str] | None = None, direction: str = "both", depth: int = 1, limit: int = 30
    ) -> dict[str, Any]:
        """Vizinhança de um nó (até 2 saltos), restrita ao que o projeto pode ver."""
        self._node("node_id", node_id)
        if direction not in ("in", "out", "both"):
            raise CuratorToolError("'direction' deve ser in, out ou both.")
        if rels is not None:
            if not isinstance(rels, list) or any(r not in schema.RELATION_TYPES for r in rels):
                raise CuratorToolError("'rels' deve listar tipos de relação do schema.")
        if not isinstance(depth, int) or not 1 <= depth <= 2:
            raise CuratorToolError("'depth' deve ser 1 ou 2.")
        sub = self.store.neighbors(node_id, rels or None, direction, depth)
        nodes = [n for n in sub.nodes if self._visible(n)][: min(max(int(limit), 1), _MAX_ROWS)]
        keep = {n.id for n in nodes} | {node_id}
        edges = [
            {"de": e.src_id, "rel": e.rel_type, "para": e.dst_id, "status": e.properties.get("status")}
            for e in sub.edges
            if e.src_id in keep and e.dst_id in keep
        ]
        return {"ok": True, "nos": [node_view(n) for n in nodes], "arestas": edges[:_MAX_ROWS * 2]}

    def find_nodes(self, label: str, filters: dict[str, Any] | None = None, limit: int = 20) -> dict[str, Any]:
        """Nós do projeto de um rótulo, por igualdade de propriedades (chaves validadas contra o schema)."""
        if label not in schema.NODE_LABELS:
            raise CuratorToolError("'label' desconhecido.")
        if filters is not None and not isinstance(filters, dict):
            raise CuratorToolError("'filters' deve ser um objeto de igualdades.")
        scalars: dict[str, Any] = {}
        for key, value in (filters or {}).items():
            if not isinstance(value, (str, int, float, bool)) or (isinstance(value, str) and len(value) > 300):
                raise CuratorToolError("valores de 'filters' devem ser escalares curtos.")
            scalars[str(key)] = value
        scalars["projeto_id"] = self.project_id  # o projeto da sessão sempre vence
        try:
            nodes = self.store.find_nodes(label, scalars, limit=min(max(int(limit), 1), _MAX_ROWS))
        except GraphStoreError as exc:
            raise CuratorToolError(str(exc)) from exc
        return {"ok": True, "nos": [node_view(n) for n in nodes]}

    def similar(
        self,
        texto: str | None = None,
        node_id: str | None = None,
        labels: list[str] | None = None,
        limit: int = 10,
        escopo: str = "projeto",
    ) -> dict[str, Any]:
        """Nós semanticamente próximos (só leitura). ``escopo``: ``projeto`` ou ``visivel`` (inclui compartilháveis)."""
        if self.index is None:
            raise CuratorToolError("índice semântico indisponível.")
        if (texto is None) == (node_id is None):
            raise CuratorToolError("informe exatamente um entre 'texto' e 'node_id'.")
        if escopo not in ("projeto", "visivel"):
            raise CuratorToolError("'escopo' deve ser projeto ou visivel.")
        wanted = labels or ["Descoberta"]
        if not isinstance(wanted, list) or any(lab not in schema.VECTORIZABLE_LABELS for lab in wanted):
            raise CuratorToolError("'labels' deve listar rótulos vetorizados.")
        if node_id is not None:
            self._node("node_id", node_id)
        try:
            hits = self.index.similar(
                text=self._text("texto", texto) if texto is not None else None,
                node_id=node_id,
                labels=wanted,
                filters={"projeto_id": self.project_id} if escopo == "projeto" else None,
                projeto_id=self.project_id if escopo == "visivel" else None,
                limit=min(max(int(limit), 1), 20),
            )
        except ValueError as exc:
            raise CuratorToolError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise CuratorToolError("busca semântica indisponível.") from exc
        out = []
        for hit in hits:
            node = self.store.get_node(hit.node_id)
            if node is not None and self._visible(node):
                out.append(
                    {"id": hit.node_id, "label": hit.label, "score": round(hit.score, 4), "resumo": _short_text(node)}
                )
        return {"ok": True, "resultados": out}

    def related_experience(self, problema_id: str, limit: int = 10) -> dict[str, Any]:
        """"O que já funcionou ou falhou em problemas parecidos?" (só o que o projeto pode ver)."""
        if self.index is None:
            raise CuratorToolError("índice semântico indisponível.")
        self._node("problema_id", problema_id, ("Problema",))
        try:
            items = self.index.related_experience(
                problema_id, min(max(int(limit), 1), 20), restrict_to_visible=True
            )
        except ValueError as exc:
            raise CuratorToolError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise CuratorToolError("consulta híbrida indisponível.") from exc
        return {
            "ok": True,
            "itens": [
                {
                    "tipo": i.kind,
                    "no": node_view(i.node),
                    "similaridade": round(i.similarity, 4),
                    "rank": round(i.rank, 4),
                }
                for i in items
            ],
        }

    def read_query(self, cypher: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Consulta Cypher livre **somente-leitura** (papel de banco sem escrita, transação ``READ ONLY``, timeout)."""
        if self.stats.consultas_livres >= self.limits.max_read_queries:
            raise CuratorToolError(f"limite de {self.limits.max_read_queries} consultas livres por execução atingido.")
        self.stats.consultas_livres += 1
        if not isinstance(cypher, str) or not cypher.strip() or len(cypher) > 2000:
            raise CuratorToolError("'cypher' deve ser um texto de até 2000 caracteres.")
        if params is not None and not isinstance(params, dict):
            raise CuratorToolError("'params' deve ser um objeto.")
        if not _LIMIT_RE.search(cypher):
            raise CuratorToolError("a consulta precisa de LIMIT <n> (resultados são limitados).")
        # Mitigação de oráculo (revisão do PR #106): sem literais de texto, sem funções/predicados de texto e sem
        # parâmetros de texto livre (só UUID, número ou booleano); a consulta precisa citar $projeto_id.
        if "'" in cypher or '"' in cypher:
            raise CuratorToolError("literais de texto não são aceitos: use parâmetros numéricos ou IDs (UUID).")
        if _TEXT_ORACLE_RE.search(cypher):
            raise CuratorToolError("funções e predicados sobre texto não são aceitos em read_query.")
        if "$projeto_id" not in cypher:
            raise CuratorToolError(
                "restrinja a consulta ao projeto da sessão com $projeto_id (ex.: n.projeto_id = $projeto_id)."
            )
        safe_params: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if key == "projeto_id":
                continue  # sempre o projeto da sessão (abaixo)
            if not _safe_param(value):
                raise CuratorToolError("parâmetros de texto livre não são aceitos: só UUID, número ou booleano.")
            safe_params[str(key)] = value
        safe_params["projeto_id"] = self.project_id  # o projeto da sessão sempre vence
        try:
            rows = self.store.read_query(cypher, safe_params)
        except GraphStoreError as exc:
            raise CuratorToolError(str(exc)) from exc
        # Só IDs (UUID) e números voltam: texto de outros projetos nunca chega ao modelo; ele hidrata por get_node.
        return {"ok": True, "linhas": _only_ids_and_numbers(rows[:_MAX_ROWS])}

    def pending_flags(self, limit: int = 20) -> dict[str, Any]:
        """Sinalizações pendentes dos outros agentes (texto de agente: dado não confiável)."""
        if self._flags is None:
            return {"ok": True, "sinalizacoes": []}
        flags = self._flags.pending(min(max(int(limit), 1), 50))
        return {
            "ok": True,
            "sinalizacoes": [
                {"id": f.id, "tipo": f.tipo, "texto": f.texto, "refs": list(f.refs), "agente": f.agente,
                 "subtarefa": f.subtarefa}
                for f in flags
            ],
        }

    def next_similarity_batch(self) -> dict[str, Any]:
        """Pares pendentes da fila de similaridade, por prioridade, até o lote da execução (``CURATOR_QUEUE_BATCH``)."""
        if self.queue is None:
            raise CuratorToolError("fila de similaridade indisponível.")
        room = self.limits.queue_batch - len(self._served)
        if room <= 0:
            return {"ok": True, "pares": [], "nota": "lote da execução esgotado; o restante fica para a próxima."}
        pairs = []
        # Busca além do lote: pares que não envolvem o projeto da sessão ficam pendentes (não são servidos).
        for item in self.queue.next_batch(room * _QUEUE_OVERFETCH + len(self._served)):
            if item.id in self._served or len(pairs) >= room:
                continue
            cand = item.candidate
            a, b = self.store.get_node(cand.node_a), self.store.get_node(cand.node_b)
            if a is not None and b is not None and not any(self._in_project(n) for n in (a, b)):
                continue  # par entre outros projetos: não é desta sessão de curadoria
            self._served.add(item.id)
            self._batch[item.id] = item
            self.stats.pares_servidos += 1
            pairs.append(
                {
                    "queue_id": item.id,
                    "tipo": cand.tipo,
                    "score": round(cand.score, 4),
                    "entre_projetos": cand.entre_projetos,
                    "a": self._pair_view(a, cand.node_a),
                    "b": self._pair_view(b, cand.node_b),
                }
            )
        return {"ok": True, "pares": pairs}

    def _in_project(self, node: Node) -> bool:
        return node.properties.get("projeto_id") == self.project_id

    def _pair_view(self, node: Node | None, node_id: str) -> dict[str, Any]:
        """Nó do par: completo se visível; de outro projeto privado, só ID e rótulo (nenhum texto)."""
        if node is None:
            return {"id": node_id, "inexistente": True}
        if self._visible(node):
            return node_view(node)
        return {"id": node.id, "label": node.label, "projeto": "outro (privado)"}

    def result_records(self, problema_id: str, limit: int = 10) -> dict[str, Any]:
        """Registros de resultado (fatos medidos, sem LLM) do problema, para o Curator interpretar e qualificar."""
        problema = self._node("problema_id", problema_id, ("Problema",))
        sub = self.store.neighbors(problema.id, ["SOBRE"], direction="in", depth=1)
        records = [
            n for n in sub.nodes if n.label == "RegistroResultado" and self._visible(n)
        ]
        records.sort(key=lambda n: (-(n.properties.get("n_atingiu_alvo") or 0), n.id))
        rows = []
        for node in records[: max(1, min(int(limit), _MAX_ROWS))]:
            keep = (
                "metrica", "melhor_valor", "delta_base", "delta_pai", "n_tentativas_validas",
                "n_replicas_independentes", "n_atingiu_alvo", "n_abaixo_alvo", "atingiu_alvo", "condicoes",
                "qualificacao", "limite_aplicabilidade", "licao",
            )
            abordagens = [n.id for n in self._neighbors_out(node.id, "REGISTRA")]
            rows.append({"id": node.id, "abordagem": abordagens[:1], **{k: node.properties.get(k) for k in keep}})
        return {"ok": True, "problema": problema.id, "registros": rows}

    # ------------------------------------------------------------------ escrita: descobertas

    @staticmethod
    def _filter(value: Any) -> dict[str, list[str]] | None:
        if value is None:
            return None
        if not isinstance(value, dict) or not set(value) <= set(_FILTER_KEYS):
            raise CuratorToolError(f"'filtro_condicoes' aceita só as chaves {list(_FILTER_KEYS)}.")
        out: dict[str, list[str]] = {}
        for key, items in value.items():
            if not isinstance(items, list) or len(items) > _MAX_DATASET_FILTER:
                raise CuratorToolError(
                    f"'filtro_condicoes.{key}' deve ser uma lista de até {_MAX_DATASET_FILTER} itens."
                )
            if not all(isinstance(i, str) and 0 < len(i) <= _MAX_FILTER_VALUE_CHARS for i in items):
                raise CuratorToolError(f"'filtro_condicoes.{key}' deve conter textos curtos.")
            out[key] = list(items)
        return out or None

    def _evidence_nodes(self, ids: list[str]) -> list[Node]:
        return [self._node("evidencia_ids", i, EVIDENCE_LABELS) for i in ids]

    def _check_evidence(self, nodes: list[Node], sobre_nodes: list[Node]) -> str | None:
        """Evidência válida: ``Resultado`` validado (ou ``Experimento`` concluído) **ligada ao escopo** da descoberta.

        Returns:
            Motivo da recusa, ou ``None`` se toda evidência serve.
        """
        for node in nodes:
            if node.label == "RegistroResultado":
                if not self.service.evidence_in_scope(node, sobre_nodes):
                    return "o registro de resultado não está ligado ao escopo (sobre_ids)."
                continue
            if node.label == "Resultado" and node.properties.get("status_validacao") != "validado":
                return "evidência exige Resultado validado pelo Validator (status_validacao='validado')."
            done = ("sucesso", "divergente_documentado")
            if node.label == "Experimento" and node.properties.get("status") not in done:
                return "evidência exige Experimento concluído (sucesso ou divergente_documentado)."
            if not self.service.evidence_in_scope(node, sobre_nodes):
                return "a evidência não está ligada ao escopo (sobre_ids): use resultados dos experimentos do escopo."
        return None

