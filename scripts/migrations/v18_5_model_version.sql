-- scripts/migrations/v18_5_model_version.sql
--
-- Migração v18.5: coluna da versão efetiva do modelo em token_usage
-- (openspec/changes/v18.5-model-catalog-locality, tarefas 0.2 e 3.3; alteração de
-- schema aprovada explicitamente pelo pesquisador).
--
-- IDEMPOTENTE: ADD COLUMN IF NOT EXISTS; pode ser aplicada várias vezes.
-- RETROCOMPATÍVEL: a coluna é anulável e sem DEFAULT; linhas antigas ficam com NULL
-- (versão não registrada). Nenhum DROP, nenhuma reescrita de dados.
--
-- Como aplicar (a partir da raiz do repositório, com o PostgreSQL do projeto no ar):
--   psql "$DATABASE_URL" -f scripts/migrations/v18_5_model_version.sql
-- Instalações novas já recebem a coluna por scripts/init_db.sql.

ALTER TABLE token_usage
    ADD COLUMN IF NOT EXISTS versao_efetiva TEXT;

COMMENT ON COLUMN token_usage.versao_efetiva IS
    'Versão efetivamente servida pelo provedor (ex.: gemini-2.5-pro-002, sha256:...); NULL em linhas anteriores à v18.5; "desconhecida" quando o provedor não informa.';
