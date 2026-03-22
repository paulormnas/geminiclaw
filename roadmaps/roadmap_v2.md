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
    │   ├── indexer.py           # Indexação vetorial com chromadb
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

## Etapa S0 — Interface base de skills

Objetivo: contrato comum que toda skill deve implementar,
garantindo que o ADK consiga registrá-las como ferramentas de forma uniforme.

- [ ] Implementar `src/skills/base.py` com a classe abstrata `BaseSkill`:
  ```python
  class BaseSkill:
      name: str         # Identificador único da skill
      description: str  # Descrição que o agente lê para decidir quando usar
      async def run(self, **kwargs) -> SkillResult: ...
  ```
- [ ] Definir `SkillResult` com campos: `success`, `output`, `error`, `metadata`
- [ ] Implementar `src/skills/__init__.py` com `SkillRegistry`:
  - [ ] `register(skill: BaseSkill)` → registra uma skill
  - [ ] `get(name: str)` → retorna a skill pelo nome
  - [ ] `list_available()` → retorna lista de skills com nome e descrição
  - [ ] `as_adk_tools()` → converte skills registradas para o formato `tools` do ADK
- [ ] Escrever testes unitários do registry (registro, recuperação, conflito de nomes)
- [ ] Commit: `feat(skills): implementa interface base e registry de skills`

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

- [ ] Implementar `src/skills/search_quick/scraper.py` com `DuckDuckGoScraper`:
  - [ ] `search(query, max_results=5)` → `list[SearchResult]`
  - [ ] `SearchResult` com campos: `title`, `url`, `snippet`
  - [ ] Requisição via `httpx.AsyncClient` com headers de browser para evitar bloqueio
  - [ ] Parser HTML com `BeautifulSoup` extraindo resultados da página de busca do DDG
  - [ ] Tratamento de rate limiting: retry com backoff exponencial (máximo 3 tentativas)
  - [ ] Timeout configurável (`QUICK_SEARCH_TIMEOUT_SECONDS`, padrão: 10)
- [ ] Implementar `src/skills/search_quick/cache.py` com `SearchCache`:
  - [ ] Cache em memória com TTL configurável (`QUICK_SEARCH_CACHE_TTL_SECONDS`, padrão: 3600)
  - [ ] Chave de cache: hash SHA-256 da query normalizada (lowercase, sem espaços extras)
  - [ ] `get(query)` → resultado cacheado ou `None`
  - [ ] `set(query, results)` → armazena resultado
  - [ ] `invalidate(query)` → remove entrada específica
  - [ ] `clear()` → limpa todo o cache
- [ ] Implementar `src/skills/search_quick/skill.py` como `QuickSearchSkill(BaseSkill)` com:
  - [ ] `run(query, max_results=5)` → `SkillResult`
  - [ ] Consulta o cache antes de fazer scraping
  - [ ] `description`: *"Use esta skill para buscar informações atuais na internet de forma rápida. Forneça uma query específica. Retorna títulos, URLs e resumos dos primeiros resultados."*
- [ ] Registrar `QuickSearchSkill` no `SkillRegistry`
- [ ] Adicionar ao `.env.example`:
  ```
  QUICK_SEARCH_TIMEOUT_SECONDS=10
  QUICK_SEARCH_CACHE_TTL_SECONDS=3600
  QUICK_SEARCH_MAX_RESULTS=5
  ```
- [ ] Escrever testes unitários do scraper com HTML mockado
- [ ] Escrever testes unitários do cache (hit, miss, TTL expirado)
- [ ] Escrever testes unitários do retry com backoff
- [ ] Escrever teste de integração: query real → resultados retornados (requer rede)
- [ ] Commit: `feat(skills): implementa skill de busca rápida com scraper DuckDuckGo`

---

## Etapa S2 — Skill de busca profunda (crawler + índice vetorial)

> **Independente da Etapa S1.** Pode ser implementada sozinha ou depois da S1.

Objetivo: permitir que agentes busquem em uma base de conhecimento curada
e indexada localmente. Ideal para tarefas que exigem profundidade em domínios
específicos (documentação técnica, papers, fontes confiáveis) sem depender
de resultados genéricos da web em tempo real.

### Funcionamento

