"""Validação de escritas no grafo contra ``src.knowledge.schema``.

Compartilhada por ``InMemoryGraphStore`` e ``AgeGraphStore`` — a mesma lógica
de validação garante paridade de comportamento entre os testes unitários
(sem banco) e a implementação real (Apache AGE).
"""

from __future__ import annotations

from src.knowledge import schema
from src.knowledge.errors import (
    DisallowedRelationError,
    ImmutableFieldError,
    InvalidEnumValueError,
    MissingJustificationError,
    MissingRequiredPropertyError,
    UnknownLabelError,
    UnknownPropertyError,
)
from src.knowledge.schema import NodeSchema, PropertySchema, RelationSchema


def validate_label(label: str) -> NodeSchema:
    """Garante que ``label`` é um rótulo de nó conhecido.

    Args:
        label: Rótulo a validar.

    Returns:
        O ``NodeSchema`` correspondente.

    Raises:
        UnknownLabelError: Se o rótulo não existir em ``NODE_SCHEMAS``.
    """
    node_schema = schema.NODE_SCHEMAS.get(label)
    if node_schema is None:
        raise UnknownLabelError(label)
    return node_schema


def _validate_properties_against(
    label: str,
    props: dict[str, object],
    property_schemas: dict[str, PropertySchema],
    *,
    error_scope: str,
) -> None:
    """Valida ``props`` contra um mapa de ``PropertySchema`` (desconhecidas/obrigatórias/enum)."""
    for prop_name, prop_schema in property_schemas.items():
        if prop_schema.required and prop_name not in props:
            raise MissingRequiredPropertyError(label, prop_name)
        if prop_name in props and prop_schema.enum is not None:
            value = props[prop_name]
            if value is not None and value not in prop_schema.enum:
                raise InvalidEnumValueError(label, prop_name, value, prop_schema.enum)

    known_names = set(property_schemas)
    unknown = set(props) - known_names
    if unknown:
        # Reporta a primeira em ordem determinística para mensagens estáveis.
        raise UnknownPropertyError(label, sorted(unknown)[0])


def validate_node_write(
    label: str,
    full_props: dict[str, object],
    *,
    requires_agent_provenance: bool,
) -> None:
    """Valida o conjunto completo de propriedades de um nó (comuns + específicas).

    Espera que o ``GraphStore`` já tenha mesclado ``full_props`` com as
    propriedades comuns de proveniência (``id``, ``criado_em``,
    ``atualizado_em``, ``criado_por``, ``projeto_id``, ``sessao_id``,
    ``visibilidade``, ``origem_no``, ``versao_schema``) antes de chamar esta
    função — os valores de proveniência derivados do ``Actor`` (``id``,
    ``criado_em``, ``atualizado_em``, ``criado_por``) devem já ter
    substituído qualquer valor enviado pelo chamador (autoria não forjável).

    Args:
        label: Rótulo do nó.
        full_props: Propriedades completas (comuns + específicas do rótulo,
            e de proveniência de agente quando aplicável).
        requires_agent_provenance: Se True, exige ``justificativa_criacao``
            não vazia e ``nos_consultados`` presentes.

    Raises:
        UnknownLabelError: Rótulo desconhecido.
        UnknownPropertyError: Propriedade não definida no schema do rótulo.
        MissingRequiredPropertyError: Propriedade obrigatória ausente.
        InvalidEnumValueError: Valor fora da enumeração permitida.
        MissingJustificationError: Nó de agente sem justificativa de criação.
    """
    node_schema = validate_label(label)

    # Checado ANTES da validação genérica de propriedades: quando o problema é
    # especificamente a ausência/vazio de `justificativa_criacao`, o chamador
    # recebe o erro semântico `MissingJustificationError` (mais acionável para
    # quem integra agentes) em vez do genérico `MissingRequiredPropertyError`
    # que a passagem abaixo também levantaria para o mesmo campo.
    if requires_agent_provenance:
        justificativa = full_props.get("justificativa_criacao")
        if not justificativa or not str(justificativa).strip():
            raise MissingJustificationError(label)

    property_schemas: dict[str, PropertySchema] = {
        **schema.COMMON_NODE_PROPERTIES,
        **node_schema.properties,
    }
    if requires_agent_provenance:
        property_schemas = {**property_schemas, **schema.AGENT_PROVENANCE_PROPERTIES}

    _validate_properties_against(label, full_props, property_schemas, error_scope="nó")


def validate_node_update(label: str, changes: dict[str, object]) -> None:
    """Valida uma atualização parcial de nó (``update_node``).

    Diferente de ``validate_node_write``, não exige presença de todas as
    propriedades obrigatórias — apenas que os campos alterados sejam
    conhecidos, mutáveis e, quando aplicável, respeitem a enumeração.

    Args:
        label: Rótulo do nó sendo atualizado.
        changes: Mudanças solicitadas pelo chamador.

    Raises:
        UnknownLabelError: Rótulo desconhecido.
        ImmutableFieldError: Tentativa de alterar ``id``, ``criado_em``,
            ``criado_por`` ou ``projeto_id``.
        UnknownPropertyError: Campo não definido no schema do rótulo.
        InvalidEnumValueError: Valor fora da enumeração permitida.
    """
    node_schema = validate_label(label)
    property_schemas: dict[str, PropertySchema] = {
        **schema.COMMON_NODE_PROPERTIES,
        **node_schema.properties,
        **schema.AGENT_PROVENANCE_PROPERTIES,
    }

    for field_name, value in changes.items():
        if field_name in schema.IMMUTABLE_NODE_FIELDS:
            raise ImmutableFieldError(field_name)
        prop_schema = property_schemas.get(field_name)
        if prop_schema is None:
            raise UnknownPropertyError(label, field_name)
        if prop_schema.enum is not None and value is not None and value not in prop_schema.enum:
            raise InvalidEnumValueError(label, field_name, value, prop_schema.enum)


def validate_edge_write(
    src_label: str,
    rel_type: str,
    dst_label: str,
    full_props: dict[str, object],
) -> RelationSchema:
    """Valida uma aresta contra a whitelist de relações e o conjunto completo de propriedades.

    Espera que o ``GraphStore`` já tenha mesclado ``full_props`` com as
    propriedades comuns de aresta (``criado_em``, ``criado_por``, ``origem``,
    ``evidencias``, ``status``) antes de chamar esta função.

    Args:
        src_label: Rótulo do nó de origem.
        rel_type: Tipo da relação.
        dst_label: Rótulo do nó de destino.
        full_props: Propriedades completas (comuns + específicas da relação).

    Returns:
        A ``RelationSchema`` que autoriza esta aresta.

    Raises:
        DisallowedRelationError: Par (origem, tipo, destino) não permitido.
        UnknownPropertyError: Propriedade não prevista para esta relação.
        MissingRequiredPropertyError: Propriedade obrigatória da relação ausente.
        InvalidEnumValueError: Valor fora da enumeração permitida.
    """
    relation_schema = schema.find_relation_schema(src_label, rel_type, dst_label)
    if relation_schema is None:
        raise DisallowedRelationError(src_label, rel_type, dst_label)

    property_schemas: dict[str, PropertySchema] = {
        **schema.COMMON_EDGE_PROPERTIES,
        **relation_schema.properties,
    }
    _validate_properties_against(
        f"{src_label}-{rel_type}->{dst_label}",
        full_props,
        property_schemas,
        error_scope="aresta",
    )
    return relation_schema
