# Roadmap V9 — Observabilidade Avançada e Métricas de Performance

**Contexto:** Este roadmap expande a infraestrutura de telemetria (V5) para fornecer uma visão analítica profunda sobre a execução de tarefas e o comportamento do sistema multi-agente. O foco é na agregação de dados por subtarefa, atribuição de recursos e avaliação de eficiência sistêmica.

---

## Objetivos Principais

1. **Agregação por Subtarefa**: Facilitar a análise de custo e tempo por unidade de trabalho (subtask) sem a necessidade de joins complexos.
2. **Atribuição de Recursos Granular**: Medir o impacto de ferramentas e agentes específicos no consumo de CPU, RAM e temperatura do Raspberry Pi 5.
3. **Análise de Caminho Crítico**: Identificar gargalos na orquestração e execução do DAG.
4. **Métricas de Colaboração**: Avaliar a eficácia da interação entre agentes e o custo de coordenação.
5. **Persistência e Comparação**: Garantir que todas as métricas sejam consultáveis via SQL para possibilitar benchmarks históricos.

---

## Novo Modelo de Dados (PostgreSQL)

### V9.1 — Tabela `subtask_metrics` (Agregação de Performance)
Esta tabela consolida dados de múltiplas fontes (`agent_events`, `tool_usage`, `token_usage`) para cada subtarefa.

```sql
CREATE TABLE IF NOT EXISTS subtask_metrics (
    id                  TEXT PRIMARY KEY,
    execution_id        TEXT NOT NULL,
    task_name           TEXT NOT NULL,
    agent_id            TEXT NOT NULL,
    status              TEXT NOT NULL,       -- success | failure | cancelled
    
    -- Métricas de Tempo
    created_at          TIMESTAMPTZ NOT NULL, -- Quando o plano foi gerado
    started_at          TIMESTAMPTZ,          -- Quando a execução começou
    finished_at         TIMESTAMPTZ,          -- Quando a execução terminou
    duration_total_ms   INTEGER,              -- Tempo total no sistema
    duration_active_ms  INTEGER,              -- Tempo em processamento (LLM + Tools)
    waiting_time_ms     INTEGER,              -- Tempo em fila/dependência
    
    -- Métricas de Recursos (Deltas)
    cpu_usage_avg       DOUBLE PRECISION,
    mem_usage_peak_mb   DOUBLE PRECISION,
    temp_delta_c        DOUBLE PRECISION,
    
    -- Métricas de LLM e Ferramentas
    total_tokens        INTEGER DEFAULT 0,
    total_cost_usd      DOUBLE PRECISION DEFAULT 0.0,
    llm_calls_count     INTEGER DEFAULT 0,
    tools_used_count    INTEGER DEFAULT 0,
    
    -- Metadados
    retry_count         INTEGER DEFAULT 0,
    error_type          TEXT,
    
    FOREIGN KEY (execution_id) REFERENCES execution_history(id)
);

CREATE INDEX IF NOT EXISTS idx_subtask_metrics_exec ON subtask_metrics(execution_id);
CREATE INDEX IF NOT EXISTS idx_subtask_metrics_task ON subtask_metrics(task_name);
```

---

## Implementação

### V9.2 — Instrumentação de Ciclo de Vida de Tarefas
Aprimorar o `src/autonomous_loop.py` e `src/orchestrator.py` para registrar os estados de transição das subtarefas no `subtask_metrics`.

| Estado | Gatilho | Ação de Telemetria |
|---|---|---|
| **Created** | Geração do Plano | Insert inicial em `subtask_metrics` |
| **Started** | Início de `_execute_agent()` | Update `started_at` e snapshot de hardware inicial |
| **Finished** | Fim de `_execute_agent()` | Update `finished_at`, delta de hardware e agregação de tokens/ferramentas |

### V9.3 — Atribuição de Recursos por Ferramenta
Modificar o `src/telemetry.py` para capturar snapshots "micro" antes e depois de invocações de ferramentas custosas (ex: `python_interpreter`, `vision_analysis`).

### V9.4 — Novas Métricas Sistêmicas
Implementar lógica de cálculo para:
- **Interaction Density**: Ratio de mensagens IPC por subtarefa bem-sucedida.
- **Orchestration Overhead**: Diferença entre o tempo de parede (wall time) e a soma dos tempos de inferência + ferramentas.
- **Energy Efficiency Proxy**: (Total Tokens / Delta Temperatura) para avaliar o custo térmico por unidade de inteligência.
- **Success Stability**: Taxa de sucesso por agente em tarefas similares.

---

## Tarefas de Integração

### Fase 1: Extensão do Schema e Coletor
- [x] Implementar migração SQL para `subtask_metrics`.
- [x] Atualizar `src/telemetry.py` para suportar agregação em tempo real ou pós-execução.
- [x] Adicionar suporte a "Micro Snapshots" de hardware.

### Fase 2: Instrumentação de Fluxo
- [x] Modificar `AutonomousLoop` para emitir eventos de criação de subtarefa.
- [x] Instrumentar `Orchestrator` para preencher os tempos de espera vs ativos.
- [x] Integrar contagem de retries e erros por subtarefa.

### Fase 3: Visualização e Exportação
- [x] Expandir `geminiclaw --metrics` para incluir o resumo por subtarefa.
- [x] Criar dashboard CLI (tabela formatada) comparando eficiência de diferentes agentes.
- [x] Atualizar `export_metrics.py` para incluir a nova tabela.

---

## Critérios de Aceite
1. Todas as execuções devem popular a tabela `subtask_metrics` automaticamente.
2. É possível consultar o custo total em tokens e dólares de uma subtarefa específica via SQL.
3. O sistema registra o pico de memória e temperatura atingido por cada agente durante sua ativação.
4. O CLI exibe claramente o "Caminho Crítico" da execução (subtarefas que mais demoraram).
