# Roadmap V8 — Migração de SQLite para PostgreSQL

**Contexto:** Este roadmap substitui todos os bancos SQLite do projeto por um único PostgreSQL rodando como container Docker, acessível por todos os agentes. Os dados existentes no SQLite **não** serão migrados — o projeto inicia do zero.

> **Pré-requisito:** Roadmaps V1–V4 concluídos. Docker Compose funcional com Qdrant.
> **Relacionado:** Roadmap V7 (Document Processing) — as tabelas de documentos serão criadas diretamente no PostgreSQL.

---

## Motivação

O SQLite apresenta limitações em cenários multi-agente concorrente:

1. **Lock de escrita exclusivo** — apenas um processo escreve por vez, causando `database is locked` frequente (mitigado por retries pesados no código atual).
2. **Múltiplos arquivos .db** — o projeto mantém `geminiclaw.db`, `memory.db` e `llm_cache.db` separados, dificultando backup e manutenção.
3. **Acesso inter-container** — cada container monta o diretório `/data` e acessa o `.db` via file lock, gerando I/O errors em concorrência.
4. **Sem connection pooling** — cada operação abre e fecha uma conexão SQLite.

O PostgreSQL resolve tudo isso com conexões TCP concorrentes, um único servidor centralizado, e connection pooling nativo.

---

## Inventário de Módulos Afetados

| Módulo | Arquivo | Tabelas SQLite | Lib Atual |
|---|---|---|---|
| SessionManager | `src/session.py` | `agent_sessions` | `sqlite3` |
| ExecutionHistory | `src/history.py` | `execution_history` | `sqlite3` |
| LLMResponseCache | `src/llm_cache.py` | `llm_cache`, `llm_cache_stats` | `sqlite3` |
| LongTermMemory | `src/skills/memory/long_term.py` | `long_term_memory` | `sqlite3` |
| DeepSearchCache | `src/skills/search_deep/cache.py` | `deep_search_cache` | `sqlite_utils` |
| Config | `src/config.py` | — (define `SQLITE_DB_PATH`) | — |
| ContainerRunner | `src/runner.py` | — (monta volume `/data`) | — |

**Total: 6 tabelas em 5 módulos + 2 módulos de infraestrutura.**

---

## Etapa V8.1 — Container PostgreSQL no Docker Compose

**Objetivo:** Adicionar o serviço PostgreSQL ao `docker-compose.yml` com volume persistente local.

### Configuração do Serviço

```yaml
# docker-compose.yml — novo serviço
  postgres:
    image: postgres:16-alpine
    container_name: geminiclaw-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-geminiclaw}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-geminiclaw_secret}
      POSTGRES_DB: ${POSTGRES_DB:-geminiclaw}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init_db.sql:/docker-entrypoint-initdb.d/01_init.sql:ro
    networks:
      - geminiclaw-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-geminiclaw}"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:    # NOVO
  qdrant_data:
  ollama_data:
```

> **Nota sobre Pi 5:** A imagem `postgres:16-alpine` suporta ARM64 nativamente e consome ~30 MB de RAM idle — aceitável para o Pi 5.

### Variáveis de Ambiente

```bash
# .env.example — novas variáveis
POSTGRES_USER=geminiclaw
POSTGRES_PASSWORD=geminiclaw_secret
POSTGRES_DB=geminiclaw
POSTGRES_HOST=localhost              # host direto
POSTGRES_PORT=5432

# URL completa (usada pelo código Python)
# Quando rodando no host: localhost
# Quando rodando em container: geminiclaw-postgres
DATABASE_URL=postgresql://geminiclaw:geminiclaw_secret@localhost:5432/geminiclaw
```

### Script de Inicialização

```sql
-- scripts/init_db.sql
-- Executado automaticamente na primeira inicialização do container PostgreSQL.
-- Cria todas as tabelas necessárias para o projeto.

-- Sessões de agentes (src/session.py)
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

-- Histórico de execuções (src/history.py)
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

-- Cache de respostas LLM (src/llm_cache.py)
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

-- Memória de longo prazo (src/skills/memory/long_term.py)
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

-- Cache de deep search (src/skills/search_deep/cache.py)
CREATE TABLE IF NOT EXISTS deep_search_cache (
    query_hash  TEXT PRIMARY KEY,
    query       TEXT NOT NULL,
    results     JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dsc_expires ON deep_search_cache(expires_at);
```

