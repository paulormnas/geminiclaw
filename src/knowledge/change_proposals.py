"""Propostas de alteração do grafo pelo pesquisador (``v17-graph-cli``; ADR 015 §11).

O Curator, em modo de edição, **só propõe**: devolve uma lista de operações tipadas (:func:`parse_ops`). A CLI faz a
**validação a seco** (:func:`plan_changes`, mesmas regras do ``GraphStore``), mostra a proposta e só aplica
(:func:`apply_plan`) depois da confirmação humana interativa, com ``Actor(kind="pesquisador")``.

Garantias deste módulo:

- **Nada é apagado**: não existe operação de remoção; pedidos de remoção viram mudança de status.
- **Só o projeto ativo**: escrever em nó de outro projeto (ou compartilhável) é recusado.
- **Decisões reservadas continuam reservadas**: o ``Problema`` e o ``Projeto`` têm comandos próprios (``project``),
  termos do vocabulário, os do ``vocab``; fatos estruturais (Sessao, Insumo, Experimento, Resultado), campos calculados
  (veredito...) e relações derivadas nunca são escritos aqui. Decidir sobre ``Oportunidade`` exige, além da
  confirmação da proposta, a autorização do ``HumanGate`` (``aprovar_oportunidade``).
- **Aplicação atômica no que for reversível**: verificação prévia do estado e, se uma escrita falhar, reversão das
  alterações de status/propriedades já feitas; nós criados não são apagados (e são reportados).
- **Auditoria**: cada escrita registra em ``knowledge_audit`` (mesma trilha das demais alterações) o pedido original.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src import config
from src.knowledge import schema, validation
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.graph_views import node_text, sanitize_text
from src.knowledge.provenance import Actor, prepare_edge_properties, prepare_node_properties

PESQUISADOR = Actor(kind="pesquisador")
EDIT_SESSION_ID = "__graph_edit__"
OP_TYPES = ("update_node", "create_node", "create_edge", "set_edge_status")
DECISION_OPPORTUNITY = "aprovar_oportunidade"

# Rótulos com comando próprio: o pesquisador os altera por ``geminiclaw project`` (confirmação do Problema etc.).
BLOCKED_LABELS: dict[str, str] = {
    "Problema": "use `geminiclaw project` (a confirmação do Problema é uma decisão reservada)",
    "Projeto": "use `geminiclaw project`",
    "Dominio": "o vocabulário controlado segue o fluxo de candidatos (`geminiclaw vocab`)",
    "Metrica": "o vocabulário controlado segue o fluxo de candidatos (`geminiclaw vocab`)",
}
# Calculados deterministicamente ou geridos pelo sistema: nunca escritos à mão.
DERIVED_FIELDS = frozenset(
    {"veredito", "suporte", "certeza", "n_tentativas", "n_evidencias", "confianca", "estado_vetorizacao"}
)
# Preenchidos pelo sistema (proveniência e escopo): o pedido não os define.
SYSTEM_FIELDS = frozenset(
    {
        "id", "criado_em", "atualizado_em", "criado_por", "projeto_id", "sessao_id", "visibilidade", "origem_no",
        "versao_schema", "justificativa_criacao", "nos_consultados",
    }
)
# Relações derivadas (cálculo determinístico) ou de fato: criá-las à mão forjaria evidência.
DERIVED_RELATIONS = frozenset({"SUSTENTA", "REFUTA", "FUNCIONOU_PARA", "FALHOU_PARA"})
VERDICT_DISCOVERY_TYPES = ("funciona", "nao_funciona")
TERMINAL_STATUSES = frozenset(
    {"rejeitada", "rejeitado", "contestada", "substituida", "abandonada", "refutada", "inconclusiva", "concluida"}
)

_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_REF_RE = re.compile(r"^\$([1-9][0-9]?)$")
_MAX_TEXT = 2000
_MAX_FIELDS = 12
_MAX_COLLECTION = 50
_OP_KEYS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # op -> (obrigatórias, opcionais)
    "update_node": (frozenset({"op", "id", "changes"}), frozenset({"motivo"})),
    "create_node": (frozenset({"op", "label", "props"}), frozenset({"motivo"})),
    "create_edge": (frozenset({"op", "src", "rel", "dst"}), frozenset({"props", "motivo"})),
    "set_edge_status": (frozenset({"op", "src", "rel", "dst", "status"}), frozenset({"motivo"})),
}


class ProposalError(ValueError):
    """Proposta malformada (estrutura, tipos ou tamanhos); a mensagem é segura para exibir e para voltar ao modelo."""


class StaleProposalError(ProposalError):
    """O grafo mudou entre a exibição da proposta e a aplicação."""


class ApplyError(RuntimeError):
    """Falha ao aplicar; informa o que foi revertido e o que permaneceu (nós criados não são apagados)."""

    def __init__(self, message: str, *, rolled_back: int, kept_created: list[str]) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back
        self.kept_created = kept_created


@dataclass(frozen=True)
class Op:
    """Operação tipada proposta (``kind`` em ``OP_TYPES``); os demais campos dependem do tipo."""

    kind: str
    data: dict[str, Any]
    motivo: str = ""


@dataclass
class PlannedOp:
    """Operação já validada a seco, com a descrição para o pesquisador e o estado atual (``before``)."""

    index: int
    op: Op
    description: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    before: dict[str, Any] = field(default_factory=dict)
    effective: dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False
    decision: str | None = None  # decisão reservada que exige o HumanGate
    label: str = ""
    node_id: str = ""


@dataclass
class Plan:
    """Proposta validada a seco."""

    project_id: str
    items: list[PlannedOp]

    @property
    def errors(self) -> list[str]:
        return [f"operação {p.index}: {e}" for p in self.items for e in p.errors]

    @property
    def warnings(self) -> list[str]:
        return [f"operação {p.index}: {w}" for p in self.items for w in p.warnings]

    @property
    def decisions(self) -> list[PlannedOp]:
        return [p for p in self.items if p.decision]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ApplyResult:
    """Resultado da aplicação."""

    applied: int
    created_ids: dict[int, str]


# ---------------------------------------------------------------------------
# Estrutura (sem tocar o grafo)
# ---------------------------------------------------------------------------


def _scalar_ok(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and len(value) <= _MAX_TEXT


def _clean_scalar(value: Any) -> Any:
    """Texto livre sem controles nem quebras (``Cc``/``Cf``/``Zl``/``Zp`` viram espaço); outros escalares intactos."""
    if isinstance(value, str):
        spaced = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in value)
        return " ".join(spaced.split())
    return value


def _clean_mapping(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > _MAX_FIELDS:
        raise ProposalError(f"'{name}' deve ser um objeto com até {_MAX_FIELDS} campos.")
    out: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
            raise ProposalError(f"'{name}': nome de campo inválido.")
        if isinstance(item, (list, tuple)):
            if len(item) > _MAX_COLLECTION or not all(_scalar_ok(v) and not isinstance(v, (list, dict)) for v in item):
                raise ProposalError(f"'{name}.{key}': lista de escalares curtos (até {_MAX_COLLECTION}).")
            out[key] = [_clean_scalar(v) for v in item]
        elif not _scalar_ok(item):
            raise ProposalError(f"'{name}.{key}' deve ser um valor simples (texto de até {_MAX_TEXT} caracteres).")
        else:
            out[key] = _clean_scalar(item)
    return out


def _ref(name: str, value: Any) -> str:
    if not isinstance(value, str) or not (_ID_RE.fullmatch(value) or _REF_RE.fullmatch(value)):
        raise ProposalError(f"'{name}' deve ser o ID de um nó ou uma referência '$N' a um nó criado antes.")
    return value


def parse_ops(raw: Any, *, max_ops: int | None = None) -> list[Op]:
    """Converte a lista bruta (vinda do modelo) em operações tipadas, com validação **estrutural** estrita.

    Operações de remoção não existem: o tipo é recusado com orientação.

    Raises:
        ProposalError: Lista/campos inesperados, tipos errados, textos longos, mais operações que o limite.
    """
    limit = config.GRAPH_EDIT_MAX_OPS if max_ops is None else max_ops
    if not isinstance(raw, list):
        raise ProposalError("'ops' deve ser uma lista de operações.")
    if len(raw) > limit:
        raise ProposalError(f"proposta com {len(raw)} operações; o máximo é {limit}. Divida o pedido.")
    ops: list[Op] = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ProposalError(f"operação {position}: deve ser um objeto.")
        kind = item.get("op")
        if kind not in _OP_KEYS:
            raise ProposalError(
                f"operação {position}: tipo '{sanitize_text(kind, 30)}' inexistente. Tipos: {', '.join(OP_TYPES)}. "
                "Não há remoção: nada é apagado; use mudança de status (contestada, substituida, rejeitada)."
            )
        required, optional = _OP_KEYS[kind]
        missing = required - set(item)
        extra = set(item) - required - optional
        if missing or extra:
            raise ProposalError(
                f"operação {position} ({kind}): campos ausentes {sorted(missing)} ou inesperados {sorted(extra)}."
            )
        motivo = item.get("motivo", "")
        if not isinstance(motivo, str) or len(motivo) > _MAX_TEXT:
            raise ProposalError(f"operação {position}: 'motivo' deve ser texto curto.")
        try:
            if kind == "update_node":
                data = {"id": _ref("id", item["id"]), "changes": _clean_mapping("changes", item["changes"])}
                if not data["changes"]:
                    raise ProposalError("'changes' não pode ser vazio.")
            elif kind == "create_node":
                label = item["label"]
                if not isinstance(label, str):
                    raise ProposalError("'label' deve ser texto.")
                data = {"label": label, "props": _clean_mapping("props", item["props"])}
            elif kind == "create_edge":
                data = {
                    "src": _ref("src", item["src"]), "rel": _plain("rel", item["rel"]),
                    "dst": _ref("dst", item["dst"]), "props": _clean_mapping("props", item.get("props", {})),
                }
            else:
                data = {
                    "src": _ref("src", item["src"]), "rel": _plain("rel", item["rel"]),
                    "dst": _ref("dst", item["dst"]), "status": _plain("status", item["status"]),
                }
        except ProposalError as exc:
            raise ProposalError(f"operação {position} ({kind}): {exc}") from None
        ops.append(Op(kind, data, _clean_scalar(motivo)))
    return ops


def _plain(name: str, value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value):
        raise ProposalError(f"'{name}' inválido.")
    return value


# ---------------------------------------------------------------------------
# Validação a seco
# ---------------------------------------------------------------------------


def _quote(value: Any, limit: int = 60) -> str:
    return sanitize_text(value, limit)


def _describe_node(node: Node) -> str:
    return f"{sanitize_text(node.label, 40)} {sanitize_text(node.id, 64)} \"{node_text(node, 60)}\""


class _Planner:
    """Valida cada operação contra o grafo e o schema, sem escrever."""

    def __init__(self, store: GraphStore, project_id: str, index: Any | None) -> None:
        self.store = store
        self.project_id = project_id
        self.index = index
        self.created_labels: dict[int, str] = {}  # posição (1-based) -> rótulo do nó a criar
        self.created_props: dict[int, dict[str, Any]] = {}

    # -- resolução de endpoints ------------------------------------------------

    def _endpoint(self, item: PlannedOp, name: str, ref: str, *, write: bool) -> tuple[str, Node | None] | None:
        """``(rótulo, nó existente | None)`` do endpoint, ou ``None`` com erro registrado."""
        match = _REF_RE.fullmatch(ref)
        if match:
            pos = int(match.group(1))
            if pos >= item.index or pos not in self.created_labels:
                item.errors.append(f"'{name}': referência '{ref}' deve apontar para um create_node anterior.")
                return None
            return self.created_labels[pos], None
        node = self.store.get_node(ref)
        if node is None:
            item.errors.append(f"'{name}': nó '{_quote(ref, 64)}' não existe.")
            return None
        own = node.properties.get("projeto_id") == self.project_id
        if write and not own:
            item.errors.append(f"'{name}': só nós do projeto ativo podem ser alterados (nó de outro projeto ou compartilhado).")
            return None
        if not own and node.properties.get("visibilidade") != "compartilhavel":
            item.errors.append(f"'{name}': nó '{_quote(ref, 64)}' não pertence ao projeto.")
            return None
        return node.label, node

    # -- operações --------------------------------------------------------------

    def plan(self, item: PlannedOp) -> None:
        op = item.op
        try:
            getattr(self, f"_plan_{op.kind}")(item)
        except GraphStoreError as exc:
            item.errors.append(sanitize_text(str(exc), 300))
        if item.sensitive and not op.motivo:
            item.warnings.append("alteração sensível sem 'motivo' informado.")

    def _plan_update_node(self, item: PlannedOp) -> None:
        op, node_id, changes = item.op, item.op.data["id"], dict(item.op.data["changes"])
        if _REF_RE.fullmatch(node_id):
            item.errors.append("update_node não aceita referência '$N': só nós existentes.")
            return
        node = self.store.get_node(node_id)
        if node is None:
            item.errors.append(f"nó '{_quote(node_id, 64)}' não existe.")
            return
        item.label, item.node_id = node.label, node.id
        if node.properties.get("projeto_id") != self.project_id:
            item.errors.append("só nós do projeto ativo podem ser alterados.")
            return
        self._check_label_writable(item, node.label)
        derived = sorted(set(changes) & DERIVED_FIELDS)
        if derived:
            item.errors.append(f"campos calculados pelo sistema não são editáveis: {', '.join(derived)}.")
        system = sorted(set(changes) & SYSTEM_FIELDS)
        if system:
            item.errors.append(f"campos de proveniência/escopo não são editáveis: {', '.join(system)}.")
        if node.label == "Descoberta" and changes.get("tipo") in VERDICT_DISCOVERY_TYPES:
            item.errors.append("descobertas 'funciona'/'nao_funciona' dependem de veredito calculado; não são editáveis.")
        if item.errors:
            return
        validation.validate_node_update(node.label, changes)
        effective = dict(changes)
        if node.label == "Oportunidade":
            if set(changes) & {"status", "decidido_por", "decidido_em", "motivo_decisao"}:
                item.decision = DECISION_OPPORTUNITY
                item.sensitive = True
                effective.pop("decidido_por", None)
                effective.pop("decidido_em", None)
                effective["decidido_por"] = PESQUISADOR.criado_por
                effective["decidido_em"] = datetime.now(timezone.utc).isoformat()
                if op.motivo and "motivo_decisao" not in effective:
                    effective["motivo_decisao"] = op.motivo
        else:
            # Decisões reservadas a humano (vocabulário, nós rejeitados de vocabulário): a mesma regra aplicada a agentes.
            try:
                validation.validate_human_only(node.label, current=node.properties, changes=changes, actor_kind="agente")
            except GraphStoreError as exc:
                hint = " Use `geminiclaw vocab`." if node.label in ("Dominio", "Metrica") else ""
                item.errors.append(f"decisão reservada ao pesquisador por comando próprio: {sanitize_text(str(exc), 200)}{hint}")
                return
        item.before = {k: node.properties.get(k) for k in effective}
        item.effective = effective
        status_new = effective.get("status")
        item.sensitive = item.sensitive or status_new in TERMINAL_STATUSES
        diffs = "; ".join(
            f"{_quote(k, 40)}: {_quote(item.before.get(k), 80)!r} → {_quote(v, 80)!r}" for k, v in effective.items()
        )
        item.description = f"Alterar {_describe_node(node)}: {diffs}"

    def _check_label_writable(self, item: PlannedOp, label: str) -> None:
        if label in BLOCKED_LABELS:
            item.errors.append(f"{label} não é alterável por aqui: {BLOCKED_LABELS[label]}.")
        if label in validation.FACT_LABELS:
            item.errors.append(f"{label} é fato estrutural (ingestão determinística): não é editável.")

    def _plan_create_node(self, item: PlannedOp) -> None:
        label, props = item.op.data["label"], dict(item.op.data["props"])
        if label not in schema.NODE_LABELS:
            item.errors.append(f"rótulo '{_quote(label, 40)}' desconhecido.")
            return
        item.label = label
        self._check_label_writable(item, label)
        bad = sorted(set(props) & (SYSTEM_FIELDS | DERIVED_FIELDS))
        if bad:
            item.errors.append(f"campos definidos pelo sistema não podem ser informados: {', '.join(bad)}.")
        if label == "Descoberta" and props.get("tipo") in VERDICT_DISCOVERY_TYPES:
            item.errors.append("descobertas 'funciona'/'nao_funciona' dependem de veredito calculado; não são criáveis.")
        if item.errors:
            return
        # Oportunidade nasce documentada; decidir sobre ela é um passo posterior, com autorização do gate.
        if label == "Oportunidade":
            props.setdefault("status", "documentada")
            if props["status"] != "documentada":
                item.errors.append("Oportunidade nasce 'documentada'; decidir é um passo posterior do pesquisador.")
                return
        if label == "Descoberta":
            props.setdefault("n_evidencias", 0)
            props.setdefault("status", "ativa")
        full = prepare_node_properties(
            {**props, "projeto_id": self.project_id, "sessao_id": EDIT_SESSION_ID}, PESQUISADOR
        )
        validation.validate_node_write(label, full, requires_agent_provenance=False)
        item.effective = props
        self.created_labels[item.index] = label
        self.created_props[item.index] = props
        item.warnings.extend(self._duplicate_warnings(label, props))
        if label == "Descoberta":
            item.warnings.append("descoberta sem evidência ligada: crie as relações BASEADA_EM e SOBRE.")
        shown = ", ".join(f"{_quote(k, 40)}={_quote(v, 80)!r}" for k, v in props.items())
        item.description = f"Criar {sanitize_text(label, 40)} (referência ${item.index}): {shown}"

    def _plan_create_edge(self, item: PlannedOp) -> None:
        data = item.op.data
        rel = data["rel"]
        if rel not in schema.RELATION_TYPES:
            item.errors.append(f"relação '{_quote(rel, 40)}' desconhecida.")
            return
        if rel in DERIVED_RELATIONS:
            item.errors.append(f"{rel} é derivada do cálculo de veredito: não é criada à mão.")
            return
        src = self._endpoint(item, "src", data["src"], write=True)
        dst = self._endpoint(item, "dst", data["dst"], write=False)
        if src is None or dst is None:
            return
        (src_label, src_node), (dst_label, dst_node) = src, dst
        if src_label in validation.FACT_LABELS:
            item.errors.append(f"relações a partir de {src_label} (fato estrutural) não são editáveis.")
            return
        full = prepare_edge_properties(dict(data["props"]), PESQUISADOR)
        validation.validate_edge_write(src_label, rel, dst_label, full)
        if src_node is not None and dst_node is not None:
            sub = self.store.neighbors(src_node.id, [rel], "out", 1)
            if any(e.src_id == src_node.id and e.rel_type == rel and e.dst_id == dst_node.id for e in sub.edges):
                item.errors.append("a relação já existe.")
                return
        item.label = src_label
        item.node_id = src_node.id if src_node is not None else ""
        src_txt = _describe_node(src_node) if src_node else f"{sanitize_text(src_label, 40)} (referência {data['src']})"
        dst_txt = _describe_node(dst_node) if dst_node else f"{sanitize_text(dst_label, 40)} (referência {data['dst']})"
        item.description = f"Criar relação: {src_txt} --{sanitize_text(rel, 40)}--> {dst_txt}"

    def _plan_set_edge_status(self, item: PlannedOp) -> None:
        data = item.op.data
        allowed = schema.COMMON_EDGE_PROPERTIES["status"].enum or ()
        if data["status"] not in allowed:
            item.errors.append(f"status de relação deve ser um de {list(allowed)}.")
            return
        if _REF_RE.fullmatch(data["src"]) or _REF_RE.fullmatch(data["dst"]):
            item.errors.append("set_edge_status não aceita referência '$N': só relações existentes.")
            return
        src = self._endpoint(item, "src", data["src"], write=True)
        dst = self._endpoint(item, "dst", data["dst"], write=False)
        if src is None or dst is None:
            return
        src_node, dst_node = src[1], dst[1]
        assert src_node is not None and dst_node is not None
        sub = self.store.neighbors(src_node.id, [data["rel"]], "out", 1)
        edge = next(
            (e for e in sub.edges if e.src_id == src_node.id and e.rel_type == data["rel"] and e.dst_id == dst_node.id),
            None,
        )
        if edge is None:
            item.errors.append("a relação não existe.")
            return
        item.label, item.node_id = src_node.label, src_node.id
        item.before = {"status": edge.properties.get("status")}
        item.effective = {"status": data["status"]}
        item.sensitive = data["status"] == "contestada"
        item.description = (
            f"Alterar o status da relação {_describe_node(src_node)} --{sanitize_text(data['rel'], 40)}--> "
            f"{_describe_node(dst_node)}: {_quote(item.before['status'], 30)!r} → {_quote(data['status'], 30)!r}"
        )

    # -- duplicatas (aviso; o pesquisador pode prosseguir) -----------------------

    def _duplicate_warnings(self, label: str, props: dict[str, Any]) -> list[str]:
        from src.knowledge.semantic_index import canonical_text

        warnings: list[str] = []
        text = canonical_text(label, props)
        if not text:
            return warnings
        wanted = " ".join(text.casefold().split())
        seen: set[str] = set()
        try:
            existing = self.store.find_nodes(label, {"projeto_id": self.project_id}, limit=200)
        except GraphStoreError:
            existing = []
        for node in existing:
            if " ".join(canonical_text(label, node.properties).casefold().split()) == wanted:
                seen.add(node.id)
                warnings.append(f"possível duplicata de {_describe_node(node)} (texto idêntico).")
        if self.index is not None:
            try:
                hits = self.index.similar(
                    text=text, labels=[label], filters={"projeto_id": self.project_id},
                    min_score=config.SIM_RELATED_MIN_SAME_DOMAIN, limit=5,
                )
            except Exception:  # noqa: BLE001 - índice fora do ar: só avisa
                warnings.append("revisão semântica de duplicatas indisponível (índice fora do ar).")
                hits = []
            for hit in hits:
                if hit.node_id in seen:
                    continue
                node = self.store.get_node(hit.node_id)
                if node is None or node.properties.get("status") in ("rejeitada", "rejeitado"):
                    continue
                kind = "possível duplicata" if hit.score >= config.SIM_DUPLICATE_MIN else "nó relacionado"
                warnings.append(f"{kind} (similaridade {hit.score:.2f}): {_describe_node(node)}.")
        return warnings


def plan_changes(store: GraphStore, ops: list[Op], *, project_id: str, index: Any | None = None) -> Plan:
    """Validação a seco: aplica as regras do ``GraphStore`` e as do módulo a cada operação, **sem escrever**.

    Args:
        store: Grafo (só leituras são feitas aqui).
        ops: Operações já estruturadas por :func:`parse_ops`.
        project_id: Projeto ativo (único em que se escreve).
        index: Índice semântico opcional (avisos de duplicata).

    Returns:
        O ``Plan``; ``plan.errors`` vazio significa que a proposta pode ser oferecida para confirmação.
    """
    planner = _Planner(store, project_id, index)
    items: list[PlannedOp] = []
    for position, op in enumerate(ops, start=1):
        item = PlannedOp(index=position, op=op)
        planner.plan(item)
        items.append(item)
    return Plan(project_id=project_id, items=items)


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------


def _check_unchanged(store: GraphStore, item: PlannedOp) -> None:
    """Falha se o estado mudou desde a exibição da proposta (a confirmação vale para o que foi mostrado)."""
    if item.op.kind == "update_node":
        node = store.get_node(item.node_id)
        if node is None or any(node.properties.get(k) != v for k, v in item.before.items()):
            raise StaleProposalError(
                f"operação {item.index}: o nó mudou depois da proposta; peça novamente para ver o estado atual."
            )
    elif item.op.kind == "set_edge_status":
        data = item.op.data
        sub = store.neighbors(data["src"], [data["rel"]], "out", 1)
        edge = next((e for e in sub.edges if e.dst_id == data["dst"] and e.rel_type == data["rel"]), None)
        if edge is None or edge.properties.get("status") != item.before.get("status"):
            raise StaleProposalError(f"operação {item.index}: a relação mudou depois da proposta.")


def _note(request: str, item: PlannedOp, **extra: Any) -> dict[str, Any]:
    return {
        "origem": "graph edit",
        "pedido_original": request[: config.GRAPH_EDIT_MAX_REQUEST_CHARS],
        "operacao": item.op.kind,
        "motivo": item.op.motivo[:500],
        **extra,
    }


def apply_plan(
    store: GraphStore,
    plan: Plan,
    *,
    request: str,
) -> ApplyResult:
    """Aplica uma proposta **já validada e confirmada**, com ``Actor(pesquisador)`` e o pedido original na auditoria.

    Ordem: criações de nó, criações de relação e, por fim, mudanças de propriedade/status (as reversíveis ficam por
    último). Antes de escrever, confere que o estado não mudou. Se uma escrita falhar, as mudanças reversíveis já
    feitas são desfeitas; nós criados permanecem (nada é apagado) e são reportados em ``ApplyError``.

    Raises:
        ProposalError: A proposta tem erros (não deve ser aplicada).
        StaleProposalError: O grafo mudou depois da proposta (nada foi escrito).
        ApplyError: Falha durante a aplicação.
    """
    if not plan.ok:
        raise ProposalError("proposta com erros: " + "; ".join(plan.errors))
    for item in plan.items:
        _check_unchanged(store, item)

    order = {"create_node": 0, "create_edge": 1, "update_node": 2, "set_edge_status": 2}
    queue = sorted(plan.items, key=lambda p: (order[p.op.kind], p.index))
    created: dict[int, str] = {}
    undo: list[Callable[[], None]] = []
    applied = 0

    def resolve(ref: str) -> str:
        match = _REF_RE.fullmatch(ref)
        return created[int(match.group(1))] if match else ref

    try:
        for item in queue:
            kind, data = item.op.kind, item.op.data
            if kind == "create_node":
                node_id = store.create_node(
                    item.label,
                    {**item.effective, "projeto_id": plan.project_id, "sessao_id": EDIT_SESSION_ID},
                    actor=PESQUISADOR,
                )
                created[item.index] = node_id
                store.record_audit_note(node_id, PESQUISADOR, _note(request, item, criado=item.label))
            elif kind == "create_edge":
                src, dst = resolve(data["src"]), resolve(data["dst"])
                store.create_edge(src, data["rel"], dst, dict(data["props"]), actor=PESQUISADOR)
                undo.append(lambda s=src, r=data["rel"], d=dst: store.set_edge_status(s, r, d, "contestada", actor=PESQUISADOR))
                store.record_audit_note(src, PESQUISADOR, _note(request, item, aresta=f"{data['rel']}->{dst}"))
            elif kind == "update_node":
                old = dict(item.before)
                store.update_node(item.node_id, dict(item.effective), actor=PESQUISADOR)
                undo.append(lambda i=item.node_id, o=old: store.update_node(i, o, actor=PESQUISADOR))
                store.record_audit_note(item.node_id, PESQUISADOR, _note(request, item, campos=sorted(item.effective)))
            else:
                old_status = item.before["status"]
                store.set_edge_status(data["src"], data["rel"], data["dst"], data["status"], actor=PESQUISADOR)
                undo.append(
                    lambda s=data["src"], r=data["rel"], d=data["dst"], o=old_status: store.set_edge_status(
                        s, r, d, o, actor=PESQUISADOR
                    )
                )
                store.record_audit_note(
                    data["src"], PESQUISADOR,
                    _note(request, item, aresta=f"{data['rel']}->{data['dst']}", status=data["status"]),
                )
            applied += 1
    except Exception as exc:  # noqa: BLE001 - qualquer falha reverte o que for reversível
        rolled = 0
        for action in reversed(undo):
            try:
                action()
                rolled += 1
            except Exception:  # noqa: BLE001 - reversão best effort; o relatório informa
                pass
        raise ApplyError(
            f"falha ao aplicar a operação {applied + 1} ({type(exc).__name__}: {sanitize_text(str(exc), 200)}); "
            f"{rolled} alteração(ões) revertida(s).",
            rolled_back=rolled,
            kept_created=list(created.values()),
        ) from exc
    return ApplyResult(applied=applied, created_ids=created)


def render_plan(plan: Plan, explanation: str) -> str:
    """Texto da proposta para o pesquisador (tudo sanitizado): explicação, operações, avisos e erros."""
    lines = ["PROPOSTA DO CURATOR (nada foi alterado ainda)", "", f"Explicação: {sanitize_text(explanation, 1500)}", ""]
    if not plan.items:
        lines.append("O Curator não propôs nenhuma alteração.")
    for item in plan.items:
        mark = " [SENSÍVEL]" if item.sensitive else ""
        mark += " [DECISÃO RESERVADA: exige autorização adicional]" if item.decision else ""
        lines.append(f"{item.index}. {item.description or sanitize_text(item.op.kind, 30)}{mark}")
        if item.op.motivo:
            lines.append(f"   motivo: {sanitize_text(item.op.motivo, 300)}")
    if plan.warnings:
        lines += ["", "Avisos (você pode prosseguir mesmo assim):"] + [f"  - {w}" for w in plan.warnings]
    if plan.errors:
        lines += ["", "ERROS (a proposta não pode ser aplicada):"] + [f"  - {e}" for e in plan.errors]
    lines += ["", "Nada é apagado: pedidos de remoção viram mudança de status."]
    return "\n".join(lines)
