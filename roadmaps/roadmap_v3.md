# Roadmap v3 — Melhorias para Auxiliar de Pesquisa no Raspberry Pi 5

Este roadmap assume que **todas as tarefas dos roadmaps v1 e v2 foram implementadas**
(com exceção da validação S8, bloqueada por rate limiting 429, e da validação
no Raspberry Pi 5 — Etapa 12).

O foco aqui é **qualidade do sistema multiagentes como auxiliar de pesquisa**
e **otimização para hardware com recursos limitados** (Raspberry Pi 5: 8 GB RAM,
4 cores ARM Cortex-A76, armazenamento em microSD/NVMe).

---

## Diagnóstico do estado atual

### Pontos fortes já implementados
- Arquitetura modular com skills independentes e registry dinâmico
- IPC robusto com fallback TCP/Unix e reconexão automática
- Loop autônomo com triage simples/complexo
- Memória de curto e longo prazo funcional
- Sandbox de código isolado com limites de recursos

### Problemas identificados na análise

| # | Problema | Módulo | Impacto |
|---|---------|--------|---------|
| 1 | Instruções dos agentes são genéricas e não orientadas a pesquisa | `agents/*/agent.py` | Agentes não sabem como colaborar em workflows de pesquisa |
| 2 | Comunicação entre agentes é sempre serializada via orquestrador | `orchestrator.py`, `autonomous_loop.py` | Sem paralelismo real; cada agente espera o anterior terminar |
| 3 | Triage gasta uma chamada LLM completa (spawna container do Planner) | `autonomous_loop.py` | Latência e custo desnecessário para classificação simples |
| 4 | `_clean_json_text` usa regex frágil para parsear JSON de LLMs | `orchestrator.py` | Falhas frequentes no parsing de planos |
| 5 | QuickSearch depende de scraping HTML do DuckDuckGo (frágil) | `search_quick/scraper.py` | Quebra com mudanças no HTML do DDG |
| 6 | CodeSkill usa `pip install` dentro do sandbox (viola regra do projeto) | `code/skill.py:84` | Inconsistência com regras de `development.md` |
| 7 | Sandbox não implementa timeout real no `exec_run` | `code/sandbox.py` | Script pode travar o container indefinidamente |
| 8 | MemorySkill instancia novo `LongTermMemory()` a cada chamada em `tools.py` | `agents/base/tools.py` | Múltiplas conexões SQLite, sem reuso |
| 9 | Delay anti-429 fixo de 2s entre agentes | `orchestrator.py:214` | Lento demais para tarefas rápidas, insuficiente sob carga |
| 10 | Sem monitoramento de temperatura/recursos do Pi 5 | — | Risco de throttling térmico sem feedback |
| 11 | Docker images não otimizadas para ARM64 | `containers/Dockerfile` | Build lento e imagens grandes no Pi |
| 12 | Qdrant healthcheck removido do docker-compose | `docker-compose.yml:14` | Service pode iniciar sem Qdrant estar pronto |
| 13 | `runner.py` tem bloco `except` duplicado (linhas 210-216) | `src/runner.py` | Código morto |
| 14 | Sem skill de leitura/extração de conteúdo de URLs | — | Researcher não consegue ler páginas completas |
| 15 | Agentes não têm acesso a resultados de agentes anteriores no plano | `autonomous_loop.py` | Subtarefas não compartilham contexto intermediário |

---

## Etapa V1 — Instruções especializadas para pesquisa

Objetivo: reescrever as instruções de cada agente com foco em **auxiliar de pesquisa acadêmica e técnica**, definindo claramente papel, limitações e formato de saída.

### Tarefas

- [x] Reescrever `AGENT_INSTRUCTION` do **Planner** com:
  - Persona: "Você é um planejador de pesquisa acadêmica"
  - Critérios de decomposição orientados a pesquisa (levantamento → análise → síntese → relatório)
  - Regra de fusão de tarefas com dependência de I/O no mesmo agente
  - Formato JSON de saída com campo `task_name`, `agent_id`, `prompt`, `depends_on`, `expected_artifacts`
  - Limite explícito: máximo de 5 subtarefas por padrão (otimização para Pi 5)

