# ADR 005 — Estratégia de Persistência: PostgreSQL + Qdrant + SQLite

**Status:** Aceito
**Data:** 2026-09-22
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap.md` (Etapa 4), `roadmaps/roadmap_V8_postgres_migration.md`, `roadmaps/roadmap_V5_observability.md`

---

## Contexto

O sistema precisa persistir múltiplos tipos de dado com características diferentes:
- **Estado de sessão:** Histórico de mensagens, status de execução, plano aprovado — acesso concorrente, consistência transacional
- **Telemetria:** Eventos de execução, uso de tokens, uso de ferramentas, snapshots de hardware — escrita em batch de alta frequência, leitura eventual
- **Memória semântica:** Embeddings de conhecimento adquirido entre sessões — busca por similaridade vetorial
- **Cache local:** Estado efêmero de runtime do processo host — sem necessidade de durabilidade entre reinicializações

---

## Decisão

Três camadas de persistência com responsabilidades distintas:

### 1. PostgreSQL 16 — Persistência Relacional Principal

**Responsabilidades:**
- Sessões e histórico de mensagens (`agent_sessions`)
- Telemetria de execução (`agent_events`, `tool_usage`, `token_usage`, `hardware_snapshots`)
- Cache de queries de busca profunda (`search_deep_cache`)
- Memória de longo prazo textual (`long_term_memory`)

**Acesso:** Pool de conexões `psycopg` v3 via singleton `src/db.py`. Agents em container escrevem via canal IPC de fallback (`_telemetry` payload), nunca diretamente ao banco.

**Configuração em `docker-compose.yml`:**
```yaml
services:
  postgres:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

### 2. Qdrant — Índice Vetorial para Memória Semântica

**Responsabilidades:**
- Memória de longo prazo com busca por similaridade semântica (`MemorySkill.long_term`)
- Índice de documentos do usuário para `DeepSearchSkill`
- Embeddings gerados por `fastembed`

**Acesso:** `qdrant-client` Python SDK, acessado pelo orquestrador e agentes via `geminiclaw-net`.

**Configuração em `docker-compose.yml`:**
```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrant_data:/qdrant/storage
```

### 3. SQLite — Cache de Runtime Local

**Responsabilidades:**
- Cache local de curto prazo no processo do orquestrador
- Dados efêmeros que não precisam de durabilidade entre reinicializações do serviço

**Localização:** `store/` na raiz do projeto.
**Configuração:** WAL mode, `PRAGMA journal_mode=WAL`, cache de 32MB, `PRAGMA synchronous=NORMAL`.

---

## Histórico: Migração SQLite → PostgreSQL (V8)

O projeto iniciou com SQLite exclusivo para sessões. A migração para PostgreSQL (V8) foi motivada por:
- Concorrência: múltiplos agentes escrevendo na mesma sessão simultaneamente causava lock contention em SQLite
- Escala: o `TelemetryCollector` com flush em batch de 50 eventos excedia capacidade do SQLite em execuções longas
- Consultas: queries analíticas de telemetria (GROUP BY, window functions) exigiam extensões do PostgreSQL

---

## Alternativas Consideradas

### Alternativa A: SQLite exclusivo para tudo

**Descartado porque:**
- Lock contention em escritas concorrentes de múltiplos containers
- Sem busca vetorial nativa
- Performance inadequada para o volume de eventos de telemetria

### Alternativa B: MongoDB para persistência principal

**Descartado porque:**
- Schema flexível não compensa a perda de consistência transacional ACID
- Curva de aprendizado para queries de telemetria (sem SQL padrão)
- Mais um serviço a manter no Pi 5 com pouca RAM

### Alternativa C: Redis para cache + PostgreSQL para persistência

**Descartado porque:**
- Redis como dependência adicional apenas para cache não justifica o overhead operacional
- O `ShortTermMemory` in-process (por sessão) resolve o caso de uso de cache sem serviço externo

---

## Consequências

### Positivas

- **Consistência ACID:** PostgreSQL garante que sessões e telemetria são persistidas de forma confiável mesmo em caso de falha de agentes.
- **Busca semântica:** Qdrant permite que o sistema recupere memórias relevantes por similaridade, não apenas por chave exata.
- **Separação de preocupações:** Cada store tem uma responsabilidade clara — facilita manutenção e evolução independente.

### Negativas / Trade-offs

- **Dois serviços externos:** PostgreSQL e Qdrant precisam estar rodando antes do orquestrador — `docker-compose up -d` é pré-requisito.
- **Setup no Pi 5:** Ambos os serviços consomem RAM (~200MB cada em idle); em memória disponível de 8GB é viável mas deve ser monitorado.
- **Latência de write:** Agents em container não escrevem diretamente ao PostgreSQL — usam canal IPC de fallback, introduzindo latência de flush.

---

## Revisão

Este ADR deve ser revisado quando:
- O hardware alvo mudar (mais RAM disponível pode justificar mover SQLite cache para Redis)
- Qdrant introduzir breaking changes de API
- O volume de telemetria crescer a ponto de exigir particionamento das tabelas PostgreSQL
