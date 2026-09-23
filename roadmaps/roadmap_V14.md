# Roadmap V14 — Reestruturação de Agentes, Model Router e Ciclo de Vida de Containers

## Objetivo

Resolver os problemas arquiteturais estruturais que comprometem a qualidade e a eficiência do sistema após a conclusão de V13. Os papéis dos agentes estão mal distribuídos, todos usam o mesmo modelo independentemente da tarefa, e o overhead de containers é desnecessariamente alto. Este roadmap consolida o sistema em **três papéis claros** alinhados ao propósito de harness de pesquisa científica (ADR 001, ADR 007).

## Dependências

- V10 (sandbox DinD, sessões legíveis) — **concluído**
- V11 (telemetria estável) — **concluído**
- V12 (cache, resiliência, circuit breaker) — **concluído**
- V13 (manifest, volume compartilhado, session_id canônico) — **concluído**
- [ADR 007](../docs/decisions/adr_007_reestruturacao_papeis_agentes.md) — decisão arquitetural que fundamenta este roadmap

## Contexto e Diagnóstico

O relatório de falhas `pipeline_failure_analysis.md` e `execution_analysis_report.md` identificaram:

| # | Problema | Impacto |
|---|---|---|
| D1 | Todos os agentes usam `DEFAULT_MODEL` | Planner precisou de 7 tentativas; base_agent gerou conteúdo genérico |
| D2 | Planner/Validator são chamadas LLM avulsas, não agentes | ~15 containers criados só na fase de planejamento |
| D3 | `base_agent` acumula routing + execução de código | Falha em tarefas complexas; impossível otimizar por responsabilidade |
| D4 | researcher_agent não integrado ao pipeline de planejamento | Planner gera planos sem contexto de domínio |
| D5 | Container destruído a cada subtarefa | Perda de contexto entre subtarefas; overhead de startup recorrente |

---

## Tarefas

### Tarefa 1: Model Router (V14.1) — PRÉ-REQUISITO CRÍTICO

**Objetivo:** Introduzir seleção de modelo por papel, substituindo a variável global `DEFAULT_MODEL`.

- **Módulos afetados:** `src/model_config.py` (novo), `src/model_router.py` (novo), `src/config.py`, `src/orchestrator.py`, `agents/base/agent.py`, `agents/researcher/agent.py`
- **ADR relacionado:** [ADR 006](../docs/decisions/adr_006_abstracao_provedores_llm.md), [ADR 007](../docs/decisions/adr_007_reestruturacao_papeis_agentes.md)
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `src/model_config.py` criado com mapeamento `researcher → gemini-2.0-flash`, `validator → qwen3:8b`, `developer → gemini-2.0-flash`
  - [ ] `src/model_router.py` implementado com `ModelRouter.get_provider(role: str) -> BaseLLMProvider`
  - [ ] `ModelRouter.get_provider("papel_inexistente")` levanta `ValueError` com mensagem clara
  - [ ] Variáveis de ambiente `RESEARCHER_PROVIDER`, `RESEARCHER_MODEL`, `VALIDATOR_PROVIDER`, `VALIDATOR_MODEL`, `DEVELOPER_PROVIDER`, `DEVELOPER_MODEL` adicionadas ao `.env.example`
  - [ ] `agents/base/agent.py` e `agents/researcher/agent.py` recebem provider via injeção em vez de ler `DEFAULT_MODEL`
  - [ ] Fallback para `DEFAULT_MODEL` quando nenhum papel especificado (compatibilidade retroativa)
  - [ ] Testes unitários em `tests/unit/test_model_router.py` (4 cenários)

---

### Tarefa 2: Validator como Corrotina Async (V14.2)

**Objetivo:** Extrair Validator e Reviewer do interior de containers Docker para corrotinas assíncronas no processo principal, eliminando overhead desnecessário.

- **Módulos afetados:** `src/agents/validator_agent.py` (novo), `src/autonomous_loop.py`
- **ADR relacionado:** [ADR 007](../docs/decisions/adr_007_reestruturacao_papeis_agentes.md)
- **Complexidade estimada:** Alta
- **Depende de:** Tarefa 1 (Model Router)
- **Critérios de aceite:**
  - [ ] `src/agents/validator_agent.py` criado com métodos `validate_plan(plan: dict) -> ValidationResult` e `review_result(task, response_text, artifacts_on_disk) -> ReviewResult`
  - [ ] `ValidatorAgent` usa `model_router.get_provider("validator")` (Ollama local)
  - [ ] System prompt do ValidatorAgent contém schema JSON explícito das chaves obrigatórias de cada subtarefa
  - [ ] Plano sem `validation_criteria` em qualquer subtarefa → SEMPRE rejeitado (10/10 execuções)
  - [ ] `autonomous_loop.py` substituiu chamadas LLM avulsas de validação por `await validator.validate_plan(plan)` e `await validator.review_result(...)`
  - [ ] Zero containers Docker criados durante fase de validação de plano
  - [ ] `review_result` verifica artefatos em disco (via manifest), não apenas `response_text`
  - [ ] Testes unitários em `tests/unit/agents/test_validator_agent.py` (4 cenários)

