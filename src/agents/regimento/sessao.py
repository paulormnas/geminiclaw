"""Regimento da sessão: carregado uma vez e injetado no ``system`` de toda chamada de papel (ADR 022 §4.3-§4.4).

A sessão do laço autônomo chama ``iniciar_sessao`` e passa a ter um ``RegimentoSessao`` vinculado ao contexto da
tarefa assíncrona. Quem monta o ``system`` de um papel chama ``com_regimento(prompt)``, que acrescenta o cabeçalho e o
recorte da combinação de tipo de objetivo e modo vigente; fora de uma sessão (nenhum regimento vinculado) devolve o
prompt como está. O arquivo é lido uma única vez: mudanças em disco só valem na sessão seguinte.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agents.regimento.carga import REGIMENTO_DIR, Recorte, Regimento, cabecalho, carregar_regimento, recorte
from src.logger import get_logger

logger = get_logger(__name__)

TIPO_PADRAO = "limiar"  # ``Problema`` sem tipo (dados antigos) segue o comportamento anterior


@dataclass
class RegimentoSessao:
    """Regimento carregado numa sessão, com o recorte da combinação vigente.

    Args:
        regimento: Regimento lido no início da sessão.
        modo: Modo da sessão (``assisted``, ``semi`` ou ``auto``).
        tipo_objetivo: Tipo do objetivo do ``Problema`` ativo; ``None`` sem projeto ou sem ``Problema``.
        on_recorte: Chamado com cada recorte novo calculado (registro do ``recorte_sha256``).
    """

    regimento: Regimento
    modo: str
    tipo_objetivo: str | None = None
    on_recorte: Callable[[Recorte], None] | None = None
    _recortes: dict[tuple[str | None, str], Recorte] = field(default_factory=dict)

    def definir_objetivo(self, tipo: str | None) -> None:
        """Atualiza o tipo de objetivo vigente (``Problema`` confirmado ou revisto)."""
        self.tipo_objetivo = tipo

    def recorte_atual(self) -> Recorte:
        """Recorte da combinação vigente, calculado uma vez por combinação."""
        chave = (self.tipo_objetivo, self.modo)
        achado = self._recortes.get(chave)
        if achado is None:
            achado = recorte(self.regimento, self.tipo_objetivo, self.modo)
            self._recortes[chave] = achado
            if self.on_recorte is not None:
                try:
                    self.on_recorte(achado)
                except Exception:  # noqa: BLE001 - o registro nunca interrompe a chamada do agente
                    logger.warning("Falha ao registrar o recorte do regimento", exc_info=True)
        return achado

    def system(self, prompt: str) -> str:
        """Prompt do papel, linha em branco, cabeçalho e recorte."""
        rec = self.recorte_atual()
        return f"{prompt}\n\n{cabecalho(self.regimento, rec)}\n{rec.texto}"


_atual: contextvars.ContextVar[RegimentoSessao | None] = contextvars.ContextVar("regimento_sessao", default=None)


def iniciar_sessao(
    modo: str,
    tipo_objetivo: str | None = None,
    *,
    base: Path = REGIMENTO_DIR,
    on_recorte: Callable[[Recorte], None] | None = None,
) -> tuple[RegimentoSessao, contextvars.Token[Any]]:
    """Carrega o regimento e o vincula ao contexto atual; devolve a sessão e o token para ``encerrar_sessao``."""
    sessao = RegimentoSessao(carregar_regimento(base), modo, tipo_objetivo, on_recorte)
    return sessao, _atual.set(sessao)


def encerrar_sessao(token: contextvars.Token[Any]) -> None:
    """Desvincula o regimento da sessão."""
    _atual.reset(token)


def sessao_atual() -> RegimentoSessao | None:
    """Regimento da sessão vinculado ao contexto atual, ou ``None`` fora de uma sessão."""
    return _atual.get()


def com_regimento(prompt: str) -> str:
    """``system`` de uma chamada de papel: o prompt seguido do recorte; sem sessão, o prompt como está."""
    sessao = _atual.get()
    return prompt if sessao is None else sessao.system(prompt)
