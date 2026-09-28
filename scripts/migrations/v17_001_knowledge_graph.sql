-- scripts/migrations/v17_001_knowledge_graph.sql
--
-- Migração v17_001: extensão Apache AGE, grafo de conhecimento e tabela de
-- auditoria de correções (ADR 009 §4, ADR 015 §2, §11).
--
-- IDEMPOTENTE: pode ser aplicada múltiplas vezes sem duplicar grafo,
-- extensão, índices ou tabela (Requirement "Migração idempotente",
-- openspec/changes/v17-graph-store/specs/knowledge-graph/spec.md).
--
-- Este arquivo é um TEMPLATE: {graph_name} é substituído pelo script Python
-- scripts/migrate_v17_knowledge.py com o valor de config.KNOWLEDGE_GRAPH_NAME
-- antes da execução. Os rótulos de nó/relação (create_vlabel/create_elabel),
-- seus índices e o papel somente-leitura `knowledge_reader` são gerados
-- separadamente pelo mesmo script Python a partir de
-- src/knowledge/schema.py (fonte única da verdade do schema) — não estão
-- neste arquivo para evitar duas fontes de verdade divergentes.

CREATE EXTENSION IF NOT EXISTS age;

LOAD 'age';

SET search_path = ag_catalog, "$user", public;

-- Cria o grafo apenas se ainda não existir.
DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = '{graph_name}'
    ) THEN
        PERFORM create_graph('{graph_name}');
    END IF;
END
$migration$;

-- Tabela relacional de auditoria de update_node (Requirement "Nada é
-- apagado" / Scenario "Auditoria de alterações"). Fora do grafo AGE:
-- é consultada e mantida via SQL comum, não via Cypher.
CREATE TABLE IF NOT EXISTS knowledge_audit (
    id         BIGSERIAL PRIMARY KEY,
    node_id    TEXT NOT NULL,
    actor      TEXT NOT NULL,
    "timestamp" TIMESTAMPTZ NOT NULL,
    changes    JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_audit_node_id ON knowledge_audit (node_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_audit_timestamp ON knowledge_audit ("timestamp");