- [x] Reescrever `AGENT_INSTRUCTION` do **Validator** com:
  - Checklist explícito: dependências, viabilidade no Pi 5, uso correto de skills, outputs especificados
  - Regra: rejeitar planos com mais de 7 subtarefas (forçar fusão)
  - Regra: verificar que subtarefas de pesquisa usam `quick_search` ou `deep_search`
  - Formato de resposta mais robusto com campo `corrected_plan` quando `revision_needed`

- [x] Reescrever `AGENT_INSTRUCTION` do **Researcher** com:
  - Persona: "Você é um pesquisador especializado em revisão bibliográfica"
  - Estratégia de pesquisa: query inicial → refinamento → síntese
  - Regra: sempre citar fontes com URL
  - Regra: salvar relatório em markdown estruturado via `write_artifact`
  - Instruções para usar `deep_search` quando domínios indexados estiverem disponíveis

- [x] Reescrever `AGENT_INSTRUCTION` do **Base** com:
  - Persona: "Você é um assistente de análise de dados e geração de código"
  - Foco em execução de código (`python_interpreter`) e produção de artefatos
  - Regra: sempre executar código gerado, nunca apenas exibi-lo
  - Regra: salvar todos os outputs via `write_artifact`

- [x] Adicionar campo `system_context` dinâmico com:
  - Lista de skills disponíveis e quando usar cada uma
  - Resumo da memória de longo prazo (já existe, melhorar formato)
  - Informações do hardware (RAM livre, temperatura) quando no Pi 5

- [x] Escrever testes unitários validando que cada agente contém palavras-chave obrigatórias na instrução
- [x] Commit: `refactor(agents): reescreve instruções especializadas para auxiliar de pesquisa`

---

## Etapa V2 — Compartilhamento de contexto entre subtarefas

Objetivo: permitir que o resultado de uma subtarefa seja injetado no prompt da próxima, eliminando a necessidade de cada agente "adivinhar" o que o anterior produziu.

### Tarefas

- [x] Adicionar campo `depends_on: list[str]` ao `AgentTask` no orquestrador
- [x] No `AutonomousLoop._run_complex_path`, ao executar cada subtarefa:
  - Verificar `depends_on` e coletar os `response.text` das subtarefas anteriores
  - Injetar como prefixo no prompt: `"Contexto das etapas anteriores:\n{contexto}"`
  - Limitar contexto injetado a 2000 tokens (truncar com aviso no log)
- [x] Atualizar o Planner para gerar `depends_on` no JSON de saída
- [x] Atualizar o Validator para verificar que `depends_on` referencia `task_name` válidos
- [x] Usar `ShortTermMemory` para armazenar resultados intermediários por `master_session_id`
- [x] Escrever testes unitários da injeção de contexto
- [x] Escrever teste de integração: subtarefa B recebe contexto de subtarefa A
- [x] Commit: `feat(orchestrator): implementa compartilhamento de contexto entre subtarefas`

---

## Etapa V3 — Triage local sem container

Objetivo: evitar o overhead de spawnar um container Docker apenas para decidir se a tarefa é simples ou complexa. No Pi 5, cada spawn custa ~3-5 segundos.

### Tarefas

- [x] Implementar `src/triage.py` com `TriageClassifier`:
  - Heurística baseada em regras (sem LLM):
    - Comprimento do prompt (< 20 tokens → SIMPLE)
    - Presença de palavras-chave de pesquisa ("pesquise", "compare", "analise dados", "pipeline") → COMPLEX
    - Presença de múltiplos verbos de ação → COMPLEX
    - Histórico: se últimas 3 tarefas do mesmo tipo foram COMPLEX → default COMPLEX
  - Fallback para LLM local via API (sem container) apenas quando heurística tem confiança < 0.7
- [x] Integrar `TriageClassifier` no `AutonomousLoop` substituindo `_is_complex_triage`
- [x] Adicionar variável `TRIAGE_MODE=heuristic|llm|hybrid` no `.env.example`
- [x] Escrever testes unitários com exemplos de prompts simples e complexos
- [x] Commit: `perf(triage): implementa classificação local sem container`

---

## Etapa V4 — Parsing robusto de JSON de LLMs

Objetivo: substituir o regex frágil de `_clean_json_text` por um parser tolerante a falhas.

### Tarefas

