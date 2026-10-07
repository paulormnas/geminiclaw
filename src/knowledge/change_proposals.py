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

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src import config
from src.knowledge import schema, validation
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.graph_views import node_text, sanitize_text
from src.knowledge.provenance import Actor, prepare_edge_properties, prepare_node_properties

_ACTOR = Actor(kind="pesquisador")  # privado: só `apply_plan` escreve, e só com `HumanConfirmation`
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
DERIVED_RELATIONS = frozenset({"SUSTENTA", "REFUTA", "FUNCIONOU_PARA", "FALHOU_PARA", "SEMELHANTE_A"})
# Propriedades de aresta controladas pelo sistema (proveniência e derivadas): nunca vêm do pedido.
EDGE_SYSTEM_PROPS = frozenset(schema.COMMON_EDGE_PROPERTIES) | frozenset({"score", "modelo", "versao", "config",
                                                                          "hash_params", "peso"})
CONFIRM_WORD = "aplicar"
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

    def __init__(
        self, message: str, *, rolled_back: int, kept_created: list[str], rollback_failures: list[str] | None = None
    ) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back
        self.kept_created = kept_created
        self.rollback_failures = rollback_failures or []


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

    def fingerprint(self) -> str:
        """Impressão digital (SHA-256) da serialização canônica de **tudo o que será gravado**.

        Cobre operação, alvos, valores efetivos, estado anterior e decisão reservada: a confirmação humana vale para
        esta impressão, e ``apply_plan`` recusa um plano cuja impressão difira da confirmada.
        """
        body = [
            {
                "i": p.index, "kind": p.op.kind, "data": p.op.data, "motivo": p.op.motivo, "label": p.label,
                "node": p.node_id, "effective": p.effective, "before": p.before, "decision": p.decision,
            }
            for p in self.items
        ]
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class ApplyResult:
    """Resultado da aplicação."""

    applied: int
    created_ids: dict[int, str]


# ---------------------------------------------------------------------------
# Estrutura (sem tocar o grafo)
# ---------------------------------------------------------------------------


def _scalar_ok(value: Any) -> bool:
    if isinstance(value, float) and not math.isfinite(value):
        return False  # nan/inf não são JSON válido (nem agtype)
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and len(value) <= _MAX_TEXT


def _clean_scalar(value: Any) -> Any:
    """Texto livre pela **mesma** sanitização da tela (sem corte): o que é gravado é o que é exibido."""
    if isinstance(value, str):
        return sanitize_text(value, 0)
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


