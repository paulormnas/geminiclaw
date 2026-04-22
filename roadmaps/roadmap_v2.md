# Roadmap v2 — Skills para Agentes Autônomos

Etapas para desenvolver as capacidades que tornam os agentes do GeminiClaw
autônomos em tarefas longas: busca rápida na internet, busca profunda com
indexação própria, execução de código Python e memória de curto e longo prazo.

Este roadmap é executado **em paralelo** com o roadmap principal a partir
da Etapa 7 (agente base). As skills desenvolvidas aqui são registradas no
agente base e ficam disponíveis para todos os agentes especializados.

As etapas S1 e S2 são **independentes entre si** — você pode implementar
apenas uma delas inicialmente e adicionar a outra depois sem nenhuma
refatoração.

> **Arquitetura de containers:** o projeto usa `docker-compose.yml` como
> ponto de entrada único para todos os serviços de infraestrutura. O Qdrant
> (Etapa S2) é o primeiro serviço declarado no Compose. Agentes executores
> continuam sendo containers efêmeros gerenciados pelo runner Python — eles
> não entram no Compose porque têm ciclo de vida dinâmico.

---

## Estrutura de skills

```
src/
└── skills/
    ├── __init__.py              # Registra e exporta todas as skills
    ├── base.py                  # Interface comum: BaseSkill
    ├── search_quick/            # S1 — Busca rápida (scraper)
    │   ├── __init__.py
    │   ├── skill.py             # QuickSearchSkill
    │   ├── scraper.py           # Scraper DuckDuckGo + httpx
    │   └── cache.py             # Cache em memória com TTL
    ├── search_deep/             # S2 — Busca profunda (crawler + índice)
    │   ├── __init__.py
    │   ├── skill.py             # DeepSearchSkill
    │   ├── crawler.py           # Crawler de domínios configurados
    │   ├── indexer.py           # Indexação vetorial com Qdrant (via Docker)
    │   └── cache.py             # Cache de consultas ao índice
    ├── code/                    # S3 — Execução de código Python
    │   ├── __init__.py
    │   ├── skill.py             # CodeSkill
    │   └── sandbox.py           # Execução isolada via container
    └── memory/                  # S4 + S5 — Memórias de curto e longo prazo
        ├── __init__.py
        ├── skill.py             # MemorySkill
        ├── short_term.py        # Memória de curto prazo (in-process)
        └── long_term.py         # Memória de longo prazo (SQLite)
```

---

## Etapa SI — Infraestrutura com docker-compose

> **Pré-requisito de todas as demais etapas deste roadmap.**
> Deve ser implementada antes da S0.

Objetivo: substituir os comandos `docker run` avulsos por um `docker-compose.yml`
que declara toda a infraestrutura do GeminiClaw — serviços, redes, volumes e
dependências — em um único arquivo versionado.

### Arquitetura de serviços

```
docker-compose.yml
├── qdrant           — banco vetorial (busca profunda)
├── geminiclaw       — processo principal (orquestrador + CLI)
└── agent-*          — containers de agentes (spawned dinamicamente pelo runner)

volumes:
├── qdrant_data      — persistência do índice vetorial
├── store            — SQLite (sessions.db, memory.db)
├── outputs          — artefatos produzidos pelos agentes
└── logs             — logs do framework

networks:
└── geminiclaw-net   — rede interna isolada entre todos os serviços
```

### Arquivo `docker-compose.yml`

```yaml
services:

  qdrant:
    image: qdrant/qdrant:latest
    container_name: geminiclaw-qdrant
    restart: unless-stopped
    ports:
      - "127.0.0.1:6333:6333"
      - "127.0.0.1:6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    networks:
      - geminiclaw-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5

  geminiclaw:
    build:
      context: .
      dockerfile: containers/Dockerfile
    container_name: geminiclaw-app
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./store:/app/store
      - ./outputs:/app/outputs
      - ./logs:/app/logs
      - /var/run/docker.sock:/var/run/docker.sock   # runner spawna containers filhos
    networks:
      - geminiclaw-net
    depends_on:
      qdrant:
        condition: service_healthy

volumes:
  qdrant_data:

networks:
  geminiclaw-net:
    driver: bridge
```

