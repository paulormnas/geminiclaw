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
from src.agents.regimento.sessao import (
    TIPO_PADRAO,
    RegimentoSessao,
    com_regimento,
    encerrar_sessao,
    iniciar_sessao,
    sessao_atual,
)

__all__ = [
    "TIPO_PADRAO", "RegimentoSessao", "com_regimento", "encerrar_sessao", "iniciar_sessao", "sessao_atual",
    "REGIMENTO_DIR", "Recorte", "Regimento", "RegimentoError", "Secao", "cabecalho", "carregar_regimento", "recorte",
    "regras_seguranca", "secao",
]