### Tarefas V8.1

- [x] Adicionar serviço `postgres` ao `docker-compose.yml` com volume `postgres_data`
- [x] Atualizar `depends_on` do serviço `geminiclaw` para incluir `postgres` com `service_healthy`
- [x] Criar `scripts/init_db.sql` com todas as 6 tabelas e índices
- [x] Adicionar variáveis `POSTGRES_*` e `DATABASE_URL` ao `.env.example`
- [x] Adicionar variáveis ao `.env` (sem commitar)
- [x] Testar: `docker compose up postgres` → verificar que as tabelas foram criadas
- [x] Commit: `feat(infra): adiciona container PostgreSQL ao docker-compose`

---

## Etapa V8.2 — Camada de Conexão PostgreSQL (`src/db.py`)

**Objetivo:** Criar um módulo centralizado de conexão ao PostgreSQL com connection pooling, substituindo as conexões SQLite espalhadas.

### Decisão: psycopg vs asyncpg

| Lib | Sync/Async | Pool Nativo | RAM (Pi 5) | Justificativa |
|---|---|---|---|---|
| **psycopg[pool]** (v3) | Ambos | Sim (`ConnectionPool`) | ~5 MB | API similar ao sqlite3, suporta sync e async |
| asyncpg | Async only | Sim | ~8 MB | Exigiria reescrever toda a camada de dados para async |

**Decisão:** `psycopg[pool]` v3 — menor impacto na refatoração pois suporta a API síncrona que o código atual já usa, com opção de migrar para async no futuro.

### Implementação

```python
# src/db.py
"""Módulo centralizado de conexão ao PostgreSQL."""

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from src.config import DATABASE_URL
from src.logger import get_logger

logger = get_logger(__name__)

_pool: ConnectionPool | None = None

def get_pool() -> ConnectionPool:
    """Retorna o pool de conexões singleton.

    Returns:
        ConnectionPool configurado e pronto para uso.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=2,
            max_size=10,
            open=False,       # Lazy: não conecta no construtor
            kwargs={"row_factory": dict_row},
        )
        logger.info("Pool PostgreSQL inicializado", extra={
            "extra": {"min_size": 2, "max_size": 10}
        })
    return _pool

def get_connection():
    """Context manager para obter uma conexão do pool.

    Uso:
        with get_connection() as conn:
            conn.execute("SELECT 1")
    """
    return get_pool().connection()

def close_pool() -> None:
    """Encerra o pool de conexões."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("Pool PostgreSQL encerrado")
```

### Tarefas V8.2

- [x] Adicionar `psycopg[binary,pool]>=3.2` ao `pyproject.toml` (dependência principal)
- [x] Criar `src/db.py` com pool singleton (lazy `open=False`)
- [x] Adicionar `DATABASE_URL` ao `src/config.py`
- [x] Lógica de fallback: dentro de containers, usar `geminiclaw-postgres` como host; fora, usar `localhost`
- [x] Testes unitários: pool inicializa, conexão funciona, pool encerra
- [x] Commit: `feat(db): cria módulo centralizado de conexão PostgreSQL`

---

## Etapa V8.3 — Migração dos Módulos

**Objetivo:** Refatorar cada módulo para usar `src/db.get_connection()` em vez de `sqlite3.connect()`.

### Padrão de Migração

O padrão é o mesmo para todos os módulos:

```python
# ANTES (SQLite)
import sqlite3
conn = sqlite3.connect(self.db_path, timeout=300.0)
conn.row_factory = sqlite3.Row
cursor = conn.execute("SELECT * FROM table WHERE id = ?", (id,))
row = cursor.fetchone()
conn.close()

# DEPOIS (PostgreSQL via psycopg)
from src.db import get_connection
with get_connection() as conn:
    row = conn.execute("SELECT * FROM table WHERE id = %s", (id,)).fetchone()
```