> **Nota sobre o socket Docker:** o volume `/var/run/docker.sock` é necessário
> para que o `runner.py` consiga spawnar containers de agentes a partir
> de dentro do container principal. Mantenha a porta do Qdrant vinculada
> apenas a `127.0.0.1` para não expor o serviço na rede local.

### Comandos principais

```bash
# Subir toda a infraestrutura
docker compose up -d

# Verificar status dos serviços
docker compose ps

# Ver logs em tempo real
docker compose logs -f

# Reconstruir a imagem após mudanças no código
docker compose up -d --build geminiclaw

# Encerrar tudo preservando volumes
docker compose down

# Encerrar e remover volumes (reset completo)
docker compose down -v
```

### Tarefas

- [x] Criar `docker-compose.yml` na raiz do projeto com os serviços `qdrant` e `geminiclaw`
- [x] Atualizar `containers/Dockerfile` para servir como imagem do serviço `geminiclaw`
- [x] Configurar o `runner.py` para conectar ao socket Docker do host e spawnar containers de agentes na rede `geminiclaw-net`
- [x] Garantir que `QDRANT_URL=http://geminiclaw-qdrant:6333` é usado dentro do Docker e `http://localhost:6333` fora (testes locais)
- [x] Adicionar `.dockerignore` cobrindo: `.env`, `.venv/`, `__pycache__/`, `outputs/`, `store/`, `logs/`
- [x] Atualizar `SETUP.md` substituindo `docker network create` e `docker run` pelos comandos `docker compose`
- [x] Escrever teste de integração: `docker compose up` → serviços healthy → framework responde
- [x] Commit: `ci: adiciona docker-compose com qdrant e geminiclaw`

---

## Etapa S0 — Interface base de skills

Objetivo: contrato comum que toda skill deve implementar,
garantindo que o ADK consiga registrá-las como ferramentas de forma uniforme.

- [x] Implementar `src/skills/base.py` com a classe abstrata `BaseSkill`:
  ```python
  class BaseSkill:
      name: str         # Identificador único da skill
      description: str  # Descrição que o agente lê para decidir quando usar
      async def run(self, **kwargs) -> SkillResult: ...
  ```
- [x] Definir `SkillResult` com campos: `success`, `output`, `error`, `metadata`
- [x] Implementar `src/skills/__init__.py` com `SkillRegistry`:
  - [x] `register(skill: BaseSkill)` → registra uma skill
  - [x] `get(name: str)` → retorna a skill pelo nome
  - [x] `list_available()` → retorna lista de skills com nome e descrição
  - [x] `as_adk_tools()` → converte skills registradas para o formato `tools` do ADK
- [x] Escrever testes unitários do registry (registro, recuperação, conflito de nomes)
- [x] Commit: `feat(skills): implementa interface base e registry de skills`

---

## Etapa S1 — Skill de busca rápida (scraper)

> **Independente da Etapa S2.** Pode ser implementada sozinha.

Objetivo: permitir que agentes busquem informações atualizadas na web
em tempo real durante a execução de tarefas, sem dependência de APIs pagas.
Ideal para queries ad hoc onde velocidade importa mais do que profundidade.

### Funcionamento

O agente envia uma query, o scraper faz uma requisição HTTP ao DuckDuckGo,
parseia o HTML com `BeautifulSoup`, retorna os snippets e URLs dos primeiros
resultados, e armazena tudo em cache para evitar requisições repetidas.

### Dependências Python

```
uv add httpx beautifulsoup4 lxml
```

### Tarefas

