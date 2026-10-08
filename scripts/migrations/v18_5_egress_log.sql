-- scripts/migrations/v18_5_egress_log.sql
--
-- Migração v18.5: tabela do registro de egresso (openspec/changes/v18.5-egress-gate, tarefas 0.2 e 1.3;
-- alteração de schema aprovada explicitamente pelo pesquisador). ADR 019 §3.5 e §8.
--
-- IDEMPOTENTE: CREATE TABLE/INDEX IF NOT EXISTS; pode ser aplicada várias vezes.
-- ADITIVA: nenhuma tabela existente é alterada; nenhum DROP, nenhuma reescrita de dados.
-- O conteúdo enviado NÃO vai ao banco: só metadados (origem, bytes, sha256 e intervenções por trecho). O payload
-- exato fica em outputs/<sessão>/egress/envios.jsonl.gz, no nó.
--
-- Como aplicar (a partir da raiz do repositório, com o PostgreSQL do projeto no ar):
--   psql "$DATABASE_URL" -f scripts/migrations/v18_5_egress_log.sql
-- Instalações novas já recebem a tabela por scripts/init_db.sql.

CREATE TABLE IF NOT EXISTS egress_log (
    id TEXT PRIMARY KEY,                       -- egr_<uuid4>
    session_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    canal TEXT NOT NULL,                       -- llm | visao | busca | leitura_web
    papel TEXT,
    provedor TEXT NOT NULL,
    modelo TEXT,
    versao_efetiva TEXT,
    trust TEXT,
    localidade TEXT NOT NULL,                  -- no_no | fora_do_no
    aceita_dados_brutos BOOLEAN NOT NULL,
    bytes_enviados INTEGER NOT NULL,
    bytes_saida_execucao_novos INTEGER NOT NULL DEFAULT 0,
    fragmentos JSONB NOT NULL,                 -- [{origem, tainted, compartilhavel, source, bytes, sha256, novo, intervencoes}]
    intervencoes JSONB NOT NULL DEFAULT '{}',  -- contagem por tipo
    recusado BOOLEAN NOT NULL DEFAULT FALSE,
    motivo_recusa TEXT
);

CREATE INDEX IF NOT EXISTS idx_egress_session ON egress_log (session_id);
