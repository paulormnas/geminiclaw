-- scripts/init_db.sql
-- Executado automaticamente na primeira inicialização do container PostgreSQL.
-- Cria todas as tabelas necessárias para o projeto GeminiClaw.
-- Idempotente: usa CREATE TABLE IF NOT EXISTS e CREATE INDEX IF NOT EXISTS.

-- =============================================================
-- Sessões de agentes (src/session.py)
-- =============================================================
CREATE TABLE IF NOT EXISTS agent_sessions (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_id ON agent_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);

-- =============================================================
-- Histórico de execuções (src/history.py)
-- =============================================================
CREATE TABLE IF NOT EXISTS execution_history (
    id                TEXT PRIMARY KEY,
    prompt            TEXT NOT NULL,
    plan_json         TEXT,
    status            TEXT NOT NULL,
    results_json      TEXT,
    artifacts_json    TEXT,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    duration_seconds  DOUBLE PRECISION,
    total_subtasks    INTEGER,
    succeeded         INTEGER,
    failed            INTEGER
);
CREATE INDEX IF NOT EXISTS idx_exec_history_started ON execution_history(started_at DESC);

-- =============================================================
-- Cache de respostas LLM (src/llm_cache.py)
-- =============================================================
CREATE TABLE IF NOT EXISTS llm_cache (
    hash_key    TEXT PRIMARY KEY,
    prompt      TEXT,
    model       TEXT,
    response    TEXT,
    timestamp   DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_timestamp ON llm_cache(timestamp);

CREATE TABLE IF NOT EXISTS llm_cache_stats (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    hits    INTEGER DEFAULT 0,
    misses  INTEGER DEFAULT 0
);
INSERT INTO llm_cache_stats (id, hits, misses)
VALUES (1, 0, 0)
ON CONFLICT (id) DO NOTHING;

-- =============================================================
-- Memória de longo prazo (src/skills/memory/long_term.py)
-- =============================================================
CREATE TABLE IF NOT EXISTS long_term_memory (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT NOT NULL,
    importance  DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    tags        JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL,
    last_used   TIMESTAMPTZ NOT NULL,
    use_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ltm_key ON long_term_memory(key);
CREATE INDEX IF NOT EXISTS idx_ltm_importance ON long_term_memory(importance DESC);

-- =============================================================
-- Cache de deep search (src/skills/search_deep/cache.py)
-- =============================================================
CREATE TABLE IF NOT EXISTS deep_search_cache (
    query_hash  TEXT PRIMARY KEY,
    query       TEXT NOT NULL,
    results     JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dsc_expires ON deep_search_cache(expires_at);