- [x] Implementar `src/utils/json_parser.py` com `extract_json(text: str) -> dict | list | None`:
  - Tentar `json.loads` direto primeiro
  - Remover blocos de código markdown (` ```json ... ``` `)
  - Buscar delimitadores `[` / `{` mais externos com contagem de balanceamento
  - Tratar trailing commas e comentários inline
  - Log de warning quando limpeza for necessária
- [x] Substituir `_clean_json_text` no orquestrador por `extract_json`
- [x] Adicionar retry com re-prompt quando parsing falhar:
  - Mensagem: "Sua resposta anterior não era JSON válido. Responda APENAS com o JSON."
- [x] Escrever testes unitários com exemplos reais de saídas problemáticas de LLMs
- [x] Commit: `fix(orchestrator): implementa parser robusto de JSON de LLMs`

---

## Etapa V5 — Skill de leitura de URLs (Web Reader)

Objetivo: permitir que o Researcher leia o conteúdo completo de uma URL, extraindo texto limpo de páginas HTML. Essencial para um auxiliar de pesquisa.

### Tarefas

- [x] Implementar `src/skills/web_reader/skill.py` com `WebReaderSkill(BaseSkill)`:
  - `run(url: str, max_chars: int = 5000) -> SkillResult`
  - Usa `httpx.AsyncClient` para buscar a página
  - Extrai texto limpo via `BeautifulSoup` (remove scripts, styles, nav)
  - Trunca conteúdo em `max_chars` com indicação de truncamento
  - Cache em memória com TTL de 1 hora (reusa `SearchCache`)
  - Respeita `robots.txt` antes de acessar
  - `description`: "Use para ler o conteúdo completo de uma URL. Retorna texto extraído da página."
- [x] Registrar `WebReaderSkill` no `SkillRegistry`
- [x] Adicionar flag `SKILL_WEB_READER_ENABLED=true` ao `.env.example`
- [x] Atualizar instrução do Researcher para mencionar a skill
- [x] Escrever testes unitários com HTML mockado
- [x] Commit: `feat(skills): implementa skill de leitura de URLs`

---

## Etapa V6 — Otimização de containers para ARM64

Objetivo: reduzir tempo de build, tamanho de imagem e consumo de memória no Raspberry Pi 5.

### Tarefas

- [x] Otimizar `containers/Dockerfile`:
  - Usar `python:3.11-slim-bookworm` com plataforma explícita `--platform=linux/arm64`
  - Separar dependências pesadas (fastembed, qdrant-client) em layer dedicado
  - Usar `--no-cache-dir` em todas as instalações
  - Remover `curl` do runtime (desnecessário para agentes)
  - Target final < 350 MB (atual estimado ~600+ MB por causa do fastembed)
- [x] Criar `containers/Dockerfile.slim` para agentes que não usam deep_search:
  - Excluir fastembed e qdrant-client → imagem < 200 MB
  - Usar para planner, validator e base (quando deep_search desabilitado)
- [x] Reduzir `mem_limit` de containers de agente:
  - Planner/Validator: `256m` (apenas texto, sem skills pesadas)
  - Base/Researcher: `384m` (com skills)
  - Sandbox de código: manter `256m`
- [x] Adicionar `.dockerignore` mais agressivo: excluir `tests/`, `roadmaps/`, `.git/`, `*.md`
- [x] Implementar pre-build de imagens no Pi: script `scripts/build_images.sh`
- [x] Escrever teste que verifica tamanho da imagem < limite configurado
- [x] Commit: `perf(docker): otimiza imagens para ARM64 e reduz footprint de memória`

---

## Etapa V7 — Monitoramento de recursos do Pi 5

Objetivo: evitar throttling térmico e OOM durante execução de múltiplos agentes.

### Tarefas

- [x] Implementar `src/health.py` com `PiHealthMonitor`:
  - `get_temperature() -> float` via `/sys/class/thermal/thermal_zone0/temp` ou `vcgencmd`
  - `get_memory_usage() -> dict` (total, available, percent)
  - `get_cpu_usage() -> float` via `/proc/stat`
  - `is_throttled() -> bool` via `vcgencmd get_throttled`
  - Fallback gracioso em non-Pi (retorna None)
- [x] Integrar no `ContainerRunner`:
  - Antes de `spawn()`: verificar temperatura < 75°C e memória disponível > 512 MB
  - Se exceder limites: aguardar com backoff até normalizar (máx 60s) ou recusar spawn
  - Log de warning quando temperatura > 70°C
