-- scripts/migrations/v18_7_001_session_process.sql
--
-- Migração v18.7: processo da sessão e presença do terminal (openspec/changes/v18.7-background-sessions, tarefa 1.1;
-- alteração de schema aprovada explicitamente pelo pesquisador em 2026-10-16, com a coluna `resumo` acrescentada
-- por decisão dele: a lista de pesquisas mostra o que cada sessão faz sem abrir o checkpoint).
--
-- IDEMPOTENTE: ADD COLUMN/CREATE TABLE/INDEX IF NOT EXISTS; pode ser aplicada várias vezes.
-- ADITIVA: nenhuma coluna ou tabela existente é alterada; nenhum DROP, nenhuma reescrita de dados.
--
-- Como aplicar (a partir da raiz do repositório, com o PostgreSQL do projeto no ar):
--   psql "$DATABASE_URL" -f scripts/migrations/v18_7_001_session_process.sql
-- Instalações novas já recebem o schema por scripts/init_db.sql.

ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS pid INTEGER;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS host TEXT;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS process_started_at TIMESTAMPTZ;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS loop_beat_at TIMESTAMPTZ;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS terminal_id TEXT;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS alias TEXT;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS resumo TEXT;  -- tarefa da pesquisa, em poucas linhas (sem LLM)
CREATE INDEX IF NOT EXISTS idx_agent_sessions_alias ON agent_sessions (alias);

CREATE TABLE IF NOT EXISTS terminal_presence (
    terminal_id  TEXT PRIMARY KEY,
    tipo         TEXT NOT NULL CHECK (tipo IN ('repl', 'direto')),
    pid          INTEGER NOT NULL,
    host         TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    ended_at     TIMESTAMPTZ,
    end_reason   TEXT CHECK (end_reason IN ('saida', 'obsoleta'))
);
CREATE INDEX IF NOT EXISTS idx_terminal_presence_ativos ON terminal_presence (tipo, heartbeat_at) WHERE ended_at IS NULL;