Um crawler coleta páginas dos domínios configurados, chunka o conteúdo em
trechos semânticos e indexa num banco vetorial local com `chromadb`. O agente
envia uma query em linguagem natural, que é convertida em embedding e comparada
com os vetores do índice. Os trechos mais similares são retornados como contexto.

### Dependências Python

```
uv add httpx beautifulsoup4 lxml chromadb
```

### Tarefas

- [ ] Implementar `src/skills/search_deep/crawler.py` com `DomainCrawler`:
  - [ ] `crawl(domains: list[str], max_pages_per_domain=50)` → `list[CrawledPage]`
  - [ ] `CrawledPage` com campos: `url`, `title`, `content`, `crawled_at`
  - [ ] Respeitar `robots.txt` de cada domínio
  - [ ] Rate limiting: máximo de 1 requisição por segundo por domínio
  - [ ] Chunking de conteúdo em trechos de ~500 tokens com sobreposição de ~50 tokens
  - [ ] Salvar estado do crawl em `store/crawl_state.json` para permitir resumo
  - [ ] Modo incremental: re-crawlar apenas páginas com `Last-Modified` mais recente que o último crawl
- [ ] Implementar `src/skills/search_deep/indexer.py` com `VectorIndexer`:
  - [ ] `index(pages: list[CrawledPage])` → indexa os chunks no ChromaDB
  - [ ] `search(query, n_results=5)` → `list[IndexResult]`
  - [ ] `IndexResult` com campos: `content`, `url`, `title`, `score`
  - [ ] Banco ChromaDB persistido em `store/vector_index/`
  - [ ] Coleção separada por domínio para facilitar filtragem
  - [ ] `reindex(domain)` → remove e re-indexa um domínio específico
  - [ ] `stats()` → retorna número de chunks indexados por domínio
- [ ] Implementar `src/skills/search_deep/cache.py` com `DeepSearchCache`:
  - [ ] Cache em SQLite para queries já realizadas ao índice (evita re-embedding)
  - [ ] TTL configurável (`DEEP_SEARCH_CACHE_TTL_SECONDS`, padrão: 86400)
- [ ] Implementar `src/skills/search_deep/skill.py` como `DeepSearchSkill(BaseSkill)` com:
  - [ ] `run(query, domains=None, n_results=5)` → `SkillResult`
  - [ ] Se `domains` fornecido, filtra a busca às coleções correspondentes
  - [ ] `description`: *"Use esta skill para buscar em profundidade dentro de fontes indexadas e confiáveis. Forneça uma query em linguagem natural. Retorna trechos relevantes com fonte e score de relevância."*
- [ ] Criar comando CLI para administração do índice:
  ```bash
  uv run python -m src.skills.search_deep.indexer crawl   # executa crawl e indexa
  uv run python -m src.skills.search_deep.indexer stats   # exibe estatísticas
  uv run python -m src.skills.search_deep.indexer reindex <domain>
  ```
- [ ] Registrar `DeepSearchSkill` no `SkillRegistry`
- [ ] Adicionar ao `.env.example`:
  ```
  DEEP_SEARCH_DOMAINS=                      # Comma-separated: docs.python.org,arxiv.org
  DEEP_SEARCH_MAX_PAGES_PER_DOMAIN=50
  DEEP_SEARCH_CACHE_TTL_SECONDS=86400
  VECTOR_INDEX_PATH=./store/vector_index
  ```
- [ ] Escrever testes unitários do crawler com HTML mockado
- [ ] Escrever testes unitários do chunking (tamanho correto, sobreposição)
- [ ] Escrever testes unitários do indexer com ChromaDB em memória
- [ ] Escrever testes unitários do cache de queries
- [ ] Escrever teste de integração: crawl de página real → indexação → busca retorna resultado relevante
- [ ] Commit: `feat(skills): implementa skill de busca profunda com crawler e índice vetorial`

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

