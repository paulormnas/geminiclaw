-- scripts/migrations/v18_7_003_session_events.sql
--
-- Migração v18.7: eventos de progresso da sessão (openspec/changes/v18.7-session-events-terminal, tarefa 1.1;
-- alteração de schema autorizada explicitamente pelo pesquisador em 2026-10-18).
--
-- O processo da sessão grava cada evento assim que ele ocorre (transação própria, fora da telemetria em lote), e o
-- terminal os lê por consulta periódica. `seq` cresce por sessão; o resumo é curto e sem dado bruto.
--
-- IDEMPOTENTE: CREATE TABLE/INDEX IF NOT EXISTS; pode ser aplicada várias vezes. ADITIVA: nada existente muda.
--
-- Como aplicar (a partir da raiz do repositório, com o PostgreSQL do projeto no ar):
--   psql "$DATABASE_URL" -f scripts/migrations/v18_7_003_session_events.sql
-- Instalações novas já recebem o schema por scripts/init_db.sql.

CREATE TABLE IF NOT EXISTS session_events (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN (
                    'sessao_iniciada','plano_aprovado','subtarefa_iniciada','subtarefa_concluida',
                    'subtarefa_reprovada','hipotese_criada','hipotese_concluida','objetivo_atingido',
                    'decisao_pendente','comando_recebido','parada','suspensao','falha')),
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resumo      TEXT NOT NULL CHECK (char_length(resumo) <= 300),
    dados       JSONB NOT NULL DEFAULT '{}',
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_session_events_sessao ON session_events (session_id, id);
