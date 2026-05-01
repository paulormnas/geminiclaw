# Roadmap V5 — Observabilidade e Métricas para Pesquisa Acadêmica

**Contexto:** Este roadmap foca exclusivamente em instrumentação, coleta de métricas e auditoria do sistema multi-agente. O objetivo é gerar dados quantitativos e qualitativos que permitam avaliar a viabilidade e eficiência de um sistema MAS executando em hardware embarcado (Raspberry Pi 5).

> **Pré-requisito:** Roadmaps V1–V4 concluídos.
> **Dependência:** Nenhum outro roadmap V5+ é pré-requisito.

---

## Motivação Acadêmica

Para validar a hipótese de que um sistema multi-agente pode operar de forma autônoma em
hardware de baixo custo, é necessário coletar métricas que demonstrem:

1. **Viabilidade operacional**: O sistema é capaz de completar tarefas dentro dos limites
   de hardware (RAM, CPU, temperatura)?
2. **Eficiência do pipeline**: Qual o overhead de orquestração vs tempo útil de inferência?
3. **Qualidade da colaboração**: Os agentes estão coordenando efetivamente via o DAG?
4. **Custo computacional**: Quanto recurso (tokens, tempo, energia) cada tarefa consome?
5. **Confiabilidade**: Qual a taxa de sucesso/falha e quais são os gargalos?

---

## Modelo de Dados: Tabelas SQLite

### V5.1 — Tabela `agent_events` (Rastreamento de Interações entre Agentes)

Registra cada mensagem e ação entre agentes, permitindo reconstruir a timeline
completa de uma execução.

```sql
CREATE TABLE IF NOT EXISTS agent_events (
    id              TEXT PRIMARY KEY,
    execution_id    TEXT NOT NULL,       -- FK → execution_history.id
    session_id      TEXT NOT NULL,       -- Sessão do agente
    agent_id        TEXT NOT NULL,       -- Qual agente gerou o evento
    event_type      TEXT NOT NULL,       -- spawn | ipc_send | ipc_receive | tool_call |
                                         -- tool_result | plan_generated | plan_validated |
                                         -- error | retry | cancel | complete
    target_agent_id TEXT,                -- Agente destinatário (se aplicável)
    task_name       TEXT,                -- Subtarefa do DAG
    payload_json    TEXT,                -- Dados do evento (prompt, resultado, etc.)
    timestamp       TEXT NOT NULL,       -- ISO 8601 com timezone
    duration_ms     INTEGER,             -- Duração da operação em ms (se aplicável)
    
    -- Índices para queries de análise
    FOREIGN KEY (execution_id) REFERENCES execution_history(id)
);

CREATE INDEX IF NOT EXISTS idx_events_execution ON agent_events(execution_id);
CREATE INDEX IF NOT EXISTS idx_events_agent ON agent_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON agent_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON agent_events(timestamp);
```

### V5.2 — Tabela `tool_usage` (Rastreamento de Ferramentas)

Registra cada invocação de skill/ferramenta com métricas granulares.

```sql
CREATE TABLE IF NOT EXISTS tool_usage (
    id              TEXT PRIMARY KEY,
    execution_id    TEXT NOT NULL,       -- FK → execution_history.id
    session_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,       -- Qual agente invocou
    tool_name       TEXT NOT NULL,       -- Nome da skill (quick_search, python_interpreter, etc.)
    arguments_json  TEXT,                -- Argumentos passados (sanitizados)
    result_summary  TEXT,                -- Resumo do resultado (truncado em 500 chars)
    success         BOOLEAN NOT NULL,
    error_message   TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    duration_ms     INTEGER NOT NULL,
    task_name       TEXT,                -- Subtarefa do DAG

    FOREIGN KEY (execution_id) REFERENCES execution_history(id)
);

CREATE INDEX IF NOT EXISTS idx_tool_agent ON tool_usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_usage(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_execution ON tool_usage(execution_id);
```

