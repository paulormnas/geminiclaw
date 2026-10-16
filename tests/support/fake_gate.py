"""``FakeGate``: gate persistente em memória para os testes da exploração (v18.7-hypothesis-linking, §2.4 do gate).

Implementa ``ApprovalPort`` (pedido ``aprovar_hipotese`` por item, idempotente; só devolve a decisão depois que o
terminal respondeu e a sessão a consumiu) e o recorte da API do ``PersistentGate`` que o laço de hipóteses usa. O
``terminal_approver`` injetado serve para provar que NÃO é chamado quando o gate está em uso. ``v18.7-persistent-human-gate``
estende este módulo com o resto da API do gate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

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


class FakeGate:
    """Gate em memória; ``terminal_approver`` (se dado) nunca é chamado."""

    def __init__(self, terminal_approver: Any = None) -> None:
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

    def answer(self, request_id: int, *, source: str, estado: str) -> FakeRequest:
        """Resposta do terminal ao pedido (só o papel do terminal responde)."""
        request = next(r for r in self.requests if r.id == request_id)
        request.estado, request.resolvido_por = estado, source
        return request

    def pending(self) -> list[FakeRequest]:
        return [r for r in self.requests if r.estado == "pendente"]

    def for_reference(self, referencia: str) -> list[FakeRequest]:
        return [r for r in self.requests if r.referencia == referencia]
