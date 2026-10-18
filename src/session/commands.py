"""Comandos de ação do pesquisador à sessão (v18.7-session-events-terminal, design §1.5).

O terminal grava o comando na caixa de entrada (``tipo='comando'``) como JSON validado; o processo da sessão o lê a
cada ``SESSION_INBOX_POLL_SECONDS``, aplica e registra o evento ``comando_recebido``. Comando desconhecido ou
malformado é consumido e registrado como ignorado, nunca executado. ``cancelar`` e ``replanejar`` não são decisões
reservadas e não passam pelo gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

COMANDOS = ("pausar", "parar", "cancelar", "replanejar")
MOTIVO_CANCELADA = "cancelada_pesquisador"  # motivo de retirada de subtarefa (não é motivo de parada de sessão)
_NOME_MAX = 128


@dataclass(frozen=True)
class Comando:
    """Comando validado."""

    comando: str
    subtarefa: str | None = None


def codifica(comando: str, subtarefa: str | None = None) -> str:
    """JSON do comando para a caixa de entrada.

    Raises:
        ValueError: comando fora da lista, ou ``cancelar`` sem subtarefa.
    """
    if comando not in COMANDOS:
        raise ValueError(f"comando desconhecido: {comando!r}")
    if comando == "cancelar" and not subtarefa:
        raise ValueError("cancelar exige o nome da subtarefa")
    corpo: dict[str, Any] = {"comando": comando}
    if subtarefa:
        corpo["subtarefa"] = subtarefa
    return json.dumps(corpo, ensure_ascii=False)


def decodifica(conteudo: str) -> Comando | None:
    """Comando do JSON da caixa; ``None`` se for inválido ou desconhecido (a sessão o ignora e registra)."""
    try:
        bruto = json.loads(conteudo)
    except (TypeError, ValueError):
        return None
    if not isinstance(bruto, dict) or bruto.get("comando") not in COMANDOS:
        return None
    sub = bruto.get("subtarefa")
    if bruto["comando"] == "cancelar":
        if not isinstance(sub, str) or not sub.strip() or len(sub) > _NOME_MAX:
            return None
        return Comando("cancelar", sub.strip())
    return Comando(bruto["comando"])