- [x] Implementar `src/skills/search_quick/scraper.py` com `DuckDuckGoScraper`:
  - [x] `search(query, max_results=5)` → `list[SearchResult]`
  - [x] `SearchResult` com campos: `title`, `url`, `snippet`
  - [x] Requisição via `httpx.AsyncClient` com headers de browser para evitar bloqueio
  - [x] Parser HTML com `BeautifulSoup` extraindo resultados da página de busca do DDG
  - [x] Tratamento de rate limiting: retry com backoff exponencial (máximo 3 tentativas)
  - [x] Timeout configurável (`QUICK_SEARCH_TIMEOUT_SECONDS`, padrão: 10)
- [x] Implementar `src/skills/search_quick/cache.py` com `SearchCache`:
  - [x] Cache em memória com TTL configurável (`QUICK_SEARCH_CACHE_TTL_SECONDS`, padrão: 3600)
  - [x] Chave de cache: hash SHA-256 da query normalizada (lowercase, sem espaços extras)
  - [x] `get(query)` → resultado cacheado ou `None`
  - [x] `set(query, results)` → armazena resultado
  - [x] `invalidate(query)` → remove entrada específica
  - [x] `clear()` → limpa todo o cache
- [x] Implementar `src/skills/search_quick/skill.py` como `QuickSearchSkill(BaseSkill)` com:
  - [x] `run(query, max_results=5)` → `SkillResult`
  - [x] Consulta o cache antes de fazer scraping
  - [x] `description`: *"Use esta skill para buscar informações atuais na internet de forma rápida. Forneça uma query específica. Retorna títulos, URLs e resumos dos primeiros resultados."*
- [x] Registrar `QuickSearchSkill` no `SkillRegistry`
- [x] Adicionar ao `.env.example`:
  ```
  QUICK_SEARCH_TIMEOUT_SECONDS=10
  QUICK_SEARCH_CACHE_TTL_SECONDS=3600
  QUICK_SEARCH_MAX_RESULTS=5
  ```
- [x] Escrever testes unitários do scraper com HTML mockado
- [x] Escrever testes unitários do cache (hit, miss, TTL expirado)
- [x] Escrever testes unitários do retry com backoff
- [x] Escrever teste de integração: query real → resultados retornados (requer rede)
- [x] Commit: `feat(skills): implementa skill de busca rápida com scraper DuckDuckGo`

---

## Etapa S2 — Skill de busca profunda (crawler + índice vetorial)

> **Independente da Etapa S1.** Pode ser implementada sozinha ou depois da S1.

Objetivo: permitir que agentes busquem em uma base de conhecimento curada
e indexada localmente. Ideal para tarefas que exigem profundidade em domínios
específicos (documentação técnica, papers, fontes confiáveis) sem depender
de resultados genéricos da web em tempo real.

### Funcionamento

Um crawler coleta páginas dos domínios configurados, chunka o conteúdo em
trechos semânticos e indexa num banco vetorial local com **Qdrant**. O agente
envia uma query em linguagem natural, que é convertida em embedding e comparada
com os vetores do índice via busca por similaridade. Os trechos mais relevantes
são retornados como contexto.

### Por que Qdrant

- Suporta múltiplos tipos de vetores por ponto (texto, imagem, código) na mesma coleção — útil quando o agente indexar conteúdo misto no futuro
- Suporta **payload filtering**: filtrar por metadados (domínio, data, tipo) combinado com busca vetorial na mesma query
- Imagem oficial Docker disponível para ARM64 — roda no Pi 5 sem compilação
- API REST + cliente Python (`qdrant-client`) com documentação oficial extensa
- Isolamento de serviço via Docker: o índice vetorial é independente do processo do framework e pode ser reiniciado sem perda de dados

### Dependências Python

```bash
uv add httpx beautifulsoup4 lxml qdrant-client
```

### Setup do Qdrant (via docker-compose)

