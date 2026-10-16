"""Tipos do gate de decisões reservadas: estados, origens humanas e o pedido (``v18.7-persistent-human-gate`` 0.9).

Movidos de ``src/gate/human_gate.py`` sem alterar o comportamento (ADR 024 §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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

MAX_REFERENCE_CHARS = 120


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
    # Gate persistente (v18.7-persistent-human-gate): o que o terminal exibe e o que a sessão consome.
    pergunta: str = ""
    opcoes: tuple[str, ...] = ()
    motivo: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    resposta: dict[str, Any] | None = field(default=None, compare=False)
    consumido: bool = False
    obsoleto: bool = False
    criado_em: str | None = None
    resolvido_em: str | None = None


class GateError(Exception):
    """Erro do gate persistente (mensagem acionável, sem eco de conteúdo de pesquisa)."""


class GateAlreadyResolved(GateError):
    """O pedido já foi resolvido (a transição condicional não encontrou ``pendente``)."""


class GatePendingLimitReached(GateError):
    """A sessão já tem ``GATE_MAX_PENDING_PER_SESSION`` pedidos pendentes; o excesso vira evento, sem novo pedido."""


class GateInvalidRequest(GateError):
    """Pedido ou resposta fora do catálogo (decisão, motivo, opção ou texto)."""


class GateAuthorizationRefused(GateError):
    """A autorização não vale para este uso.

    Attributes:
        motivo: ``nao_encontrada``, ``outra_sessao``, ``ja_consumida`` ou ``nao_autorizada``.
    """

    def __init__(self, motivo: str, message: str = "") -> None:
        super().__init__(message or f"autorização recusada ({motivo})")
        self.motivo = motivo
