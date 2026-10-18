"""Regimento da pesquisa: texto comum a todos os agentes (v18.7-agent-system-prompts, ADR 022 §4)."""

from src.agents.regimento.carga import (
    REGIMENTO_DIR,
    Recorte,
    Regimento,
    RegimentoError,
    Secao,
    cabecalho,
    carregar_regimento,
    recorte,
    regras_seguranca,
    secao,
)

__all__ = [
    "REGIMENTO_DIR", "Recorte", "Regimento", "RegimentoError", "Secao", "cabecalho", "carregar_regimento", "recorte",
    "regras_seguranca", "secao",
]