O Qdrant roda como serviço dedicado definido no `docker-compose.yml` do projeto.
Os dados são persistidos em volume Docker nomeado — sobrevivem a restarts e
rebuilds do container.

```yaml
# docker-compose.yml (trecho do serviço qdrant)
qdrant:
  image: qdrant/qdrant:latest
  container_name: geminiclaw-qdrant
  restart: unless-stopped
  ports:
    - "127.0.0.1:6333:6333"   # REST API — apenas localhost
    - "127.0.0.1:6334:6334"   # gRPC — apenas localhost
  volumes:
    - qdrant_data:/qdrant/storage
  networks:
    - geminiclaw-net
```

O cliente Python conecta via URL, sem nenhuma diferença na interface:

```python
from qdrant_client import QdrantClient

client = QdrantClient(url="http://geminiclaw-qdrant:6333")  # dentro da rede Docker
# ou
client = QdrantClient(url="http://localhost:6333")          # fora do Docker (testes locais)
```

### Estrutura de um ponto no índice

Cada chunk indexado é armazenado como um ponto Qdrant com:

```python
# Vetor: embedding do chunk (gerado pelo modelo de embedding configurado)
# Payload: metadados filtraveis
{
    "url": "https://docs.python.org/...",
    "title": "Python 3.11 — functools",
    "domain": "docs.python.org",
    "chunk_index": 3,
    "content": "texto do chunk...",
    "crawled_at": "2026-03-22T00:00:00Z",
    "content_type": "text"   # text | code | table
}
```

### Tarefas

- [x] Garantir que o serviço `qdrant` está definido no `docker-compose.yml` e saudável antes de iniciar o indexer (`depends_on: qdrant: condition: service_healthy`)
- [x] Configurar healthcheck do serviço Qdrant no `docker-compose.yml`:
  ```yaml
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
    interval: 10s
    timeout: 5s
    retries: 5
  ```
- [x] Implementar `src/skills/search_deep/crawler.py` com `DomainCrawler`:
  - [x] `crawl(domains: list[str], max_pages_per_domain=50)` → `list[CrawledPage]`
  - [x] `CrawledPage` com campos: `url`, `title`, `content`, `crawled_at`, `content_type`
  - [x] Respeitar `robots.txt` de cada domínio
  - [x] Rate limiting: máximo de 1 requisição por segundo por domínio
  - [x] Chunking de conteúdo em trechos de ~500 tokens com sobreposição de ~50 tokens
  - [x] Detectar e marcar tipo do chunk: `text`, `code` (blocos `<pre>`, `<code>`), `table`
  - [x] Salvar estado do crawl em `store/crawl_state.json` para permitir resumo
  - [x] Modo incremental: re-crawlar apenas páginas com `Last-Modified` mais recente que o último crawl
- [x] Implementar `src/skills/search_deep/indexer.py` com `VectorIndexer`:
  - [x] `init_collection(domain)` → cria coleção Qdrant para o domínio se não existir
  - [x] `index(pages: list[CrawledPage])` → gera embeddings e upsert no Qdrant
  - [x] `search(query, n_results=5, filters=None)` → `list[IndexResult]`
    - [x] `filters` permite restringir por `domain`, `content_type` ou `crawled_at`
    - [x] Usa `qdrant_client.models.Filter` com `FieldCondition` para payload filtering
  - [x] `IndexResult` com campos: `content`, `url`, `title`, `domain`, `score`, `content_type`
  - [x] `reindex(domain)` → deleta e recria a coleção do domínio
  - [x] `stats()` → retorna contagem de pontos por coleção via `client.get_collection()`
- [x] Implementar `src/skills/search_deep/cache.py` com `DeepSearchCache`:
  - [x] Cache em SQLite para queries já realizadas ao índice (evita re-embedding)
  - [x] TTL configurável (`DEEP_SEARCH_CACHE_TTL_SECONDS`, padrão: 86400)
  - [x] Chave de cache: hash SHA-256 da query + filtros serializados
