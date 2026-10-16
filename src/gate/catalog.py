"""Catálogo dos pedidos ao pesquisador: tipos, subtipos (``motivo``) e opções de resposta (design §1.1).

O catálogo é desta mudança; ``v18.7-exploration-limits`` produz ``decidir_continuidade`` e ``restringir_direcao`` com os
mesmos nomes, sem invólucro próprio. Uma resposta fora das opções gravadas no pedido é recusada.
"""

from __future__ import annotations

from dataclasses import dataclass

AUTORIZAR_NEGAR = ("autorizar", "negar")

#: Ações que valem como "negada" no estado do pedido; as demais respostas válidas são "autorizada" (a ação fica em
#: ``resposta.acao`` e quem consome decide o efeito).
ACOES_NEGATIVAS = frozenset({"negar", "rejeitar"})

CONTINUIDADE_MOTIVOS = (
    "estagnacao",
    "saturacao",
    "intervencoes_esgotadas",
    "cobertura_saturada",
    "varias_compativeis",
    "aguarda_experimento_fisico",
    "planos_rejeitados",
)


@dataclass(frozen=True)
class GateKind:
    """Um tipo de pedido: ações aceitas, subtipos aceitos (``None`` = qualquer) e se a resposta leva texto livre."""

    acoes: tuple[str, ...]
    motivos: tuple[str, ...] | None = None
    texto_livre: bool = False


GATE_CATALOG: dict[str, GateKind] = {
    "aprovar_oportunidade": GateKind(AUTORIZAR_NEGAR),
    "confirmar_problema": GateKind(AUTORIZAR_NEGAR),  # ``motivo="revisao_objetivo"`` para a revisão do objetivo
    "aprovar_termo_vocabulario": GateKind(AUTORIZAR_NEGAR),
    "autorizar_escrita_instrumento": GateKind(AUTORIZAR_NEGAR),
    "ativar_modo_sem_limite": GateKind(AUTORIZAR_NEGAR),
    "ativar_adendo_regimento": GateKind(AUTORIZAR_NEGAR),
    "aprovar_hipotese": GateKind(("aprovar", "rejeitar", "editar"), texto_livre=True),
    "decidir_objetivo_atingido": GateKind(("encerrar", "continuar")),
    "responder_pergunta_agente": GateKind(("responder",), texto_livre=True),
    "decidir_continuidade": GateKind(
        ("continuar", "orientar", "parar", "aceitar_conjunto", "objetivo_atingido"),
        CONTINUIDADE_MOTIVOS,
        texto_livre=True,
    ),
    "restringir_direcao": GateKind(("restringir", "liberar"), ("restricao_duvidosa",)),
}


def validate_request(decisao: str, motivo: str | None, opcoes: tuple[str, ...]) -> GateKind:
    """Confere o pedido contra o catálogo (decisão, subtipo e opções); devolve o tipo.

    Raises:
        ValueError: decisão desconhecida, subtipo fora da lista do tipo ou opção que o tipo não aceita.
    """
    kind = GATE_CATALOG.get(decisao)
    if kind is None:
        raise ValueError(f"decisão desconhecida: use um de {list(GATE_CATALOG)}.")
    if kind.motivos is not None and motivo is not None and motivo not in kind.motivos:
        raise ValueError(f"motivo '{motivo}' inválido para '{decisao}': use um de {list(kind.motivos)}.")
    if decisao in ("decidir_continuidade", "restringir_direcao") and motivo is None:
        raise ValueError(f"'{decisao}' exige o motivo (subtipo): use um de {list(kind.motivos or ())}.")
    invalid = [o for o in opcoes if o not in kind.acoes]
    if invalid:
        raise ValueError(f"opções {invalid} não existem para '{decisao}': use {list(kind.acoes)}.")
    return kind
