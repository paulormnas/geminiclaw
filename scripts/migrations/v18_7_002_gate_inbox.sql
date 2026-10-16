-- scripts/migrations/v18_7_002_gate_inbox.sql
--
-- Migração v18.7: gate persistente de decisões reservadas e caixa de entrada da sessão
-- (openspec/changes/v18.7-persistent-human-gate, tarefa 1.1; alteração de schema aprovada explicitamente pelo
-- pesquisador em 2026-10-16).
--
-- Decisão do pesquisador (2026-10-16): ambiente de desenvolvimento, sem endurecimento agora. Esta versão NÃO cria o
-- papel `terminal_writer`, o arquivo de credencial nem os gatilhos de proteção do design §1.3: a regra "só o
-- terminal resolve pedidos" vale na aplicação (`resolvido_por` fechado em terminal/cli, transição condicional e
-- consumo de uso único). O endurecimento (papel não superusuário + usuário de sistema separado) fica na mudança
-- anterior à produção (design §8, Questão 1).
--
-- IDEMPOTENTE: CREATE TABLE/INDEX IF NOT EXISTS; pode ser aplicada várias vezes. ADITIVA: nada existente muda.
--
-- Como aplicar (a partir da raiz do repositório, com o PostgreSQL do projeto no ar):
--   psql "$DATABASE_URL" -f scripts/migrations/v18_7_002_gate_inbox.sql
-- Instalações novas já recebem o schema por scripts/init_db.sql.

CREATE TABLE IF NOT EXISTS gate_requests (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT,                                   -- NULL para decisão da CLI fora de sessão
    project_id      TEXT,
    decisao         TEXT NOT NULL CHECK (decisao IN (
                        'aprovar_oportunidade','confirmar_problema','aprovar_termo_vocabulario',
                        'autorizar_escrita_instrumento','ativar_modo_sem_limite','aprovar_hipotese',
                        'decidir_objetivo_atingido','responder_pergunta_agente','decidir_continuidade',
                        'restringir_direcao','ativar_adendo_regimento')),
    motivo          TEXT CHECK (char_length(motivo) <= 64),             -- subtipo (ex.: estagnacao, saturacao)
    referencia      TEXT NOT NULL CHECK (char_length(referencia) <= 120),
    pergunta        TEXT NOT NULL DEFAULT '' CHECK (char_length(pergunta) <= 1000),
    opcoes          JSONB NOT NULL DEFAULT '[]',
    estado          TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','autorizada','negada')),
    resposta        JSONB,
    resolvido_por   TEXT CHECK (resolvido_por IN ('terminal','cli')),
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolvido_em    TIMESTAMPTZ,
    consumido_em    TIMESTAMPTZ,
    obsoleto_em     TIMESTAMPTZ,
    CHECK ((estado = 'pendente') = (resolvido_por IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_gate_pendente
    ON gate_requests ((COALESCE(session_id, '')), decisao, referencia) WHERE estado = 'pendente';
CREATE INDEX IF NOT EXISTS idx_gate_sessao ON gate_requests (session_id, estado);

CREATE TABLE IF NOT EXISTS session_inbox (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL,
    tipo         TEXT NOT NULL CHECK (tipo IN ('orientacao', 'comando')),
    conteudo     TEXT NOT NULL CHECK (char_length(conteudo) <= 2000),
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    entregue_em  TIMESTAMPTZ,
    consumido_em TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_inbox_pendentes ON session_inbox (session_id, id) WHERE consumido_em IS NULL;
