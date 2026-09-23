# ADR 002 — Arquitetura Multi-Agent System com DAG de Execução

**Status:** Aceito
**Data:** 2026-09-22
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap.md` (Etapas 8–9), `roadmaps/roadmap_V6_research_autonomy.md`

---

## Contexto

Pesquisa científica assistida por IA envolve tarefas com dependências complexas e heterogêneas: buscar referências, analisar dados, escrever código, validar resultados, gerar relatórios. Um agente único tentando fazer tudo em sequência linear teria: contexto excessivamente longo, impossibilidade de paralelismo, e falha total quando qualquer etapa falha.

Era necessário decidir como decompor o problema em unidades menores que possam ser coordenadas de forma confiável.

---

## Decisão

Adotar uma arquitetura **Multi-Agent System (MAS)** com:

1. **Triage inicial:** O `AutonomousLoop` classifica a tarefa como `SIMPLE` (agente base direto) ou `COMPLEX` (pipeline MAS completo).

2. **Ciclo Planner → Validator:** Para tarefas complexas, o Planner decompõe a tarefa em subtarefas estruturadas (JSON com campos: `name`, `agent`, `depends_on`, `artifacts_expected`). O Validator revisa o plano — até 3 iterações — antes da execução.

3. **DAG de execução:** As subtarefas são executadas como um Grafo Direcionado Acíclico (DAG):
   - Todas as subtarefas independentes são agendadas concorrentemente como corrotinas async
   - Cada subtarefa aguarda apenas a conclusão de suas próprias dependências (`depends_on`)
   - Falha de uma subtarefa cancela apenas as que dela dependem; as demais continuam

4. **Re-planejamento automático:** Se o DAG terminar com falhas, o `AutonomousLoop` consolida os erros e solicita um plano de recuperação ao Planner (até `MAX_PLAN_RETRIES` ciclos), mantendo os artefatos já produzidos.

5. **Circuit breakers:** Detecção de progresso zero entre ciclos de replanejamento e limite de containers por sessão (`MAX_CONTAINERS_PER_SESSION`).

---

## Alternativas Consideradas

### Alternativa A: Agente monolítico único

Um único agente LLM recebe a tarefa completa e usa tool calls para executar tudo (pesquisa, código, relatório) sequencialmente.

**Descartado porque:**
- Janela de contexto insuficiente para tarefas longas
- Sem paralelismo: etapas independentes ficam em fila
- Falha em qualquer step desfaz todo o progresso
- Impossível atribuir modelos diferentes por tipo de tarefa

### Alternativa B: Pipeline fixo sequencial

Sequência hard-coded: Researcher → Developer → Validator → Summarizer, sempre nessa ordem.

**Descartado porque:**
- Não se adapta a tarefas que não precisam de todas as etapas
- Sem capacidade de paralelismo entre etapas independentes
- Difícil de estender com novos tipos de agente sem quebrar o pipeline

### Alternativa C: MAS com orquestração centralizada via LLM

Um LLM orquestrador decide dinamicamente quais agentes chamar e em qual ordem, via tool calls.

**Descartado porque:**
- LLM orquestrador é não-determinístico e dificulta debugging e replay
- Telemetria de execução seria difusa e opaca
- O V10 diagnosticou que planejamento por LLM sem estrutura de DAG levou a 184 subdiretórios em uma execução — evidência de loop destrutivo

---

## Consequências

### Positivas

- **Paralelismo:** Subtarefas independentes executam concorrentemente, reduzindo latência total no Pi 5.
- **Resiliência parcial:** Falha isolada não desfaz trabalho completo; o re-planejamento é cirúrgico.
- **Extensibilidade:** Novos tipos de agente são registrados no `AGENT_REGISTRY` sem alterar o loop.
- **Observabilidade:** Cada subtarefa tem telemetria própria (events, tool_usage, token_usage).

### Negativas / Trade-offs

- **Overhead de containers:** Cada agente é um container Docker; há overhead de startup para tarefas muito simples.
- **Complexidade do loop:** O `autonomous_loop.py` acumula lógica de triage, planejamento, DAG e retry — débito técnico que o V14 endereça.
- **Latência de aprovação do plano:** O ciclo Planner → Validator adiciona latência antes da execução.

---

## Parâmetros de Configuração

| Variável | Default | Descrição |
|---|---|---|
| `MAX_RETRY_PER_SUBTASK` | 10 | Tentativas por subtarefa antes de marcar como falha |
| `MAX_SUBTASKS_PER_TASK` | 15 | Limite de subtarefas por plano |
| `MAX_PLAN_RETRIES` | 5 | Ciclos máximos de re-planejamento |
| `MAX_CONTAINERS_PER_SESSION` | 30 | Circuit breaker de containers |
| `TRIAGE_CONFIDENCE_THRESHOLD` | 0.7 | Threshold para classificar como complexo |

---

## Revisão

Este ADR deve ser revisado quando:
- V14 for implementado (Validator passa a ser corrotina, não container)
- A estratégia de triage mudar (ex: threshold ou critérios de complexidade)
