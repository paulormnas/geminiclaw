"""Schema declarativo do grafo de conhecimento (ADR 015 §2–§5, §11).

Fonte única da verdade para:
    - os 13 tipos de nó, suas propriedades e enumerações;
    - as relações permitidas (par rótulo-origem → tipo → rótulo-destino);
    - as propriedades comuns preenchidas automaticamente pelo ``GraphStore``.

Tanto ``InMemoryGraphStore`` quanto ``AgeGraphStore`` (``src.knowledge.graph_store``)
validam toda escrita contra este módulo — nenhuma outra parte do sistema deve
duplicar estas regras. O script ``scripts/migrate_v17_knowledge.py`` também lê
este módulo para gerar os rótulos (``create_vlabel``/``create_elabel``) da
migração.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PropertySchema:
    """Definição de uma propriedade de nó ou aresta.

    Attributes:
        required: Se True, a propriedade deve estar presente na escrita.
        enum: Se definido, os únicos valores aceitos para a propriedade.
    """

    required: bool = False
    enum: tuple[str, ...] | None = None


@dataclass(frozen=True)
class NodeSchema:
    """Definição de um tipo de nó (rótulo) do grafo.

    Attributes:
        label: Rótulo do nó (ex.: ``"Problema"``).
        properties: Propriedades específicas deste rótulo (além das comuns).
    """

    label: str
    properties: dict[str, PropertySchema] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationSchema:
    """Definição de uma relação permitida entre rótulos.

    Attributes:
        src_labels: Rótulos de origem aceitos.
        rel_type: Tipo da relação (ex.: ``"EXECUTADO_EM"``).
        dst_labels: Rótulos de destino aceitos.
        properties: Propriedades específicas desta relação (além das comuns).
    """

    src_labels: frozenset[str]
    rel_type: str
    dst_labels: frozenset[str]
    properties: dict[str, PropertySchema] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Propriedades comuns
# ---------------------------------------------------------------------------

# Preenchidas pelo GraphStore em toda escrita — nunca aceitas "cruas" do
# chamador para os campos derivados de proveniência (id, criado_em,
# atualizado_em, criado_por); os demais podem ser informados na criação.
COMMON_NODE_PROPERTIES: dict[str, PropertySchema] = {
    "id": PropertySchema(required=True),
    "criado_em": PropertySchema(required=True),
    "atualizado_em": PropertySchema(required=True),
    "criado_por": PropertySchema(required=True),
    "projeto_id": PropertySchema(required=True),
    "sessao_id": PropertySchema(required=True),
    "visibilidade": PropertySchema(required=True, enum=("privado", "compartilhavel")),
    "origem_no": PropertySchema(required=True),
    "versao_schema": PropertySchema(required=True),
}

# Exigidas adicionalmente quando o nó é criado por um agente (Actor.kind ==
# "agente" — ver GraphStore._requires_justification).
AGENT_PROVENANCE_PROPERTIES: dict[str, PropertySchema] = {
    "justificativa_criacao": PropertySchema(required=True),
    "nos_consultados": PropertySchema(required=True),
}

# Campos de proveniência que update_node nunca pode alterar (Requirement
# "Nada é apagado" / Scenario "Campos imutáveis").
IMMUTABLE_NODE_FIELDS: frozenset[str] = frozenset({"id", "criado_em", "criado_por", "projeto_id"})

COMMON_EDGE_PROPERTIES: dict[str, PropertySchema] = {
    "criado_em": PropertySchema(required=True),
    "criado_por": PropertySchema(required=True),
    "origem": PropertySchema(required=True, enum=("fato", "afirmado", "derivado")),
    "evidencias": PropertySchema(required=False),
    "status": PropertySchema(required=True, enum=("confirmada", "contestada")),
}

DEFAULT_VISIBILIDADE = "privado"
DEFAULT_ORIGEM_NO = "local"
DEFAULT_VERSAO_SCHEMA = 1
DEFAULT_EDGE_STATUS = "confirmada"
DEFAULT_EDGE_ORIGEM = "afirmado"


# ---------------------------------------------------------------------------
# Nós (13 tipos — ADR 015 §3)
# ---------------------------------------------------------------------------

NODE_SCHEMAS: dict[str, NodeSchema] = {
    "Projeto": NodeSchema(
        "Projeto",
        {
            "titulo": PropertySchema(required=True),
            "objetivo": PropertySchema(required=True),
            "status": PropertySchema(required=True, enum=("ativo", "pausado", "concluido")),
        },
    ),
    "Sessao": NodeSchema(
        "Sessao",
        {
            "modo": PropertySchema(required=True, enum=("assisted", "semi", "auto")),
            "inicio": PropertySchema(required=True),
            "fim": PropertySchema(),
            "motivo_parada": PropertySchema(
                enum=(
                    "solucao_encontrada",
                    "limite_tokens",
                    "limite_tempo",
                    "limite_retentativas",
                    "limite_conexao",
                    "limite_execucoes",
                    "erro",
                    "interrompida",
                )
            ),
            "consumo": PropertySchema(),
            "no_execucao": PropertySchema(required=True),
        },
    ),
    "Insumo": NodeSchema(
        "Insumo",
        {
            "tipo": PropertySchema(required=True, enum=("artigo", "dataset", "protocolo", "outro")),
            "titulo": PropertySchema(required=True),
            "hash_conteudo": PropertySchema(required=True),
            "caminho": PropertySchema(required=True),
        },
    ),
    "Problema": NodeSchema(
        "Problema",
        {
            "titulo": PropertySchema(required=True),
            "resumo": PropertySchema(required=True),
            "classe": PropertySchema(),
            "caracteristicas_dados": PropertySchema(),
            "criterio_sucesso": PropertySchema(),
            "status": PropertySchema(required=True, enum=("rascunho", "confirmado")),
        },
    ),
    "Hipotese": NodeSchema(
        "Hipotese",
        {
            "enunciado": PropertySchema(required=True),
            "justificativa": PropertySchema(required=True),
            "status": PropertySchema(
                required=True,
                enum=("proposta", "em_teste", "validada", "refutada", "inconclusiva", "abandonada"),
            ),
            "origem": PropertySchema(required=True, enum=("pesquisador", "researcher", "curator", "oportunidade")),
            "suporte": PropertySchema(),
            "certeza": PropertySchema(),
            "veredito": PropertySchema(),
            "n_tentativas": PropertySchema(),
        },
    ),
    "Abordagem": NodeSchema(
        "Abordagem",
        {
            "nome": PropertySchema(required=True),
            "tipo": PropertySchema(
                required=True,
                enum=(
                    "arquitetura",
                    "algoritmo",
                    "teste_estatistico",
                    "pipeline",
                    "protocolo",
                    "instrumento",
                    "biblioteca",
                    "configuracao",
                    "outro",
                ),
            ),
            "descricao": PropertySchema(required=True),
            "versao": PropertySchema(),
            "config_normalizada": PropertySchema(),
            # v17-curator-agent: ``fundida`` marca a duplicata fundida a outra (``FUNDIDA_EM``); ausente = ``ativa``.
            "status": PropertySchema(enum=("ativa", "fundida")),
        },
    ),
    "Experimento": NodeSchema(
        "Experimento",
        {
            "subtarefa_id": PropertySchema(required=True),
            "status": PropertySchema(required=True, enum=("sucesso", "falha", "divergente_documentado")),
            "causa_falha": PropertySchema(enum=("infraestrutura", "abordagem", "ambigua")),
            "assinatura_falha": PropertySchema(),
            "hash_params": PropertySchema(),
            "seed": PropertySchema(),
            "hash_codigo": PropertySchema(),
            "ambiente": PropertySchema(),
            "caminho_artefatos": PropertySchema(required=True),
            "no_execucao": PropertySchema(required=True),
            "dataset_ids": PropertySchema(),
        },
    ),
    "Resultado": NodeSchema(
        "Resultado",
        {
            "nome_original": PropertySchema(required=True),
            "valor": PropertySchema(required=True),
            "unidade": PropertySchema(),
            "baseline": PropertySchema(),
            "status_validacao": PropertySchema(
                required=True, enum=("validado", "divergente_documentado", "nao_validado")
            ),
            "caminho_metrics": PropertySchema(required=True),
        },
    ),
    "Decisao": NodeSchema(
        "Decisao",
        {
            "contexto": PropertySchema(required=True),
            "justificativa": PropertySchema(required=True),
            "criterio": PropertySchema(),
            "resultado_posterior": PropertySchema(),
        },
    ),
    "Descoberta": NodeSchema(
        "Descoberta",
        {
            "tipo": PropertySchema(
                required=True,
                enum=("funciona", "nao_funciona", "condicional", "licao_de_caminho", "caminho_sem_conclusao"),
            ),
            "enunciado": PropertySchema(required=True),
            "condicoes": PropertySchema(),
            # v17-curator-agent: filtro estruturado das tentativas que contam no veredito
            # (``{"dataset_ids": [...], "no_execucao": [...]}``); ``condicoes`` segue sendo o texto legível.
            "filtro_condicoes": PropertySchema(),
            "veredito": PropertySchema(),
            "confianca": PropertySchema(),
            "n_evidencias": PropertySchema(required=True),
            "status": PropertySchema(required=True, enum=("ativa", "contestada", "substituida")),
            "ponto_de_parada": PropertySchema(),
            "motivo": PropertySchema(),
            "proximo_passo_sugerido": PropertySchema(),
        },
    ),
    "Oportunidade": NodeSchema(
        "Oportunidade",
        {
            "enunciado": PropertySchema(required=True),
            "justificativa": PropertySchema(required=True),
            "status": PropertySchema(
                required=True,
                enum=("documentada", "aprovada", "rejeitada", "em_investigacao", "concluida"),
            ),
            "decidido_por": PropertySchema(),
            "decidido_em": PropertySchema(),
            "motivo_decisao": PropertySchema(),
        },
    ),
    "Dominio": NodeSchema(
        "Dominio",
        {
            "termo": PropertySchema(required=True),
            "nivel": PropertySchema(
                required=True, enum=("grande_area", "area", "subarea", "especialidade")
            ),
            "sinonimos": PropertySchema(),
            "sinonimos_candidatos": PropertySchema(),
            "codigo_cnpq": PropertySchema(),
            "status": PropertySchema(required=True, enum=("candidato", "aprovado", "rejeitado")),
            "motivo_decisao": PropertySchema(),
        },
    ),
    "Metrica": NodeSchema(
        "Metrica",
        {
            "nome": PropertySchema(required=True),
            "sinonimos": PropertySchema(),
            "sentido": PropertySchema(required=True, enum=("maior_melhor", "menor_melhor")),
            "unidade": PropertySchema(),
            "faixa": PropertySchema(),
            "familia": PropertySchema(),
            "sinonimos_candidatos": PropertySchema(),
            "status": PropertySchema(required=True, enum=("candidato", "aprovado", "rejeitado")),
            "motivo_decisao": PropertySchema(),
        },
    ),
}

NODE_LABELS: frozenset[str] = frozenset(NODE_SCHEMAS)


def _rel(src: str | tuple[str, ...], rel_type: str, dst: str | tuple[str, ...],
         **props: PropertySchema) -> RelationSchema:
    """Atalho para declarar uma ``RelationSchema`` a partir de rótulos soltos ou tuplas."""
    src_labels = frozenset((src,) if isinstance(src, str) else src)
    dst_labels = frozenset((dst,) if isinstance(dst, str) else dst)
    return RelationSchema(src_labels=src_labels, rel_type=rel_type, dst_labels=dst_labels, properties=props)


_SEMELHANTE_A_PROPS = {
    "score": PropertySchema(required=True),
    "modelo": PropertySchema(required=True),
    "versao": PropertySchema(required=True),
}

# ---------------------------------------------------------------------------
# Relações permitidas (par origem/destino) — ADR 015 §5
# ---------------------------------------------------------------------------

RELATION_SCHEMAS: list[RelationSchema] = [
    _rel("Sessao", "PERTENCE_A", "Projeto"),
    _rel("Sessao", "CONTINUA", "Sessao"),
    _rel("Projeto", "INVESTIGA", "Problema"),
    _rel("Projeto", "RECEBEU", "Insumo"),
    _rel("Experimento", "EXECUTADO_EM", "Sessao"),
    _rel("Experimento", "APLICOU", "Abordagem", config=PropertySchema(), hash_params=PropertySchema()),
    _rel("Experimento", "USOU", "Insumo"),
    _rel("Experimento", "PRODUZIU", "Resultado"),
    _rel("Resultado", "MEDE", "Metrica"),
    _rel("Hipotese", "SOBRE", "Problema"),
    _rel("Hipotese", "PROPOE", "Abordagem"),
    _rel("Hipotese", "DERIVADA_DE", ("Insumo", "Descoberta", "Oportunidade")),
    _rel("Experimento", "TESTA", "Hipotese"),
    _rel("Decisao", "TOMADA_EM", "Sessao"),
    _rel("Decisao", "ESCOLHEU", ("Abordagem", "Hipotese")),
    _rel("Decisao", "DESCARTOU", ("Abordagem", "Hipotese"), motivo=PropertySchema(required=True)),
    _rel("Decisao", "INFORMADA_POR", "Descoberta"),
    _rel("Resultado", "SUSTENTA", "Hipotese", peso=PropertySchema()),
    _rel("Resultado", "REFUTA", "Hipotese", peso=PropertySchema()),
    _rel("Descoberta", "BASEADA_EM", ("Resultado", "Experimento", "Decisao")),
    _rel("Descoberta", "SOBRE", ("Abordagem", "Problema", "Hipotese")),
    _rel("Descoberta", "CONTRADIZ", "Descoberta"),
    _rel("Descoberta", "SUBSTITUI", "Descoberta"),
    _rel(
        "Abordagem", "FUNCIONOU_PARA", "Problema",
        metrica=PropertySchema(required=True),
        melhor_valor=PropertySchema(required=True),
        config=PropertySchema(),
        n_exp=PropertySchema(required=True),
        descoberta_id=PropertySchema(),
    ),
    _rel(
        "Abordagem", "FALHOU_PARA", "Problema",
        motivo=PropertySchema(required=True),
        n_exp=PropertySchema(required=True),
        descoberta_id=PropertySchema(),
    ),
    _rel("Abordagem", "VARIANTE_DE", "Abordagem"),
    # v17-curator-agent: duplicata de abordagem fundida na canônica, sem apagar nenhum nó.
    _rel("Abordagem", "FUNDIDA_EM", "Abordagem"),
    _rel("Abordagem", "COMPONENTE_DE", "Abordagem"),
    _rel("Oportunidade", "ORIGINADA_DE", "Descoberta"),
    _rel("Oportunidade", "SUGERE", ("Abordagem", "Hipotese")),
    _rel("Oportunidade", "PARA", "Problema"),
    _rel("Oportunidade", "GEROU", "Hipotese"),
    _rel(("Projeto", "Problema"), "NO_DOMINIO", "Dominio"),
    _rel("Dominio", "SUBAREA_DE", "Dominio"),
    _rel("Metrica", "RELACIONADA_A", "Metrica"),
    # SEMELHANTE_A: mesmo rótulo para os 5 tipos indicados + Descoberta -> Problema
    *(
        _rel(label, "SEMELHANTE_A", label, **_SEMELHANTE_A_PROPS)
        for label in ("Projeto", "Problema", "Abordagem", "Descoberta", "Oportunidade")
    ),
    _rel("Descoberta", "SEMELHANTE_A", "Problema", **_SEMELHANTE_A_PROPS),
]


def find_relation_schema(src_label: str, rel_type: str, dst_label: str) -> RelationSchema | None:
    """Busca a definição de relação que autoriza o triplo (origem, tipo, destino).

    Args:
        src_label: Rótulo do nó de origem.
        rel_type: Tipo da relação (ex.: ``"APLICOU"``).
        dst_label: Rótulo do nó de destino.

    Returns:
        A ``RelationSchema`` correspondente, ou ``None`` se a relação não é permitida.
    """
    for schema in RELATION_SCHEMAS:
        if schema.rel_type != rel_type:
            continue
        if src_label in schema.src_labels and dst_label in schema.dst_labels:
            return schema
    return None


RELATION_TYPES: frozenset[str] = frozenset(r.rel_type for r in RELATION_SCHEMAS)


# ---------------------------------------------------------------------------
# Vetorização (v17-knowledge-semantic-index / ADR 015 §6)
# ---------------------------------------------------------------------------

# Rótulos com ponto no Qdrant (``Sessao``, ``Insumo``, ``Experimento`` e
# ``Resultado`` não são vetorizados).
VECTORIZABLE_LABELS: frozenset[str] = frozenset(
    {"Projeto", "Problema", "Hipotese", "Abordagem", "Descoberta", "Decisao", "Oportunidade", "Dominio", "Metrica"}
)
ESTADO_VETORIZACAO_PENDENTE = "pendente"
ESTADO_VETORIZACAO_OK = "ok"

# Propriedade de sistema ``estado_vetorizacao``: gravada apenas pela camada do
# índice semântico (``src.knowledge.indexed_store``), nunca pelo chamador.
for _label in VECTORIZABLE_LABELS:
    NODE_SCHEMAS[_label] = NodeSchema(
        _label,
        {
            **NODE_SCHEMAS[_label].properties,
            "estado_vetorizacao": PropertySchema(
                enum=(ESTADO_VETORIZACAO_PENDENTE, ESTADO_VETORIZACAO_OK)
            ),
        },
    )

del _label
