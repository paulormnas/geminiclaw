"""Interface ``GraphStore`` e implementações do grafo de conhecimento (ADR 009, ADR 015).

Este módulo é a **única porta de acesso** ao grafo de conhecimento. Nenhum
outro módulo deve montar Cypher diretamente ou acessar Apache AGE fora
daqui.

Contém:
    - ``Node`` / ``Subgraph``: modelos de leitura devolvidos pelo store.
    - ``GraphStore``: interface abstrata com as operações tipadas de escrita
      e leitura definidas no design da V17.
    - ``InMemoryGraphStore``: implementação sem banco, para testes unitários
      — aplica exatamente as mesmas regras de validação de
      ``src.knowledge.validation``.
    - ``AgeGraphStore``: implementação real sobre Apache AGE/PostgreSQL 16.

``Actor`` está em ``src.knowledge.provenance`` (junto com as regras de
preenchimento de proveniência) e é reexportado aqui por conveniência.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.knowledge import schema, validation
from src.knowledge.errors import NodeNotFoundError
from src.knowledge.provenance import (
    Actor,
    prepare_edge_properties,
    prepare_node_properties,
    prepare_node_update,
)
from src.knowledge.read_guard import reject_unsafe_read_query
from src.logger import get_logger

logger = get_logger(__name__)

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

__all__ = [
    "Actor",
    "Node",
    "Edge",
    "Subgraph",
    "GraphStore",
    "InMemoryGraphStore",
    "AgeGraphStore",
]


@dataclass(frozen=True)
class Node:
    """Nó do grafo devolvido por operações de leitura.

    Attributes:
        id: Identificador estável do nó (UUIDv7, texto).
        label: Rótulo do nó (ex.: ``"Problema"``).
        properties: Todas as propriedades do nó (comuns + específicas).
    """

    id: str
    label: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class Edge:
    """Aresta do grafo devolvida por operações de leitura.

    Attributes:
        src_id: ID do nó de origem.
        rel_type: Tipo da relação (ex.: ``"APLICOU"``).
        dst_id: ID do nó de destino.
        properties: Todas as propriedades da aresta (comuns + específicas).
    """

    src_id: str
    rel_type: str
    dst_id: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class Subgraph:
    """Conjunto de nós e arestas devolvido por ``neighbors``/``project_subgraph``.

    Attributes:
        nodes: Nós do subgrafo.
        edges: Arestas entre esses nós.
    """

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


class GraphStore(ABC):
    """Porta de acesso única ao grafo de conhecimento.

    Toda escrita passa por validação contra ``src.knowledge.schema``
    (rótulo, propriedades, enumerações, relações permitidas) e recebe
    proveniência derivada do ``Actor`` — nunca do conteúdo enviado pelo
    chamador (``src.knowledge.provenance``). Não há operação de remoção:
    correções são mudanças de status (``set_edge_status``) ou novos nós.
    """

    # -- Escrita -----------------------------------------------------------

    @abstractmethod
    def create_node(self, label: str, props: dict[str, Any], *, actor: Actor) -> str:
        """Cria um nó, valida contra o schema e preenche a proveniência.

        Args:
            label: Rótulo do nó (deve existir em ``schema.NODE_SCHEMAS``).
            props: Propriedades específicas do rótulo mais ``projeto_id`` e
                ``sessao_id`` (obrigatórias) e, opcionalmente,
                ``visibilidade``/``origem_no``/``versao_schema``. Quando o
                ator é um agente, requer também ``justificativa_criacao`` e
                ``nos_consultados``.
            actor: Quem está criando o nó.

        Returns:
            O ``id`` (UUIDv7) do nó criado.

        Raises:
            GraphStoreError: Alguma subclasse de validação (rótulo
                desconhecido, propriedade ausente/desconhecida, enum
                inválido, justificativa ausente).
        """

    @abstractmethod
    def update_node(self, node_id: str, changes: dict[str, Any], *, actor: Actor) -> None:
        """Atualiza propriedades mutáveis de um nó existente e audita a mudança.

        Args:
            node_id: ID do nó a atualizar.
            changes: Mapa de propriedades a alterar. Nunca pode conter
                ``id``, ``criado_em``, ``criado_por`` ou ``projeto_id``.
            actor: Quem está realizando a atualização (registrado na
                auditoria, não sobrescreve ``criado_por`` do nó).

        Raises:
            NodeNotFoundError: Nó não existe.
            ImmutableFieldError: ``changes`` tenta alterar campo imutável.
            UnknownPropertyError: Campo desconhecido para o rótulo do nó.
            InvalidEnumValueError: Valor fora da enumeração permitida.
        """

    @abstractmethod
    def create_edge(self, src_id: str, rel: str, dst_id: str, props: dict[str, Any], *, actor: Actor) -> None:
        """Cria uma aresta entre dois nós existentes, validando a whitelist de relações.

        Args:
            src_id: ID do nó de origem.
            rel: Tipo da relação (ex.: ``"APLICOU"``).
            dst_id: ID do nó de destino.
            props: Propriedades específicas da relação.
            actor: Quem está criando a aresta.

        Raises:
            NodeNotFoundError: ``src_id`` ou ``dst_id`` não existem.
            DisallowedRelationError: Par (rótulo origem, rel, rótulo destino) não permitido.
            UnknownPropertyError: Propriedade não prevista para a relação.
            MissingRequiredPropertyError: Propriedade obrigatória da relação ausente.
            InvalidEnumValueError: Valor fora da enumeração permitida.
        """

    @abstractmethod
    def set_edge_status(self, src_id: str, rel: str, dst_id: str, status: str, *, actor: Actor) -> None:
        """Altera o ``status`` de uma aresta existente (única forma de "corrigi-la").

        Args:
            src_id: ID do nó de origem.
            rel: Tipo da relação.
            dst_id: ID do nó de destino.
            status: Novo status (``"confirmada"`` ou ``"contestada"``).
            actor: Quem está realizando a mudança.

        Raises:
            InvalidEnumValueError: ``status`` fora da enumeração permitida.
            GraphStoreError: Aresta não encontrada.
        """

    # -- Leitura -------------------------------------------------------------

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        """Busca um nó pelo ID.

        Args:
            node_id: ID do nó.

        Returns:
            O ``Node``, ou ``None`` se não existir.
        """

    @abstractmethod
    def find_nodes(self, label: str, filters: dict[str, Any], limit: int = 50) -> list[Node]:
        """Busca nós de um rótulo cujas propriedades casam com ``filters`` (igualdade).

        Args:
            label: Rótulo a buscar.
            filters: Mapa propriedade → valor exigido (igualdade exata).
            limit: Número máximo de nós retornados.

        Returns:
            Lista de nós encontrados (pode ser vazia).
        """

    @abstractmethod
    def neighbors(
        self,
        node_id: str,
        rels: list[str] | None,
        direction: str = "both",
        depth: int = 1,
    ) -> Subgraph:
        """Explora a vizinhança de um nó até ``depth`` saltos.

        Args:
            node_id: ID do nó de partida.
            rels: Tipos de relação a considerar, ou ``None`` para qualquer tipo.
            direction: ``"out"``, ``"in"`` ou ``"both"``.
            depth: Profundidade máxima (número de saltos).

        Returns:
            Subgrafo com os nós e arestas alcançados.
        """

    @abstractmethod
    def project_subgraph(self, projeto_id: str, labels: list[str] | None = None) -> Subgraph:
        """Projeta o subgrafo de um projeto (todos os nós com esse ``projeto_id``).

        Args:
            projeto_id: ID do nó ``Projeto``.
            labels: Rótulos a incluir, ou ``None`` para todos.

        Returns:
            Subgrafo com os nós do projeto e as arestas entre eles.
        """

    @abstractmethod
    def read_query(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Executa uma consulta Cypher livre, somente-leitura, com timeout.

        Args:
            cypher: Texto da consulta Cypher.
            params: Parâmetros nomeados referenciados na consulta.

        Returns:
            Lista de resultados (um dicionário por linha).

        Raises:
            ReadOnlyQueryViolation: A consulta contém palavra-chave de escrita.
            GraphQueryTimeoutError: A consulta excedeu o timeout configurado.
        """


