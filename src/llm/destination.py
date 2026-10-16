"""Destino de um envio ao modelo ou a um serviço externo (``Destination``).

Movido de ``src/egress/gate.py`` sem alterar o corpo, para que a camada de LLM (``vision``) não dependa do
filtro de egresso (ADR 024 §4, ``v18.7-layer-cycles``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Canal = Literal["llm", "visao", "busca", "leitura_web"]


@dataclass(frozen=True)
class Destination:
    """Destino de um envio (design §2)."""

    canal: Canal
    provedor: str
    modelo: str | None
    trust: str | None
    localidade: str  # "no_no" | "fora_do_no" (busca e leitura web: fora_do_no)
    aceita_dados_brutos: bool  # busca e leitura web: False
    papel: str | None
    versao_efetiva: str | None = None
