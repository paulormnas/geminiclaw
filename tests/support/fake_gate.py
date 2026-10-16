"""``FakeGate``: gate persistente em memória para os testes da exploração (v18.7-hypothesis-linking, §2.4 do gate).

Implementa ``ApprovalPort`` (pedido ``aprovar_hipotese`` por item, idempotente; só devolve a decisão depois que o
terminal respondeu e a sessão a consumiu) e a API do ``PersistentGate``/``TerminalGate`` (``request``, ``pending``,
``answered_unconsumed``, ``consume_authorized``, ``was_authorized``, ``authorized_reference``, ``answer``...), com
respostas roteirizadas por id de pedido. O ``terminal_approver`` injetado serve para provar que NÃO é chamado quando o
gate está em uso.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from src.gate.catalog import ACOES_NEGATIVAS, GATE_CATALOG, validate_request
from src.gate.types import (
    GateAlreadyResolved,
    GateAuthorizationRefused,
    GateInvalidRequest,
    GatePendingLimitReached,
    Source,
)
from src.knowledge.hypothesis_cycle import ApprovalDecision, ApprovalItem

HUMAN_SOURCES = ("terminal", "cli")


@dataclass
class FakeRequest:
    id: int
    decisao: str
    referencia: str
    estado: str = "pendente"  # pendente | autorizada | negada
    resolvido_por: str | None = None
    consumido: bool = False
    pergunta: str = ""
    origem: str = ""
    enunciado_fonte: str = ""
    opcoes: tuple[str, ...] = ()
    motivo: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    resposta: dict[str, Any] | None = None
    obsoleto: bool = False
    respostas_ignoradas: int = 0


class FakeGate:
    """Gate em memória; ``terminal_approver`` (se dado) nunca é chamado."""

    def __init__(self, terminal_approver: Any = None, *, max_pending_per_session: int = 20) -> None:
        self.max_pending_per_session = max_pending_per_session
        self.requests: list[FakeRequest] = []
        self.terminal_approver = terminal_approver
        self.items_seen: list[ApprovalItem] = []

    # -- ApprovalPort -----------------------------------------------------------------------------

    def __call__(self, items: list[ApprovalItem]) -> dict[str, ApprovalDecision]:
        decisions: dict[str, ApprovalDecision] = {}
        for item in items:
            self.items_seen.append(item)
            request = self._request("aprovar_hipotese", item.id, origem=item.origem, fonte=item.enunciado_fonte)
            if request.resolvido_por not in HUMAN_SOURCES:  # ``consume_authorized`` recusa o que não é humano
                continue
            if request.estado == "autorizada" and not request.consumido:
                request.consumido = True
                decisions[item.id] = ApprovalDecision("aprovar")
            elif request.estado == "negada" and not request.consumido:
                request.consumido = True
                decisions[item.id] = ApprovalDecision("rejeitar", motivo="negada no terminal")
        return decisions

    def previously_approved(self, hypothesis_id: str, session_chain: Iterable[str]) -> bool:
        return any(
            r.decisao == "aprovar_hipotese" and r.referencia == hypothesis_id and r.estado == "autorizada"
            and r.resolvido_por in HUMAN_SOURCES
            for r in self.requests
        )

    # -- API do gate ------------------------------------------------------------------------------

    def _request(self, decisao: str, referencia: str, *, origem: str = "", fonte: str = "") -> FakeRequest:
        for request in self.requests:
            if request.decisao == decisao and request.referencia == referencia:
                return request
        request = FakeRequest(len(self.requests) + 1, decisao, referencia, origem=origem, enunciado_fonte=fonte)
        self.requests.append(request)
        return request

    def seed(self, decisao: str, referencia: str, *, estado: str, resolvido_por: str | None = "terminal") -> FakeRequest:
        """Pedido já resolvido (por quem diz ``resolvido_por``), como se o terminal o tivesse respondido antes."""
        request = self._request(decisao, referencia)
        request.estado, request.resolvido_por = estado, resolvido_por
        return request

    def answer(
        self,
        request_id: int,
        *,
        source: Any,
        estado: str | None = None,
        approved: bool | None = None,
        resposta: dict[str, Any] | None = None,
    ) -> FakeRequest:
        """Resposta do terminal ao pedido, com a interface do ``TerminalGate.answer`` (``approved`` ou ``resposta``) e,
        para semear estados nos testes, ``estado`` direto. Fonte não humana é ignorada (o pedido segue pendente)."""
        request = next(r for r in self.requests if r.id == request_id)
        if estado is not None:
            request.estado, request.resolvido_por = estado, getattr(source, "value", source)
            return request
        if not isinstance(source, Source):  # como o TerminalGate real: texto solto nunca vale como origem humana
            request.respostas_ignoradas += 1
            return request
        return self.respond(request_id, source=source.value, approved=approved, resposta=resposta)

    def resolve(self, decisao: str, referencia: str = "", *, source: Any, approved: bool, pergunta: str = "",
                session_id: str | None = None, project_id: str | None = None) -> FakeRequest:
        """Pede e resolve de uma vez (decisão tomada no próprio terminal); idempotente, como o ``TerminalGate``."""
        request = self.request(decisao, referencia, pergunta, session_id=session_id, project_id=project_id)
        if request.estado != "pendente":
            return request
        return self.answer(request.id, source=source, approved=approved)

    def pending(self, session_ids: Iterable[str] | None = None) -> list[FakeRequest]:
        ids = None if session_ids is None else set(session_ids)
        return [r for r in self.requests if r.estado == "pendente" and (ids is None or r.session_id in ids)]

    def for_reference(self, referencia: str) -> list[FakeRequest]:
        return [r for r in self.requests if r.referencia == referencia]

    # -- API do PersistentGate / TerminalGate -----------------------------------------------------

    def request(
        self,
        decisao: str,
        referencia: str = "",
        pergunta: str = "",
        opcoes: Iterable[str] = (),
        *,
        motivo: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> FakeRequest:
        """Cria o pedido (idempotente enquanto não consumido), validado contra o catálogo como o gate real."""
        options = tuple(opcoes)
        try:
            validate_request(decisao, motivo, options)
        except ValueError as exc:
            raise GateInvalidRequest(str(exc)) from None
        for request in self.requests:
            if (request.decisao, request.referencia, request.session_id or "") == (decisao, referencia, session_id or "") \
                    and not request.consumido and not request.obsoleto:
                return request
        if session_id is not None:
            pending = [r for r in self.requests if r.session_id == session_id and r.estado == "pendente" and not r.obsoleto]
            if len(pending) >= self.max_pending_per_session:
                raise GatePendingLimitReached("pedidos pendentes demais")
        request = FakeRequest(
            len(self.requests) + 1, decisao, referencia, pergunta=pergunta, opcoes=options, motivo=motivo,
            session_id=session_id, project_id=project_id,
        )
        self.requests.append(request)
        return request

    def get(self, request_id: int) -> FakeRequest | None:
        return next((r for r in self.requests if r.id == request_id), None)

    def respond(self, request_id: int, *, source: str = "terminal", approved: bool | None = None,
                resposta: dict[str, Any] | None = None) -> FakeRequest:
        """Resposta roteirizada do terminal, com as mesmas regras do ``TerminalGate.answer`` real."""
        request = self.get(request_id)
        if request is None:
            raise KeyError(request_id)
        if source not in HUMAN_SOURCES:
            request.respostas_ignoradas += 1
            return request
        if request.estado != "pendente":
            raise GateAlreadyResolved(f"o pedido {request_id} já foi resolvido.")
        if resposta is None:
            resposta = {"acao": "autorizar" if approved else "negar"}
        kind = GATE_CATALOG[request.decisao]
        acao = "responder" if request.decisao == "responder_pergunta_agente" else resposta.get("acao")
        if acao not in (request.opcoes or kind.acoes):
            raise GateInvalidRequest("resposta fora das opções do pedido")
        request.resposta = {**resposta, "acao": acao}
        request.estado = "negada" if acao in ACOES_NEGATIVAS else "autorizada"
        request.resolvido_por = source
        return request

    def pending_for(self, session_ids: Iterable[str] | None = None) -> list[FakeRequest]:
        ids = None if session_ids is None else set(session_ids)
        return [r for r in self.requests if r.estado == "pendente" and not r.obsoleto
                and (ids is None or r.session_id in ids)]

    def find_in_chain(self, decisao: str, referencia: str, session_chain: Iterable[str]) -> FakeRequest | None:
        chain = set(session_chain)
        found = [r for r in self.requests if r.decisao == decisao and r.referencia == referencia
                 and r.session_id in chain and not r.consumido and not r.obsoleto]
        return found[-1] if found else None

    def answered_unconsumed(self, session_ids: Iterable[str]) -> list[FakeRequest]:
        ids = set(session_ids)
        return [r for r in self.requests if r.estado != "pendente" and not r.consumido and not r.obsoleto
                and r.session_id in ids]

    def authorized(self, request_id: int) -> bool:
        request = self.get(request_id)
        return request is not None and request.estado == "autorizada" and request.resolvido_por in HUMAN_SOURCES

    def mark_consumed(self, request_id: int) -> bool:
        request = self.get(request_id)
        if request is None or request.consumido:
            return False
        request.consumido = True
        return True

    def mark_obsolete(self, request_id: int) -> bool:
        request = self.get(request_id)
        if request is None or request.obsoleto:
            return False
        request.obsoleto = True
        return True

    def consume_authorized(self, decisao: str, referencia: str, session_chain: Iterable[str]) -> FakeRequest:
        chain = list(session_chain)
        rows = [r for r in self.requests if r.decisao == decisao and r.referencia == referencia and not r.obsoleto]
        if not rows:
            raise GateAuthorizationRefused("nao_encontrada")
        valid = [r for r in rows if (r.session_id in chain if chain else r.session_id is None)]
        if not valid:
            raise GateAuthorizationRefused("outra_sessao")
        human = [r for r in valid if r.estado == "autorizada" and r.resolvido_por in HUMAN_SOURCES]
        usable = [r for r in human if not r.consumido]
        if not usable:
            raise GateAuthorizationRefused("ja_consumida" if human else "nao_autorizada")
        usable[-1].consumido = True
        return usable[-1]

    def was_authorized(self, decisao: str, referencia: str, session_chain: Iterable[str]) -> bool:
        chain = set(session_chain)
        return any(
            r.decisao == decisao and r.referencia == referencia and r.estado == "autorizada"
            and r.resolvido_por in HUMAN_SOURCES and r.session_id in chain
            for r in self.requests
        )

    def authorized_reference(self, decisao: str, referencia: str) -> bool:
        if decisao != "ativar_adendo_regimento":
            raise GateInvalidRequest("leitura sem consumo só existe para 'ativar_adendo_regimento'.")
        return any(
            r.decisao == decisao and r.referencia == referencia and r.estado == "autorizada"
            and r.resolvido_por in HUMAN_SOURCES
            for r in self.requests
        )
