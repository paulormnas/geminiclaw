"""Avaliação de critérios de métrica contra ``metrics.json`` (núcleo do Validator).

Definições movidas do Validator sem alterar o corpo, para que a ingestão de fatos
(``src/knowledge/ingestion.py``) não dependa do pacote de agentes (ADR 024 §2, ``v18.7-source-layout``).
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src import config
from src.artifacts.metrics_file import metric_candidates
from src.utils.normalization import (
    criterion_qualifier,
    normalize_metric_name,
    normalized_words,
    split_metric_name,
)

# Roadmap V15.2 / Spec G2 — parsing de critérios quantitativos contra metrics.json real.
_METRIC_ALIASES = {
    "acuracia": "accuracy",
    "accuracy": "accuracy",
    "precisao": "precision",
    "precision": "precision",
    "recall": "recall",
    "revocacao": "recall",
    "sensibilidade": "recall",
    "f1": "f1",
    "f1score": "f1",
    "erro": "error",
    "error": "error",
    "mse": "mse",
    "rmse": "rmse",
    "mae": "mae",
    "r2": "r2",
    "auc": "auc",
    "loss": "loss",
    "perda": "loss",
}

_CRITERION_VALUE_PATTERN = re.compile(r"([^<>=]+?)\s*(>=|<=|==|>|<)\s*(\d+(?:[.,]\d+)?)\s*%?")


_normalize_metric_name = normalize_metric_name


def _metric_key(raw_name: str) -> Optional[str]:
    """Mapeia o nome citado em um critério a uma métrica conhecida, ou ``None``.

    Tenta o nome inteiro e depois cada palavra ("acurácia no teste" -> ``accuracy``).
    """
    whole = _normalize_metric_name(raw_name)
    if whole in _METRIC_ALIASES:
        return _METRIC_ALIASES[whole]
    for word in re.split(r"\s+", raw_name.strip()):
        key = _normalize_metric_name(word)
        if key in _METRIC_ALIASES:
            return _METRIC_ALIASES[key]
        if "." in word:  # chave qualificada citada (``modelo_b.acuracia``): vale a métrica depois do ponto
            tail = _normalize_metric_name(word.rsplit(".", 1)[-1])
            if tail in _METRIC_ALIASES:
                return _METRIC_ALIASES[tail]
    return None


@dataclass(frozen=True)
class Comparison:
    """Uma comparação ``<nome> <operador> <valor>`` de um critério; ``metric`` é ``None`` se o nome é desconhecido."""

    raw_name: str
    metric: Optional[str]
    operator: str
    threshold: float


@dataclass(frozen=True)
class MetricCriterion:
    """Critério de aceite cujas comparações citam todas uma métrica conhecida."""

    text: str
    comparisons: Tuple[Comparison, ...]

    @property
    def metric(self) -> str:
        """Métrica da primeira comparação (compatibilidade com consumidores de critério simples)."""
        return str(self.comparisons[0].metric)

    @property
    def operator(self) -> str:
        return self.comparisons[0].operator

    @property
    def threshold(self) -> float:
        return self.comparisons[0].threshold


def _comparisons(criterion: str) -> List[Comparison]:
    """Todas as comparações do critério (``finditer``), cada uma com a métrica conhecida ou ``None``."""
    return [
        Comparison(raw_name.strip(), _metric_key(raw_name), operator, float(raw_value.replace(",", ".")))
        for raw_name, operator, raw_value in _CRITERION_VALUE_PATTERN.findall(criterion)
    ]


def criterion_comparisons(criterion: str) -> List[Comparison]:
    """Comparações ``<nome> <operador> <valor>`` de um critério (públicas para o contrato da subtarefa)."""
    return _comparisons(criterion)


def _metric_criteria(criteria: List[Any]) -> List[MetricCriterion]:
    """Seleciona os critérios cujas comparações citam todas uma métrica conhecida.

    Critério de contagem, qualitativo ou com alguma comparação sem métrica conhecida não entra: segue para o
    revisor LLM (``v16-pipeline-robustness`` §3, ``v18.6-review-evidence`` §3.1).
    """
    found: List[MetricCriterion] = []
    for criterion in criteria or []:
        if not isinstance(criterion, str):
            continue
        comparisons = _comparisons(criterion)
        if comparisons and all(c.metric is not None for c in comparisons):
            found.append(MetricCriterion(criterion.strip(), tuple(comparisons)))
    return found


_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


def _compare(crit_text: str, cmp: Comparison, key: str, actual: float) -> Tuple[bool, str]:
    passed = _OPERATORS[cmp.operator](actual, cmp.threshold)
    return passed, (
        f"Critério '{crit_text}' avaliado contra metrics.json: '{key}' valor real = {actual}, "
        f"threshold {cmp.operator} {cmp.threshold} -> {'atendido' if passed else 'não atendido'}."
    )


def _group_named(group: str, criterion_text: str) -> bool:
    """O nome do grupo (``random_forest``) aparece no critério: todas as suas palavras, normalizadas."""
    group_words = set(normalized_words(group))
    return bool(group_words) and group_words <= set(normalized_words(criterion_text))


def _evaluate_comparison(
    crit: MetricCriterion, cmp: Comparison, metrics: Dict[str, Any], *, contract_keys: bool = False
) -> Tuple[Optional[bool], str]:
    """Avalia uma comparação: ``True``/``False`` ou ``None`` (indecidida: vai ao revisor LLM)."""
    ok, detail, _ = _evaluate_comparison_found(crit, cmp, metrics, contract_keys=contract_keys)
    return ok, detail


def _key_norm(key: str) -> str:
    return ".".join(_normalize_metric_name(part) for part in str(key).split("."))


def _select_candidates(
    crit: MetricCriterion, cmp: Comparison, metrics: Dict[str, Any], contract_keys: bool
) -> Tuple[str, List[Tuple[str, float]]]:
    """Chave de ``metrics.json`` que o critério avalia: ``(estado, candidatas)``.

    Estados: ``missing`` (nenhuma chave), ``cited_missing`` (o critério cita a chave qualificada e ela não existe),
    ``found`` (uma chave decidida em ``candidatas[0]``) e ``ambiguous`` (várias chaves qualificadas, sem chave sem
    qualificador, sem chave citada e sem grupo nomeado). Com ``contract_keys`` vale a tabela do ADR 022 §2.7: a
    chave sem qualificador, a citada pelo critério ou a única qualificada; o revisor nunca escolhe entre grupos.
    """
    qualifier = criterion_qualifier(cmp.raw_name)
    allowed = {qualifier} if qualifier not in ("", "teste") else {"teste", ""}
    candidates = metric_candidates(metrics, str(cmp.metric), allowed, _METRIC_ALIASES)
    cited = cmp.raw_name.strip() if contract_keys and "." in cmp.raw_name.strip() else ""
    if cited:
        match = [c for c in candidates if _key_norm(c[0]) == _key_norm(cited)]
        return ("found", match[:1]) if match else ("cited_missing", [])
    if not candidates:
        return "missing", []
    if contract_keys:
        plain = [c for c in candidates if "." not in c[0]]
        if plain:
            return "found", plain[:1]
    if len(candidates) > 1:
        named = [c for c in candidates if "." in c[0] and _group_named(c[0].rsplit(".", 1)[0], crit.text)]
        if len(named) != 1:
            return "ambiguous", candidates
        candidates = named
    return "found", candidates[:1]


def criterion_ambiguities(
    criteria: List[MetricCriterion], metrics: Dict[str, Any]
) -> List[Tuple[MetricCriterion, List[str]]]:
    """Critérios cuja métrica só existe em dois ou mais grupos qualificados (``criterio_ambiguo``, ADR 022 §2.7).

    Cada item traz o critério e as chaves candidatas. O Validator nunca escolhe entre elas.
    """
    found: List[Tuple[MetricCriterion, List[str]]] = []
    for crit in criteria:
        keys: List[str] = []
        for cmp in crit.comparisons:
            state, candidates = _select_candidates(crit, cmp, metrics, True)
            if state == "ambiguous":
                keys += [k for k, _ in candidates if k not in keys]
        if keys:
            found.append((crit, keys))
    return found


def _evaluate_comparison_found(
    crit: MetricCriterion, cmp: Comparison, metrics: Dict[str, Any], *, contract_keys: bool = False
) -> Tuple[Optional[bool], str, Optional[Tuple[str, float]]]:
    """Como ``_evaluate_comparison``, com ``(chave, valor)`` quando houve comparação numérica de fato.

    O terceiro item é ``None`` para métrica ausente, valor não numérico e comparação indecidida: só a comparação
    numérica reprovada pode virar resultado negativo (``v18.6-hypothesis-closure`` §1).
    """
    existing = sorted(str(k) for k in (metrics or {}))
    missing = (
        False,
        f"Critério '{crit.text}': a métrica '{cmp.metric}' não está em metrics.json (chaves existentes: {existing}).",
        None,
    )
    if not config.REVIEW_METRIC_QUALIFIERS:  # comportamento anterior: nome inteiro normalizado
        normalized: Dict[str, Any] = {}
        for key, value in (metrics or {}).items():
            norm = _normalize_metric_name(str(key))
            normalized[_METRIC_ALIASES.get(norm, norm)] = value
        if cmp.metric not in normalized:
            return missing
        try:
            actual_norm = float(normalized[cmp.metric])
        except (TypeError, ValueError):
            return False, f"Critério '{crit.text}': valor de '{cmp.metric}' em metrics.json não é numérico.", None
        passed, detail = _compare(crit.text, cmp, str(cmp.metric), actual_norm)
        return passed, detail, (str(cmp.metric), actual_norm)
    state, candidates = _select_candidates(crit, cmp, metrics, contract_keys)
    if state == "missing":
        return missing
    if state == "cited_missing":
        return (
            False,
            f"Critério '{crit.text}': a chave '{cmp.raw_name.strip()}' citada pelo critério não está em "
            f"metrics.json (chaves existentes: {existing}).",
            None,
        )
    if state == "ambiguous":
        return None, (
            f"Critério '{crit.text}': a métrica '{cmp.metric}' aparece em mais de um grupo "
            f"({[k for k, _ in candidates]}) e o critério não nomeia o grupo."
        ), None
    key, actual = candidates[0]
    passed, detail = _compare(crit.text, cmp, key, actual)
    return passed, detail, (key, float(actual))


def _evaluate_metric_criteria(
    criteria: List[MetricCriterion], metrics: Dict[str, Any], *, contract_keys: bool = False
) -> List[Tuple[Optional[bool], str]]:
    """Avalia cada critério (todas as comparações) contra os valores reais de ``metrics.json``.

    Devolve ``(True, ...)`` atendido, ``(False, ...)`` reprovado e ``(None, ...)`` indecidido (métrica em vários
    grupos sem o critério nomear o grupo: segue para o revisor LLM, nunca reprova por métrica ausente).
    """
    results: List[Tuple[Optional[bool], str]] = []
    for crit in criteria:
        outcomes = [_evaluate_comparison(crit, cmp, metrics, contract_keys=contract_keys) for cmp in crit.comparisons]
        failed = [d for ok, d in outcomes if ok is False]
        if failed:
            results.append((False, " ".join(failed)))
        elif any(ok is None for ok, _ in outcomes):
            results.append((None, " ".join(d for _, d in outcomes)))
        else:
            results.append((True, " ".join(d for _, d in outcomes)))
    return results

def evaluated_metric_names(criteria: List[Any], metrics: Optional[Dict[str, Any]]) -> List[str]:
    """Nomes (como escritos em ``metrics.json``) das métricas citadas por critérios quantitativos.

    Usada pela ingestão de fatos para marcar ``Resultado.status_validacao="validado"`` nas
    métricas que o Validator avaliou contra um limiar (``v17-structural-fact-ingestion``).
    """
    wanted = {
        str(cmp.metric)
        for c in _metric_criteria(criteria if isinstance(criteria, list) else [])
        for cmp in c.comparisons
    }
    names: List[str] = []
    for key in (metrics or {}):
        norm = _normalize_metric_name(str(key))
        if _METRIC_ALIASES.get(norm, norm) in wanted:
            names.append(str(key))
            continue
        if config.REVIEW_METRIC_QUALIFIERS:
            parts = split_metric_name(str(key).rsplit(".", 1)[-1])
            if parts.qualifier in ("teste", "") and _METRIC_ALIASES.get(parts.base, parts.base) in wanted:
                names.append(str(key))
    return names