**Mudanças principais:**
- Placeholder: `?` → `%s`
- Sem `conn.close()` manual — o context manager devolve ao pool
- Sem `PRAGMA` — PostgreSQL não usa PRAGMAs
- Sem `BEGIN IMMEDIATE` — PostgreSQL gerencia transações nativamente
- `sqlite3.Row` → `dict_row` (configurado no pool)
- `sqlite_utils` → `psycopg` direto (para `DeepSearchCache`)
- Remove decorador `_retry_db()` — PostgreSQL não tem file locks

### Módulos a Migrar

#### 1. `src/session.py` — SessionManager

- Remover `import sqlite3`, `_retry_db`, `init_db()`
- `__init__`: remover `db_path`, usar `get_connection()`
- Remover todos os `PRAGMA` e `BEGIN IMMEDIATE`
- Trocar `?` por `%s` em todas as queries
- `_get_connection()` → `get_connection()` do `src/db`

#### 2. `src/history.py` — ExecutionHistory

- Remover `import sqlite3`, `_init_db()`, `_get_connection()`
- Usar `get_connection()` do `src/db`
- Trocar placeholders

#### 3. `src/llm_cache.py` — LLMResponseCache

- Remover `import sqlite3`, `_init_db()`, `_get_connection()`
- `ON CONFLICT(hash_key) DO UPDATE SET` funciona igual no PostgreSQL
- Trocar placeholders

#### 4. `src/skills/memory/long_term.py` — LongTermMemory

- Remover `import sqlite3`, `_init_db()`, `_get_connection()`
- Remover `_retry_db`
- Tags: `json.dumps(tags)` → pode usar JSONB diretamente com `Json()` adapter

#### 5. `src/skills/search_deep/cache.py` — DeepSearchCache

- Remover `import sqlite_utils`
- Reescrever usando `get_connection()` + SQL direto
- `sqlite_utils.db.NotFoundError` → checar `fetchone() is None`

### Tarefas V8.3

- [x] Migrar `src/session.py` — remover sqlite3, usar `src/db`
- [x] Migrar `src/history.py`
- [x] Migrar `src/llm_cache.py`
- [x] Migrar `src/skills/memory/long_term.py`
- [x] Migrar `src/skills/search_deep/cache.py` — remover `sqlite_utils`
- [x] Atualizar testes unitários de cada módulo (substituir `sqlite3` in-memory por mocks de `get_connection`)
- [x] Commit: `refactor(db): migra todos os módulos de SQLite para PostgreSQL`

---

## Etapa V8.4 — Configuração e Runner

**Objetivo:** Atualizar `config.py`, `runner.py` e Docker Compose para que os containers dos agentes acessem o PostgreSQL via rede Docker.

### Alterações em `src/config.py`

```python
# REMOVER
SQLITE_DB_PATH = get_env("SQLITE_DB_PATH", default="store/geminiclaw.db")
LONG_TERM_MEMORY_DB = get_env("LONG_TERM_MEMORY_DB", default="./store/memory.db")

# ADICIONAR
DATABASE_URL = get_env(
    "DATABASE_URL",
    default="postgresql://geminiclaw:geminiclaw_secret@localhost:5432/geminiclaw"
)

# Manter LONG_TERM_MEMORY_DB como alias se necessário para retrocompatibilidade
```

### Alterações em `src/runner.py`

```python
# REMOVER referências a SQLITE_DB_PATH nos volumes e env do container
# Os containers não precisam mais montar /data para o banco — 
# acessam o PostgreSQL via rede Docker (geminiclaw-net)

# env do container:
env = {
    # ...
    "DATABASE_URL": "postgresql://geminiclaw:geminiclaw_secret@geminiclaw-postgres:5432/geminiclaw",
    # REMOVER: "SQLITE_DB_PATH": "/data/geminiclaw.db",
    # REMOVER: "LONG_TERM_MEMORY_DB": "/data/memory.db",
}

# volumes: remover o mapeamento db_dir_host -> /data
# Manter apenas /outputs e /logs
```

### Alterações no `docker-compose.yml`

```yaml
  geminiclaw:
    environment:
      - DATABASE_URL=postgresql://geminiclaw:geminiclaw_secret@geminiclaw-postgres:5432/geminiclaw
    depends_on:
      qdrant:
        condition: service_healthy
      postgres:
        condition: service_healthy
```

### Tarefas V8.4