- [x] Adicionar endpoint de saúde no `AutonomousLoop`:
  - Após cada subtarefa, logar métricas: `{"temp": 68.2, "mem_avail_mb": 2100, "cpu_pct": 45}`
- [x] Adicionar variáveis ao `.env.example`:
  ```
  PI_TEMPERATURE_LIMIT=75
  PI_MIN_AVAILABLE_MEMORY_MB=512
  HEALTH_CHECK_ENABLED=true
  ```
- [x] Escrever testes unitários com mock de `/sys/class/thermal`
- [ ] Verificar funcionamento do HealthMonitor no hardware real (Raspberry Pi 5)
- [x] Commit: `feat(health): implementa monitoramento de saúde do Raspberry Pi 5`

---

## Etapa V8 — Rate limiting adaptativo para API Gemini

Objetivo: substituir o delay fixo de 2 segundos por um sistema adaptativo que respeite os limites da API e maximize throughput.

### Tarefas

- [x] Implementar `src/rate_limiter.py` com `AdaptiveRateLimiter`:
  - Token bucket com taxa configurável (`GEMINI_REQUESTS_PER_MINUTE=15` requests por minuto)
  - Backoff exponencial automático ao receber HTTP 429
  - Janela deslizante de 60s para contagem de requests
  - `acquire()` → aguarda até que um token esteja disponível
  - `report_429()` → reduz taxa temporariamente (cool-down de 30s)
  - `report_success()` → incrementa taxa gradualmente até o limite
- [x] Integrar no `_execute_agent` do orquestrador, substituindo `asyncio.sleep(2)`
- [x] Adicionar ao `.env.example`:
  ```
  GEMINI_REQUESTS_PER_MINUTE=15
  GEMINI_RATE_LIMIT_COOLDOWN_SECONDS=30
  ```
- [x] Escrever testes unitários do token bucket e backoff
- [x] Commit: `feat(rate-limiter): implementa rate limiting adaptativo para API Gemini`

---

## Etapa V9 — Correções de bugs e dívida técnica

Objetivo: corrigir problemas identificados na análise do código.

### Tarefas

- [x] **Bloco except duplicado** em `src/runner.py` (linhas 210-216): remover o segundo bloco
- [x] **CodeSkill usa `pip install`**: substituir por `uv pip install` no sandbox ou pré-instalar no Dockerfile
- [x] **Sandbox sem timeout real**: implementar timeout via `threading.Timer` que mata o container após `exec_timeout`
- [x] **MemorySkill instanciada a cada chamada** em `agents/base/tools.py`: usar singleton ou injetar instância compartilhada
- [x] **Healthcheck do Qdrant removido**: restaurar healthcheck usando `wget` em vez de `curl` (disponível na imagem Qdrant)
- [x] **`except Exception: pass`** nos blocos finally do orquestrador: logar o erro antes de ignorá-lo
- [x] **`network_disabled=False`** no sandbox mesmo quando não há setup_commands: habilitar rede apenas quando `setup_commands` existe
- [x] Escrever testes para cada correção
- [ ] Commit: `fix: corrige bugs e dívida técnica identificados na análise v3`

---

## Etapa V10 — Execução paralela de subtarefas independentes

Objetivo: quando o plano contém subtarefas sem dependência entre si, executá-las em paralelo para reduzir o tempo total.

### Tarefas

- [ ] Implementar `src/task_scheduler.py` com `TaskScheduler`:
  - Recebe lista de `AgentTask` com campo `depends_on`
  - Constrói grafo de dependências (DAG)
  - Identifica subtarefas que podem rodar em paralelo (mesmo nível no DAG)
  - `schedule() -> list[list[AgentTask]]` → retorna "ondas" de execução
- [ ] Integrar no `AutonomousLoop._run_complex_path`:
  - Substituir loop sequencial por execução em ondas via `asyncio.gather`
  - Respeitar `Semaphore(3)` do runner (máx 3 containers simultâneos)
  - Se uma subtarefa de uma onda falhar, cancelar as demais da mesma onda
- [ ] Atualizar o Planner para usar `depends_on: []` para tarefas paralelizáveis
- [ ] Escrever testes unitários do DAG e scheduler
- [ ] Escrever teste de integração: 2 subtarefas paralelas → ambas completam
- [ ] Commit: `feat(scheduler): implementa execução paralela de subtarefas independentes`

