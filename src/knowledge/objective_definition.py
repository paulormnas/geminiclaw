"""Objetivo proposto no plano (v18.7-exploration-limits, design §4.3).

No modo ``auto`` o Researcher propõe a chave ``objetivo`` quando o ``Problema`` não tem objetivo válido; no
``assisted`` e no ``semi`` uma revisão proposta vira pedido ao pesquisador. Este módulo só **lê e confere** a
declaração (dado não confiável); a gravação no grafo é da exploração, depois da aprovação do Validator.

Formato: ``{"tipo": "discriminacao", "hipoteses_concorrentes": [{"ref": "h1", "predicao": "..."}, ...],
"justificativa": "..."}``. No ``limiar``, métrica, alvo e ``delta_min`` vêm da chave ``metricas`` (V18.6). Qualquer
``ao_atingir_objetivo`` do plano é ignorado: a política é do pesquisador.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.knowledge import schema

MAX_RIVALS = 10
MAX_JUSTIFICATION = 600
FRONTEIRA_RECUSADA = "tipo `fronteira` ainda não suportado; será especificado com a V19 (equipamentos)"
_REF_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class RivalDecl:
    """Concorrente do plano: ``ref`` de uma hipótese declarada em ``hipoteses`` e a sua predição."""

    ref: str
    predicao: str


@dataclass(frozen=True)
class ObjectiveDecl:
    """``objetivo`` declarado no plano.

    Attributes:
        tipo: Texto do plano (a validade é conferida em :func:`objective_issues`, para a mensagem ser acionável).
        concorrentes: Hipóteses concorrentes (``discriminacao``).
        justificativa: Por que este objetivo serve ao problema.
        politica_ignorada: O plano trouxe ``ao_atingir_objetivo``, que nunca é aplicado.
    """

    tipo: str
    concorrentes: tuple[RivalDecl, ...] = ()
    justificativa: str = ""
    politica_ignorada: bool = False
    erros: tuple[str, ...] = field(default=(), compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "hipoteses_concorrentes": [{"ref": c.ref, "predicao": c.predicao} for c in self.concorrentes],
            "justificativa": self.justificativa,
        }


def _clean(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def parse_objective(raw: Any) -> ObjectiveDecl | None:
    """``objetivo`` do plano, ou ``None`` se a chave não veio ou não é um objeto (dado do LLM: nunca levanta)."""
    if not isinstance(raw, dict):
        return None
    errors: list[str] = []
    rivals: list[RivalDecl] = []
    items = raw.get("hipoteses_concorrentes")
    for item in items[:MAX_RIVALS] if isinstance(items, list) else []:
        ref = item.get("ref") if isinstance(item, dict) else None
        if not isinstance(ref, str) or not _REF_RE.match(ref):
            errors.append("cada item de 'hipoteses_concorrentes' exige 'ref' (referência de uma hipótese do plano)")
            continue
        rivals.append(RivalDecl(ref, _clean(item.get("predicao"), config.HYPOTHESIS_TEXT_MAX_CHARS)))
    return ObjectiveDecl(
        tipo=_clean(raw.get("tipo"), 32).lower(),
        concorrentes=tuple(rivals),
        justificativa=_clean(raw.get("justificativa"), MAX_JUSTIFICATION),
        politica_ignorada="ao_atingir_objetivo" in raw,
        erros=tuple(errors),
    )


def objective_issues(
    decl: ObjectiveDecl | None, *, declared_refs: set[str], criterion: dict[str, Any] | None, metrics: list[Any]
) -> list[str]:
    """Reprovações determinísticas do objetivo proposto (sem chamada ao LLM); vazio = estrutura válida.

    Args:
        decl: Objetivo do plano, ou ``None`` se a chave faltou.
        declared_refs: ``ref`` das hipóteses declaradas no plano.
        criterion: ``criterio_sucesso`` atual do ``Problema`` (métrica e ``delta_min`` já definidos, se houver).
        metrics: ``MetricDecl`` do plano (``metricas``).
    """
    if decl is None:
        return [
            "Objetivo ausente: o Problema não tem objetivo válido e, no modo auto, o plano DEVE trazer a chave "
            "'objetivo' com 'tipo' (limiar, discriminacao ou cobertura)."
        ]
    if decl.tipo == "fronteira":
        return [FRONTEIRA_RECUSADA]
    if decl.tipo not in schema.TIPOS_OBJETIVO:
        return [f"Objetivo: 'tipo' deve ser um de: {', '.join(t for t in schema.TIPOS_OBJETIVO if t != 'fronteira')}."]
    issues = list(decl.erros)
    if decl.tipo == "discriminacao":
        refs = [c.ref for c in decl.concorrentes]
        if len(refs) < 2 or len(set(refs)) != len(refs):
            issues.append("Objetivo de discriminação exige ao menos duas hipóteses concorrentes distintas.")
        issues.extend(
            f"Objetivo: a concorrente '{c.ref}' não está declarada em 'hipoteses' do plano."
            for c in decl.concorrentes if c.ref not in declared_refs
        )
        issues.extend(
            f"Objetivo: a concorrente '{c.ref}' exige 'predicao'." for c in decl.concorrentes if not c.predicao
        )
    elif decl.concorrentes:
        issues.append(f"Objetivo do tipo '{decl.tipo}' não leva 'hipoteses_concorrentes'.")
    if decl.tipo == "limiar":
        current = criterion or {}
        has_metric = bool(current.get("metrica_id") or current.get("metrica")) or bool(metrics)
        delta = current.get("delta_min") or (getattr(metrics[0], "delta_min", None) if metrics else None)
        if not has_metric:
            issues.append("Objetivo de limiar exige a métrica principal definida em 'metricas'.")
        elif not delta:
            issues.append("Objetivo de limiar exige 'delta_min' (na primeira métrica de 'metricas').")
    return issues