- [ ] Implementar `src/skills/code/sandbox.py` com `PythonSandbox`:
  - [ ] `run(code, session_id, task_name, timeout)` → `SandboxResult`
  - [ ] Container efêmero `python:3.11-slim` com:
    - Volume: `outputs/<session_id>/<task_name>/` → `/outputs`
    - Rede desabilitada (`network_disabled=True`)
    - Memória: `256m`, CPU: `0.5`, usuário non-root
  - [ ] Injeta código como `/tmp/script.py` e executa `python /tmp/script.py`
  - [ ] `SandboxResult` com: `stdout`, `stderr`, `exit_code`, `artifacts`
  - [ ] Destroi o container após execução (`remove=True`)
- [ ] Implementar `src/skills/code/skill.py` como `CodeSkill(BaseSkill)` com:
  - [ ] `run(code, session_id, task_name, packages=None)` → `SkillResult`
  - [ ] Se `packages` fornecido, instala com `uv pip install` antes da execução
  - [ ] Rejeita código com `os.system`, `subprocess` com `shell=True` ou acesso a `/etc/`, `/root/`
  - [ ] `description`: *"Use esta skill para executar código Python. Forneça o código completo como string. Todo arquivo salvo em '/outputs/' estará disponível como artefato."*
- [ ] Registrar `CodeSkill` no `SkillRegistry`
- [ ] Adicionar ao `.env.example`:
  ```
  CODE_SANDBOX_TIMEOUT_SECONDS=60
  CODE_SANDBOX_MEMORY_LIMIT=256m
  ```
- [ ] Escrever testes unitários da validação de segurança
- [ ] Escrever teste de integração: código simples → stdout capturado
- [ ] Escrever teste de integração: código salva arquivo → artefato disponível no host
- [ ] Escrever teste de integração: timeout excedido → container destruído corretamente
- [ ] Commit: `feat(skills): implementa skill de execução de código Python em sandbox`

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

- [ ] Implementar `src/skills/memory/short_term.py` com `ShortTermMemory`:
  - [ ] `write(session_id, key, value, source, tags=[])` → `MemoryEntry`
  - [ ] `read(session_id, key)` → `MemoryEntry | None`
  - [ ] `search(session_id, tags)` → `list[MemoryEntry]`
  - [ ] `list_all(session_id)` → `list[MemoryEntry]` por `created_at`
  - [ ] `clear(session_id)` → limpa memória da sessão
  - [ ] Storage: dicionário em RAM por `session_id`
- [ ] Implementar `MemorySkill` em `src/skills/memory/skill.py`:
  - [ ] `remember(key, value, tags=[])` → grava na memória da sessão atual
  - [ ] `recall(key)` → recupera por chave exata
  - [ ] `recall_by_tags(tags)` → recupera por tags
  - [ ] `description`: *"Use 'remember' para registrar descobertas durante a tarefa. Use 'recall' ou 'recall_by_tags' para recuperar o que foi registrado anteriormente na mesma sessão."*
- [ ] Escrever testes unitários: escrita, leitura, busca por tags, isolamento entre sessões
- [ ] Commit: `feat(skills): implementa memória de curto prazo por sessão`

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

- [ ] Implementar `src/skills/memory/long_term.py` com `LongTermMemory`:
  - [ ] `write(key, value, source, importance=0.5, tags=[])` → `MemoryEntry`
  - [ ] `read(key)` → `MemoryEntry | None` (atualiza `last_used` e `use_count`)
  - [ ] `search(tags=[], min_importance=0.0, limit=10)` → `list[MemoryEntry]`
  - [ ] `update_importance(key, delta)` → ajusta importância (+/-)
  - [ ] `forget(key)` → remove entrada obsoleta
  - [ ] `summarize_for_context(limit=5)` → texto das entradas mais importantes para injetar no contexto
- [ ] Integrar ao `SessionManager`: ao criar sessão, chamar `summarize_for_context()` e injetar no contexto inicial
- [ ] Atualizar `MemorySkill` adicionando:
  - [ ] `memorize(key, value, importance, tags=[])` → grava na memória de longo prazo
  - [ ] `remember_forever(key)` → promove entrada de curto para longo prazo
  - [ ] `retrieve(key)` → busca em curto prazo primeiro, depois longo prazo
  - [ ] `description` atualizada para incluir as novas operações
