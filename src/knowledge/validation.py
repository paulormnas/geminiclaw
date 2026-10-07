"""Validação de escritas no grafo contra ``src.knowledge.schema``.

Compartilhada por ``InMemoryGraphStore`` e ``AgeGraphStore`` — a mesma lógica
de validação garante paridade de comportamento entre os testes unitários
(sem banco) e a implementação real (Apache AGE).
"""

from __future__ import annotations

from src.knowledge import schema
from src.knowledge.errors import (
    DisallowedRelationError,
    EdgeUpdateNotAllowedError,
    FactWriteNotAllowedError,
    HumanConfirmationRequiredError,
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


def validate_node_filter_keys(label: str, filters: dict[str, object]) -> NodeSchema:
    """Garante que as chaves de ``filters`` (``GraphStore.find_nodes``) são propriedades conhecidas.

    ``find_nodes`` interpola os *nomes* das chaves de ``filters`` como
    identificadores de propriedade Cypher (``n.{key} = $filters.{key}``) —
    os valores sempre viajam por parâmetro, mas os nomes não. Esta validação
    é o que impede que uma chave arbitrária injete sintaxe Cypher no texto
    da consulta: ela é checada contra o mesmo schema declarativo usado para
    validar escritas, antes de qualquer interpolação.

    Args:
        label: Rótulo do nó sendo buscado.
        filters: Mapa propriedade → valor exigido, informado pelo chamador.

    Returns:
        O ``NodeSchema`` correspondente ao rótulo.

    Raises:
        UnknownLabelError: Rótulo desconhecido.
        UnknownPropertyError: Alguma chave de ``filters`` não é uma
            propriedade conhecida (comum ou específica) do rótulo.
    """
    node_schema = validate_label(label)
    known_names = set(schema.COMMON_NODE_PROPERTIES) | set(node_schema.properties)
    unknown = set(filters) - known_names
    if unknown:
        raise UnknownPropertyError(label, sorted(unknown)[0])
    return node_schema


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


def validate_edge_update(
    src_label: str,
    rel_type: str,
    dst_label: str,
    changes: dict[str, object],
) -> RelationSchema:
    """Valida a atualização de propriedades de uma aresta (``update_edge``).

    Só as propriedades **específicas** da relação (e ``evidencias``) são atualizáveis: a proveniência
    (``criado_em``, ``criado_por``, ``origem``) é imutável e ``status`` só muda por ``set_edge_status``.

    Raises:
        DisallowedRelationError: Par (origem, tipo, destino) não permitido.
        UnknownPropertyError: Propriedade não atualizável.
        InvalidEnumValueError: Valor fora da enumeração permitida.
    """
    relation_schema = schema.find_relation_schema(src_label, rel_type, dst_label)
    if relation_schema is None:
        raise DisallowedRelationError(src_label, rel_type, dst_label)
    updatable: dict[str, PropertySchema] = {
        **relation_schema.properties,
        "evidencias": schema.COMMON_EDGE_PROPERTIES["evidencias"],
    }
    scope = f"{src_label}-{rel_type}->{dst_label}"
    for name, value in changes.items():
        prop_schema = updatable.get(name)
        if prop_schema is None:
            raise UnknownPropertyError(scope, name)
        if prop_schema.enum is not None and value is not None and value not in prop_schema.enum:
            raise InvalidEnumValueError(scope, name, value, prop_schema.enum)
    return relation_schema


# Transições reservadas ao pesquisador: rótulo -> (campo, valor protegido). Não altera o schema:
# a regra vive na porta única de escrita e a trilha fica na auditoria (autor ``pesquisador``).
HUMAN_ONLY_TRANSITIONS: dict[str, tuple[str, str]] = {"Problema": ("status", "confirmado")}


# Allowlist do que um AGENTE (Curator, Researcher...) pode escrever em campos de decisão do pesquisador
# (v17-curator-agent; revisão do PR #106): rótulo -> campo -> valores permitidos (``None`` = nenhum valor é permitido).
# Termos do vocabulário só nascem ``candidato`` e Oportunidades só ``documentada``; aprovar, rejeitar, investigar ou
# concluir (e os ``decidido_*``/``motivo_decisao``) é do humano. O orquestrador segue semeando o vocabulário aprovado.
AGENT_ALLOWED_VALUES: dict[str, dict[str, tuple[str, ...] | None]] = {
    "Dominio": {"status": ("candidato",), "motivo_decisao": None},
    "Metrica": {"status": ("candidato",), "motivo_decisao": None},
    "Oportunidade": {
        "status": ("documentada",),
        "decidido_por": None,
        "decidido_em": None,
        "motivo_decisao": None,
    },
}
# Fatos estruturais (ADR 015 §1, project.md): escritos só pela ingestão determinística; agente nunca os cria nem altera.
FACT_LABELS: frozenset[str] = frozenset({"Sessao", "Insumo", "Experimento", "Resultado"})
# Nós rejeitados pelo pesquisador são imutáveis para agentes: a decisão humana não é reaberta por LLM.
REJECTED_STATUSES: frozenset[str] = frozenset({"rejeitado", "rejeitada"})


def validate_human_only(
    label: str,
    *,
    current: dict[str, object] | None,
    changes: dict[str, object],
    actor_kind: str,
) -> None:
    """Decisões reservadas ao pesquisador: só ele as toma, nenhum agente (nem o orquestrador, no Problema).

    - ``Problema``: só o pesquisador cria, promove ou rebaixa o estado ``confirmado``.
    - Agentes (``actor_kind == "agente"``) não aprovam nem rejeitam ``Dominio``/``Metrica``, não decidem sobre
      ``Oportunidade`` (``AGENT_ALLOWED_VALUES``) e não alteram nós já ``rejeitado``/``rejeitada``.

    Args:
        label: Rótulo do nó.
        current: Propriedades atuais (``None`` em ``create_node``).
        changes: Propriedades da criação ou mudanças do ``update_node``.
        actor_kind: ``Actor.kind`` de quem escreve (recebido explicitamente).

    Raises:
        HumanConfirmationRequiredError: Escrita fora do pesquisador que cria com o valor
            protegido, entra nele ou sai dele; ou escrita de agente num campo reservado ou num nó rejeitado.
    """
    if actor_kind == "agente":
        if label in FACT_LABELS:
            raise FactWriteNotAllowedError(label, actor_kind)
        _validate_agent_reserved(label, current, changes)
    rule = HUMAN_ONLY_TRANSITIONS.get(label)
    if rule is None or actor_kind == "pesquisador":
        return
    field, protected = rule
    if field not in changes:
        return
    new = changes[field]
    old = (current or {}).get(field)
    if new == protected or (old == protected and new != protected):
        raise HumanConfirmationRequiredError(label, field, actor_kind)


def _validate_agent_reserved(label: str, current: dict[str, object] | None, changes: dict[str, object]) -> None:
    """Aplica ``AGENT_RESERVED_FIELDS`` e a imutabilidade dos nós rejeitados a uma escrita de agente."""
    if current is not None and current.get("status") in REJECTED_STATUSES and changes:
        raise HumanConfirmationRequiredError(label, "status", "agente")
    for field, allowed in AGENT_ALLOWED_VALUES.get(label, {}).items():
        if field in changes and (allowed is None or changes[field] not in allowed):
            raise HumanConfirmationRequiredError(label, field, "agente")


# Relações cujas propriedades ``update_edge`` pode alterar: só as derivadas pelo cálculo determinístico. As demais
# (``APLICOU.config`` e ``hash_params`` incluídas) são fatos e nunca são reescritas.
EDGE_UPDATABLE_RELS: frozenset[str] = frozenset({"SUSTENTA", "REFUTA", "FUNCIONOU_PARA", "FALHOU_PARA"})
EDGE_UPDATE_ACTORS: frozenset[str] = frozenset({"orquestrador", "pesquisador"})


def validate_edge_update_policy(rel_type: str, actor_kind: str) -> None:
    """Só o orquestrador (cálculo determinístico) ou o pesquisador atualizam arestas derivadas.

    Raises:
        EdgeUpdateNotAllowedError: Ator de agente ou relação protegida.
    """
    if actor_kind not in EDGE_UPDATE_ACTORS:
        raise EdgeUpdateNotAllowedError(rel_type, actor_kind, "somente o orquestrador ou o pesquisador")
    if rel_type not in EDGE_UPDATABLE_RELS:
        raise EdgeUpdateNotAllowedError(rel_type, actor_kind, "relação protegida (fato ou afirmação)")


def validate_edge_endpoints_mutable(
    src: dict[str, object], dst: dict[str, object], rel_type: str, actor_kind: str
) -> None:
    """Agente não cria nem altera arestas de/para nós ``rejeitado``/``rejeitada`` (decisão humana imutável)."""
    if actor_kind != "agente":
        return
    for props in (src, dst):
        if props.get("status") in REJECTED_STATUSES:
            raise HumanConfirmationRequiredError(rel_type, "status", actor_kind)