---

### Tarefa 3: Researcher Agent absorve Planner (V14.3)

**Objetivo:** Consolidar researcher_agent com lógica de planejamento. O Researcher passa a ser o único responsável por decompor tarefas EM subtarefas E por buscar contexto técnico para informar essa decomposição.

- **Módulos afetados:** `agents/researcher/agent.py`, `src/autonomous_loop.py`, `src/runner.py`
- **ADR relacionado:** [ADR 001](../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md), [ADR 007](../docs/decisions/adr_007_reestruturacao_papeis_agentes.md)
- **Complexidade estimada:** Alta
- **Depende de:** Tarefa 1 (Model Router)
- **Critérios de aceite:**
  - [ ] `agents/researcher/agent.py` expõe métodos `plan(task, context) -> ExecutionPlan` e `replan(original_plan, failed_tasks, artifacts_available) -> ExecutionPlan`
  - [ ] Para tarefa de domínio técnico (ex: "comparar Random Forest e SVM no Iris"), log contém ao menos 1 chamada `web_search` antes do plano
  - [ ] Web search no Researcher é para contexto técnico, NUNCA para busca bibliográfica (ver ADR 001)
  - [ ] Plano gerado contém `validation_criteria` em todas as subtarefas
  - [ ] `replan` não redefine subtarefas já concluídas com sucesso
  - [ ] `autonomous_loop.py` chama `researcher.plan(task, context)` via IPC em vez de chamada LLM avulsa do Planner
  - [ ] URL retornada por `web_search` é lida corretamente por `web_reader`
  - [ ] Testes de integração em `tests/integration/agents/test_researcher_agent.py` (4 cenários)

---

### Tarefa 4: Developer Agent substitui base_agent (V14.4)

**Objetivo:** Criar Developer Agent com responsabilidade exclusiva de geração e correção incremental de código. Extrair lógica de routing do base_agent para o Orchestrator.

- **Módulos afetados:** `agents/developer/agent.py` (novo), `containers/developer/Dockerfile` (novo), `agents/base/agent.py`, `src/autonomous_loop.py`
- **ADR relacionado:** [ADR 007](../docs/decisions/adr_007_reestruturacao_papeis_agentes.md), [ADR 008](../docs/decisions/adr_008_workspace_manifest_session_scoped.md)
- **Complexidade estimada:** Alta
- **Depende de:** Tarefa 1 (Model Router), Tarefa 3 (Researcher)
- **Critérios de aceite:**
  - [ ] `agents/developer/agent.py` criado com system prompt focado exclusivamente em geração de código
  - [ ] Developer Agent lê manifest antes de cada geração de código (contexto do V13)
  - [ ] Com manifest registrando 1 step bem-sucedido, código do step 2 referencia artefatos do step 1 (não os recria)
  - [ ] Developer Agent recebe subtarefa de pesquisa via IPC → retorna erro claro ("use researcher_agent para pesquisa")
  - [ ] `containers/developer/Dockerfile` criado com numpy, pandas, scikit-learn, matplotlib, seaborn, scipy pré-instalados
  - [ ] `autonomous_loop.py` tem método `_dispatch_subtask(task)` com routing baseado em `task.agent_id`
  - [ ] `agents/base/agent.py` marcado como `# DEPRECATED: use developer_agent. Será removido na V15.`
  - [ ] Testes de integração em `tests/integration/agents/test_developer_agent.py` (4 cenários)

---

### Tarefa 5: Ciclo de Vida de Container por Sessão (V14.5)

**Objetivo:** Containers de Researcher e Developer persistem durante toda a sessão do usuário, recebendo múltiplas subtarefas via IPC. Eliminação de overhead de startup recorrente.

- **Módulos afetados:** `src/runner.py`, `src/autonomous_loop.py`
- **Complexidade estimada:** Alta
- **Depende de:** Tarefa 2, Tarefa 3, Tarefa 4
- **Critérios de aceite:**
  - [ ] `SessionContainerRunner` implementado em `src/runner.py` com métodos `start`, `send`, `stop`, `is_alive`
  - [ ] Um único container de Developer permanece ativo durante 3 subtarefas consecutivas (container ID não muda entre subtarefas)
  - [ ] Health check periódico a cada 30s detecta container morto
  - [ ] Container morto durante subtarefa → reconstrói com contexto do manifest + reenvio da subtarefa
  - [ ] Máximo 2 recuperações automáticas por subtarefa; se exceder → circuit breaker
  - [ ] Shutdown graceful via IPC: orquestrador envia `{"type": "shutdown"}`, container confirma `shutdown_ack` antes de encerrar
  - [ ] Testes de integração em `tests/integration/test_session_container_lifecycle.py` (4 cenários)

