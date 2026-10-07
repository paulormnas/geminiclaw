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

Este módulo também é o único lugar que lista as variáveis de ambiente removidas
(``LLM_PROVIDER``, ``LLM_MODEL``, ``DEFAULT_MODEL``, ``AGENT_MODEL``) para o aviso de obsolescência.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

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

# Variáveis que deixaram de existir (ADR 017, Consequências): ignoradas com um WARNING único.
REMOVED_ENV_VARS = ("LLM_PROVIDER", "LLM_MODEL", "DEFAULT_MODEL", "AGENT_MODEL")
_removed_warned = False


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


def resolve(
    papel: str,
    catalogo: Catalog,
    disponiveis: Mapping[str, Availability],
    politica: str,
    overrides: Mapping[str, Pin] | None = None,
    routing: str = ROUTING_FLEXIBLE,
) -> RoleResolution:
    """Resolve o modelo de um papel (função pura; ver o algoritmo no docstring do módulo).

    Raises:
        ValueError: Papel desconhecido.
        NoEligibleModelError: Nenhum candidato elegível.
        PinError: Pin inválido em ``LLM_ROUTING=strict``.
    """
    validate_policy(politica)
    validate_routing_mode(routing)
    role = catalogo.normalize_role(papel)
    spec = catalogo.papeis[role]
    descartados: list[tuple[str, str]] = []

    pin = (overrides or {}).get(role)
    if pin is not None:
        entry = catalogo.modelos.get(pin.id)
        reason = "fora_do_catalogo" if entry is None else _discard_reason(entry, spec.requisitos, disponiveis, politica)
        if reason is None and entry is not None:
            return RoleResolution(role, entry.id, entry.trust, "pin_legado" if pin.legado else "pin")
        message = f"Pin '{pin.id}' do papel '{role}' não vale: {reason}"
        if reason == MOTIVO_POLITICA:
            message += " (defina LLM_DATA_POLICY=third_party_allowed ou remova o pin)"
        if routing == ROUTING_STRICT:
            raise PinError(message + "; LLM_ROUTING=strict não aceita pin em conflito.")
        logger.warning(message + "; seguindo a ordem de preferência do catálogo.")
        descartados.append((pin.id, f"pin:{reason}"))

    for model_id in spec.preferencia:
        entry = catalogo.modelos[model_id]
        reason = _discard_reason(entry, spec.requisitos, disponiveis, politica)
        if reason is None:
            return RoleResolution(role, entry.id, entry.trust, "preferencia", tuple(descartados))
        descartados.append((model_id, reason))

    discarded = tuple(descartados)
    raise NoEligibleModelError(role, politica, discarded, _suggestion(politica, discarded))


def resolve_session(
    catalogo: Catalog,
    disponiveis: Mapping[str, Availability],
    politica: str,
    overrides: Mapping[str, Pin] | None = None,
    routing: str = ROUTING_FLEXIBLE,
) -> dict[str, RoleResolution]:
    """Resolve todos os papéis do catálogo de uma vez (o **mapa resolvido** da sessão).

    Todos os papéis sem modelo elegível são reportados juntos, para o pesquisador corrigir de
    uma vez. Pins inválidos em ``strict`` são fatais imediatamente.
    """
    resolved: dict[str, RoleResolution] = {}
    failures: list[NoEligibleModelError] = []
    for role in catalogo.papeis:
        try:
            resolved[role] = resolve(role, catalogo, disponiveis, politica, overrides, routing)
        except (NoEligibleModelError, PinError) as exc:
            if role in OPTIONAL_ROLES:
                logger.warning(
                    "Papel opcional sem modelo elegível: desligado nesta sessão",
                    extra={"role": role, "politica": politica},
                )
                continue
            if isinstance(exc, PinError):
                raise  # pin inválido de papel obrigatório segue fatal (strict)
            failures.append(exc)
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
    return resolved


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
    return found


def reset_removed_variables_warning() -> None:
    """Rearma o aviso único (uso em testes)."""
    global _removed_warned
    _removed_warned = False


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