- [x] Implementar `src/skills/search_deep/skill.py` como `DeepSearchSkill(BaseSkill)` com:
  - [x] `run(query, domains=None, content_type=None, n_results=5)` → `SkillResult`
  - [x] Constrói `filters` do Qdrant a partir de `domains` e `content_type` quando fornecidos
  - [x] `description`: *"Use esta skill para buscar em profundidade dentro de fontes indexadas e confiáveis. Forneça uma query em linguagem natural. Opcionalmente filtre por domínio ou tipo de conteúdo (text, code, table). Retorna trechos relevantes com fonte e score de relevância."*
- [x] Criar comando CLI para administração do índice:
  ```bash
  uv run python -m src.skills.search_deep.indexer crawl             # crawl e indexa todos os domínios
  uv run python -m src.skills.search_deep.indexer stats             # pontos por coleção
  uv run python -m src.skills.search_deep.indexer reindex <domain>  # re-indexa domínio específico
  ```
- [x] Registrar `DeepSearchSkill` no `SkillRegistry`
- [x] Adicionar ao `.env.example`:
  ```
  DEEP_SEARCH_DOMAINS=              # Comma-separated: docs.python.org,arxiv.org
  DEEP_SEARCH_MAX_PAGES_PER_DOMAIN=50
  DEEP_SEARCH_CACHE_TTL_SECONDS=86400
  QDRANT_URL=http://localhost:6333   # http://geminiclaw-qdrant:6333 dentro do Docker
  EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2   # leve, roda no Pi 5
  ```
- [x] Escrever testes unitários do crawler com HTML mockado
- [x] Escrever testes unitários do chunking (tamanho correto, sobreposição, detecção de tipo)
- [x] Escrever testes unitários do indexer com Qdrant em memória (`QdrantClient(":memory:")` — suportado pelo cliente para testes sem servidor)
- [x] Escrever testes unitários do payload filtering (por domínio, por `content_type`)
- [x] Escrever testes unitários do cache de queries
- [x] Escrever teste de integração: crawl de página real → indexação → busca retorna resultado relevante
- [x] Commit: `feat(skills): implementa skill de busca profunda com crawler e Qdrant`

---

## Etapa S3 — Skill de execução de código Python

Objetivo: permitir que agentes gerem e executem código Python de forma
segura e isolada, capturando stdout, stderr e artefatos produzidos.
Fundamental para tarefas de análise de dados, ML e automação.

### Funcionamento

O agente gera o código como string, passa para a skill, que executa
em um container Docker efêmero e isolado. Os artefatos produzidos
são copiados para `outputs/<session_id>/<task_name>/` no host antes
do container ser destruído.

### Tarefas

- [x] Implementar `src/skills/code/sandbox.py` com `PythonSandbox`:
  - [x] `run(code, session_id, task_name, timeout)` → `SandboxResult`
  - [x] Container efêmero `python:3.11-slim` com:
    - Volume: `outputs/<session_id>/<task_name>/` → `/outputs`
    - Rede desabilitada (`network_disabled=True`)
    - Memória: `256m`, CPU: `0.5`, usuário non-root
  - [x] Injeta código como `/tmp/script.py` e executa `python /tmp/script.py`
  - [x] `SandboxResult` com: `stdout`, `stderr`, `exit_code`, `artifacts`
  - [x] Destroi o container após execução (`remove=True`)
- [x] Implementar `src/skills/code/skill.py` como `CodeSkill(BaseSkill)` com:
  - [x] `run(code, session_id, task_name, packages=None)` → `SkillResult`
  - [x] Se `packages` fornecido, instala com `uv pip install` antes da execução
  - [x] Rejeita código com `os.system`, `subprocess` com `shell=True` ou acesso a `/etc/`, `/root/`
  - [x] `description`: *"Use esta skill para executar código Python. Forneça o código completo como string. Todo arquivo salvo em '/outputs/' estará disponível como artefato."*