### V5.3 — Tabela `token_usage` (Contabilidade de Tokens)

Registra o consumo de tokens por chamada LLM, essencial para análise de custo
e eficiência.

```sql
CREATE TABLE IF NOT EXISTS token_usage (
    id                  TEXT PRIMARY KEY,
    execution_id        TEXT NOT NULL,
    session_id          TEXT NOT NULL,
    agent_id            TEXT NOT NULL,
    task_name           TEXT,
    llm_provider        TEXT NOT NULL,       -- google | ollama
    llm_model           TEXT NOT NULL,       -- gemini-2.0-flash | qwen3.5:4b
    prompt_tokens       INTEGER NOT NULL,
    completion_tokens   INTEGER NOT NULL,
    total_tokens        INTEGER NOT NULL,
    estimated_cost_usd  REAL,                -- Estimativa de custo (apenas para cloud)
    latency_ms          INTEGER NOT NULL,    -- Tempo de resposta da API/Ollama
    timestamp           TEXT NOT NULL,
    context_window_used INTEGER,             -- Tokens usados do contexto total
    context_window_max  INTEGER,             -- Contexto máximo configurado
    was_compressed      BOOLEAN DEFAULT 0,   -- Se o histórico foi comprimido

    FOREIGN KEY (execution_id) REFERENCES execution_history(id)
);

CREATE INDEX IF NOT EXISTS idx_tokens_execution ON token_usage(execution_id);
CREATE INDEX IF NOT EXISTS idx_tokens_agent ON token_usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_tokens_provider ON token_usage(llm_provider);
```

### V5.4 — Tabela `hardware_snapshots` (Monitoramento do Hardware)

Captura periódica do estado do hardware durante execuções.

```sql
CREATE TABLE IF NOT EXISTS hardware_snapshots (
    id              TEXT PRIMARY KEY,
    execution_id    TEXT,                -- FK (NULL se for coleta periódica)
    task_name       TEXT,
    cpu_temp_c      REAL,
    cpu_usage_pct   REAL,
    mem_total_mb    REAL,
    mem_available_mb REAL,
    mem_usage_pct   REAL,
    is_throttled    BOOLEAN,
    disk_free_gb    REAL,
    active_containers INTEGER,
    timestamp       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hw_execution ON hardware_snapshots(execution_id);
CREATE INDEX IF NOT EXISTS idx_hw_timestamp ON hardware_snapshots(timestamp);
```

---

## Implementação

### V5.5 — Módulo `src/telemetry.py` (Coletor Central de Métricas)

```python
# Estrutura proposta
class TelemetryCollector:
    """Coletor central de eventos e métricas do sistema multi-agente.
    
    Responsável por registrar agent_events, tool_usage, token_usage
    e hardware_snapshots em SQLite de forma assíncrona e não-bloqueante.
    
    Pattern: Singleton com buffer interno e flush periódico para
    minimizar I/O de disco no Pi 5.
    """
    
    # Buffer em memória para batch inserts (reduz escritas em disco)
    _buffer_size: int = 50  # Flush a cada 50 eventos

    def record_agent_event(self, ...) -> None: ...
    def record_tool_usage(self, ...) -> None: ...
    def record_token_usage(self, ...) -> None: ...
    def record_hardware_snapshot(self, ...) -> None: ...
    def flush(self) -> None: ...  # Força escrita do buffer
    
    # Queries para análise
    def get_execution_timeline(self, execution_id: str) -> list[dict]: ...
    def get_token_summary(self, execution_id: str) -> dict: ...
    def get_tool_summary(self, execution_id: str) -> dict: ...
```

### V5.6 — Instrumentação do Orchestrator

Pontos de instrumentação no `src/orchestrator.py`:

| Ponto | Evento | Dados Capturados |
|---|---|---|
| `handle_request()` início | `execution_start` | prompt, timestamp, hardware_snapshot |
| `_execute_agent()` spawn | `agent_spawn` | agent_id, image, task_name |
| `ipc.send()` | `ipc_send` | mensagem, tamanho, agent_id destino |
| `ipc.receive()` | `ipc_receive` | resposta, latência, agent_id origem |
| `_execute_agent()` sucesso | `agent_complete` | duração, status, artefatos |
| `_execute_agent()` falha | `agent_error` | erro, tentativa, stack trace |
| `handle_request()` final | `execution_end` | duração total, hardware_snapshot |

### V5.7 — Instrumentação do Agent Loop

Pontos de instrumentação no `src/llm/agent_loop.py`:

| Ponto | Evento | Dados Capturados |
|---|---|---|
| `provider.generate()` chamada | `llm_request` | prompt_tokens, modelo, provider |
| `provider.generate()` resposta | `llm_response` | completion_tokens, latência, finish_reason |
| Tool call detectado | `tool_call_start` | tool_name, arguments |
| Tool call executado | `tool_call_end` | resultado (truncado), duração, sucesso |

### V5.8 — Instrumentação do Autonomous Loop

Pontos de instrumentação no `src/autonomous_loop.py`:

| Ponto | Evento | Dados Capturados |
|---|---|---|
| Triage classificação | `triage_decision` | decisão, confiança, modo usado |
| Plano gerado | `plan_generated` | nº subtarefas, DAG edges, tentativa |
| Plano validado | `plan_validated` | status, feedback, iteração |
| Subtarefa iniciada | `subtask_start` | task_name, depends_on, agent_id |
| Subtarefa concluída | `subtask_end` | task_name, status, duração, retry_count |
| Re-planejamento | `replan_triggered` | falhas acumuladas, feedback |
| Promoção memória | `memory_promotion` | itens promovidos, fonte |

---

## Métricas Derivadas

Além das métricas brutas coletadas, estas são as métricas derivadas sugeridas para análise:

### Métricas de Eficiência

| Métrica | Cálculo | Relevância Acadêmica |
|---|---|---|
| **Overhead de Orquestração** | `(tempo_total - Σ tempo_agentes) / tempo_total` | Mede o custo de coordenação do MAS |
| **Taxa de Utilização de Contexto** | `tokens_usados / contexto_máximo` | Avalia eficiência do uso de memória do LLM |
| **Ratio Token/Resultado** | `total_tokens / nº_artefatos_gerados` | Custo computacional por output útil |
| **Throughput por Watt** | `tarefas_concluídas / (tempo × potência_estimada)` | Eficiência energética no Pi 5 |
| **Latência de Inferência Média** | `média(latency_ms por chamada LLM)` | Performance do LLM local vs cloud |

### Métricas de Confiabilidade

| Métrica | Cálculo | Relevância Acadêmica |
|---|---|---|
| **Taxa de Sucesso Global** | `execuções_sucesso / total_execuções` | Confiabilidade end-to-end |
| **Taxa de Sucesso por Agente** | `sucessos_agente_X / total_agente_X` | Identifica agentes problemáticos |
| **Retry Rate** | `total_retries / total_subtarefas` | Robustez da cadeia de validação |
| **MTTR (Mean Time To Recovery)** | `média(tempo entre falha e retry bem-sucedido)` | Resiliência do re-planejamento |
| **Falha Cascateada Rate** | `subtarefas_canceladas / subtarefas_falhadas` | Impacto de falhas no DAG |

### Métricas de Colaboração Multi-Agente

| Métrica | Cálculo | Relevância Acadêmica |
|---|---|---|
| **Profundidade do DAG** | `caminho_mais_longo no grafo de dependências` | Complexidade da decomposição |
| **Paralelismo Efetivo** | `max_agentes_simultâneos_observado / max_permitido` | Uso real da concorrência |
| **Planning Iterations** | `iterações_planner_validator até aprovação` | Eficiência do ciclo de validação |
| **Context Propagation Accuracy** | `subtarefas_com_contexto_correto / total_com_depends_on` | Qualidade da passagem de contexto |
| **Cross-Agent Information Loss** | `informação_original - informação_no_contexto_propagado` | Degradação de informação entre agentes |