def _shown(value: Any, limit: int | None = None) -> str:
    """Valor como será gravado (JSON canônico, íntegro). Só o estado ``antes`` pode ser cortado (``limit``)."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if limit is not None and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


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
            item.errors.append(f"'{name}': só nós do projeto ativo são alterados (outro projeto ou compartilhado).")
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
            item.errors.append("descobertas 'funciona'/'nao_funciona' dependem de veredito calculado: não editáveis.")
        if item.errors:
            return
        validation.validate_node_update(node.label, changes)
        effective = dict(changes)
        if node.label == "Oportunidade":
            if set(changes) & {"status", "decidido_por", "decidido_em", "motivo_decisao"}:
                item.decision = DECISION_OPPORTUNITY
                item.sensitive = True
                effective.pop("decidido_por", None)
                effective.pop("decidido_em", None)  # preenchido na aplicação, com o instante real da confirmação
                effective["decidido_por"] = _ACTOR.criado_por
                if op.motivo and "motivo_decisao" not in effective:
                    effective["motivo_decisao"] = op.motivo
        else:
            # Decisões reservadas a humano: aplica-se a mesma regra que barra os agentes.
            try:
                validation.validate_human_only(
                    node.label, current=node.properties, changes=changes, actor_kind="agente"
                )
            except GraphStoreError as exc:
                hint = " Use `geminiclaw vocab`." if node.label in ("Dominio", "Metrica") else ""
                reason = sanitize_text(str(exc), 200)
                item.errors.append(f"decisão reservada ao pesquisador por comando próprio: {reason}{hint}")
                return
        item.before = {k: node.properties.get(k) for k in effective}
        if item.decision:
            item.before["decidido_em"] = node.properties.get("decidido_em")
        item.effective = effective
        status_new = effective.get("status")
        item.sensitive = item.sensitive or status_new in TERMINAL_STATUSES
        diffs = "; ".join(
            f"{_quote(k, 40)}: {_shown(item.before.get(k), 200)} → {_shown(v)}" for k, v in effective.items()
        )
        if item.decision:
            diffs += "; decidido_em: (instante da sua confirmação)"
        item.description = f"Alterar {_describe_node(node)}: {diffs}"

    def _check_label_writable(self, item: PlannedOp, label: str, *, edge: bool = False) -> None:
        what = "relações a partir de" if edge else "alterações em"
        if label in BLOCKED_LABELS:
            item.errors.append(f"{what} {label} não são feitas por aqui: {BLOCKED_LABELS[label]}.")
        if label in validation.FACT_LABELS:
            item.errors.append(f"{what} {label} (fato estrutural, ingestão determinística) não são editáveis.")

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
            item.errors.append("descobertas 'funciona'/'nao_funciona' dependem de veredito calculado: não criáveis.")
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
            {**props, "projeto_id": self.project_id, "sessao_id": EDIT_SESSION_ID}, _ACTOR
        )
        validation.validate_node_write(label, full, requires_agent_provenance=False)
        item.effective = props
        self.created_labels[item.index] = label
        self.created_props[item.index] = props
        item.warnings.extend(self._duplicate_warnings(label, props))
        if label == "Descoberta":
            item.warnings.append("descoberta sem evidência ligada: crie as relações BASEADA_EM e SOBRE.")
        shown = ", ".join(f"{_quote(k, 40)}={_shown(v)}" for k, v in props.items())
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
        if data["src"] == data["dst"]:
            item.errors.append("relação de um nó com ele mesmo (auto-laço) não é aceita.")
            return
        self._check_label_writable(item, src_label, edge=True)
        if item.errors:
            return
        props = dict(data["props"])
        forbidden = sorted(set(props) & EDGE_SYSTEM_PROPS)
        if forbidden:
            item.errors.append(
                f"propriedades de relação definidas pelo sistema não podem ser informadas: {', '.join(forbidden)}."
            )
            return
        full = prepare_edge_properties(props, _ACTOR)
        validation.validate_edge_write(src_label, rel, dst_label, full)
        if src_node is not None and dst_node is not None:
            sub = self.store.neighbors(src_node.id, [rel], "out", 1)
            if any(e.src_id == src_node.id and e.rel_type == rel and e.dst_id == dst_node.id for e in sub.edges):
                item.errors.append("a relação já existe.")
                return
        item.label = src_label
        item.effective = props  # tudo o que será gravado além dos campos fixos do sistema (afirmado/confirmada)
        item.node_id = src_node.id if src_node is not None else ""
        src_txt = _describe_node(src_node) if src_node else f"{sanitize_text(src_label, 40)} (referência {data['src']})"
        dst_txt = _describe_node(dst_node) if dst_node else f"{sanitize_text(dst_label, 40)} (referência {data['dst']})"
        extra = f" props={_shown(props)}" if props else ""
        item.description = (
            f"Criar relação: {src_txt} --{sanitize_text(rel, 40)}--> {dst_txt}{extra} "
            "[origem=afirmado, status=confirmada, evidencias=[]]"
        )

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
        self._check_label_writable(item, src_node.label, edge=True)
        if item.errors:
            return
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
            f"{_describe_node(dst_node)}: {_shown(item.before['status'], 40)} → {_shown(data['status'])}"
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
    shown = sum(len(i.description) + len(i.op.motivo) for i in items)
    if items and shown > config.GRAPH_EDIT_MAX_DISPLAY_CHARS:
        items[0].errors.append(
            f"proposta grande demais para ser exibida por inteiro ({shown} caracteres; máximo "
            f"{config.GRAPH_EDIT_MAX_DISPLAY_CHARS}): divida o pedido."
        )
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
    elif item.op.kind == "create_edge":
        data = item.op.data
        if _REF_RE.fullmatch(data["src"]) or _REF_RE.fullmatch(data["dst"]):
            return  # ponta criada na própria proposta: não existe ainda
        if store.get_node(data["src"]) is None or store.get_node(data["dst"]) is None:
            raise StaleProposalError(f"operação {item.index}: um dos nós da relação deixou de existir.")
        sub = store.neighbors(data["src"], [data["rel"]], "out", 1)
        if any(e.src_id == data["src"] and e.dst_id == data["dst"] and e.rel_type == data["rel"] for e in sub.edges):
            raise StaleProposalError(f"operação {item.index}: a relação já foi criada depois da proposta.")


@dataclass(frozen=True)
class HumanConfirmation:
    """Prova de que o pesquisador confirmou **esta** proposta, digitando a palavra exata, num terminal interativo.

    Só ``src/cli_graph.py`` a emite (guarda estática em ``test_hardening``); ``apply_plan`` a exige e confere que a
    impressão digital é a da proposta exibida.
    """

    fingerprint: str
    typed: str
    tty: bool

    def __post_init__(self) -> None:
        if self.tty is not True or self.typed != CONFIRM_WORD:
            raise PermissionError("confirmação humana inválida: exige terminal interativo e a palavra exata.")


def issue_confirmation(plan: Plan, typed: str | None, *, tty: bool) -> HumanConfirmation:
    """Emite a confirmação para ``plan`` (``PermissionError`` se não houve TTY ou a palavra exata)."""
    return HumanConfirmation(plan.fingerprint(), typed if typed is not None else "", bool(tty))


def _note(request: str, item: PlannedOp, adjustments: tuple[str, ...], **extra: Any) -> dict[str, Any]:
    note = {
        "origem": "graph edit",
        "pedido_original": sanitize_text(request, config.GRAPH_EDIT_MAX_REQUEST_CHARS),
        "operacao": item.op.kind,
        "motivo": item.op.motivo[:500],
        **extra,
    }
    if adjustments:
        note["ajustes_do_pesquisador"] = [sanitize_text(a, config.GRAPH_EDIT_MAX_REQUEST_CHARS) for a in adjustments]
    return note


def apply_plan(
    store: GraphStore,
    plan: Plan,
    *,
    request: str,
    confirmation: HumanConfirmation,
    adjustments: tuple[str, ...] = (),
) -> ApplyResult:
    """Aplica uma proposta **já validada, exibida e confirmada**, com ``Actor(pesquisador)`` e o pedido na auditoria.

    Exige a ``HumanConfirmation`` da **mesma** proposta exibida (impressão digital idêntica): o que é gravado é o que
    foi mostrado. Ordem: criações de nó, de relação e, por fim, mudanças de propriedade/status (as reversíveis por
    último). Antes de escrever, confere que o estado não mudou. Se uma escrita falha, as mudanças reversíveis já
    feitas são desfeitas (e as falhas de reversão são reportadas e auditadas); nós criados permanecem (nada é
    apagado) e são reportados em ``ApplyError``.

    Raises:
        PermissionError: Sem ``HumanConfirmation`` válida.
        ProposalError: A proposta tem erros ou difere da exibida.
        StaleProposalError: O grafo mudou depois da proposta (nada foi escrito).
        ApplyError: Falha durante a aplicação.
    """
    if not isinstance(confirmation, HumanConfirmation):
        raise PermissionError("apply_plan exige a confirmação humana da proposta.")
    if not plan.ok:
        raise ProposalError("proposta com erros: " + "; ".join(plan.errors))
    if confirmation.fingerprint != plan.fingerprint():
        raise ProposalError("a proposta a aplicar difere da que foi exibida e confirmada.")
    for item in plan.items:
        _check_unchanged(store, item)

    order = {"create_node": 0, "create_edge": 1, "update_node": 2, "set_edge_status": 2}
    queue = sorted(plan.items, key=lambda p: (order[p.op.kind], p.index))
    created: dict[int, str] = {}
    undo: list[tuple[str, Callable[[], None]]] = []
    applied = 0

    def resolve(ref: str) -> str:
        match = _REF_RE.fullmatch(ref)
        return created[int(match.group(1))] if match else ref

    def note(node_id: str, item: PlannedOp, **extra: Any) -> None:
        store.record_audit_note(node_id, _ACTOR, _note(request, item, adjustments, **extra))

    try:
        for item in queue:
            kind, data = item.op.kind, item.op.data
            if kind == "create_node":
                node_id = store.create_node(
                    item.label,
                    {**item.effective, "projeto_id": plan.project_id, "sessao_id": EDIT_SESSION_ID},
                    actor=_ACTOR,
                )
                created[item.index] = node_id
                note(node_id, item, criado=item.label)
            elif kind == "create_edge":
                src, dst = resolve(data["src"]), resolve(data["dst"])
                store.create_edge(src, data["rel"], dst, dict(item.effective), actor=_ACTOR)
                undo.append((
                    src,
                    lambda s=src, r=data["rel"], d=dst: store.set_edge_status(s, r, d, "contestada", actor=_ACTOR),
                ))
                note(src, item, aresta=f"{data['rel']}->{dst}")
            elif kind == "update_node":
                old = dict(item.before)
                changes = dict(item.effective)
                if item.decision:
                    changes["decidido_em"] = datetime.now(timezone.utc).isoformat()  # instante real da confirmação
                store.update_node(item.node_id, changes, actor=_ACTOR)
                undo.append((item.node_id, lambda i=item.node_id, o=old: store.update_node(i, o, actor=_ACTOR)))
                note(item.node_id, item, campos=sorted(changes))
            else:
                old_status = item.before["status"]
                store.set_edge_status(data["src"], data["rel"], data["dst"], data["status"], actor=_ACTOR)
                undo.append((
                    data["src"],
                    lambda s=data["src"], r=data["rel"], d=data["dst"], o=old_status: store.set_edge_status(
                        s, r, d, o, actor=_ACTOR
                    ),
                ))
                note(data["src"], item, aresta=f"{data['rel']}->{data['dst']}", status=data["status"])
            applied += 1
    except Exception as exc:  # noqa: BLE001 - qualquer falha reverte o que for reversível
        rolled, failed = 0, []
        for node_id, action in reversed(undo):
            try:
                action()
                rolled += 1
            except Exception as undo_exc:  # noqa: BLE001 - nunca engolida: reportada e auditada
                failed.append(f"{node_id} ({type(undo_exc).__name__})")
        trail = {
            "origem": "graph edit", "evento": "reversao", "causa": type(exc).__name__,
            "revertidas": rolled, "falhas_de_reversao": failed,
            "pedido_original": sanitize_text(request, config.GRAPH_EDIT_MAX_REQUEST_CHARS),
        }
        for node_id in {n for n, _ in undo} | set(created.values()):
            try:
                store.record_audit_note(node_id, _ACTOR, trail)
            except Exception:  # noqa: BLE001 - auditoria da reversão é best effort; o relatório informa
                failed.append(f"auditoria de {node_id}")
        message = (
            f"falha ao aplicar a operação {applied + 1} ({type(exc).__name__}: {sanitize_text(str(exc), 200)}); "
            f"{rolled} alteração(ões) revertida(s)"
        )
        if undo:
            message += "; relações criadas voltam como 'contestada' (nada é apagado)"
        if failed:
            message += f"; ATENÇÃO, a reversão FALHOU em: {', '.join(failed)}. Confira o grafo"
        raise ApplyError(
            message + ".", rolled_back=rolled, kept_created=list(created.values()), rollback_failures=failed
        ) from exc
    return ApplyResult(applied=applied, created_ids=created)


def render_plan(plan: Plan, explanation: str) -> str:
    """Texto da proposta (sanitizado): operações **íntegras**, avisos, erros e, por último, a explicação do modelo."""
    lines = ["PROPOSTA DO CURATOR (nada foi alterado ainda)", ""]
    if not plan.items:
        lines.append("O Curator não propôs nenhuma alteração.")
    for item in plan.items:
        mark = " [SENSÍVEL]" if item.sensitive else ""
        mark += " [DECISÃO RESERVADA: exige autorização adicional]" if item.decision else ""
        lines.append(f"{item.index}. {item.description or sanitize_text(item.op.kind, 30)}{mark}")
        if item.op.motivo:
            lines.append(f"   motivo: {_shown(item.op.motivo)}")
    if plan.warnings:
        lines += ["", "Avisos (você pode prosseguir mesmo assim):"] + [f"  - {w}" for w in plan.warnings]
    if plan.errors:
        lines += ["", "ERROS (a proposta não pode ser aplicada):"] + [f"  - {e}" for e in plan.errors]
    lines += [
        "",
        f"Sugestão do assistente (texto do modelo, NÃO verificado; vale o que está nas operações acima): "
        f"{sanitize_text(explanation, 1500)}",
        "",
        "Nada é apagado: pedidos de remoção viram mudança de status.",
        f"Impressão digital da proposta: {plan.fingerprint()[:16]} (é a do que será aplicado).",
    ]
    return "\n".join(lines)