---

## Etapa V11 — Agente Summarizer

Objetivo: adicionar um agente especializado em sintetizar resultados de pesquisa em relatórios finais estruturados.

### Tarefas

- [ ] Criar `agents/summarizer/agent.py` com:
  - Persona: "Você é um redator acadêmico especializado em síntese"
  - Instrução: receber múltiplos relatórios parciais e produzir um documento final coeso
  - Formato de saída: Markdown com seções, citações e conclusões
  - Skill de memória para consultar descobertas anteriores
  - Skill `write_artifact` para salvar o relatório final
- [ ] Criar `containers/Dockerfile.summarizer`
- [ ] Registrar no `AGENT_REGISTRY` do orquestrador
- [ ] Atualizar o Planner para incluir etapa de síntese final quando o plano tem múltiplas pesquisas
- [ ] Escrever testes unitários dos atributos do agente
- [ ] Commit: `feat(agents): implementa agente summarizer para síntese de pesquisas`

---

## Etapa V12 — Cache de respostas do Gemini

Objetivo: evitar chamadas repetidas à API para prompts idênticos ou muito similares, reduzindo custo e latência.

### Tarefas

- [ ] Implementar `src/llm_cache.py` com `LLMResponseCache`:
  - Storage em SQLite (`store/llm_cache.db`)
  - Chave: hash SHA-256 do prompt normalizado + model name
  - TTL configurável (`LLM_CACHE_TTL_SECONDS=3600`)
  - `get(prompt, model) -> str | None`
  - `set(prompt, model, response) -> None`
  - `stats() -> dict` (hits, misses, hit_rate)
  - Limite de tamanho: máximo 1000 entradas (FIFO eviction)
- [ ] Integrar no `agents/runner.py` (antes de chamar `InMemoryRunner.run_async`)
- [ ] Adicionar ao `.env.example`:
  ```
  LLM_CACHE_ENABLED=true
  LLM_CACHE_TTL_SECONDS=3600
  LLM_CACHE_MAX_ENTRIES=1000
  ```
- [ ] Escrever testes unitários
- [ ] Commit: `feat(cache): implementa cache de respostas do Gemini`

---

## Etapa V13 — QuickSearch resiliente com fallback

Objetivo: tornar a busca rápida mais confiável, sem depender exclusivamente do scraping HTML do DuckDuckGo.

### Tarefas

- [ ] Implementar fallback no `QuickSearchSkill`:
  - Tentativa 1: DuckDuckGo HTML scraping (atual)
  - Tentativa 2: DuckDuckGo Lite (HTML mais simples, menos propenso a mudanças)
  - Tentativa 3: Brave Search API (free tier, 1 req/s) se `BRAVE_API_KEY` configurada
- [ ] Implementar `src/skills/search_quick/ddg_lite.py` como scraper alternativo
- [ ] Adicionar ao `.env.example`:
  ```
  BRAVE_API_KEY=              # Opcional: fallback para busca rápida
  QUICK_SEARCH_STRATEGY=ddg,ddg_lite,brave
  ```
- [ ] Escrever testes unitários de cada backend e do mecanismo de fallback
- [ ] Commit: `feat(skills): adiciona fallback resiliente para busca rápida`

---

## Etapa V14 — Persistência de planos e histórico de execuções

Objetivo: salvar o plano aprovado e o resultado de cada execução em SQLite para auditoria e reuso.

### Tarefas

- [ ] Criar tabela `execution_history` no SQLite:
  ```sql
  CREATE TABLE execution_history (
      id TEXT PRIMARY KEY,
      prompt TEXT NOT NULL,
      plan_json TEXT,
      status TEXT NOT NULL,
      results_json TEXT,
      artifacts_json TEXT,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      duration_seconds REAL,
      total_subtasks INTEGER,
      succeeded INTEGER,
      failed INTEGER
  );
  ```
- [ ] Implementar `src/history.py` com `ExecutionHistory`:
  - `record(prompt, plan, result) -> str` (retorna ID)
  - `get(execution_id) -> ExecutionRecord | None`
  - `list_recent(limit=10) -> list[ExecutionRecord]`
  - `search(query) -> list[ExecutionRecord]` (busca no prompt)