- [x] Atualizar `src/config.py`: remover `SQLITE_DB_PATH` e `LONG_TERM_MEMORY_DB`, adicionar `DATABASE_URL`
- [x] Atualizar `src/runner.py`: remover volume `/data` para DB, injetar `DATABASE_URL` nos containers
- [x] Atualizar `docker-compose.yml`: adicionar `DATABASE_URL` e `depends_on: postgres`
- [x] Adicionar método `_ensure_postgres()` ao `ContainerRunner.ensure_infrastructure()`
- [x] Atualizar testes unitários de `runner` e `config`
- [x] Commit: `refactor(config): remove SQLITE_DB_PATH, usa DATABASE_URL para PostgreSQL`

---

## Etapa V8.5 — Limpeza e Documentação

**Objetivo:** Remover dependências SQLite, atualizar documentação e validar o sistema end-to-end.

### Dependências

```toml
# pyproject.toml — REMOVER
"sqlite-utils>=3.39",

# pyproject.toml — ADICIONAR (já feito em V8.2)
"psycopg[binary,pool]>=3.2",
```

### Limpeza

- Remover arquivos `*.db` do `.gitignore` (não mais necessários)
- Manter `store/` para IPC sockets e outros dados de runtime
- Remover `Path(SQLITE_DB_PATH).parent.mkdir(...)` do `config.py`
- Remover `_retry_db` decorator de `src/session.py` (não mais necessário)
- Atualizar `AGENTS.md`: trocar referências a SQLite por PostgreSQL
- Atualizar `README.md`: diagrama de arquitetura, tabela de componentes, estrutura de diretórios

### Validação End-to-End

1. `docker compose up -d` — todos os serviços sobem (postgres, qdrant, geminiclaw)
2. Verificar healthcheck do PostgreSQL
3. Conectar no banco e validar tabelas: `docker exec -it geminiclaw-postgres psql -U geminiclaw -c '\dt'`
4. Executar pipeline completo com pelo menos 2 agentes simultâneos
5. Verificar que sessões, histórico e cache foram gravados no PostgreSQL
6. Parar e reiniciar containers — dados persistem

### Tarefas V8.5

- [x] Remover `sqlite-utils` do `pyproject.toml`
- [x] Rodar `uv sync` para atualizar lockfile
- [x] Remover `_retry_db` e imports de `sqlite3` residuais em `src/`
- [x] Remover todos os `SQLITE_DB_PATH` e `LONG_TERM_MEMORY_DB` de agentes, CLI e testes
- [x] Pool com `open=False` (lazy) — não bloqueia em importações sem banco disponível
- [x] Rodar `uv run pytest tests/unit/ tests/skills/` — **387/387 passando**
- [ ] Rodar validação end-to-end com `docker compose up` (requer ambiente Pi 5)
- [ ] Commit: `chore(db): remove dependências SQLite, atualiza documentação`


---

## Dependências a Adicionar

```toml
# pyproject.toml
dependencies = [
    # ... existentes ...
    "psycopg[binary,pool]>=3.2",    # NOVO — driver PostgreSQL com pool
]
```

```bash
uv add "psycopg[binary,pool]>=3.2"
```

> **Nota ARM64:** O extra `binary` inclui o libpq compilado, evitando instalar `libpq-dev` no container. Funciona em ARM64/Pi 5.

---

## Ordem de Implementação

```
V8.1 (Container PG) → V8.2 (src/db.py) → V8.3 (Migração módulos) → V8.4 (Config/Runner) → V8.5 (Limpeza)
```

Cada etapa depende da anterior — pipeline sequencial.

---

## Critérios de Aceite

1. `docker compose up -d` sobe PostgreSQL, Qdrant e a aplicação sem erros
2. Todas as 6 tabelas existem no PostgreSQL após o primeiro boot
3. Os dados persistem entre restarts do container (`docker compose down && docker compose up`)
4. Múltiplos agentes em containers separados acessam o banco simultaneamente sem erros de lock
5. `uv run pytest` passa com 100% dos testes
6. Nenhum `import sqlite3` ou `import sqlite_utils` resta no código de produção (`src/`)
7. A variável `DATABASE_URL` é a única configuração de banco necessária
8. O volume `postgres_data` está mapeado e os dados sobrevivem a `docker compose down`