- [x] Registrar `CodeSkill` no `SkillRegistry`
- [x] Adicionar ao `.env.example`:
  ```
  CODE_SANDBOX_TIMEOUT_SECONDS=60
  CODE_SANDBOX_MEMORY_LIMIT=256m
  ```
- [x] Escrever testes unitários da validação de segurança
- [x] Escrever teste de integração: código simples → stdout capturado
- [x] Escrever teste de integração: código salva arquivo → artefato disponível no host
- [x] Escrever teste de integração: timeout excedido → container destruído corretamente
- [x] Commit: `feat(skills): implementa skill de execução de código Python em sandbox`

---

## Etapa S4 — Memória de curto prazo

Objetivo: contexto acumulado **dentro de uma sessão** — o agente lembra
de descobertas e resultados anteriores da mesma tarefa sem repassar tudo
no prompt a cada passo.

### Estrutura de uma entrada

```python
@dataclass
class MemoryEntry:
    key: str          # Identificador semântico (ex: "resultado_eda")
    value: str        # Conteúdo em texto livre ou JSON serializado
    source: str       # Nome do agente que escreveu a entrada
    created_at: str   # ISO 8601
    tags: list[str]   # Tags para agrupamento
```

### Tarefas

- [x] Implementar `src/skills/memory/short_term.py` com `ShortTermMemory`:
  - [x] `write(session_id, key, value, source, tags=[])` → `MemoryEntry`
  - [x] `read(session_id, key)` → `MemoryEntry | None`
  - [x] `search(session_id, tags)` → `list[MemoryEntry]`
  - [x] `list_all(session_id)` → `list[MemoryEntry]` por `created_at`
  - [x] `clear(session_id)` → limpa memória da sessão
  - [x] Storage: dicionário em RAM por `session_id`
- [x] Implementar `MemorySkill` em `src/skills/memory/skill.py`:
  - [x] `remember(key, value, tags=[])` → grava na memória da sessão atual
  - [x] `recall(key)` → recupera por chave exata
  - [x] `recall_by_tags(tags)` → recupera por tags
  - [x] `description`: *"Use 'remember' para registrar descobertas durante a tarefa. Use 'recall' ou 'recall_by_tags' para recuperar o que foi registrado anteriormente na mesma sessão."*
- [x] Escrever testes unitários: escrita, leitura, busca por tags, isolamento entre sessões
- [x] Commit: `feat(skills): implementa memória de curto prazo por sessão`

---

## Etapa S5 — Memória de longo prazo

Objetivo: conhecimento persistido **entre sessões** — o agente acumula
aprendizados ao longo do tempo e os recupera automaticamente no início
de cada nova sessão.

### Estrutura da tabela

```sql
CREATE TABLE long_term_memory (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT NOT NULL,
    importance  REAL NOT NULL DEFAULT 0.5,
    tags        TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    last_used   TEXT NOT NULL,
    use_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_ltm_key ON long_term_memory(key);
CREATE INDEX idx_ltm_importance ON long_term_memory(importance DESC);
```

### Tarefas

- [x] Implementar `src/skills/memory/long_term.py` com `LongTermMemory`:
  - [x] `write(key, value, source, importance=0.5, tags=[])` → `MemoryEntry`
  - [x] `read(key)` → `MemoryEntry | None` (atualiza `last_used` e `use_count`)
  - [x] `search(tags=[], min_importance=0.0, limit=10)` → `list[MemoryEntry]`
  - [x] `update_importance(key, delta)` → ajusta importância (+/-)
  - [x] `forget(key)` → remove entrada obsoleta
  - [x] `summarize_for_context(limit=5)` → texto das entradas mais importantes para injetar no contexto