- [ ] Integrar no orquestrador: persistir plano aprovado e resultado final
- [ ] Adicionar comando CLI: `geminiclaw history` para listar execuções anteriores
- [ ] Escrever testes unitários
- [ ] Commit: `feat(history): implementa persistência de planos e histórico de execuções`

---

## Etapa V15 — Swap e otimização de memória no Pi 5

Objetivo: documentar e automatizar a configuração de swap e ajustes de memória no Raspberry Pi 5.

### Tarefas

- [ ] Criar script `scripts/setup_pi.sh` com:
  - Configuração de swap de 4 GB (via `dphys-swapfile`)
  - Ajuste de `vm.swappiness=10`
  - Verificação de espaço em disco mínimo (10 GB livres)
  - Instalação de Docker e docker-compose se necessário
  - Criação da rede `geminiclaw-net`
  - Pre-pull das imagens base
- [ ] Implementar ajuste dinâmico do `Semaphore` baseado em memória disponível:
  - RAM >= 6 GB livre → Semaphore(3)
  - RAM >= 3 GB livre → Semaphore(2)
  - RAM < 3 GB livre → Semaphore(1)
- [ ] Documentar no `SETUP.md` (se instruído pelo usuário)
- [ ] Commit: `chore(pi): implementa script de setup e ajuste dinâmico de concorrência`

---

## Etapa V16 — Validação completa no Raspberry Pi 5

Objetivo: executar a validação end-to-end no hardware alvo com todas as melhorias do roadmap v3.

### Tarefas

- [ ] Clonar e configurar o repositório no Pi 5
- [ ] Executar `scripts/setup_pi.sh`
- [ ] Build de todas as imagens Docker para ARM64
- [ ] Rodar suite de testes completa: `uv run pytest -m "unit or integration" -v`
- [ ] Executar `validation-task.md` com skills habilitadas
- [ ] Monitorar durante execução:
  - Temperatura (< 75°C em operação sustentada)
  - Uso de memória por container (`docker stats`)
  - Tempo total da tarefa de validação (< 5 minutos)
- [ ] Verificar artefatos em `outputs/<session_id>/`
- [ ] Documentar resultados e ajustes necessários
- [ ] Commit: `chore: milestone/v3.0.0 — framework validado no Raspberry Pi 5 com melhorias v3`

---

## Dependências entre etapas

```
V1 (instruções) ─────────────────────────────────────────┐
V2 (contexto entre subtarefas) ──┐                       │
V3 (triage local) ───────────────┤                       │
V4 (parser JSON) ────────────────┤                       │
                                 ├── V10 (paralelo) ─────┤
V5 (web reader) ─────────────────┤                       ├── V16 (validação Pi 5)
V6 (ARM64) ──────────────────────┤                       │
V7 (health monitor) ─────────────┤                       │
V8 (rate limiter) ───────────────┤                       │
V9 (bugfixes) ───────────────────┘                       │
V11 (summarizer) ────────────────────────────────────────┤
V12 (LLM cache) ─────────────────────────────────────────┤
V13 (search fallback) ───────────────────────────────────┤
V14 (histórico) ─────────────────────────────────────────┤
V15 (swap Pi) ───────────────────────────────────────────┘
```

> Etapas V1–V9 são o **núcleo crítico** e devem ser implementadas antes das demais.
> V10 depende de V2 (campo `depends_on`).
> V11–V15 são independentes entre si e podem ser implementadas em qualquer ordem.
> V16 (validação) deve ser a última etapa.

---

## Variáveis de ambiente adicionadas por este roadmap

```bash
# Triage (V3)
TRIAGE_MODE=hybrid                     # heuristic | llm | hybrid

# Rate Limiting (V8)
GEMINI_REQUESTS_PER_MINUTE=15
GEMINI_RATE_LIMIT_COOLDOWN_SECONDS=30

# Health Monitor (V7)
PI_TEMPERATURE_LIMIT=75
PI_MIN_AVAILABLE_MEMORY_MB=512
HEALTH_CHECK_ENABLED=true

# Web Reader (V5)
SKILL_WEB_READER_ENABLED=true

# LLM Cache (V12)
LLM_CACHE_ENABLED=true
LLM_CACHE_TTL_SECONDS=3600
LLM_CACHE_MAX_ENTRIES=1000

# Search Fallback (V13)
BRAVE_API_KEY=
QUICK_SEARCH_STRATEGY=ddg,ddg_lite,brave
```
