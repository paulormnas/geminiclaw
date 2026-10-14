"""Roteador puro de modelos por papel (ADR 017 §2, §5, §7).

``resolve`` e ``resolve_session`` não fazem I/O: catálogo e disponibilidade entram como
argumentos. O algoritmo, por papel:

1. normaliza o papel (``aliases_papel``: ``planner`` -> ``researcher``);
2. monta os candidatos a partir da ``preferencia`` do papel, na ordem;
3. descarta, registrando o motivo: ``trust: third_party`` sob ``self_hosted_only`` (antes de
   qualquer outra regra), requisito não atendido, provedor fora da lista de permissão ou
   ``(provedor, modelo)`` indisponível;
4. um **pin** (``{PAPEL}_MODEL=provedor/modelo``) precisa existir no catálogo e passar pelas mesmas
   regras; se passar, vence a preferência; se não, ``flexible`` registra ``WARNING`` e segue a
   preferência, ``strict`` levanta :class:`PinError`;
5. o primeiro candidato restante vence; nenhum -> :class:`NoEligibleModelError` com a sugestão.

Cada posição da preferência pode ser um grupo de ids (empate; v18.5-model-catalog-locality, ADR 019 §6): só para
o ``validator``, se a primeira posição com elegível tiver mais de um, vence o de ``familia_modelo`` diferente das
``familias_autor`` (famílias dos papéis que escrevem afirmações); sem diferente, vale a ordem da lista. Um modelo de
posição inferior nunca substitui o da primeira posição com elegível, e o pin desliga o desempate.

Independência do julgamento (ADR 020; v18.6-validator-independence): ``familias_proibidas`` descarta, com o motivo
``mesma_familia_julgamento``, os modelos cuja ``familia_modelo`` coincide com a de um modelo do outro grupo
(juiz: ``validator``; julgado: ``developer``), mesmo em posição inferior da preferência.
``resolve_session`` resolve na ordem: pins, julgados, demais papéis e, por último, os juízes sem pin.

Este módulo também é o único lugar que lista as variáveis de ambiente removidas
(``LLM_PROVIDER``, ``LLM_MODEL``, ``DEFAULT_MODEL``, ``AGENT_MODEL``) para o aviso de obsolescência.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Collection, Mapping

from src.llm.availability import MOTIVO_NAO_VERIFICADO, Availability
from src.llm.catalog import OPTIONAL_ROLES, Catalog, ModelEntry
from src.logger import get_logger

logger = get_logger(__name__)

POLICY_SELF_HOSTED = "self_hosted_only"
POLICY_THIRD_PARTY = "third_party_allowed"
POLICIES = (POLICY_SELF_HOSTED, POLICY_THIRD_PARTY)
ROUTING_FLEXIBLE = "flexible"
ROUTING_STRICT = "strict"
ROUTING_MODES = (ROUTING_FLEXIBLE, ROUTING_STRICT)

MOTIVO_POLITICA = "politica"
MOTIVO_MESMA_FAMILIA = "mesma_familia_julgamento"

# Independência do julgamento (ADR 020 §1): juízes não podem compartilhar família com julgados em uso.
JUDGE_ROLES: tuple[str, ...] = ("validator",)
JUDGED_ROLES: tuple[str, ...] = ("developer",)
# O par exigido na inicialização (ADR 020 §4).
PAIR_ROLES: tuple[str, ...] = ("validator", "developer")
JUDGE_MODE_REQUIRED = "required"
JUDGE_MODE_PREFERRED = "preferred"
JUDGE_MODE_OFF = "off"
JUDGE_MODES = (JUDGE_MODE_REQUIRED, JUDGE_MODE_PREFERRED, JUDGE_MODE_OFF)
ORIGEM_MODO_VARIAVEL = "variavel"
ORIGEM_MODO_PADRAO = "padrao_politica"

# Papéis que escrevem afirmações verificadas pelo Validator (ADR 019 §6); o Validator é resolvido por último.
AUTHOR_ROLES: tuple[str, ...] = ("researcher", "developer", "summarizer", "curator")
VALIDATOR_ROLE = "validator"

# Variáveis que deixaram de existir (ADR 017, Consequências): ignoradas com um WARNING único.
REMOVED_ENV_VARS = ("LLM_PROVIDER", "LLM_MODEL", "DEFAULT_MODEL", "AGENT_MODEL")
# Variáveis de papéis removidos (v18.6-remove-unused-agents): ignoradas com um WARNING único.
REMOVED_ROLE_ENV_VARS = ("REVIEWER_MODEL", "REVIEWER_PROVIDER")
_removed_warned = False
_removed_role_warned = False


class RoutingError(RuntimeError):
    """Falha de roteamento: a sessão não deve começar."""


class NoEligibleModelError(RoutingError):
    """Nenhum modelo elegível para um (ou mais) papel(is)."""

    def __init__(self, papel: str, politica: str, descartados: tuple[tuple[str, str], ...], sugestao: str):
        self.papel = papel
        self.politica = politica
        self.descartados = descartados
        self.sugestao = sugestao
        listed = "; ".join(f"{model_id} ({motivo})" for model_id, motivo in descartados) or "nenhum candidato"
        subject = f"os papéis '{papel}'" if "," in papel else f"o papel '{papel}'"
        super().__init__(
            f"Nenhum modelo elegível para {subject} (política: {politica}). "
            f"Descartados: {listed}. {sugestao}"
        )


class PinError(RoutingError):
    """Pin inválido, indisponível ou em conflito (sempre fatal em ``strict``)."""


@dataclass(frozen=True)
class Pin:
    """Pin ``provedor/modelo`` de um papel; ``legado`` marca ``{PAPEL}_PROVIDER`` + ``{PAPEL}_MODEL``."""

    id: str
    legado: bool = False


@dataclass(frozen=True)
class RoleResolution:
    """Modelo resolvido para um papel, com os descartados para auditoria."""

    papel: str
    id: str
    trust: str
    origem: str  # "preferencia" | "pin" | "pin_legado"
    descartados: tuple[tuple[str, str], ...] = ()
    # Só no validator: {"aplicado", "familias_autor", "candidatos", "escolhido"} (ADR 019 §6).
    desempate: Mapping[str, object] | None = None
    # ADR 020: o modo ``preferred`` (ou o pin em ``strict``) manteve um modelo da mesma família do outro grupo.
    conflito_independencia: bool = False


def effective_judge_mode(env_value: str | None, data_policy: str) -> tuple[str, str]:
    """``(modo, origem)`` da independência do julgamento (ADR 020 §2).

    Valor explícito vence o padrão; sem ele, ``required`` com ``third_party_allowed`` e ``preferred`` com
    ``self_hosted_only``.

    Raises:
        RoutingError: Valor inválido (a inicialização não prossegue).
    """
    value = (env_value or "").strip().lower()
    if value:
        if value not in JUDGE_MODES:
            raise RoutingError(
                f"LLM_JUDGE_INDEPENDENCE inválido: '{value}'. Valores aceitos: {', '.join(JUDGE_MODES)}."
            )
        return value, ORIGEM_MODO_VARIAVEL
    mode = JUDGE_MODE_REQUIRED if data_policy == POLICY_THIRD_PARTY else JUDGE_MODE_PREFERRED
    return mode, ORIGEM_MODO_PADRAO


def validate_policy(politica: str) -> str:
    if politica not in POLICIES:
        raise RoutingError(f"LLM_DATA_POLICY inválida: '{politica}'. Valores aceitos: {', '.join(POLICIES)}.")
    return politica


def validate_routing_mode(routing: str) -> str:
    if routing not in ROUTING_MODES:
        raise RoutingError(f"LLM_ROUTING inválido: '{routing}'. Valores aceitos: {', '.join(ROUTING_MODES)}.")
    return routing


def _discard_reason(
    entry: ModelEntry,
    requisitos: Mapping[str, object],
    disponiveis: Mapping[str, Availability],
    politica: str,
) -> str | None:
    """Motivo de descarte, ou ``None`` se o modelo é elegível (a política vem antes de tudo)."""
    if politica == POLICY_SELF_HOSTED and entry.trust != "self_hosted":
        return MOTIVO_POLITICA
    if requisitos.get("ferramentas") and not entry.ferramentas:
        return "requisito:ferramentas"
    if requisitos.get("saida_estruturada") and not entry.saida_estruturada:
        return "requisito:saida_estruturada"
    minimum = requisitos.get("janela_contexto_min")
    if isinstance(minimum, int) and entry.janela_contexto < minimum:
        return "requisito:janela_contexto"
    status = disponiveis.get(entry.id)
    if status is None:
        return MOTIVO_NAO_VERIFICADO
    if not status.ok:
        return status.motivo or "indisponivel"
    return None


def is_eligible(entry: ModelEntry, requisitos: Mapping[str, object], politica: str) -> bool:
    """Política e requisitos atendidos (sem considerar disponibilidade)."""
    return _discard_reason(entry, requisitos, {entry.id: Availability(True)}, politica) is None


def _suggestion(politica: str, descartados: tuple[tuple[str, str], ...]) -> str:
    parts: list[str] = []
    reasons = [motivo for _, motivo in descartados]
    if MOTIVO_MESMA_FAMILIA in reasons:
        return (
            "Nenhum modelo elegível de outra família que o juiz possa usar: defina LLM_JUDGE_INDEPENDENCE=preferred "
            "para seguir com aviso, habilite outra família (LLM_DATA_POLICY=third_party_allowed com credencial "
            "do provedor, ou um modelo local de outra família em catalog.local.yaml) ou use LLM_JUDGE_INDEPENDENCE=off."
        )
    if politica == POLICY_SELF_HOSTED and MOTIVO_POLITICA in reasons:
        parts.append(
            "Defina LLM_DATA_POLICY=third_party_allowed para permitir provedores de nuvem "
            "(prompts com dados do projeto sairão do host)"
        )
    if any(r != MOTIVO_POLITICA and not r.startswith("requisito:") for r in reasons):
        parts.append(
            "ou deixe um provedor disponível: configure a credencial/endpoint, inclua-o em "
            "LLM_PROVIDER_PRIORITY e, para o Ollama, instale o modelo (ollama pull <modelo>)"
        )
    return (parts[0] + (", " + parts[1] if len(parts) > 1 else "") + ".") if parts else (
        "Revise o catálogo (src/llm/catalog.yaml) e os requisitos do papel."
    )


def _tiebreak_record(
    role: str, applied: bool, familias_autor: Collection[str], candidates: Collection[str], chosen: str
) -> dict[str, object] | None:
    if role != VALIDATOR_ROLE:
        return None
    return {
        "aplicado": applied,
        "familias_autor": sorted(set(familias_autor)),
        "candidatos": list(candidates),
        "escolhido": chosen,
    }


def resolve(
    papel: str,
    catalogo: Catalog,
    disponiveis: Mapping[str, Availability],
    politica: str,
    overrides: Mapping[str, Pin] | None = None,
    routing: str = ROUTING_FLEXIBLE,
    familias_autor: Collection[str] = (),
    familias_proibidas: Collection[str] = (),
    tolerar_conflito: bool = False,
) -> RoleResolution:
    """Resolve o modelo de um papel (função pura; ver o algoritmo no docstring do módulo).

    ``familias_autor``: famílias já resolvidas para os papéis autores (usadas só no ``validator``, para o
    desempate do ADR 019 §6). ``familias_proibidas``: famílias que o papel não pode usar (ADR 020); o descarte
    vale também para o pin. ``tolerar_conflito``: sem alternativa, segue com o modelo em conflito e marca
    ``conflito_independencia`` (modo ``preferred``); senão, :class:`NoEligibleModelError` (ou :class:`PinError`
    para um pin em ``strict``).

    Raises:
        ValueError: Papel desconhecido.
        NoEligibleModelError: Nenhum candidato elegível.
        PinError: Pin inválido em ``LLM_ROUTING=strict``.
    """
    validate_policy(politica)
    validate_routing_mode(routing)
    role = catalogo.normalize_role(papel)
    spec = catalogo.papeis[role]
    forbidden = frozenset(familias_proibidas)
    descartados: list[tuple[str, str]] = []
    kept_pin: RoleResolution | None = None

    pin = (overrides or {}).get(role)
    if pin is not None:
        entry = catalogo.modelos.get(pin.id)
        reason = "fora_do_catalogo" if entry is None else _discard_reason(entry, spec.requisitos, disponiveis, politica)
        if reason is None and entry is not None:
            origem = "pin_legado" if pin.legado else "pin"
            pin_resolution = RoleResolution(
                role, entry.id, entry.trust, origem,
                desempate=_tiebreak_record(role, False, familias_autor, (), entry.id),
            )
            if entry.familia_modelo not in forbidden:
                return pin_resolution
            message = (
                f"Pin '{pin.id}' do papel '{role}' é da família '{entry.familia_modelo}', a mesma de um modelo do "
                f"outro grupo do julgamento ({MOTIVO_MESMA_FAMILIA})"
            )
            if routing == ROUTING_STRICT:
                if tolerar_conflito:
                    logger.warning(message + "; LLM_ROUTING=strict mantém o pin e a independência não é atendida.")
                    return replace(pin_resolution, conflito_independencia=True)
                raise PinError(
                    message + "; LLM_ROUTING=strict não troca o pin. Use pins de famílias diferentes ou "
                    "LLM_JUDGE_INDEPENDENCE=preferred."
                )
            logger.warning(message + "; ignorando o pin e seguindo a ordem de preferência do catálogo.")
            descartados.append((pin.id, MOTIVO_MESMA_FAMILIA))
            kept_pin = replace(pin_resolution, conflito_independencia=True)
        else:
            message = f"Pin '{pin.id}' do papel '{role}' não vale: {reason}"
            if reason == MOTIVO_POLITICA:
                message += " (defina LLM_DATA_POLICY=third_party_allowed ou remova o pin)"
            if routing == ROUTING_STRICT:
                raise PinError(message + "; LLM_ROUTING=strict não aceita pin em conflito.")
            logger.warning(message + "; seguindo a ordem de preferência do catálogo.")
            descartados.append((pin.id, f"pin:{reason}"))

    for group in spec.preferencia_grupos:
        eligible: list[ModelEntry] = []
        for model_id in group:
            entry = catalogo.modelos[model_id]
            reason = _discard_reason(entry, spec.requisitos, disponiveis, politica)
            if reason is None and entry.familia_modelo in forbidden:
                reason = MOTIVO_MESMA_FAMILIA
            if reason is None:
                eligible.append(entry)
            else:
                descartados.append((model_id, reason))
        if not eligible:
            continue
        chosen, applied = eligible[0], False
        if role == VALIDATOR_ROLE and len(eligible) > 1:
            different = [e for e in eligible if e.familia_modelo not in set(familias_autor)]
            if different:
                chosen, applied = different[0], True
        return RoleResolution(
            role, chosen.id, chosen.trust, "preferencia", tuple(descartados),
            desempate=_tiebreak_record(role, applied, familias_autor, [e.id for e in eligible], chosen.id),
        )

    if forbidden and tolerar_conflito:
        if kept_pin is not None:
            logger.warning(
                "Sem alternativa de outra família: o pin é mantido e a independência não é atendida",
                extra={"role": role, "pin": kept_pin.id},
            )
            return replace(kept_pin, descartados=tuple(descartados))
        fallback = resolve(
            papel, catalogo, disponiveis, politica, overrides, routing, familias_autor, (), False
        )
        logger.warning(
            "Sem alternativa de outra família: segue com o preferido e a independência não é atendida",
            extra={"role": role, "modelo": fallback.id},
        )
        return replace(
            fallback, descartados=tuple(descartados) + fallback.descartados, conflito_independencia=True
        )

    discarded = tuple(descartados)
    raise NoEligibleModelError(role, politica, discarded, _suggestion(politica, discarded))


def _family(catalogo: Catalog, resolution: RoleResolution) -> str | None:
    entry = catalogo.modelos.get(resolution.id)
    return entry.familia_modelo if entry is not None else None


def resolve_session(
    catalogo: Catalog,
    disponiveis: Mapping[str, Availability],
    politica: str,
    overrides: Mapping[str, Pin] | None = None,
    routing: str = ROUTING_FLEXIBLE,
    modo_independencia: str = JUDGE_MODE_OFF,
) -> dict[str, RoleResolution]:
    """Resolve todos os papéis do catálogo de uma vez (o **mapa resolvido** da sessão).

    Todos os papéis sem modelo elegível são reportados juntos, para o pesquisador corrigir de
    uma vez. Pins inválidos em ``strict`` são fatais imediatamente.

    Ordem (ADR 020 §3): (a) papéis com pin, julgados antes dos livres e dos juízes; (b) julgados sem pin, evitando
    as famílias dos juízes com pin; (c) livres sem pin (o desempate do ADR 019 §6 usa os autores já resolvidos);
    (d) juízes sem pin, evitando as famílias de todos os julgados resolvidos. Com ``modo_independencia="off"``
    nenhuma família é proibida.
    """
    if modo_independencia not in JUDGE_MODES:
        raise RoutingError(
            f"modo de independência inválido: '{modo_independencia}'. Valores aceitos: {', '.join(JUDGE_MODES)}."
        )
    pins = overrides or {}
    check = modo_independencia != JUDGE_MODE_OFF
    preferred = modo_independencia == JUDGE_MODE_PREFERRED
    resolved: dict[str, RoleResolution] = {}
    failures: list[NoEligibleModelError] = []

    def families(roles: tuple[str, ...]) -> set[str]:
        return {f for r in roles if r in resolved and (f := _family(catalogo, resolved[r])) is not None}

    def authors() -> set[str]:
        return families(AUTHOR_ROLES)

    def one(role: str) -> None:
        if role in JUDGE_ROLES:
            forbidden = families(JUDGED_ROLES) if check else set()
        elif role in JUDGED_ROLES:
            forbidden = families(JUDGE_ROLES) if check else set()
        else:
            forbidden = set()
        try:
            resolved[role] = resolve(
                role, catalogo, disponiveis, politica, pins, routing, authors(), forbidden,
                preferred if role in PAIR_ROLES else True,
            )
        except (NoEligibleModelError, PinError) as exc:
            if role in OPTIONAL_ROLES:
                logger.warning(
                    "Papel opcional sem modelo elegível: desligado nesta sessão",
                    extra={"role": role, "politica": politica},
                )
                return
            if isinstance(exc, PinError):
                raise  # pin inválido de papel obrigatório segue fatal (strict)
            failures.append(exc)

    roles = list(catalogo.papeis)
    pinned = [r for r in roles if r in pins]
    unpinned = [r for r in roles if r not in pins]
    phases = [
        [r for r in pinned if r in JUDGED_ROLES],
        [r for r in pinned if r not in JUDGED_ROLES and r not in JUDGE_ROLES],
        [r for r in pinned if r in JUDGE_ROLES],
        [r for r in unpinned if r in JUDGED_ROLES],
        [r for r in unpinned if r not in JUDGED_ROLES and r not in JUDGE_ROLES],
        [r for r in unpinned if r in JUDGE_ROLES],
    ]
    for phase in phases:
        for role in phase:
            one(role)
    if len(failures) == 1:
        raise failures[0]
    if failures:
        merged = NoEligibleModelError(
            ", ".join(f.papel for f in failures),
            politica,
            tuple(dict.fromkeys(item for f in failures for item in f.descartados)),
            failures[0].sugestao,
        )
        raise merged
    return {role: resolved[role] for role in catalogo.papeis if role in resolved}


def validate_hint(
    papel: str,
    hint: str | None,
    catalogo: Catalog,
    disponiveis: Mapping[str, Availability],
    politica: str,
    routing: str,
) -> str | None:
    """Valida a dica ``preferred_model`` do plano; devolve o ``id`` aceito ou ``None`` (ignorada).

    A dica só vale no formato ``provedor/modelo``, com o modelo no catálogo, atendendo aos
    requisitos do papel e à política, e disponível. Em ``strict`` é sempre ignorada.
    """
    if not hint:
        return None
    if routing == ROUTING_STRICT:
        logger.warning("Dica de modelo do plano ignorada em LLM_ROUTING=strict", extra={"hint": hint})
        return None
    if "/" not in hint:
        logger.warning(
            "Dica de modelo do plano ignorada: use o formato provedor/modelo", extra={"hint": hint}
        )
        return None
    role = catalogo.normalize_role(papel)
    entry = catalogo.modelos.get(hint)
    reason = "fora_do_catalogo" if entry is None else _discard_reason(
        entry, catalogo.papeis[role].requisitos, disponiveis, politica
    )
    if reason is not None:
        logger.warning("Dica de modelo do plano ignorada", extra={"hint": hint, "role": role, "motivo": reason})
        return None
    return hint


def warn_removed_variables(env: Mapping[str, str] | None = None) -> list[str]:
    """Registra um ``WARNING`` único listando as variáveis removidas encontradas no ambiente."""
    global _removed_warned
    environ = os.environ if env is None else env
    found = [name for name in REMOVED_ENV_VARS if environ.get(name)]
    if found and not _removed_warned:
        _removed_warned = True
        logger.warning(
            "Variáveis de ambiente removidas são ignoradas; use LLM_DATA_POLICY, o catálogo "
            "(src/llm/catalog.yaml) e {PAPEL}_MODEL=provedor/modelo",
            extra={"variaveis": found},
        )
    global _removed_role_warned
    found_roles = [name for name in REMOVED_ROLE_ENV_VARS if environ.get(name)]
    if found_roles and not _removed_role_warned:
        _removed_role_warned = True
        logger.warning(
            "O papel reviewer foi removido na V18.6 (a revisão de subtarefa é do validator): as variáveis "
            "REVIEWER_MODEL e REVIEWER_PROVIDER são ignoradas",
            extra={"variaveis": found_roles},
        )
    return found + found_roles


def reset_removed_variables_warning() -> None:
    """Rearma o aviso único (uso em testes)."""
    global _removed_warned, _removed_role_warned
    _removed_warned = False
    _removed_role_warned = False


def read_pins(
    catalogo: Catalog,
    env: Mapping[str, str] | None = None,
    cli_pins: Mapping[str, str] | None = None,
) -> dict[str, Pin]:
    """Lê os pins por papel de ``{PAPEL}_MODEL`` (e ``{PAPEL}_PROVIDER`` legado) e da CLI.

    ``{PAPEL}_MODEL=provedor/modelo`` é o pin. ``{PAPEL}_PROVIDER=p`` + ``{PAPEL}_MODEL=m`` (sem
    ``/``) vira o pin ``p/m`` com ``origem="pin_legado"`` e ``WARNING`` de obsolescência;
    ``{PAPEL}_MODEL=m`` sozinho é erro acionável. ``cli_pins`` (``--model``) vence o ambiente.

    Raises:
        PinError: Pin sem ``provedor/``.
    """
    environ = os.environ if env is None else env
    warn_removed_variables(environ)
    pins: dict[str, Pin] = {}
    for role in catalogo.papeis:
        prefix = role.upper()
        model = (environ.get(f"{prefix}_MODEL") or "").strip()
        provider = (environ.get(f"{prefix}_PROVIDER") or "").strip().lower()
        if model:
            if "/" in model:
                pins[role] = Pin(model)
            elif provider:
                logger.warning(
                    "Variáveis obsoletas: use um único pin provedor/modelo",
                    extra={"variaveis": [f"{prefix}_PROVIDER", f"{prefix}_MODEL"], "pin": f"{provider}/{model}"},
                )
                pins[role] = Pin(f"{provider}/{model}", legado=True)
            else:
                raise PinError(
                    f"{prefix}_MODEL='{model}' sem provedor: use {prefix}_MODEL=provedor/modelo "
                    f"(ex.: ollama/{model})."
                )
        elif provider:
            logger.warning(
                "Variável obsoleta ignorada: sem {PAPEL}_MODEL não há pin",
                extra={"variavel": f"{prefix}_PROVIDER"},
            )
    for role, spec in (cli_pins or {}).items():
        normalized = catalogo.normalize_role(role)
        if "/" not in spec:
            raise PinError(f"--model '{spec}' sem provedor: use o formato provedor/modelo.")
        pins[normalized] = Pin(spec)
    return pins