# ---------------------------------------------------------------------------
# InMemoryGraphStore — implementação sem banco, para testes unitários
# ---------------------------------------------------------------------------


class InMemoryGraphStore(GraphStore):
    """Implementação em memória de ``GraphStore``, para testes unitários.

    Aplica exatamente a mesma validação de schema que ``AgeGraphStore``
    (``src.knowledge.validation``), sem depender de PostgreSQL/AGE. Também
    mantém uma trilha de auditoria em memória (``self.audit_log``) equivalente
    à tabela ``knowledge_audit``.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self.audit_log: list[dict[str, Any]] = []

    def create_node(self, label: str, props: dict[str, Any], *, actor: Actor) -> str:
        full_props = prepare_node_properties(props, actor)
        validation.validate_node_write(
            label, full_props, requires_agent_provenance=actor.requires_provenance_justification
        )
        node = Node(id=full_props["id"], label=label, properties=full_props)
        self._nodes[node.id] = node
        logger.info(
            "Nó criado (InMemoryGraphStore)",
            extra={"extra": {"node_id": node.id, "label": label, "criado_por": full_props["criado_por"]}},
        )
        return node.id

    def update_node(self, node_id: str, changes: dict[str, Any], *, actor: Actor) -> None:
        node = self._nodes.get(node_id)
        if node is None:
            raise NodeNotFoundError(node_id)

        validation.validate_node_update(node.label, changes)
        full_changes = prepare_node_update(changes)

        updated_props = {**node.properties, **full_changes}
        self._nodes[node_id] = Node(id=node.id, label=node.label, properties=updated_props)

        audit_entry = {
            "node_id": node_id,
            "actor": actor.criado_por,
            "timestamp": full_changes["atualizado_em"],
            "changes": dict(changes),
        }
        self.audit_log.append(audit_entry)
        logger.info(
            "Nó atualizado (InMemoryGraphStore)",
            extra={"extra": {"node_id": node_id, "actor": actor.criado_por, "fields": list(changes)}},
        )

    def create_edge(self, src_id: str, rel: str, dst_id: str, props: dict[str, Any], *, actor: Actor) -> None:
        src = self._nodes.get(src_id)
        if src is None:
            raise NodeNotFoundError(src_id)
        dst = self._nodes.get(dst_id)
        if dst is None:
            raise NodeNotFoundError(dst_id)

        full_props = prepare_edge_properties(props, actor)
        validation.validate_edge_write(src.label, rel, dst.label, full_props)

        self._edges.append(Edge(src_id=src_id, rel_type=rel, dst_id=dst_id, properties=full_props))
        logger.info(
            "Aresta criada (InMemoryGraphStore)",
            extra={"extra": {"src_id": src_id, "rel": rel, "dst_id": dst_id}},
        )

    def set_edge_status(self, src_id: str, rel: str, dst_id: str, status: str, *, actor: Actor) -> None:
        if status not in schema.COMMON_EDGE_PROPERTIES["status"].enum:  # type: ignore[union-attr]
            from src.knowledge.errors import InvalidEnumValueError

            raise InvalidEnumValueError(
                f"{rel}", "status", status, schema.COMMON_EDGE_PROPERTIES["status"].enum  # type: ignore[arg-type]
            )

        for i, edge in enumerate(self._edges):
            if edge.src_id == src_id and edge.rel_type == rel and edge.dst_id == dst_id:
                new_props = {**edge.properties, "status": status}
                self._edges[i] = Edge(src_id=src_id, rel_type=rel, dst_id=dst_id, properties=new_props)
                logger.info(
                    "Status de aresta alterado (InMemoryGraphStore)",
                    extra={"extra": {"src_id": src_id, "rel": rel, "dst_id": dst_id, "status": status}},
                )
                return

        from src.knowledge.errors import GraphStoreError

        raise GraphStoreError(f"Aresta '{src_id}-{rel}->{dst_id}' não encontrada.")

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def find_nodes(self, label: str, filters: dict[str, Any], limit: int = 50) -> list[Node]:
        # Paridade com AgeGraphStore.find_nodes: mesma validação de rótulo/chaves,
        # ainda que InMemoryGraphStore não interpole nada em Cypher.
        validation.validate_node_filter_keys(label, filters)
        results = []
        for node in self._nodes.values():
            if node.label != label:
                continue
            if all(node.properties.get(k) == v for k, v in filters.items()):
                results.append(node)
            if len(results) >= limit:
                break
        return results

    def neighbors(
        self,
        node_id: str,
        rels: list[str] | None,
        direction: str = "both",
        depth: int = 1,
    ) -> Subgraph:
        if node_id not in self._nodes:
            return Subgraph()

        rel_filter = set(rels) if rels else None
        visited_nodes: dict[str, Node] = {}
        visited_edges: list[Edge] = []
        frontier = {node_id}

        for _ in range(max(depth, 0)):
            next_frontier: set[str] = set()
            for edge in self._edges:
                if rel_filter is not None and edge.rel_type not in rel_filter:
                    continue

                matches_out = direction in ("out", "both") and edge.src_id in frontier
                matches_in = direction in ("in", "both") and edge.dst_id in frontier
                if not (matches_out or matches_in):
                    continue

                other_id = edge.dst_id if matches_out else edge.src_id
                if edge not in visited_edges:
                    visited_edges.append(edge)
                if other_id in self._nodes and other_id not in visited_nodes:
                    visited_nodes[other_id] = self._nodes[other_id]
                    next_frontier.add(other_id)
            frontier = next_frontier
            if not frontier:
                break

        return Subgraph(nodes=list(visited_nodes.values()), edges=visited_edges)

    def project_subgraph(self, projeto_id: str, labels: list[str] | None = None) -> Subgraph:
        label_filter = set(labels) if labels else None
        nodes = [
            node
            for node in self._nodes.values()
            if node.properties.get("projeto_id") == projeto_id and (label_filter is None or node.label in label_filter)
        ]
        node_ids = {n.id for n in nodes}
        edges = [e for e in self._edges if e.src_id in node_ids and e.dst_id in node_ids]
        return Subgraph(nodes=nodes, edges=edges)

    def read_query(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        reject_unsafe_read_query(cypher)
        logger.warning(
            "read_query chamado em InMemoryGraphStore: não há motor Cypher — retorna lista vazia. "
            "Use apenas para testar o filtro de segurança; comportamento de consulta real é "
            "coberto pelos testes de integração com AgeGraphStore.",
        )
        return []


# ---------------------------------------------------------------------------
# AgeGraphStore — implementação real sobre Apache AGE / PostgreSQL 16
# ---------------------------------------------------------------------------


class AgeGraphStore(GraphStore):
    """Implementação de ``GraphStore`` sobre Apache AGE (PostgreSQL 16).

    Escritas usam o pool de leitura-e-escrita padrão do projeto
    (``src.db.get_connection``). Rótulos e tipos de relação são sempre
    lidos do schema (whitelist) e interpolados na consulta Cypher — nunca a
    partir de texto do chamador; todos os *valores* trafegam como um único
    parâmetro ``agtype`` (mapa JSON) do ``cypher()``, nunca concatenados na
    consulta. ``read_query`` usa uma conexão dedicada com o papel
    ``knowledge_reader``, em transação ``READ ONLY`` e com
    ``statement_timeout``.
    """

    def __init__(self, graph_name: str, *, reader_conninfo: str, read_timeout_ms: int) -> None:
        """Inicializa o store.

        Args:
            graph_name: Nome do grafo AGE (``config.KNOWLEDGE_GRAPH_NAME``).
            reader_conninfo: DSN da conexão somente-leitura
                (``config.KNOWLEDGE_READER_DATABASE_URL``), usada
                exclusivamente por ``read_query``.
            read_timeout_ms: Timeout (ms) aplicado às consultas de
                ``read_query`` via ``statement_timeout``.
        """
        self._graph_name = graph_name
        self._reader_conninfo = reader_conninfo
        self._read_timeout_ms = read_timeout_ms
        self._reader_pool: Any = None  # inicializado sob demanda (import tardio de psycopg_pool)

    # -- Infra interna -------------------------------------------------------

    def _connection(self):
        """Obtém uma conexão de leitura-e-escrita do pool padrão do projeto, já configurada para AGE."""
        from src.db import get_connection

        return get_connection()

    def _get_reader_pool(self):
        """Obtém (criando na primeira chamada) o pool somente-leitura (papel ``knowledge_reader``).

        Cada conexão do pool é configurada, ao ser aberta, com ``LOAD 'age'``,
        o ``search_path`` do AGE e o ``statement_timeout`` de
        ``KNOWLEDGE_READ_TIMEOUT_MS``. A garantia de somente-leitura vem do
        próprio papel de banco (``knowledge_reader``, sem privilégio de
        escrita) mais ``SET TRANSACTION READ ONLY`` em cada conexão emprestada.
        """
        if self._reader_pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            timeout_ms = int(self._read_timeout_ms)

            def _configure(conn: Any) -> None:
                conn.execute("LOAD 'age'")
                conn.execute('SET search_path = ag_catalog, "$user", public')
                conn.execute(f"SET statement_timeout = {timeout_ms}")

            self._reader_pool = ConnectionPool(
                conninfo=self._reader_conninfo,
                min_size=1,
                max_size=5,
                open=True,
                kwargs={"row_factory": dict_row},
                configure=_configure,
            )
            logger.info(
                "Pool somente-leitura do grafo inicializado.",
                extra={"extra": {"read_timeout_ms": timeout_ms}},
            )
        return self._reader_pool

    @staticmethod
    def _property_map(param: str, keys: Any) -> str:
        """Monta o mapa de propriedades de um ``CREATE`` como acessos ao parâmetro.

        O AGE não aceita ``CREATE (n:L $props)`` (mapa inteiro como parâmetro),
        mas aceita ``{chave: $props.chave}``: os *valores* continuam trafegando
        no parâmetro ``agtype`` (nunca no texto da consulta) e só os nomes de
        propriedade — já validados contra o schema — são interpolados.

        Args:
            param: Nome do parâmetro que contém o mapa (ex.: ``"props"``).
            keys: Nomes das propriedades.

        Returns:
            Texto ``{k1: $param.k1, k2: $param.k2}``.

        Raises:
            ValueError: Se algum nome não for um identificador simples.
        """
        for key in keys:
            if not _IDENTIFIER_RE.fullmatch(key):
                raise ValueError(f"Nome de propriedade inválido para Cypher: {key!r}")
        return "{" + ", ".join(f"{key}: ${param}.{key}" for key in keys) + "}"

    @staticmethod
    def _to_agtype_param(value: dict[str, Any]) -> str:
        """Serializa um mapa Python para o texto que o PostgreSQL converte via ``::agtype``."""
        return json.dumps(value, default=str)

    def _run_cypher_rows(
        self, cypher_body: str, params: dict[str, Any], *, columns: tuple[str, ...] = ("result",)
    ) -> list[dict[str, Any]]:
        """Executa um corpo Cypher (já validado/whitelisted) via ``cypher()`` do AGE.

        ``cypher_body`` só pode conter rótulos/tipos de relação vindos do
        schema — os valores reais são sempre passados pelo parâmetro
        ``agtype`` ``$$params``, nunca interpolados no texto. ``columns``
        declara os nomes/quantidade de colunas devolvidas pelo ``RETURN`` do
        Cypher (o AGE exige que a cláusula ``AS`` do ``cypher()`` declare
        exatamente essa aridade).

        Args:
            cypher_body: Corpo da consulta Cypher (sem os delimitadores ``$$``).
            params: Mapa de parâmetros nomeados (vira um único ``agtype``).
            columns: Nomes das colunas de saída, na ordem do ``RETURN``.

        Returns:
            Lista de dicionários ``{coluna: valor_decodificado}``, um por
            linha de resultado.
        """
        col_defs = ", ".join(f"{c} agtype" for c in columns)
        sql = f"SELECT * FROM cypher('{self._graph_name}', $$ {cypher_body} $$, %s::agtype) as ({col_defs})"
        params_json = self._to_agtype_param(params)
        # A sessão AGE (LOAD 'age' + search_path) já é preparada pelo callback
        # `configure` do pool (src.db._configure_age_session) na abertura da conexão.
        with self._connection() as conn:
            rows = conn.execute(sql, (params_json,)).fetchall()
        return [{c: self._decode_agtype(row[c]) for c in columns} for row in rows]

    def _run_cypher(self, cypher_body: str, params: dict[str, Any]) -> list[Any]:
        """Atalho de ``_run_cypher_rows`` para consultas com uma única coluna (``RETURN x``).

        Returns:
            Lista com o valor decodificado de ``result`` para cada linha.
        """
        return [row["result"] for row in self._run_cypher_rows(cypher_body, params, columns=("result",))]

    @staticmethod
    def _decode_agtype(raw: Any) -> Any:
        """Decodifica um valor ``agtype`` (texto JSON com sufixo de tipo) em objeto Python.

        O driver devolve o ``agtype`` como texto no formato
        ``'{...}'::vertex``/``'{...}'::edge`` ou um literal JSON simples. A
        decodificação remove o sufixo de tipo, quando presente, e usa
        ``json.loads`` no restante.

        Args:
            raw: Valor bruto devolvido pela coluna ``agtype``.

        Returns:
            O valor Python decodificado (``dict`` para vértice/aresta, ou o
            tipo primitivo correspondente).
        """
        if raw is None:
            return None
        text = raw if isinstance(raw, str) else str(raw)
        for suffix in ("::vertex", "::edge", "::path"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    @staticmethod
    def _node_from_agtype(value: dict[str, Any]) -> Node:
        """Converte um vértice decodificado (``{id, label, properties}``) em ``Node``.

        AGE devolve o ``id`` interno do grafo (``graphid``) no campo ``id`` do
        vértice — o identificador estável do domínio (UUIDv7) vive em
        ``properties["id"]`` e é o que ``Node.id`` expõe.
        """
        props = dict(value.get("properties", {}))
        return Node(id=str(props.get("id")), label=value["label"], properties=props)

    # -- Escrita ---------------------------------------------------------------

    def create_node(self, label: str, props: dict[str, Any], *, actor: Actor) -> str:
        full_props = prepare_node_properties(props, actor)
        validation.validate_node_write(
            label, full_props, requires_agent_provenance=actor.requires_provenance_justification
        )

        cypher_body = f"CREATE (n:{label} {self._property_map('props', full_props)}) RETURN n"
        self._run_cypher(cypher_body, {"props": full_props})

        logger.info(
            "Nó criado (AgeGraphStore)",
            extra={"extra": {"node_id": full_props["id"], "label": label, "criado_por": full_props["criado_por"]}},
        )
        return full_props["id"]

    def update_node(self, node_id: str, changes: dict[str, Any], *, actor: Actor) -> None:
        node = self.get_node(node_id)
        if node is None:
            raise NodeNotFoundError(node_id)

        validation.validate_node_update(node.label, changes)
        full_changes = prepare_node_update(changes)

        # Nomes de propriedade vêm do schema (validados acima) — seguro interpolar
        # como identificador; os VALORES vão sempre pelo parâmetro agtype.
        self._property_map("changes", full_changes)  # valida os nomes como identificadores
        set_clauses = ", ".join(f"n.{key} = $changes.{key}" for key in full_changes)
        cypher_body = f"MATCH (n:{node.label} {{id: $id}}) SET {set_clauses} RETURN n"
        self._run_cypher(cypher_body, {"id": node_id, "changes": full_changes})

        self._record_audit(node_id=node_id, actor=actor, changes=changes, timestamp=full_changes["atualizado_em"])
        logger.info(
            "Nó atualizado (AgeGraphStore)",
            extra={"extra": {"node_id": node_id, "actor": actor.criado_por, "fields": list(changes)}},
        )

    def _record_audit(self, *, node_id: str, actor: Actor, changes: dict[str, Any], timestamp: str) -> None:
        """Grava o registro de auditoria de ``update_node`` na tabela relacional ``knowledge_audit``."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_audit (node_id, actor, "timestamp", changes)
                VALUES (%s, %s, %s, %s)
                """,
                (node_id, actor.criado_por, timestamp, json.dumps(changes, default=str)),
            )

    def create_edge(self, src_id: str, rel: str, dst_id: str, props: dict[str, Any], *, actor: Actor) -> None:
        src = self.get_node(src_id)
        if src is None:
            raise NodeNotFoundError(src_id)
        dst = self.get_node(dst_id)
        if dst is None:
            raise NodeNotFoundError(dst_id)

        full_props = prepare_edge_properties(props, actor)
        validation.validate_edge_write(src.label, rel, dst.label, full_props)

        cypher_body = (
            f"MATCH (a:{src.label} {{id: $src_id}}), (b:{dst.label} {{id: $dst_id}}) "
            f"CREATE (a)-[r:{rel} {self._property_map('props', full_props)}]->(b) RETURN r"
        )
        self._run_cypher(cypher_body, {"src_id": src_id, "dst_id": dst_id, "props": full_props})

        logger.info(
            "Aresta criada (AgeGraphStore)",
            extra={"extra": {"src_id": src_id, "rel": rel, "dst_id": dst_id}},
        )

    def set_edge_status(self, src_id: str, rel: str, dst_id: str, status: str, *, actor: Actor) -> None:
        status_schema = schema.COMMON_EDGE_PROPERTIES["status"]
        if status_schema.enum is not None and status not in status_schema.enum:
            from src.knowledge.errors import InvalidEnumValueError

            raise InvalidEnumValueError(rel, "status", status, status_schema.enum)
        if rel not in schema.RELATION_TYPES:
            from src.knowledge.errors import DisallowedRelationError

            raise DisallowedRelationError("*", rel, "*")

        cypher_body = f"MATCH (a {{id: $src_id}})-[r:{rel}]->(b {{id: $dst_id}}) SET r.status = $status RETURN r"
        self._run_cypher(cypher_body, {"src_id": src_id, "dst_id": dst_id, "status": status})

        logger.info(
            "Status de aresta alterado (AgeGraphStore)",
            extra={
                "extra": {
                    "src_id": src_id,
                    "rel": rel,
                    "dst_id": dst_id,
                    "status": status,
                    "actor": actor.criado_por,
                }
            },
        )

    # -- Leitura -----------------------------------------------------------

    def get_node(self, node_id: str) -> Node | None:
        cypher_body = "MATCH (n {id: $id}) RETURN n"
        results = self._run_cypher(cypher_body, {"id": node_id})
        if not results:
            return None
        return self._node_from_agtype(results[0])

    def find_nodes(self, label: str, filters: dict[str, Any], limit: int = 50) -> list[Node]:
        # `validate_node_filter_keys` checa `label` e as CHAVES de `filters` contra o
        # schema do rótulo antes de qualquer interpolação — os nomes de campo são
        # interpolados como identificadores Cypher abaixo (os valores sempre viajam
        # pelo parâmetro agtype `$filters`), então só chaves conhecidas do schema
        # podem chegar até a montagem da string (PR #64 review, achado "Importante").
        validation.validate_node_filter_keys(label, filters)
        if filters:
            conditions = " AND ".join(f"n.{key} = $filters.{key}" for key in filters)
            cypher_body = f"MATCH (n:{label}) WHERE {conditions} RETURN n LIMIT $limit"
        else:
            cypher_body = f"MATCH (n:{label}) RETURN n LIMIT $limit"

        results = self._run_cypher(cypher_body, {"filters": filters, "limit": limit})
        return [self._node_from_agtype(r) for r in results]

    def neighbors(
        self,
        node_id: str,
        rels: list[str] | None,
        direction: str = "both",
        depth: int = 1,
    ) -> Subgraph:
        if direction not in ("out", "in", "both"):
            raise ValueError(f"direction inválida: '{direction}' (use 'out', 'in' ou 'both').")

        rel_types = list(rels) if rels else None
        if rel_types is not None:
            for rt in rel_types:
                if rt not in schema.RELATION_TYPES:
                    from src.knowledge.errors import DisallowedRelationError

                    raise DisallowedRelationError("*", rt, "*")
        rel_pattern = f":{'|'.join(rel_types)}" if rel_types else ""

        if direction == "out":
            pattern = f"(n)-[r{rel_pattern}*1..{int(depth)}]->(m)"
        elif direction == "in":
            pattern = f"(n)<-[r{rel_pattern}*1..{int(depth)}]-(m)"
        else:
            pattern = f"(n)-[r{rel_pattern}*1..{int(depth)}]-(m)"

        # Para saltos únicos (depth=1, o caso comum), pedimos o triplo (a relação e os
        # dois vértices adjacentes) em uma única consulta — isso permite resolver o
        # ``src_id``/``dst_id`` de domínio (UUIDv7) da aresta a partir dos próprios
        # vértices retornados, em vez do graphid interno do AGE. Para depth > 1, o
        # caminho tem uma lista de relações; extraímos cada uma via UNWIND e resolvemos
        # seus vértices adjacentes com uma segunda consulta por identidade (id de nó).
        node_cypher = f"MATCH (n {{id: $id}}){pattern} RETURN DISTINCT m"
        node_rows = self._run_cypher_rows(node_cypher, {"id": node_id}, columns=("result",))
        nodes = [self._node_from_agtype(row["result"]) for row in node_rows]
        nodes_by_domain_id = {node.id: node for node in nodes}

        rel_pattern_edges = f":{'|'.join(rel_types)}" if rel_types else ""
        edge_cypher = (
            f"MATCH (n {{id: $id}})-[rel{rel_pattern_edges}*1..{int(depth)}]-(x) "
            "UNWIND rel AS one_rel "
            "WITH one_rel, startNode(one_rel) AS a, endNode(one_rel) AS b "
            "RETURN DISTINCT a, one_rel, b"
        )
        edge_rows = self._run_cypher_rows(edge_cypher, {"id": node_id}, columns=("a", "one_rel", "b"))
        edges = []
        for row in edge_rows:
            a_node = self._node_from_agtype(row["a"])
            b_node = self._node_from_agtype(row["b"])
            rel_value = row["one_rel"]
            edges.append(
                Edge(
                    src_id=a_node.id,
                    rel_type=rel_value["label"],
                    dst_id=b_node.id,
                    properties=dict(rel_value.get("properties", {})),
                )
            )
            nodes_by_domain_id.setdefault(a_node.id, a_node)
            nodes_by_domain_id.setdefault(b_node.id, b_node)

        return Subgraph(nodes=list(nodes_by_domain_id.values()), edges=edges)

    def project_subgraph(self, projeto_id: str, labels: list[str] | None = None) -> Subgraph:
        if labels:
            for label in labels:
                validation.validate_label(label)
            # O AGE não aceita predicado de rótulo (``n:A OR n:B``) no WHERE; usa label(n).
            cypher_body = "MATCH (n) WHERE n.projeto_id = $projeto_id AND label(n) IN $labels RETURN n"
        else:
            cypher_body = "MATCH (n) WHERE n.projeto_id = $projeto_id RETURN n"

        node_rows = self._run_cypher_rows(
            cypher_body, {"projeto_id": projeto_id, "labels": list(labels or [])}, columns=("result",)
        )
        nodes = [self._node_from_agtype(row["result"]) for row in node_rows]
        node_ids = {n.id for n in nodes}

        edge_cypher = (
            "MATCH (a)-[r]->(b) WHERE a.projeto_id = $projeto_id AND b.projeto_id = $projeto_id "
            "RETURN a, r, b"
        )
        edge_rows = self._run_cypher_rows(edge_cypher, {"projeto_id": projeto_id}, columns=("a", "r", "b"))
        edges = []
        for row in edge_rows:
            a_node = self._node_from_agtype(row["a"])
            b_node = self._node_from_agtype(row["b"])
            rel_value = row["r"]
            if a_node.id in node_ids and b_node.id in node_ids:
                edges.append(
                    Edge(
                        src_id=a_node.id,
                        rel_type=rel_value["label"],
                        dst_id=b_node.id,
                        properties=dict(rel_value.get("properties", {})),
                    )
                )

        return Subgraph(nodes=nodes, edges=edges)

    def read_query(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        reject_unsafe_read_query(cypher)

        from src.knowledge.errors import GraphQueryTimeoutError

        sql = f"SELECT * FROM cypher('{self._graph_name}', $$ {cypher} $$, %s::agtype) as (result agtype)"
        params_json = self._to_agtype_param(params)
        pool = self._get_reader_pool()

        try:
            with pool.connection() as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                rows = conn.execute(sql, (params_json,)).fetchall()
        except Exception as exc:  # pragma: no cover - dependente de driver/erro real do PG
            if "statement timeout" in str(exc).lower() or "canceling statement" in str(exc).lower():
                raise GraphQueryTimeoutError(self._read_timeout_ms) from exc
            raise

        decoded = [self._decode_agtype(row["result"]) for row in rows]
        return [d if isinstance(d, dict) else {"result": d} for d in decoded]

    def close(self) -> None:
        """Encerra o pool somente-leitura, se inicializado. Deve ser chamado no shutdown."""
        if self._reader_pool is not None:
            self._reader_pool.close()
            self._reader_pool = None