- [ ] Adicionar ao `.env.example`: `LONG_TERM_MEMORY_DB=./store/memory.db`
- [ ] Escrever testes unitários: escrita, leitura, busca, promoção de entradas
- [ ] Escrever teste de integração: memória gravada em sessão A → recuperada em sessão B
- [ ] Commit: `feat(skills): implementa memória de longo prazo persistente com SQLite`

---

## Etapa S6 — Integração das skills ao agente base

Objetivo: registrar todas as skills implementadas no agente base e garantir
que agentes especializados as herdem automaticamente.

- [ ] Atualizar `agents/base/agent.py` para:
  - [ ] Registrar no `SkillRegistry` as skills habilitadas via `.env` (cada skill é opcional)
  - [ ] Passar `registry.as_adk_tools()` ao `Agent(tools=...)`
  - [ ] Injetar `summarize_for_context()` na `instruction` do agente ao iniciar
- [ ] Definir flags de habilitação no `.env.example`:
  ```
  SKILL_QUICK_SEARCH_ENABLED=true
  SKILL_DEEP_SEARCH_ENABLED=false   # Requer crawl prévio
  SKILL_CODE_ENABLED=true
  SKILL_MEMORY_ENABLED=true
  ```
- [ ] Atualizar `Dockerfile` base com dependências das skills habilitadas
- [ ] Atualizar `GEMINI.md` com a lista de skills disponíveis e quando cada uma deve ser usada
- [ ] Escrever teste de integração: agente base inicializa com as skills habilitadas
- [ ] Escrever teste de integração: agente usa `QuickSearchSkill` → resultado gravado na `ShortTermMemory`
- [ ] Escrever teste de integração: agente usa `CodeSkill` → artefato em `outputs/<session_id>/<task_name>/`
- [ ] Commit: `feat(agents): integra skills ao agente base com habilitação por flags`

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

- [ ] Implementar `src/autonomous_loop.py` com `AutonomousLoop`:
  - [ ] `run(agent, task, session_id)` → `LoopResult`
  - [ ] `MAX_RETRY_PER_SUBTASK` (padrão: 3) — subtarefa marcada como `failed` se atingido
  - [ ] `MAX_SUBTASKS_PER_TASK` (padrão: 10) — orquestrador notificado se atingido
  - [ ] Log de cada iteração: subtarefa, skill usada, resultado, número de tentativas
- [ ] Integrar `AutonomousLoop` ao `src/orchestrator.py` como modo padrão
- [ ] Escrever testes unitários com agente mockado
- [ ] Escrever teste de integração: 3 subtarefas → loop completo → artefatos em `outputs/`
- [ ] Escrever teste de retry: subtarefa falha 3 vezes → `failed` → loop continua
- [ ] Commit: `feat(orchestrator): implementa loop de execução autônoma`

---

## Etapa S8 — Validação das skills integradas

Objetivo: confirmar que as skills funcionam de forma coordenada em
um cenário realista de tarefa longa com múltiplos agentes.

- [ ] Executar `validation-task.md` com as skills habilitadas e verificar:
  - [ ] `QuickSearchSkill` (ou `DeepSearchSkill`) usada pelo researcher
  - [ ] `CodeSkill` usada para o pipeline de ML completo
  - [ ] `ShortTermMemory` consultada pelo agente de avaliação
  - [ ] `LongTermMemory` recebe ao menos uma entrada promovida
  - [ ] Artefatos em `outputs/<session_id>/` com estrutura correta
- [ ] Verificar no log: `skill_invoked`, `skill_completed`, `memory_written`, `memory_promoted`
- [ ] Commit: `feat(skills): milestone/skills-v1 — skills validadas em tarefa completa`

---

## Dependências entre etapas

```
roadmap principal (Etapa 7 — agente base)
└── S0 (interface base)
    ├── S1 (busca rápida)       ← independente de S2
    ├── S2 (busca profunda)     ← independente de S1
    ├── S3 (execução de código)
    └── S4 (memória curto prazo)
        └── S5 (memória longo prazo)
            └── S6 (integração ao agente base)
                └── S7 (loop autônomo)
                    └── S8 (validação integrada)
```

> S1 e S2 são paralelas e independentes. S6 integra as que estiverem
> implementadas via flags de habilitação — você não precisa de ambas
> para avançar.

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
VECTOR_INDEX_PATH=./store/vector_index

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