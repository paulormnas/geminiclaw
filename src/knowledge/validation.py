"""Validação de escritas no grafo contra ``src.knowledge.schema``.

Compartilhada por ``InMemoryGraphStore`` e ``AgeGraphStore`` — a mesma lógica
de validação garante paridade de comportamento entre os testes unitários
(sem banco) e a implementação real (Apache AGE).
"""

from __future__ import annotations

import math
from typing import Any, Callable

from src.knowledge import schema
from src.knowledge.errors import (
    DisallowedRelationError,
    EdgeUpdateNotAllowedError,
    FactWriteNotAllowedError,
    HumanConfirmationRequiredError,
    ImmutableFieldError,
    InvalidEnumValueError,
    InvalidPropertyValueError,
    MissingJustificationError,
    MissingRequiredPropertyError,
    SelfRelationNotAllowedError,
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
    if label == "Hipotese":
        _validate_hypothesis_rules(full_props)
    _validate_exploration_fields(label, full_props)


def _validate_exploration_fields(label: str, props: dict[str, object]) -> None:
    """Estrutura dos campos de v18.7-exploration-limits presentes em ``props`` (criação ou atualização)."""
    if label == "Problema":
        if props.get("criterio_sucesso") is not None:
            _validate_success_criterion(props["criterio_sucesso"])
        if props.get("objetivo_atingido") is not None:
            _validate_achievement_marks(props["objetivo_atingido"])
    elif label == "Hipotese":
        if props.get("concorrente") is not None and not isinstance(props["concorrente"], bool):
            raise InvalidPropertyValueError("Hipotese", "concorrente", "esperado booleano")
        predicao = props.get("predicao")
        if predicao is not None:
            from src import config

            if not isinstance(predicao, str) or len(predicao) > config.HYPOTHESIS_TEXT_MAX_CHARS:
                raise InvalidPropertyValueError(
                    "Hipotese", "predicao", f"esperado texto de até {config.HYPOTHESIS_TEXT_MAX_CHARS} caracteres"
                )
    elif label == "Experimento" and props.get("conferencia_predicoes") is not None:
        _validate_prediction_check(props["conferencia_predicoes"])
    elif label == "Restricao" and props.get("abordagens") is not None:
        values = props["abordagens"]
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise InvalidPropertyValueError("Restricao", "abordagens", "esperada lista de textos não vazios")


def _validate_success_criterion(value: object) -> None:
    """``criterio_sucesso`` por tipo de objetivo (design §4.1). Sem ``tipo`` (Problema anterior): lido como ``limiar``
    e não revalidado, para que atualizar outra propriedade continue aceito."""
    if not isinstance(value, dict):
        raise InvalidPropertyValueError("Problema", "criterio_sucesso", "esperado um mapa")
    if "tipo" not in value:
        _validate_objective_policy(value)
        return
    kind = value["tipo"]
    if kind not in schema.TIPOS_OBJETIVO:
        raise InvalidEnumValueError("Problema", "criterio_sucesso.tipo", kind, schema.TIPOS_OBJETIVO)
    _validate_objective_policy(value)
    required, forbidden = schema.CAMPOS_OBJETIVO_POR_TIPO[kind]
    for name in sorted(forbidden & set(value)):
        raise InvalidPropertyValueError("Problema", f"criterio_sucesso.{name}", f"não vale no tipo '{kind}'")
    for name in sorted(required):
        if value.get(name) in (None, "", []):
            raise MissingRequiredPropertyError("Problema", f"criterio_sucesso.{name}")
    if kind == "discriminacao":
        rivals = value["hipoteses_concorrentes"]
        if not isinstance(rivals, list) or len(rivals) < 2:
            raise InvalidPropertyValueError(
                "Problema", "criterio_sucesso.hipoteses_concorrentes", "esperada lista com ao menos 2 itens"
            )
        for item in rivals:
            if not isinstance(item, dict) or not isinstance(item.get("predicao"), str) or not item["predicao"].strip():
                raise InvalidPropertyValueError(
                    "Problema", "criterio_sucesso.hipoteses_concorrentes", "cada item exige 'predicao' não vazia"
                )


def _validate_objective_policy(criterion: dict[str, object]) -> None:
    policy = criterion.get("ao_atingir_objetivo")
    if policy is not None and policy not in schema.POLITICAS_OBJETIVO:
        raise InvalidEnumValueError(
            "Problema", "criterio_sucesso.ao_atingir_objetivo", policy, schema.POLITICAS_OBJETIVO
        )
    author = criterion.get("definido_por")
    if author is not None and author not in schema.DEFINIDO_POR_OBJETIVO:
        raise InvalidEnumValueError("Problema", "criterio_sucesso.definido_por", author, schema.DEFINIDO_POR_OBJETIVO)


def _validate_achievement_marks(value: object) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise InvalidPropertyValueError("Problema", "objetivo_atingido", "esperada lista de marcos")


def _validate_prediction_check(value: object) -> None:
    if not isinstance(value, dict):
        raise InvalidPropertyValueError(
            "Experimento", "conferencia_predicoes", "esperado mapa hipotese_id -> conferência"
        )
    for hypothesis_id, check in value.items():
        if check not in schema.CONFERENCIAS_PREDICAO:
            raise InvalidEnumValueError(
                "Experimento", f"conferencia_predicoes.{hypothesis_id}", check, schema.CONFERENCIAS_PREDICAO
            )


_REFERENCE_KEYS = frozenset({"valor", "origem_referencia", "metrica_id", "resultado_id", "fixada_em"})


def _validate_hypothesis_rules(props: dict[str, object]) -> None:
    """Regras condicionais da ``Hipotese`` (v18.7-graph-exploration-relations, design §2.2).

    A hipótese do sistema nasce com ``chave_estruturada`` e ``referencia_fixada``; as duas só existem nela.
    """
    is_system = props.get("origem") == schema.ORIGEM_SISTEMA
    for name in ("chave_estruturada", "referencia_fixada"):
        if is_system and props.get(name) is None:
            raise MissingRequiredPropertyError("Hipotese", name)
        if not is_system and name in props:
            raise InvalidPropertyValueError("Hipotese", name, "só existe em hipótese de origem 'sistema'")
    if is_system:
        _validate_structured_key(props["chave_estruturada"])
        _validate_fixed_reference(props["referencia_fixada"])
    _validate_abandonment_reason(props.get("motivo_abandono"))


def _validate_structured_key(value: object) -> None:
    """``"<problema_id>|<abordagem_id>|<metrica_id>"``, cada componente um identificador conferido no grafo."""
    parts = value.split("|") if isinstance(value, str) else []
    if len(parts) != 3 or not all(schema.IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise InvalidPropertyValueError(
            "Hipotese", "chave_estruturada", "esperado '<problema_id>|<abordagem_id>|<metrica_id>' com identificadores"
        )


def _validate_fixed_reference(value: object) -> None:
    """Forma de ``referencia_fixada``: chaves conhecidas, ``valor`` finito ou ``null`` e origem no enum."""
    if not isinstance(value, dict):
        raise InvalidPropertyValueError("Hipotese", "referencia_fixada", "esperado um mapa")
    unknown = set(value) - _REFERENCE_KEYS
    if unknown:
        raise InvalidPropertyValueError("Hipotese", f"referencia_fixada.{sorted(unknown)[0]}", "chave desconhecida")
    if "valor" not in value:
        raise MissingRequiredPropertyError("Hipotese", "referencia_fixada.valor")
    number = value["valor"]
    if number is not None and (
        isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)
    ):
        raise InvalidPropertyValueError("Hipotese", "referencia_fixada.valor", "esperado número finito ou null")
    origin = value.get("origem_referencia")
    if origin not in schema.ORIGENS_REFERENCIA:
        raise InvalidEnumValueError(
            "Hipotese", "referencia_fixada.origem_referencia", origin, schema.ORIGENS_REFERENCIA
        )
    for required in ("metrica_id", "fixada_em"):
        if not isinstance(value.get(required), str) or not value[required]:
            raise MissingRequiredPropertyError("Hipotese", f"referencia_fixada.{required}")
    has_result = value.get("resultado_id") is not None
    if origin == "referencia_medida" and not has_result:
        raise MissingRequiredPropertyError("Hipotese", "referencia_fixada.resultado_id")
    if origin != "referencia_medida" and has_result:
        raise InvalidPropertyValueError(
            "Hipotese", "referencia_fixada.resultado_id", "só existe com origem_referencia 'referencia_medida'"
        )
    if number is None and origin != "indisponivel":
        raise InvalidPropertyValueError(
            "Hipotese", "referencia_fixada.valor", "null só com origem_referencia 'indisponivel'"
        )


def _validate_abandonment_reason(value: object) -> None:
    if value is not None and (not isinstance(value, str) or len(value) > schema.MOTIVO_ABANDONO_MAX_CHARS):
        raise InvalidPropertyValueError(
            "Hipotese", "motivo_abandono", f"esperado texto de até {schema.MOTIVO_ABANDONO_MAX_CHARS} caracteres"
        )


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
        if field_name in schema.IMMUTABLE_NODE_FIELDS or field_name in schema.IMMUTABLE_LABEL_FIELDS.get(label, ()):
            raise ImmutableFieldError(field_name)
        prop_schema = property_schemas.get(field_name)
        if prop_schema is None:
            raise UnknownPropertyError(label, field_name)
        if prop_schema.enum is not None and value is not None and value not in prop_schema.enum:
            raise InvalidEnumValueError(label, field_name, value, prop_schema.enum)
        if label == "Hipotese" and field_name == "motivo_abandono":
            _validate_abandonment_reason(value)
    _validate_exploration_fields(label, changes)


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
# v18.7-graph-exploration-relations: só o pesquisador grava o abandono que bloqueia novos testes (``abandonada_por``).
HUMAN_ONLY_TRANSITIONS: dict[str, tuple[str, str]] = {
    "Problema": ("status", "confirmado"),
    "Hipotese": ("abandonada_por", "pesquisador"),
}


# Allowlist do que um AGENTE (Curator, Researcher...) pode escrever em campos de decisão do pesquisador
# (v17-curator-agent; revisão do PR #106): rótulo -> campo -> valores permitidos (``None`` = nenhum valor é permitido).
# Termos do vocabulário só nascem ``candidato`` e Oportunidades só ``documentada``; aprovar, rejeitar, investigar ou
# concluir (e os ``decidido_*``/``motivo_decisao``) é do humano. O orquestrador segue semeando o vocabulário aprovado.
AGENT_ALLOWED_VALUES: dict[str, dict[str, tuple[str, ...] | None]] = {
    "Dominio": {"status": ("candidato",), "motivo_decisao": None},
    "Metrica": {"status": ("candidato",), "motivo_decisao": None},
    # v18.5-operation-metrics: a marcação do modo sem limite é decisão do pesquisador (agentes: nenhum valor).
    "Projeto": {"modo_sem_limite": None, "modo_sem_limite_decidido_em": None, "modo_sem_limite_decidido_por": None},
    # v18.7-exploration-limits: os marcos de objetivo atingido são do orquestrador.
    "Problema": {"objetivo_atingido": None},
    "Oportunidade": {
        "status": ("documentada",),
        "decidido_por": None,
        "decidido_em": None,
        "motivo_decisao": None,
    },
}
# Fatos estruturais (ADR 015 §1, project.md): escritos só pela ingestão determinística; agente nunca os cria nem altera.
FACT_LABELS: frozenset[str] = frozenset({"Sessao", "Insumo", "Experimento", "Resultado"})
# v18.9-result-records (ADR 026 §4): o ``RegistroResultado`` é fato do orquestrador, exceto a qualificação que o Curator
# escreve. Rótulo -> únicos campos que um agente pode alterar (a criação é sempre do orquestrador).
AGENT_WRITABLE_FIELDS: dict[str, frozenset[str]] = {
    "RegistroResultado": frozenset({"qualificacao", "limite_aplicabilidade", "licao"}),
}
# Nós rejeitados pelo pesquisador são imutáveis para agentes: a decisão humana não é reaberta por LLM.
REJECTED_STATUSES: frozenset[str] = frozenset({"rejeitado", "rejeitada"})


def validate_human_only(
    label: str,
    *,
    current: dict[str, object] | None,
    changes: dict[str, object],
    actor_kind: str,
    actor_role: str | None = None,
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
        actor_role: ``Actor.role``; só ``REVERT_ON_REOPEN_ROLE`` (revisão dos efeitos de ``sync_statuses``) importa.

    Raises:
        HumanConfirmationRequiredError: Escrita fora do pesquisador que cria com o valor
            protegido, entra nele ou sai dele; ou escrita de agente num campo reservado ou num nó rejeitado.
    """
    if actor_kind == "agente":
        if label in FACT_LABELS:
            raise FactWriteNotAllowedError(label, actor_kind)
        writable = AGENT_WRITABLE_FIELDS.get(label)
        if writable is not None and (current is None or not set(changes) <= writable):
            raise FactWriteNotAllowedError(label, actor_kind)
        _validate_agent_reserved(label, current, changes)
    if label == "Oportunidade" and actor_kind == "orquestrador":
        _validate_opportunity_orchestrator(current, changes, revert_on_reopen=actor_role == REVERT_ON_REOPEN_ROLE)
    if label == "Restricao" and actor_kind != "pesquisador":
        # Fechado a agentes e ao orquestrador; o caminho da sessão (pedido ``restringir_direcao`` consumido) é de 7.5.
        raise HumanConfirmationRequiredError(label, "status", actor_kind)
    if label == "Problema" and "criterio_sucesso" in changes and actor_kind != "pesquisador":
        _validate_objective_authority(current, changes["criterio_sucesso"], actor_kind)
    rule = HUMAN_ONLY_TRANSITIONS.get(label)
    if rule is None or actor_kind == "pesquisador":
        return
    if label == "Hipotese":
        _validate_hypothesis_reopening(current, changes, actor_kind)
    field, protected = rule
    if field not in changes:
        return
    new = changes[field]
    old = (current or {}).get(field)
    if new == protected or (old == protected and new != protected):
        raise HumanConfirmationRequiredError(label, field, actor_kind)


_RESTRICTION_WITHDRAWAL_FIELDS = frozenset({"status", "abandonada_por", "motivo_abandono"})


def validate_derived_authority(
    label: str,
    changes: dict[str, object],
    *,
    restriction_id: str | None,
    request_id: int | None,
    lookup: Callable[[str], Any],
) -> None:
    """Confere a autoridade derivada do ``Actor`` pesquisador (parecer de segurança, itens 2 e 3).

    - ``restriction_id``: só a retirada de uma ``Hipotese`` (``abandonada`` / ``abandonada_por = "pesquisador"`` /
      ``motivo_abandono = "direcao_restrita:<id>"``), e só se a ``Restricao`` existe, é do pesquisador e está ``ativa``.
    - ``request_id``: a criação de ``Restricao``, com ``pedido_id`` igual ao pedido consumido, ou a revisão do
      ``criterio_sucesso`` do ``Problema`` autorizada pelo pesquisador (único campo).

    Raises:
        HumanConfirmationRequiredError: A derivação não cabe nesta escrita.
    """
    if restriction_id is not None:
        node = lookup(restriction_id)
        props = node.properties if node is not None and node.label == "Restricao" else {}
        valid = (
            label == "Hipotese"
            and props.get("decidida_por") == "pesquisador"
            and props.get("status") == "ativa"
            and set(changes) <= _RESTRICTION_WITHDRAWAL_FIELDS
            and changes.get("status") == "abandonada"
            and changes.get("abandonada_por") == "pesquisador"
            and changes.get("motivo_abandono") == f"direcao_restrita:{restriction_id}"
        )
        if not valid:
            raise HumanConfirmationRequiredError(label, "restricao_id", "pesquisador derivado de restrição")
    if request_id is not None:
        if label == "Problema" and set(changes) == {"criterio_sucesso"}:
            return  # revisão do objetivo autorizada pelo pesquisador (pedido ``confirmar_problema`` consumido)
        if label != "Restricao" or changes.get("pedido_id") != request_id:
            field = "pedido_id" if label == "Restricao" else "status"
            raise HumanConfirmationRequiredError(label, field, "pesquisador derivado de pedido")


def _validate_objective_authority(current: dict[str, object] | None, new: object, actor_kind: str) -> None:
    """Política ao atingir e ``definido_por = "pesquisador"`` são do pesquisador (ADR 021 §5.2, §5.3).

    O orquestrador também não substitui um critério já definido pelo pesquisador.
    """
    new_criterion = new if isinstance(new, dict) else {}
    old = (current or {}).get("criterio_sucesso")
    old_criterion = old if isinstance(old, dict) else {}
    if old_criterion.get("definido_por") == "pesquisador" and new_criterion != old_criterion:
        raise HumanConfirmationRequiredError("Problema", "criterio_sucesso", actor_kind)
    if new_criterion.get("definido_por") == "pesquisador":
        raise HumanConfirmationRequiredError("Problema", "criterio_sucesso.definido_por", actor_kind)
    if new_criterion.get("ao_atingir_objetivo") != old_criterion.get("ao_atingir_objetivo"):
        raise HumanConfirmationRequiredError("Problema", "criterio_sucesso.ao_atingir_objetivo", actor_kind)


def _validate_hypothesis_reopening(
    current: dict[str, object] | None, changes: dict[str, object], actor_kind: str
) -> None:
    """Só o pesquisador tira do estado ``abandonada`` uma hipótese que ele mesmo abandonou (ADR 021 §3.5, §6)."""
    if current is None or current.get("abandonada_por") != "pesquisador" or "status" not in changes:
        return
    if changes["status"] != current.get("status") and changes["status"] != "abandonada":
        raise HumanConfirmationRequiredError("Hipotese", "status", actor_kind)


def validate_not_self_relation(rel_type: str, src_id: str, dst_id: str) -> None:
    """``DERIVADA_DE`` não liga uma hipótese a ela mesma (ciclos longos não são verificados; design §3).

    Raises:
        SelfRelationNotAllowedError: Origem e destino são o mesmo nó.
    """
    if rel_type == "DERIVADA_DE" and src_id == dst_id:
        raise SelfRelationNotAllowedError(rel_type, src_id)


# Transições de ``Oportunidade`` que o orquestrador pode fazer sozinho, só depois da aprovação do pesquisador
# (v18-hypothesis-loop §7): ``aprovada -> em_investigacao`` (virou hipótese) e ``em_investigacao -> concluida``.
OPPORTUNITY_ORCHESTRATOR_TRANSITIONS: dict[str, str] = {"em_investigacao": "aprovada", "concluida": "em_investigacao"}
OPPORTUNITY_DECISION_FIELDS: tuple[str, ...] = ("decidido_por", "decidido_em", "motivo_decisao")
# v18.7-hypothesis-linking (ADR 021 §4.4; parecer de segurança, item 3): a reversão ``concluida -> em_investigacao``
# vale só para o orquestrador com este papel, passado exclusivamente pela revisão dos efeitos de ``sync_statuses`` ao
# fim do ciclo (hipótese concluída que reabre). Nenhuma ferramenta de agente nem campo do plano constrói este ``Actor``.
REVERT_ON_REOPEN_ROLE = "revert_on_reopen"


def _validate_opportunity_orchestrator(
    current: dict[str, object] | None, changes: dict[str, object], *, revert_on_reopen: bool = False
) -> None:
    """O orquestrador nunca decide sobre ``Oportunidade``: aprovar e rejeitar são do pesquisador (CLI).

    Ele só cria ``documentada`` e só avança uma oportunidade **já aprovada pelo pesquisador** (``aprovada`` ->
    ``em_investigacao`` -> ``concluida``). Os campos ``decidido_*`` e ``motivo_decisao`` são sempre do humano.
    """
    for field in OPPORTUNITY_DECISION_FIELDS:
        if field in changes:
            raise HumanConfirmationRequiredError("Oportunidade", field, "orquestrador")
    if "status" not in changes:
        return
    new = changes["status"]
    old = (current or {}).get("status")
    if current is None:
        if new != "documentada":
            raise HumanConfirmationRequiredError("Oportunidade", "status", "orquestrador")
        return
    if new == old:
        return
    if revert_on_reopen and old == "concluida" and new == "em_investigacao":
        return
    required_previous = OPPORTUNITY_ORCHESTRATOR_TRANSITIONS.get(str(new))
    if required_previous is None or old != required_previous:
        raise HumanConfirmationRequiredError("Oportunidade", "status", "orquestrador")


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