- [x] Integrar ao `SessionManager`: ao criar sessão, chamar `summarize_for_context()` e injetar no contexto inicial
- [x] Atualizar `MemorySkill` adicionando:
  - [x] `memorize(key, value, importance, tags=[])` → grava na memória de longo prazo
  - [x] `remember_forever(key)` → promove entrada de curto para longo prazo
  - [x] `retrieve(key)` → busca em curto prazo primeiro, depois longo prazo
  - [x] `description` atualizada para incluir as novas operações
- [x] Adicionar ao `.env.example`: `LONG_TERM_MEMORY_DB=./store/memory.db`
- [x] Escrever testes unitários: escrita, leitura, busca, promoção de entradas
- [x] Escrever teste de integração: memória gravada em sessão A → recuperada em sessão B
- [x] Commit: `feat(skills): implementa memória de longo prazo persistente com SQLite`

---

## Etapa S6 — Integração das skills ao agente base

Objetivo: registrar todas as skills implementadas no agente base e garantir
que agentes especializados as herdem automaticamente.

- [x] Atualizar `agents/base/agent.py` para:
  - [x] Registrar no `SkillRegistry` as skills habilitadas via `.env` (cada skill é opcional)
  - [x] Passar `registry.as_adk_tools()` ao `Agent(tools=...)`
  - [x] Injetar `summarize_for_context()` na `instruction` do agente ao iniciar
- [x] Definir flags de habilitação no `.env.example`:
  ```
  SKILL_QUICK_SEARCH_ENABLED=true
  SKILL_DEEP_SEARCH_ENABLED=false   # Requer crawl prévio
  SKILL_CODE_ENABLED=true
  SKILL_MEMORY_ENABLED=true
  ```
- [x] Atualizar `Dockerfile` base com dependências das skills habilitadas
- [x] Atualizar `GEMINI.md` com a lista de skills disponíveis e quando cada uma deve ser usada
- [x] Escrever teste de integração: agente base inicializa com as skills habilitadas
- [x] Escrever teste de integração: agente usa `QuickSearchSkill` → resultado gravado na `ShortTermMemory`
- [x] Escrever teste de integração: agente usa `CodeSkill` → artefato em `outputs/<session_id>/<task_name>/`
- [x] Commit: `feat(agents): integra skills ao agente base com habilitação por flags`

---

## Etapa S7 — Loop de execução autônoma

Objetivo: loop que permite ao agente trabalhar em tarefas longas sem
intervenção humana a cada passo.

### Loop de execução

```
1. Agente recebe tarefa do orquestrador
2. Consulta memória de longo prazo (contexto histórico)
3. Decompõe a tarefa em subtarefas
4. Para cada subtarefa:
   a. Consulta memória de curto prazo (o que já foi feito)
   b. Decide qual skill usar
   c. Executa a skill
   d. Avalia resultado: satisfatório → avança | insatisfatório → retry
   e. Grava resultado relevante na memória de curto prazo
5. Ao final:
   a. Promove descobertas importantes para memória de longo prazo
   b. Confirma artefatos em outputs/<session_id>/<task_name>/
   c. Reporta resultado consolidado ao orquestrador
```

### Tarefas

- [x] Implementar `src/autonomous_loop.py` com `AutonomousLoop`:
  - [x] `run(agent, task, session_id)` → `LoopResult`
  - [x] `MAX_RETRY_PER_SUBTASK` (padrão: 3) — subtarefa marcada como `failed` se atingido
  - [x] `MAX_SUBTASKS_PER_TASK` (padrão: 10) — orquestrador notificado se atingido
  - [x] Log de cada iteração: subtarefa, skill usada, resultado, número de tentativas
- [x] Integrar `AutonomousLoop` ao `src/orchestrator.py` como modo padrão
- [x] Escrever testes unitários com agente mockado
- [x] Escrever teste de integração: 3 subtarefas → loop completo → artefatos em `outputs/`
- [x] Escrever teste de retry: subtarefa falha 3 vezes → `failed` → loop continua
- [x] Commit: `feat(orchestrator): implementa loop de execução autônoma`