### Métricas de Hardware (Pi 5)

| Métrica | Cálculo | Relevância Acadêmica |
|---|---|---|
| **Temperatura Máxima por Execução** | `max(cpu_temp_c) durante execução` | Sustentabilidade térmica |
| **Correlação Temp × Latência** | `correlação(temp, latency_ms)` | Identifica throttling impactando performance |
| **Memory Pressure Score** | `1 - (mem_available / mem_total)` durante pico | Pressão de memória sob carga |
| **Throttling Incidents** | `contagem de snapshots com is_throttled=true` | Frequência de degradação térmica |

---

## Tarefas

### Fase 1 — Schema e Coletor (pré-requisito para tudo)

- [x] Criar `src/telemetry.py` com `TelemetryCollector` singleton e buffer
- [x] Criar tabelas `agent_events`, `tool_usage`, `token_usage`, `hardware_snapshots` (em `scripts/init_db.sql` — adaptadas para PostgreSQL)
- [x] Testes unitários para o `TelemetryCollector` (insert, flush, queries) — 24 testes em `tests/unit/test_telemetry.py`
- [x] Commit: `feat(telemetry): cria coletor central de métricas com schema PostgreSQL`

### Fase 2 — Instrumentação dos módulos core

- [x] Instrumentar `src/orchestrator.py` (V5.6) — spawn, ipc_send, ipc_receive, complete, error
- [x] Instrumentar `src/llm/agent_loop.py` (V5.7) — token_usage por chamada LLM, tool_usage por skill
- [x] Instrumentar `src/autonomous_loop.py` (V5.8) — triage_decision, plan_generated, subtask_start/end, replan_triggered, memory_promotion
- [ ] Instrumentar `src/skills/__init__.py` (tool usage tracking no `run_with_logging`) — coberto via agent_loop
- [ ] Instrumentar `src/llm/providers/ollama.py` e `google.py` (token usage) — coberto via agent_loop
- [x] Testes de integração: 350 testes unitários passando (incluindo orchestrator, autonomous_loop, agent_loop)
- [x] Commit: `feat(telemetry): instrumenta orchestrator, agent_loop e autonomous_loop`

### Fase 3 — Hardware snapshots e queries de análise

- [x] Integrar `PiHealthMonitor` ao `TelemetryCollector` (snapshots automáticos após cada subtarefa)
- [x] Implementar coleta de snapshot antes/depois de cada subtarefa
- [x] Implementar queries de métricas derivadas (5 métricas: latência, contexto, memória, throttling, replans)
- [x] Criar `scripts/export_metrics.py` para exportar métricas em CSV para análise
- [x] Testes unitários para as queries derivadas (incluídos em `test_telemetry.py`)
- [x] Commit: `feat(telemetry): adiciona hardware snapshots e queries de métricas derivadas`

### Fase 4 — CLI de consulta de métricas

- [x] Adicionar comando `geminiclaw --metrics <execution_id>` ao CLI
- [x] Exibir: timeline de agentes, token summary, tool usage, hardware peaks, métricas derivadas
- [x] Adicionar comando `geminiclaw --export <execution_id>` (CSV)
- [x] Commit: `feat(cli): adiciona comando de consulta de métricas de execução`

---

## Critérios de Aceite

1. Uma execução completa (prompt → resultado) gera pelo menos:
   - 1 registro em `agent_events` por agente spawnado ✅
   - 1 registro em `tool_usage` por invocação de skill ✅
   - 1 registro em `token_usage` por chamada LLM ✅
   - 2 registros em `hardware_snapshots` (início e fim) ✅

2. `geminiclaw --metrics <id>` exibe timeline legível com duração, tokens e temperatura ✅

3. `scripts/export_metrics.py` gera CSVs importáveis em pandas/Excel para análise ✅
