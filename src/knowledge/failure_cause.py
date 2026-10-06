"""Classificação determinística da causa de falha de um experimento (ADR 015 §9.3).

A causa (``infraestrutura``, ``abordagem`` ou ``ambigua``) e a assinatura da falha saem de dados
**estruturados** da execução (saída do sandbox gravada no ``manifest.json``, categoria do erro do
agente e presença de ``metrics.json``), nunca de heurística sobre mensagens. Nenhum LLM é usado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

CAUSA_INFRA = "infraestrutura"
CAUSA_ABORDAGEM = "abordagem"
CAUSA_AMBIGUA = "ambigua"

SIG_OOM = "oom"
SIG_TIMEOUT = "timeout_execucao"
SIG_SEM_METRICAS = "sem_metricas"
SIG_VALIDACAO_INDETERMINADA = "validacao_indeterminada"
SIG_CRITERIO_NAO_ATENDIDO = "criterio_nao_atendido"
SIG_FALHA_SEM_EXCECAO = "falha_execucao_sem_excecao"
SIG_INSTALACAO_PACOTES = "instalacao_pacotes"

OOM_EXIT_CODE = 137
_SIGNATURE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")


@dataclass(frozen=True)
class FailureCause:
    """Causa e assinatura de uma falha (valores do schema ``Experimento``)."""

    causa: str
    assinatura: str


def _signature(value: object, fallback: str) -> str:
    """Aceita só identificadores curtos (o valor pode vir de texto do sandbox); senão usa ``fallback``."""
    return value if isinstance(value, str) and _SIGNATURE_RE.fullmatch(value) else fallback


def classify_failure(
    *,
    agent_error_category: str | None,
    last_run: dict[str, Any] | None,
    metrics_status: str,
    review_status: str | None,
) -> FailureCause:
    """Classifica a falha de um experimento.

    Ordem de precedência (design §3): infraestrutura, falhas do código no sandbox (``oom``,
    ``timeout_execucao``, tipo da exceção), ausência ou ilegibilidade de ``metrics.json`` e,
    por fim, critério não atendido com métricas válidas.

    Args:
        agent_error_category: Categoria estruturada do erro do agente (ex.: ``llm_connection``).
        last_run: Saída estruturada do último passo no sandbox (``exit_code``, ``oom_killed``,
            ``exception_type``, ``timed_out``, ``infra_error``, ``install_failed``), ou ``None``.
        metrics_status: ``"ausente"``, ``"ok"`` ou ``"invalido"``.
        review_status: Parecer do Validator (``pass``, ``fail``, ``divergent_but_documented``) ou ``None``.

    Returns:
        ``FailureCause``.
    """
    if agent_error_category:
        return FailureCause(CAUSA_INFRA, _signature(agent_error_category, "infraestrutura_desconhecida"))

    run = last_run or {}
    if run.get("infra_error"):
        return FailureCause(CAUSA_INFRA, _signature(run["infra_error"], "infraestrutura_desconhecida"))
    if run.get("oom_killed") or run.get("exit_code") == OOM_EXIT_CODE:
        return FailureCause(CAUSA_ABORDAGEM, SIG_OOM)
    if run.get("timed_out"):
        return FailureCause(CAUSA_ABORDAGEM, SIG_TIMEOUT)
    exception_type = run.get("exception_type")
    if isinstance(exception_type, str) and _SIGNATURE_RE.fullmatch(exception_type):
        return FailureCause(CAUSA_ABORDAGEM, exception_type)

    if metrics_status == "ausente":
        return FailureCause(CAUSA_AMBIGUA, SIG_SEM_METRICAS)
    if metrics_status == "invalido":
        return FailureCause(CAUSA_AMBIGUA, SIG_VALIDACAO_INDETERMINADA)
    if run.get("install_failed"):
        return FailureCause(CAUSA_AMBIGUA, SIG_INSTALACAO_PACOTES)
    if review_status == "fail":
        return FailureCause(CAUSA_AMBIGUA, SIG_CRITERIO_NAO_ATENDIDO)
    return FailureCause(CAUSA_AMBIGUA, SIG_FALHA_SEM_EXCECAO)
