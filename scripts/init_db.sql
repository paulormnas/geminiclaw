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

-- =============================================================
-- Telemetria V5: Rastreamento de Eventos entre Agentes
-- =============================================================
CREATE TABLE IF NOT EXISTS agent_events (
    id              TEXT PRIMARY KEY,
    execution_id    TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,   -- spawn | ipc_send | ipc_receive | tool_call |
                                     -- tool_result | plan_generated | plan_validated |
                                     -- triage_decision | subtask_start | subtask_end |
                                     -- replan_triggered | memory_promotion |
                                     -- llm_request | llm_response | error | complete
    target_agent_id TEXT,
    task_name       TEXT,
    payload_json    TEXT,
    timestamp       TIMESTAMPTZ NOT NULL,
    duration_ms     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_execution ON agent_events(execution_id);
CREATE INDEX IF NOT EXISTS idx_events_agent ON agent_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON agent_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON agent_events(timestamp);

-- =============================================================
-- Telemetria V5: Rastreamento de Uso de Ferramentas (Skills)
-- =============================================================
CREATE TABLE IF NOT EXISTS tool_usage (
    id              TEXT PRIMARY KEY,
    execution_id    TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    arguments_json  TEXT,
    result_summary  TEXT,
    success         BOOLEAN NOT NULL,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ NOT NULL,
    duration_ms     INTEGER NOT NULL,
    task_name       TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_agent ON tool_usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_usage(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_execution ON tool_usage(execution_id);

-- =============================================================
-- Telemetria V5: Contabilidade de Tokens LLM
-- =============================================================
CREATE TABLE IF NOT EXISTS token_usage (
    id                  TEXT PRIMARY KEY,
    execution_id        TEXT NOT NULL,
    session_id          TEXT NOT NULL,
    agent_id            TEXT NOT NULL,
    task_name           TEXT,
    llm_provider        TEXT NOT NULL,
    llm_model           TEXT NOT NULL,
    prompt_tokens       INTEGER NOT NULL,
    completion_tokens   INTEGER NOT NULL,
    total_tokens        INTEGER NOT NULL,
    estimated_cost_usd  DOUBLE PRECISION,
    latency_ms          INTEGER NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    context_window_used INTEGER,
    context_window_max  INTEGER,
    was_compressed      BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_tokens_execution ON token_usage(execution_id);
CREATE INDEX IF NOT EXISTS idx_tokens_agent ON token_usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_tokens_provider ON token_usage(llm_provider);

-- =============================================================
-- Telemetria V5: Snapshots de Hardware (Pi 5)
-- =============================================================
CREATE TABLE IF NOT EXISTS hardware_snapshots (
    id                TEXT PRIMARY KEY,
    execution_id      TEXT,
    task_name         TEXT,
    cpu_temp_c        DOUBLE PRECISION,
    cpu_usage_pct     DOUBLE PRECISION,
    mem_total_mb      DOUBLE PRECISION,
    mem_available_mb  DOUBLE PRECISION,
    mem_usage_pct     DOUBLE PRECISION,
    is_throttled      BOOLEAN,
    disk_free_gb      DOUBLE PRECISION,
    active_containers INTEGER,
    timestamp         TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hw_execution ON hardware_snapshots(execution_id);
CREATE INDEX IF NOT EXISTS idx_hw_timestamp ON hardware_snapshots(timestamp);
