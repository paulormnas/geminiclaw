"""Catálogo versionado de modelos e papéis (ADR 017 §1, §8, §9).

Carrega ``src/llm/catalog.yaml`` com ``yaml.safe_load`` e o valida por esquema estrito antes de
qualquer chamada de LLM. Um ``catalog.local.yaml`` opcional (caminho em
``LLM_CATALOG_LOCAL_PATH``) só pode **acrescentar** modelos: não redeclara ``id`` existente e
não tem ``papeis``. Todo erro de validação cita o arquivo, o caminho do campo e o ``id``.

O catálogo efetivo recebe ``hash`` (sha256 do arquivo versionado concatenado ao local, se
houver), usado no banner, no payload da sessão e na telemetria.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.llm.endpoints import EndpointError, is_private_host, validate_remote_endpoint  # noqa: F401
from src.logger import get_logger

logger = get_logger(__name__)

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")
DEFAULT_LOCAL_PATH = Path(__file__).with_name("catalog.local.yaml")

REQUIRED_ROLES: tuple[str, ...] = (
    "researcher", "developer", "reviewer", "summarizer", "validator", "curator", "base",
)
# Papéis que não impedem a sessão quando não há modelo elegível (a resolução os omite e o papel fica desligado): o
# Curator (v17-curator-agent) nunca pode derrubar uma sessão (ADR 014 §4).
OPTIONAL_ROLES: tuple[str, ...] = ("curator",)
TRUST_VALUES: tuple[str, ...] = ("self_hosted", "third_party")
# Provedores que só existem em nuvem: `trust: self_hosted` seria um rótulo falso que contornaria
# `LLM_DATA_POLICY=self_hosted_only` (ADR 017 §3, §8). `ollama` e `openai_compatible` podem ser locais.
CLOUD_ONLY_PROVIDERS: frozenset[str] = frozenset({"google", "anthropic", "openai"})

_TOP_KEYS = {"versao", "modelos", "papeis", "aliases_papel"}
_LOCAL_KEYS = {"modelos"}
_MODEL_KEYS = {"id", "provedor", "trust", "ferramentas", "saida_estruturada", "janela_contexto"}
_ROLE_KEYS = {"requisitos", "preferencia"}
_REQUIREMENT_KEYS = {"ferramentas", "saida_estruturada", "janela_contexto_min"}


class CatalogError(ValueError):
    """Catálogo inválido: a inicialização deve parar com esta mensagem."""


@dataclass(frozen=True)
class ModelEntry:
    """Fatos filtráveis de um modelo do catálogo."""

    id: str
    provedor: str
    modelo: str
    trust: str
    ferramentas: bool
    saida_estruturada: bool
    janela_contexto: int


@dataclass(frozen=True)
class RoleSpec:
    """Requisitos e ordem de preferência de um papel."""

    papel: str
    requisitos: Mapping[str, Any]
    preferencia: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    """Catálogo efetivo (versionado + local) já validado."""

    versao: int
    modelos: Mapping[str, ModelEntry]
    papeis: Mapping[str, RoleSpec]
    aliases_papel: Mapping[str, str]
    hash: str
    local: bool = False
    local_path: str | None = None

    def normalize_role(self, papel: str) -> str:
        """Aplica ``aliases_papel`` e valida o papel (``planner`` -> ``researcher``)."""
        normalized = papel.strip().lower()
        normalized = self.aliases_papel.get(normalized, normalized)
        if normalized not in self.papeis:
            valid = ", ".join(sorted(self.papeis))
            raise ValueError(f"Papel desconhecido para ModelRouter: '{papel}'. Papéis válidos suportados: {valid}.")
        return normalized

    @property
    def short_hash(self) -> str:
        return self.hash[:8]


def split_model_id(model_id: str) -> tuple[str, str]:
    """Divide ``provedor/modelo`` no primeiro ``/`` (o nome do modelo pode ter outras barras)."""
    provider, sep, model = model_id.partition("/")
    if not sep or not provider or not model:
        raise ValueError(f"id de modelo '{model_id}' fora do formato provedor/modelo")
    return provider, model


def _fail(source: str, path: str, message: str, model_id: str | None = None) -> CatalogError:
    where = f"{source}: {path}" if path else source
    suffix = f" (id: {model_id})" if model_id else ""
    return CatalogError(f"Catálogo inválido em {where}: {message}{suffix}")


def _check_keys(
    data: Mapping[str, Any], allowed: set[str], source: str, path: str, model_id: str | None = None
) -> None:
    for key in data:
        if key not in allowed:
            raise _fail(source, f"{path}.{key}" if path else str(key), f"chave desconhecida '{key}'", model_id)


class _UniqueKeyLoader(yaml.SafeLoader):
    """``safe_load`` que recusa chave repetida no mesmo mapeamento (a última venceria em silêncio)."""

    def construct_mapping(self, node, deep=False):  # noqa: ANN001
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"chave duplicada '{key}'", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep)


def _load_yaml(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        data = yaml.load(raw, Loader=_UniqueKeyLoader)  # noqa: S506 — subclasse de SafeLoader
    except yaml.YAMLError as exc:
        detail = f": {exc.problem}" if isinstance(exc, yaml.MarkedYAMLError) and exc.problem else ""
        line = f" (linha {exc.problem_mark.line + 1})" if getattr(exc, "problem_mark", None) else ""
        raise _fail(str(path), "", f"YAML inválido ({type(exc).__name__}{detail}){line}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise _fail(str(path), "", "o documento precisa ser um mapeamento")
    return data, raw


def _parse_models(
    raw_models: Any, source: str, registered: set[str], seen: dict[str, str]
) -> dict[str, ModelEntry]:
    if not isinstance(raw_models, list):
        raise _fail(source, "modelos", "precisa ser uma lista")
    parsed: dict[str, ModelEntry] = {}
    for index, item in enumerate(raw_models):
        path = f"modelos[{index}]"
        if not isinstance(item, dict):
            raise _fail(source, path, "cada modelo precisa ser um mapeamento")
        model_id = item.get("id")
        shown_id = model_id if isinstance(model_id, str) else None
        _check_keys(item, _MODEL_KEYS, source, path, shown_id)
        for key in _MODEL_KEYS:
            if key not in item:
                raise _fail(source, f"{path}.{key}", f"campo obrigatório '{key}' ausente", shown_id)
        if not isinstance(model_id, str):
            raise _fail(source, f"{path}.id", "precisa ser texto", None)
        try:
            prefix, model = split_model_id(model_id)
        except ValueError as exc:
            raise _fail(source, f"{path}.id", str(exc), model_id) from exc
        provider = item["provedor"]
        if provider != prefix:
            raise _fail(
                source, f"{path}.provedor", f"provedor '{provider}' difere do prefixo do id '{prefix}'", model_id
            )
        if provider not in registered:
            raise _fail(
                source,
                f"{path}.provedor",
                f"provedor '{provider}' não registrado; provedores registrados: {', '.join(sorted(registered))}",
                model_id,
            )
        if item["trust"] not in TRUST_VALUES:
            raise _fail(source, f"{path}.trust", f"trust '{item['trust']}' fora de {list(TRUST_VALUES)}", model_id)
        for flag in ("ferramentas", "saida_estruturada"):
            if not isinstance(item[flag], bool):
                raise _fail(source, f"{path}.{flag}", "precisa ser booleano", model_id)
        window = item["janela_contexto"]
        if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
            raise _fail(source, f"{path}.janela_contexto", "precisa ser inteiro positivo", model_id)
        if model_id in seen:
            raise _fail(source, f"{path}.id", f"id duplicado (já declarado em {seen[model_id]})", model_id)
        if item["trust"] == "self_hosted" and provider in CLOUD_ONLY_PROVIDERS:
            raise _fail(
                source,
                f"{path}.trust",
                f"provedor de nuvem '{provider}' não pode ser 'self_hosted' (use 'third_party')",
                model_id,
            )
        seen[model_id] = source
        parsed[model_id] = ModelEntry(
            id=model_id,
            provedor=provider,
            modelo=model,
            trust=item["trust"],
            ferramentas=item["ferramentas"],
            saida_estruturada=item["saida_estruturada"],
            janela_contexto=window,
        )
    return parsed


def _parse_roles(raw_roles: Any, source: str, models: Mapping[str, ModelEntry]) -> dict[str, RoleSpec]:
    if not isinstance(raw_roles, dict):
        raise _fail(source, "papeis", "precisa ser um mapeamento")
    roles: dict[str, RoleSpec] = {}
    for name, spec in raw_roles.items():
        path = f"papeis.{name}"
        if not isinstance(spec, dict):
            raise _fail(source, path, "precisa ser um mapeamento")
        _check_keys(spec, _ROLE_KEYS, source, path)
        requirements = spec.get("requisitos") or {}
        if not isinstance(requirements, dict):
            raise _fail(source, f"{path}.requisitos", "precisa ser um mapeamento")
        _check_keys(requirements, _REQUIREMENT_KEYS, source, f"{path}.requisitos")
        for key, value in requirements.items():
            if key == "janela_contexto_min":
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise _fail(source, f"{path}.requisitos.{key}", "precisa ser inteiro positivo")
            elif not isinstance(value, bool):
                raise _fail(source, f"{path}.requisitos.{key}", "precisa ser booleano")
        preference = spec.get("preferencia")
        if not isinstance(preference, list) or not preference:
            raise _fail(source, f"{path}.preferencia", f"papel '{name}' sem nenhum modelo na preferência")
        for model_id in preference:
            if model_id not in models:
                raise _fail(
                source, f"{path}.preferencia", f"cita id inexistente '{model_id}'", str(model_id)
            )
        roles[name] = RoleSpec(papel=name, requisitos=dict(requirements), preferencia=tuple(preference))
    for required in REQUIRED_ROLES:
        if required not in roles:
            raise _fail(source, f"papeis.{required}", f"papel obrigatório '{required}' ausente")
    return roles


def _parse_aliases(raw: Any, source: str, roles: Mapping[str, RoleSpec]) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _fail(source, "aliases_papel", "precisa ser um mapeamento")
    for alias, target in raw.items():
        if target not in roles:
            raise _fail(source, f"aliases_papel.{alias}", f"aponta para papel inexistente '{target}'")
    return {str(alias).lower(): target for alias, target in raw.items()}


def load_catalog(
    path: Path | str | None = None,
    local_path: Path | str | None = None,
    *,
    registered_providers: set[str] | None = None,
    base_urls: Mapping[str, str | None] | None = None,
) -> Catalog:
    """Carrega e valida o catálogo efetivo.

    Args:
        path: Catálogo versionado (padrão: ``src/llm/catalog.yaml``).
        local_path: Catálogo local opcional (padrão: ``LLM_CATALOG_LOCAL_PATH`` ou
            ``src/llm/catalog.local.yaml``); ignorado se o arquivo não existir.
        registered_providers: Provedores registrados (padrão: ``registry.available_providers()``).
        base_urls: Endpoints por provedor a validar (padrão: os configurados no ambiente). Todo
            provedor com ``base_url`` e ao menos um modelo no catálogo efetivo é validado: fora de
            loopback/rede privada, só ``https``.

    Raises:
        CatalogError: Qualquer violação do esquema, com arquivo, campo e ``id``.
    """
    # Import com efeito colateral: popula o registro de provedores.
    import src.llm.providers  # noqa: F401
    from src import config
    from src.llm import registry

    registered = set(registered_providers) if registered_providers is not None else set(registry.available_providers())

    main_path = Path(path) if path is not None else CATALOG_PATH
    data, raw = _load_yaml(main_path)
    source = str(main_path)
    _check_keys(data, _TOP_KEYS, source, "")
    version = data.get("versao")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _fail(source, "versao", "precisa ser inteiro >= 1")
    seen: dict[str, str] = {}
    models = _parse_models(data.get("modelos", []), source, registered, seen)

    digest_input = raw
    local_used: str | None = None
    if local_path is None:
        local_path = config.LLM_CATALOG_LOCAL_PATH or DEFAULT_LOCAL_PATH
    local_file = Path(local_path)
    if local_file.is_file():
        local_data, local_raw = _load_yaml(local_file)
        local_source = str(local_file)
        if "papeis" in local_data:
            raise _fail(local_source, "papeis", "o catálogo local só pode ter a chave 'modelos'")
        _check_keys(local_data, _LOCAL_KEYS, local_source, "")
        models.update(_parse_models(local_data.get("modelos", []), local_source, registered, seen))
        digest_input = raw + local_raw
        local_used = local_source
        logger.warning(
            "Catálogo local de modelos carregado",
            extra={"path": local_source, "sha256": hashlib.sha256(local_raw).hexdigest()},
        )

    roles = _parse_roles(data.get("papeis"), source, models)
    aliases = _parse_aliases(data.get("aliases_papel"), source, roles)

    for provider in sorted({entry.provedor for entry in models.values()}):
        base_url = base_urls.get(provider) if base_urls is not None else registry.resolve_base_url(provider)
        if base_url:
            try:
                validate_remote_endpoint(provider, base_url, registry.base_url_env_name(provider))
            except EndpointError as exc:
                raise CatalogError(str(exc)) from exc

    return Catalog(
        versao=version,
        modelos=models,
        papeis=roles,
        aliases_papel=aliases,
        hash=hashlib.sha256(digest_input).hexdigest(),
        local=local_used is not None,
        local_path=local_used,
    )