---

### Tarefa 6: Comandos CLI para Gerenciamento de Sessão (V14.6)

**Objetivo:** Dar ao usuário controle explícito sobre o ciclo de vida de containers de sessão via CLI.

- **Módulos afetados:** `src/cli.py`
- **Complexidade estimada:** Baixa
- **Depende de:** Tarefa 5
- **Critérios de aceite:**
  - [ ] `geminiclaw sessions` lista sessões ativas com containers e status
  - [ ] `geminiclaw stop` encerra todos os containers ativos via shutdown graceful em < 15s
  - [ ] `geminiclaw stop --session <id>` encerra containers de sessão específica
  - [ ] `Ctrl+C` durante execução aciona `SIGINT` handler que derruba containers antes de encerrar o processo
  - [ ] Após `stop`, `docker ps` não lista nenhum container do projeto
  - [ ] Testes de integração em `tests/integration/test_cli_session_management.py` (3 cenários)

---

## Ordem de Execução

```
Tarefa 1 — Model Router (pré-requisito absoluto)
│
├──► Tarefa 2 — Validator async (independente das Tarefas 3 e 4)
│
├──► Tarefa 3 — Researcher absorve Planner
│         │
└──► Tarefa 4 — Developer Agent
          │
          └──► Tarefa 5 — Container por sessão
                    │
                    └──► Tarefa 6 — CLI sessions/stop
```

**Tarefas 2, 3 e 4 podem ser implementadas em paralelo após a conclusão da Tarefa 1.**

---

## Validação da Etapa

- [ ] Todos os testes unitários e de integração passam: `uv run pytest -m "unit or integration" -v`
- [ ] Cobertura mínima de 80% nos módulos novos (`model_router`, `validator_agent`, `developer`)
- [ ] Zero containers criados para validação de plano (Validator é corrotina)
- [ ] Pipeline benchmark Iris executado com sucesso: Researcher planeja com web search, Validator aprova em ≤ 2 tentativas, Developer constrói código incrementalmente
- [ ] ADR 007 atualizado de "Proposto" para "Aceito" após implementação
- [ ] PR merged em `dev` via workflow `do-pull-request.md`

---

## Resumo de Arquivos

### Criados

| Arquivo | Tarefa | Descrição |
|---|---|---|
| `src/model_config.py` | T1 | Mapeamento estático papel → provider/modelo |
| `src/model_router.py` | T1 | Factory de providers LLM por papel |
| `src/agents/validator_agent.py` | T2 | ValidatorAgent como corrotina async |
| `agents/developer/agent.py` | T4 | Developer Agent — código exclusivamente |
| `containers/developer/Dockerfile` | T4 | Imagem com deps científicas pré-instaladas |
| `tests/unit/test_model_router.py` | T1 | Testes do Model Router |
| `tests/unit/agents/test_validator_agent.py` | T2 | Testes do ValidatorAgent |
| `tests/integration/agents/test_researcher_agent.py` | T3 | Testes de integração do Researcher |
| `tests/integration/agents/test_developer_agent.py` | T4 | Testes de integração do Developer |
| `tests/integration/test_session_container_lifecycle.py` | T5 | Testes do ciclo de vida por sessão |
| `tests/integration/test_cli_session_management.py` | T6 | Testes dos comandos CLI |

### Modificados

| Arquivo | Tarefas | Natureza da Mudança |
|---|---|---|
| `src/autonomous_loop.py` | T2, T3, T4, T5 | Usar ValidatorAgent, dispatch por agent_id, inicializar containers de sessão |
| `src/runner.py` | T5 | Adicionar `SessionContainerRunner` |
| `agents/researcher/agent.py` | T3, T5 | Absorver Planner, corrigir web skills, `plan()`, `replan()`, shutdown handler |
| `agents/base/agent.py` | T4 | Remover routing, marcar como deprecated |
| `src/config.py` / `.env.example` | T1 | Novas variáveis de modelo por papel |
| `src/orchestrator.py` | T1 | Substituir DEFAULT_MODEL por ModelRouter |
| `src/cli.py` | T6 | Comandos `sessions`, `stop`, handler SIGINT |

### Removidos (na V15, após estabilização do V14)

| Arquivo | Substituto |
|---|---|
| `agents/base/agent.py` | `agents/developer/agent.py` + routing no `autonomous_loop.py` |
| Planner interno ao `autonomous_loop.py` | `agents/researcher/agent.py` método `plan()` |
| Reviewer interno ao `autonomous_loop.py` | `src/agents/validator_agent.py` método `review_result()` |
