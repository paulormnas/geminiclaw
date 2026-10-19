"""Variantes da fórmula do veredito (design §3 de ``v18.8-verdict-lab``).

Uma variante é um conjunto de valores de ``VerdictParams`` mais alternativas de estrutura que só existem no
laboratório. Sem alternativa de estrutura, ``lab_verdict`` delega a ``compute_verdict``; com alguma, usa a
reimplementação abaixo, que com todas as alternativas no valor atual dá o mesmo resultado que
``compute_verdict`` (conferido por teste).
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.knowledge.verdict import (
    Attempt,
    Criterion,
    EvidenceBreakdown,
    VerdictParams,
    VerdictResult,
    _quality,
    _reproduced_failure_signatures,
    _validate_attempt,
    compute_verdict,
    read_verdict,
)

DEFAULT_VARIANTS_PATH = Path(__file__).with_name("variantes.json")

_CHOICES: dict[str, tuple[str, ...]] = {
    "independencia": ("atual", "por_tipo"),
    "variacao_util": ("nenhuma", "melhora_o_melhor"),
    "m_sem_baseline": ("fixo", "folga"),
    "b_por": ("configuracao", "variacao_sem_ganho", "variacao_sem_ganho_acumulada"),
    "criterio_com_alvo": ("baseline_primeiro", "exige_alvo"),
}


class VariantError(ValueError):
    """Arquivo ou definição de variante inválida."""


@dataclass(frozen=True)
class Structure:
    """Alternativas de estrutura da equação (design §3.2). Os padrões reproduzem ``compute_verdict``."""

    n_config_conta_falhas: bool = True
    independencia: str = "atual"
    d_variacao: float = 1.0
    d_replica_no: float = 0.5
    d_dataset: float = 1.0
    d_sessao: float = 0.5
    d_semente: float = 0.2
    variacao_util: str = "nenhuma"
    variacao_util_epsilon: float = 0.0
    m_sem_baseline: str = "fixo"
    b_por: str = "configuracao"
    criterio_com_alvo: str = "baseline_primeiro"
    m_folga_piso: float = 0.0
    d_replica_contraria: float | None = None
    d_variacao_sem_ganho: float | None = None

    def is_default(self) -> bool:
        """``True`` quando nenhuma alternativa muda a equação atual (os pesos de ``por_tipo`` não contam)."""
        return (
            self.n_config_conta_falhas
            and self.independencia == "atual"
            and self.variacao_util == "nenhuma"
            and self.m_sem_baseline == "fixo"
            and self.b_por == "configuracao"
            and self.criterio_com_alvo == "baseline_primeiro"
        )


@dataclass(frozen=True)
class Variant:
    """Uma variante nomeada da fórmula."""

    nome: str
    params: VerdictParams
    estrutura: Structure = field(default_factory=Structure)
    descricao: str = ""
    origem_params: str = "padrao"

    def manifest(self) -> dict[str, Any]:
        """Parâmetros efetivos e estrutura, para o manifesto."""
        params = dataclasses.asdict(self.params)
        params["thresholds"] = list(self.params.thresholds)
        return {
            "nome": self.nome,
            "descricao": self.descricao,
            "origem_params": self.origem_params,
            "parametros": params,
            "estrutura": dataclasses.asdict(self.estrutura),
        }


def base_params() -> tuple[VerdictParams, str]:
    """``VerdictParams`` do projeto (variáveis ``VERDICT_*``) ou, se ``src.config`` não carregar, os padrões."""
    try:
        params, origem = VerdictParams.from_config(), "config"
    except Exception:  # noqa: BLE001 - sem configuração do projeto, os padrões do ADR 015 §9.8 valem
        params, origem = VerdictParams(), "padrao"
    # O laboratório mede variantes da equação do ADR 015; o modelo v2 do sistema é comparado pela variante completa2.
    return dataclasses.replace(params, modelo="adr015"), origem


def _coerce_params(base: VerdictParams, raw: Any, where: str) -> VerdictParams:
    if raw is None:
        return base
    if not isinstance(raw, dict):
        raise VariantError(f"{where}: 'parametros' deve ser um objeto.")
    names = {f.name: f for f in dataclasses.fields(VerdictParams)}
    changes: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in names:
            raise VariantError(f"{where}: parâmetro desconhecido '{key}'.")
        if key == "thresholds":
            if not (isinstance(value, list) and len(value) == 3 and all(_is_number(v) for v in value)):
                raise VariantError(f"{where}: 'thresholds' deve ser uma lista de três números.")
            changes[key] = tuple(float(v) for v in value)
        elif key == "approach_failure_min_repeats":
            if not isinstance(value, int) or isinstance(value, bool):
                raise VariantError(f"{where}: '{key}' deve ser inteiro.")
            changes[key] = value
        else:
            if not _is_number(value):
                raise VariantError(f"{where}: '{key}' deve ser numérico.")
            changes[key] = float(value)
    return dataclasses.replace(base, **changes)


def _coerce_structure(raw: Any, where: str) -> Structure:
    if raw is None:
        return Structure()
    if not isinstance(raw, dict):
        raise VariantError(f"{where}: 'estrutura' deve ser um objeto.")
    names = {f.name for f in dataclasses.fields(Structure)}
    changes: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in names:
            raise VariantError(f"{where}: alternativa de estrutura desconhecida '{key}'.")
        if key in _CHOICES:
            if value not in _CHOICES[key]:
                raise VariantError(f"{where}: '{key}' deve ser um de {list(_CHOICES[key])}, não {value!r}.")
            changes[key] = value
        elif key == "n_config_conta_falhas":
            if not isinstance(value, bool):
                raise VariantError(f"{where}: '{key}' deve ser booleano.")
            changes[key] = value
        else:
            if not _is_number(value):
                raise VariantError(f"{where}: '{key}' deve ser numérico.")
            changes[key] = float(value)
    return Structure(**changes)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_variants(data: Any, *, source: str = "variantes") -> list[Variant]:
    """Valida e constrói as variantes de um documento ``{"versao": 1, "variantes": [...]}``.

    Raises:
        VariantError: Documento fora do formato, nome repetido, campo ou valor desconhecido.
    """
    if not isinstance(data, dict) or data.get("versao") != 1 or not isinstance(data.get("variantes"), list):
        raise VariantError(f"{source}: esperado {{'versao': 1, 'variantes': [...]}}.")
    base, origem = base_params()
    variants: list[Variant] = []
    seen: set[str] = set()
    for index, raw in enumerate(data["variantes"]):
        if not isinstance(raw, dict) or not isinstance(raw.get("nome"), str) or not raw["nome"]:
            raise VariantError(f"{source}: variante {index} sem 'nome'.")
        nome = raw["nome"]
        where = f"{source}: variante '{nome}'"
        unknown = set(raw) - {"nome", "descricao", "parametros", "estrutura"}
        if unknown:
            raise VariantError(f"{where}: campo desconhecido {sorted(unknown)}.")
        if nome in seen:
            raise VariantError(f"{where}: nome repetido.")
        seen.add(nome)
        variants.append(
            Variant(
                nome=nome,
                params=_coerce_params(base, raw.get("parametros"), where),
                estrutura=_coerce_structure(raw.get("estrutura"), where),
                descricao=str(raw.get("descricao") or ""),
                origem_params=origem,
            )
        )
    if not variants:
        raise VariantError(f"{source}: nenhuma variante.")
    return variants


def load_variants(path: Path | None = None) -> list[Variant]:
    """Lê as variantes de ``path`` (padrão: ``variantes.json`` do pacote)."""
    path = path or DEFAULT_VARIANTS_PATH
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VariantError(f"{path}: não foi possível ler as variantes ({exc}).") from exc
    return parse_variants(data, source=str(path))


def select_variants(variants: list[Variant], names: list[str] | None) -> list[Variant]:
    """Filtra pelo nome, na ordem pedida; nome desconhecido é erro."""
    if not names:
        return variants
    by_name = {v.nome: v for v in variants}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise VariantError(f"variantes desconhecidas: {missing}.")
    return [by_name[n] for n in names]


def current_variant() -> Variant:
    """A variante ``atual`` (parâmetros do projeto, sem alternativa de estrutura)."""
    params, origem = base_params()
    return Variant(nome="atual", params=params, descricao="ADR 015 §9.8", origem_params=origem)


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------


@dataclass
class _Record:
    attempt: Attempt
    classificacao: str
    q: float
    m: float
    d: float = 0.0
    b: float = 0.0
    w: float = 0.0
    nova_config: bool = False
    melhorou: bool = False


def _gain(criterion: Criterion, value: float, reference: float) -> float:
    """Diferença no sentido favorável da métrica (positiva = melhor)."""
    return value - reference if criterion.sentido == "maior_melhor" else reference - value


def _direction_and_magnitude(attempt: Attempt, criterion: Criterion, st: Structure) -> tuple[int, float] | None:
    value = attempt.value
    assert value is not None
    if criterion.delta_min is not None and attempt.baseline is not None:
        delta = _gain(criterion, value, attempt.baseline)
        if delta >= criterion.delta_min:
            o, m = 1, min(1.0, delta / (2 * criterion.delta_min))
        else:
            o, m = -1, min(1.0, (criterion.delta_min - delta) / criterion.delta_min)
        if o == 1 and st.criterio_com_alvo == "exige_alvo" and criterion.alvo is not None:
            shortfall = -_gain(criterion, value, criterion.alvo)
            if shortfall > 0:
                return -1, min(1.0, shortfall / criterion.delta_min)
        return o, m

    if criterion.alvo is not None:
        margin = _gain(criterion, value, criterion.alvo)
        if st.m_sem_baseline == "folga" and criterion.delta_min:
            if margin >= 0:
                return 1, max(st.m_folga_piso, min(1.0, margin / (2 * criterion.delta_min)))
            return -1, min(1.0, -margin / criterion.delta_min)
        return (1, 0.5) if margin >= 0 else (-1, 0.5)

    return None


def _classify(
    attempt: Attempt, criterion: Criterion, params: VerdictParams, reproduced: set[str], st: Structure
) -> tuple[str, float, float]:
    if attempt.outcome_kind == "resultado":
        if attempt.validation == "nao_validado":
            return "nao_evidencia", 0.0, 0.0
        direction = _direction_and_magnitude(attempt, criterion, st)
        if direction is None:
            return "ambigua", 0.0, 0.0
        o, m = direction
        return ("positiva" if o == 1 else "negativa"), _quality(attempt, params), m
    if attempt.failure_cause == "infraestrutura":
        return "infraestrutura", 0.0, 0.0
    if attempt.failure_cause == "abordagem" and attempt.failure_signature in reproduced:
        return "negativa", params.approach_failure_q, 1.0
    return "ambigua", 0.0, 0.0


def _mark_variations(records: list[_Record], criterion: Criterion, st: Structure) -> None:
    """Marca, nas evidências em ordem cronológica, configuração nova e melhora sobre o melhor valor anterior."""
    seen: set[str] = set()
    best: float | None = None
    for r in records:
        if r.classificacao not in ("positiva", "negativa"):
            continue
        r.nova_config = r.attempt.config_hash not in seen
        seen.add(r.attempt.config_hash)
        value = r.attempt.value
        if value is None:
            continue
        r.melhorou = best is None or _gain(criterion, value, best) > st.variacao_util_epsilon
        if best is None or _gain(criterion, value, best) > 0:
            best = value


def _independence_current(records: list[_Record], params: VerdictParams) -> None:
    seen_nodes: set[str] = set()
    seen_datasets: set[str] = set()
    seen_sessions: set[str] = set()
    for r in records:
        if r.classificacao not in ("positiva", "negativa"):
            continue
        a = r.attempt
        if a.node_id not in seen_nodes or any(ds not in seen_datasets for ds in a.dataset_ids):
            r.d = params.d_new_node_or_dataset
        elif a.session_id not in seen_sessions:
            r.d = params.d_new_session
        else:
            r.d = params.d_new_seed
        seen_nodes.add(a.node_id)
        seen_datasets.update(a.dataset_ids)
        seen_sessions.add(a.session_id)


def _independence_by_kind(records: list[_Record], st: Structure) -> None:
    config_nodes: dict[str, set[str]] = {}
    seen_datasets: set[str] = set()
    seen_sessions: set[str] = set()
    for r in records:
        if r.classificacao not in ("positiva", "negativa"):
            continue
        a = r.attempt
        nodes = config_nodes.get(a.config_hash)
        contraria = st.d_replica_contraria is not None and nodes is not None and r.classificacao == "negativa"
        if contraria:
            r.d = st.d_replica_contraria
        elif nodes is None:
            useful = st.variacao_util == "nenhuma" or r.attempt.value is None or r.melhorou
            if useful:
                r.d = st.d_variacao
            elif st.d_variacao_sem_ganho is not None and r.classificacao == "positiva":
                r.d = st.d_variacao_sem_ganho
            else:
                r.d = st.d_semente
        elif a.node_id not in nodes:
            r.d = st.d_replica_no
        elif any(ds not in seen_datasets for ds in a.dataset_ids):
            r.d = st.d_dataset
        elif a.session_id not in seen_sessions:
            r.d = st.d_sessao
        else:
            r.d = st.d_semente
        config_nodes.setdefault(a.config_hash, set()).add(a.node_id)
        seen_datasets.update(a.dataset_ids)
        seen_sessions.add(a.session_id)


def _n_config(records: list[_Record], st: Structure) -> int:
    if st.b_por in ("variacao_sem_ganho", "variacao_sem_ganho_acumulada"):
        return 1 + sum(1 for r in records if r.nova_config and not r.melhorou and r.attempt.value is not None)
    pool = records if st.n_config_conta_falhas else [r for r in records if r.classificacao in ("positiva", "negativa")]
    return max(1, len({r.attempt.config_hash for r in pool}))


def _n_config_ate(records: list[_Record], upto: _Record, st: Structure) -> int:
    """``n_config`` visto até a própria evidência (inclusive): evidência posterior não altera o peso das anteriores."""
    index = records.index(upto)
    return _n_config(records[: index + 1], st)


def _search_penalty(record: _Record, records: list[_Record], n_config: int, params: VerdictParams) -> float:
    replicated = any(
        other.classificacao == "positiva"
        and other.attempt.attempt_id != record.attempt.attempt_id
        and other.attempt.config_hash == record.attempt.config_hash
        and (other.attempt.node_id != record.attempt.node_id or other.attempt.session_id != record.attempt.session_id)
        for other in records
    )
    if replicated:
        return 1.0
    return 1.0 / (1.0 + params.gamma * math.log(n_config))


def _reimplemented(attempts: list[Attempt], criterion: Criterion, variant: Variant) -> VerdictResult:
    params, st = variant.params, variant.estrutura
    for attempt in attempts:
        _validate_attempt(attempt)
    ordered = sorted(attempts, key=lambda a: a.timestamp)
    reproduced = _reproduced_failure_signatures(ordered, params)

    records = []
    for attempt in ordered:
        classificacao, q, m = _classify(attempt, criterion, params, reproduced, st)
        records.append(_Record(attempt=attempt, classificacao=classificacao, q=q, m=m))
    _mark_variations(records, criterion, st)
    if st.independencia == "atual":
        _independence_current(records, params)
    else:
        _independence_by_kind(records, st)

    n_config = _n_config(records, st)
    for r in records:
        if r.classificacao == "positiva":
            r.b = _search_penalty(
                r, records, _n_config_ate(records, r, st) if st.b_por.endswith("acumulada") else n_config, params
            )
        elif r.classificacao == "negativa":
            r.b = 1.0
        r.w = r.q * r.m * r.d * r.b

    alpha = params.prior + sum(r.w for r in records if r.classificacao == "positiva")
    beta = params.prior + sum(r.w for r in records if r.classificacao == "negativa")
    n_tentativas = len(ordered)
    n_infraestrutura = sum(1 for r in records if r.classificacao == "infraestrutura")
    n_evidencias = sum(1 for r in records if r.classificacao in ("positiva", "negativa"))
    n_ambiguas = sum(1 for r in records if r.classificacao == "ambigua")
    n_validas = n_tentativas - n_infraestrutura
    fator = 1.0 if n_validas == 0 else 1.0 - params.lambda_ambiguous * n_ambiguas / n_validas
    suporte = alpha / (alpha + beta)
    certeza = (alpha + beta - 2 * params.prior) / (alpha + beta)
    veredito = fator * certeza * (2 * suporte - 1)
    leitura, tipo = read_verdict(veredito, params.thresholds)
    return VerdictResult(
        alpha=alpha,
        beta=beta,
        suporte=suporte,
        certeza=certeza,
        f=fator,
        veredito=veredito,
        confianca=abs(veredito),
        leitura=leitura,
        tipo_descoberta=tipo,
        n_tentativas=n_tentativas,
        n_evidencias=n_evidencias,
        n_ambiguas=n_ambiguas,
        n_infraestrutura=n_infraestrutura,
        detalhes=tuple(
            EvidenceBreakdown(
                attempt_id=r.attempt.attempt_id, classificacao=r.classificacao, q=r.q, m=r.m, d=r.d, b=r.b, w=r.w
            )
            for r in records
        ),
    )


def lab_verdict(
    attempts: list[Attempt], criterion: Criterion, variant: Variant, *, reimplementar: bool = False
) -> VerdictResult:
    """Veredito sob a variante: ``compute_verdict`` sem alternativa de estrutura; a reimplementação com alguma.

    Args:
        attempts: Tentativas da hipótese.
        criterion: Critério de sucesso.
        variant: Variante da fórmula.
        reimplementar: Força a reimplementação mesmo sem alternativa (teste de equivalência).
    """
    if variant.estrutura.is_default() and not reimplementar:
        return compute_verdict(attempts, criterion, dataclasses.replace(variant.params, modelo="adr015"))
    return _reimplemented(attempts, criterion, variant)
