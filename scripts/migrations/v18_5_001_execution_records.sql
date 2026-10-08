-- scripts/migrations/v18_5_001_execution_records.sql
--
-- Migração v18.5: registro de execuções encadeado por hash (openspec/changes/v18.5-execution-provenance, tarefas 0.1 e
-- 1.1; alteração de schema aprovada explicitamente pelo pesquisador). ADR 019 §4.
--
-- IDEMPOTENTE: CREATE TABLE/INDEX IF NOT EXISTS e CREATE OR REPLACE para função e gatilhos; pode ser aplicada várias
-- vezes. ADITIVA: nenhuma tabela existente é alterada; nenhum DROP, nenhuma reescrita de dados.
--
-- A tabela é SOMENTE-ACRÉSCIMO: os gatilhos recusam UPDATE, DELETE e TRUNCATE. Isso impede alterações acidentais, não o
-- dono do banco (que pode desativar os gatilhos); a cadeia de hash (prev_hash/record_hash) é o que torna a adulteração
-- detectável (`geminiclaw provenance verify`).
--
-- Como aplicar (a partir da raiz do repositório, com o PostgreSQL do projeto no ar):
--   uv run python scripts/migrate_v18_5_provenance.py
-- ou, diretamente:
--   psql "$DATABASE_URL" -f scripts/migrations/v18_5_001_execution_records.sql
-- Instalações novas já recebem a tabela por scripts/init_db.sql.

CREATE TABLE IF NOT EXISTS execution_records (
    project_id    TEXT        NOT NULL,        -- projeto (ou "sem_projeto:<sessão>" quando a sessão não tem projeto)
    seq           BIGINT      NOT NULL,        -- consecutivo por projeto, a partir de 1
    exec_id       TEXT        NOT NULL,        -- exec_<uuid4>
    tipo          TEXT        NOT NULL CHECK (tipo IN ('inicio', 'termino')),
    session_id    TEXT        NOT NULL,
    subtask_id    TEXT,
    task_name     TEXT        NOT NULL,
    registrado_em TEXT        NOT NULL,        -- o mesmo texto que entra no hash
    prev_hash     CHAR(64)    NOT NULL,        -- record_hash do registro anterior do projeto (64 zeros no primeiro)
    record_hash   CHAR(64)    NOT NULL,
    corpo         JSONB       NOT NULL,
    PRIMARY KEY (project_id, seq),
    UNIQUE (exec_id, tipo)
);

CREATE INDEX IF NOT EXISTS idx_exec_records_session ON execution_records (session_id);
CREATE INDEX IF NOT EXISTS idx_exec_records_subtask ON execution_records (subtask_id);

CREATE OR REPLACE FUNCTION execution_records_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'execution_records é somente-acréscimo (% recusado)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE OR REPLACE TRIGGER execution_records_no_update_delete
    BEFORE UPDATE OR DELETE ON execution_records
    FOR EACH ROW EXECUTE FUNCTION execution_records_append_only();

CREATE OR REPLACE TRIGGER execution_records_no_truncate
    BEFORE TRUNCATE ON execution_records
    FOR EACH STATEMENT EXECUTE FUNCTION execution_records_append_only();