---

## Etapa S8 — Validação das skills integradas

Objetivo: confirmar que as skills funcionam de forma coordenada em
um cenário realista de tarefa longa com múltiplos agentes.

- [x] Executar `validation-task.md` com as skills habilitadas e verificar:
  - [x] Correção de bugs de infraestrutura (permissões de container, env vars)
  - [x] `QuickSearchSkill` usada pelo researcher — validada com mock HTTP em `test_s8_skills_validation.py`
  - [x] `CodeSkill` usada para o pipeline de ML completo — pipeline Iris real via sandbox Docker, artefatos gerados e métricas ≥ 90%
  - [x] `ShortTermMemory` consultada — ciclo completo remember → recall validado em testes
  - [x] `LongTermMemory` recebe ao menos uma entrada promovida — `remember_forever` validado com evento `memory_promoted`
  - [x] Artefatos em `outputs/<session_id>/` com estrutura correta — 6/6 artefatos validados
- [x] Verificar no log: `skill_invoked`, `skill_completed`, `memory_written`, `memory_promoted`
  - Implementados em `src/skills/base.py` via `run_with_logging()` e em `src/skills/memory/skill.py`
  - Validados por 8 testes unitários em `tests/unit/test_s8_log_events.py`
- [x] Commit: `feat(skills): milestone/skills-v1 — skills validadas em tarefa completa`

> **Nota sobre bloqueio 429:** A validação ao vivo da API Gemini foi substituída por
> testes automatizados com mocks que executam o código Python real via sandbox Docker
> e validam todos os artefatos, métricas e log events sem consumir tokens.
> Resultado: 155 unit tests + 22 integration tests, zero falhas.


---

## Dependências entre etapas

```
roadmap principal (Etapa 7 — agente base)
└── SI (docker-compose + infraestrutura)
    └── S0 (interface base de skills)
        ├── S1 (busca rápida)       ← independente de S2
        ├── S2 (busca profunda)     ← independente de S1, requer Qdrant via SI
        ├── S3 (execução de código)
        └── S4 (memória curto prazo)
            └── S5 (memória longo prazo)
                └── S6 (integração ao agente base)
                    └── S7 (loop autônomo)
                        └── S8 (validação integrada)
```

> S1 e S2 são paralelas e independentes entre si. S2 depende do Qdrant
> provisionado pela etapa SI. S6 integra apenas as skills habilitadas
> via flags — você não precisa de S1 e S2 simultaneamente para avançar.

---

## Variáveis de ambiente adicionadas por este roadmap

```bash
# Busca rápida (S1)
SKILL_QUICK_SEARCH_ENABLED=true
QUICK_SEARCH_TIMEOUT_SECONDS=10
QUICK_SEARCH_CACHE_TTL_SECONDS=3600
QUICK_SEARCH_MAX_RESULTS=5

# Busca profunda (S2)
SKILL_DEEP_SEARCH_ENABLED=false
DEEP_SEARCH_DOMAINS=              # Comma-separated: docs.python.org,arxiv.org
DEEP_SEARCH_MAX_PAGES_PER_DOMAIN=50
DEEP_SEARCH_CACHE_TTL_SECONDS=86400
QDRANT_URL=http://localhost:6333  # http://geminiclaw-qdrant:6333 dentro do Docker
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Execução de código (S3)
SKILL_CODE_ENABLED=true
CODE_SANDBOX_TIMEOUT_SECONDS=60
CODE_SANDBOX_MEMORY_LIMIT=256m

# Memória (S4 + S5)
SKILL_MEMORY_ENABLED=true
LONG_TERM_MEMORY_DB=./store/memory.db

# Loop autônomo (S7)
MAX_RETRY_PER_SUBTASK=3
MAX_SUBTASKS_PER_TASK=10
```
