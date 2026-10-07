"""Gate de decisões reservadas ao pesquisador (``v17-curator-agent`` task 6.99; ADR 012 §8; ``researcher-consult``).

Aprovar uma Oportunidade, confirmar o Problema, aprovar um termo do vocabulário, autorizar escrita em instrumento e
ativar o modo sem limite (``DECISOES_RESERVADAS``) exigem **ação explícita do pesquisador**, no terminal ou na CLI. A
resposta de ``ask_researcher`` (inclusive a do Researcher consultor nos modos ``semi``/``auto``), a de um agente e o
texto de um documento **nunca contam como autorização**: um pedido respondido por qualquer fonte fora de
``HUMAN_SOURCES`` continua ``pendente``.

O gate não grava no grafo: ele só decide se a ação reservada **pode** seguir. Quem executa a ação (ex.:
``projects.confirm_problem`` ou ``vocabulary.approve_term``) o faz depois de ``authorized(...)``, com o ``Actor``
``pesquisador``; o ``GraphStore`` continua sendo a última barreira (``validate_human_only``).
"""

from __future__ import annotations

import itertools
import sys
import threading
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable

from src.logger import get_logger
from src.research_consult import DECISOES_RESERVADAS

logger = get_logger(__name__)

ESTADO_PENDENTE = "pendente"
ESTADO_AUTORIZADA = "autorizada"
ESTADO_NEGADA = "negada"



class Source(str, Enum):
    """Origem de uma resposta ao gate (enum fechado: texto livre nunca vale como origem humana)."""

    TERMINAL = "terminal"  # o pesquisador respondeu no terminal interativo (TTY)
    CLI = "cli"  # o pesquisador executou um comando da CLI (ex.: ``geminiclaw vocab approve``)
    ASK_RESEARCHER = "ask_researcher"
    RESEARCHER_CONSULT = "researcher_consult"
    AGENT = "agente"
    DOCUMENT = "documento"


# Únicas origens que valem como ação do pesquisador. ``ask_researcher``, o consultor, agentes e conteúdo de arquivos
# ficam de fora de propósito; uma string solta (mesmo "terminal") também não conta: só membros de ``Source``.
HUMAN_SOURCES: frozenset[Source] = frozenset({Source.TERMINAL, Source.CLI})

_MAX_REFERENCE_CHARS = 120


@dataclass(frozen=True)
class GateRequest:
    """Um pedido de decisão reservada.

    Attributes:
        id: Identificador sequencial do pedido.
        decisao: Um item de ``DECISOES_RESERVADAS``.
        referencia: Identificador curto do que se decide (ex.: nome da subtarefa ou ID de nó); nunca texto de pesquisa.
        estado: ``pendente``, ``autorizada`` ou ``negada``.
        resolvido_por: Origem humana que decidiu (``terminal``/``cli``), se houver.
        respostas_ignoradas: Quantas respostas de fontes não humanas foram recebidas e descartadas.
    """

    id: int
    decisao: str
    referencia: str
    estado: str = ESTADO_PENDENTE
    resolvido_por: str | None = None
    respostas_ignoradas: int = 0


class HumanGate:
    """Registro de pedidos de decisão reservada: só uma origem humana os resolve."""

    def __init__(self) -> None:
        self._requests: dict[int, GateRequest] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def request(self, decisao: str, referencia: str = "") -> GateRequest:
        """Registra um pedido pendente.

        Raises:
            ValueError: ``decisao`` fora de ``DECISOES_RESERVADAS`` (valor desconhecido também é reservado, mas o
                chamador deve classificá-lo antes de registrar).
        """
        if decisao not in DECISOES_RESERVADAS:
            raise ValueError(f"decisão desconhecida: use um de {list(DECISOES_RESERVADAS)}.")
        with self._lock:
            req = GateRequest(next(self._ids), decisao, str(referencia)[:_MAX_REFERENCE_CHARS])
            self._requests[req.id] = req
        logger.info("Decisão reservada ao pesquisador registrada", extra={"extra": {"decisao": decisao, "id": req.id}})
        return req

    def answer(self, request_id: int, *, source: Source, approved: bool) -> GateRequest:
        """Recebe uma resposta. Só ``HUMAN_SOURCES`` resolvem; outra fonte é ignorada e o pedido segue pendente.

        Args:
            request_id: Pedido.
            source: Origem da resposta (``terminal``/``cli`` para o pesquisador; ``ask_researcher``,
                ``researcher_consult``, ``agente``... não valem).
            approved: Autorizar (``True``) ou negar (``False``).

        Raises:
            KeyError: Pedido inexistente.
        """
        with self._lock:
            req = self._requests[request_id]
            if req.estado != ESTADO_PENDENTE:
                return req
            if not isinstance(source, Source) or source not in HUMAN_SOURCES:
                req = replace(req, respostas_ignoradas=req.respostas_ignoradas + 1)
                self._requests[request_id] = req
                logger.warning(
                    "Resposta de fonte não humana ignorada: a decisão continua pendente para o pesquisador",
                    extra={"extra": {"decisao": req.decisao, "origem": str(getattr(source, "value", source))[:40]}},
                )
                return req
            req = replace(req, estado=ESTADO_AUTORIZADA if approved else ESTADO_NEGADA, resolvido_por=source)
            self._requests[request_id] = req
            return req

    def authorized(self, request_id: int) -> bool:
        """``True`` somente se o pesquisador autorizou (pendente e negada falham fechado)."""
        req = self._requests.get(request_id)
        return req is not None and req.estado == ESTADO_AUTORIZADA

    def get(self, request_id: int) -> GateRequest | None:
        return self._requests.get(request_id)

    def pending(self) -> list[GateRequest]:
        """Pedidos ainda sem decisão do pesquisador."""
        return [r for r in self._requests.values() if r.estado == ESTADO_PENDENTE]

    def ask_in_terminal(
        self,
        request_id: int,
        *,
        input_fn: Callable[[str], str] = input,
        interactive: bool | None = None,
    ) -> GateRequest:
        """Pergunta ao pesquisador no terminal. Sem TTY o pedido continua pendente (nada é autorizado em silêncio).

        Args:
            request_id: Pedido pendente.
            input_fn: Leitura do terminal (injetável em testes).
            interactive: Força o estado interativo (testes); padrão: ``stdin`` e ``stdout`` são TTY.
        """
        req = self._requests[request_id]
        if interactive is None:
            try:
                interactive = bool(sys.stdin.isatty() and sys.stdout.isatty())
            except (AttributeError, ValueError):
                interactive = False
        if not interactive or req.estado != ESTADO_PENDENTE:
            return req
        try:
            reply = input_fn(f"Autoriza '{req.decisao}'? [s/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return req
        return self.answer(request_id, source=Source.TERMINAL, approved=reply in ("s", "sim", "y", "yes"))


_default_gate = HumanGate()


def default_gate() -> HumanGate:
    """Gate do processo, usado pelos pontos reais de decisão (confirmação do Problema, ``vocab approve``)."""
    return _default_gate


def authorize_from_cli(decisao: str, referencia: str = "", gate: HumanGate | None = None) -> bool:
    """Registra e autoriza uma decisão reservada executada pelo **pesquisador** na CLI.

    Só deve ser chamado de dentro de um comando de CLI disparado pelo pesquisador (nunca de código que processe
    resposta de agente ou de consultor). A barreira final continua sendo ``validate_human_only`` no ``GraphStore``.
    """
    gate = gate or default_gate()
    req = gate.request(decisao, referencia)
    gate.answer(req.id, source=Source.CLI, approved=True)
    return gate.authorized(req.id)
