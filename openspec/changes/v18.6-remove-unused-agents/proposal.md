# Proposta: Remoção de Agentes e Papéis sem Uso

**ID:** `v18.6-remove-unused-agents` · **Versão:** V18.6 ·
**Capacidades:** `agent-runtime`, `llm-providers`, `communication-eval`
**ADRs de origem:** [ADR 007](../../../docs/decisions/adr_007_reestruturacao_papeis_agentes.md) (o Validator absorveu o Reviewer) e
[ADR 020](../../../docs/decisions/adr_020_independencia_validator.md) (papéis de juiz e julgado).
**Origem dos requisitos:** pedido do pesquisador (2026-10-13): sem débito técnico de agentes que não
são usados.
**Depende de:** nada. **Simplifica:** [`v18.6-validator-independence`](../archive/v18.6-validator-independence/proposal.md) (já mergeada, #145)
(juízes = `validator`; julgados = `developer`).

## Por quê

O ADR 007 registrou que o Validator absorveu o Reviewer, mas o agente e o papel `reviewer`
continuam no código. O mesmo vale para `base` e `summarizer` como agentes de subtarefa: o
planejador só oferece `developer` e `researcher` (`agents/researcher/agent.py:103`), e o despacho
redireciona `base` para `developer` (`src/autonomous_loop.py:722`).

Uso real na telemetria do Pi 5 (Postgres, 2026-09-30 a 2026-10-13):

| Papel | Subtarefas executadas (`subtask_metrics`) | Outros usos registrados |
|---|---|---|
| `developer` | 526 | — |
| `researcher` | 42 | planejamento, consulta |
| `reviewer` | **0** | 121 eventos `subtask_review`, mas são do `validator` (`review_result`) com rótulo errado (`src/autonomous_loop.py:2300`, `src/agents/validator_agent.py:876`) |
| `base` | **0** | 7 execuções internas de promoção de memória (`_promote_findings`, `src/autonomous_loop.py:2111`) e 3 `sandbox_run` em 2026-10-12 sem origem identificada |
| `summarizer` | **0** | 12 execuções da síntese final (`final_synthesis`, `src/autonomous_loop.py:2401`) e revisão de afirmações (`src/claims/revision.py`) |
| `curator` | — (fora do plano por desenho) | 90 execuções do Curator |

## O que muda

### Removido

- **Agente `reviewer`:** `agents/reviewer/`, a entrada em `src/agent_runtime/definitions.py`, o
  papel em `AGENT_IDS` (`src/orchestrator.py:79`), em `REQUIRED_ROLES` (`src/llm/catalog.py:36`) e em
  `src/llm/catalog.yaml`, os sinônimos `reviewer`/`revisor` de `src/plan_normalizer.py`,
  `REVIEWER_MODEL` do `.env.example` e `reviewer` de `POOL_ROLES`
  (`scripts/benchmark/comm_judge.py:30`).
- **`base` e `summarizer` como agentes de subtarefa:** saem de `AGENT_IDS`. Os papéis de subtarefa
  passam a ser só `developer` e `researcher`, os mesmos que o planejador oferece. O ramo
  "`base` legado → `developer`" de `_dispatch_subtask` sai; o normalizador do plano passa a fazer
  esse reparo (`base` → `developer`, registrado como `normalize_agent_id`).
- **Código morto relacionado:**
  - o atalho `agent_tasks` de `Orchestrator.handle_request` (`src/orchestrator.py:1185-1265`), que
    não tem nenhum chamador;
  - o valor `end_only` de `REVIEW_MODE` (`src/config.py:452`), que nenhum código implementa.

### Mantido

- **`summarizer`:** continua como papel interno, fora do plano, para a síntese final e a revisão
  de afirmações (como o `curator`).
- **`base`:** continua como papel interno, fora do plano, para a promoção de memória e a extração
  de padrões de código. O módulo `agents/base/` continua como biblioteca comum (`Agent`, ferramentas
  de artefato e skills), que todos os agentes importam.

### Modificado

- **Rótulo da revisão de subtarefa:** a telemetria registra papel `validator` e
  `funcao = "revisao_subtarefa"`, não `reviewer`. A chave `reviewer` das métricas de comunicação
  (`scripts/benchmark/communication.py:419-422`, `report.py:142-159`) passa a se chamar
  `revisao_subtarefa`. A chamada LLM já usa o papel `validator` desde o #145 (`v18.6-validator-independence`); aqui só o evento `subtask_review` deixa de usar `agent_id = "reviewer"`.
- **Variável obsoleta:** `REVIEWER_MODEL` definida no ambiente gera `WARNING` na inicialização
  ("variável obsoleta, o papel `reviewer` foi removido"), em vez de ser ignorada em silêncio.

### Fora do escopo

- Renomear `base` (ex.: para `memory`): muda telemetria e catálogo sem ganho funcional.
- Mudar o que a síntese final ou a promoção de memória fazem.

## Impacto

- **Código:** `agents/reviewer/` (removido), `src/agent_runtime/definitions.py`,
  `src/orchestrator.py`, `src/autonomous_loop.py`, `src/plan_normalizer.py`, `src/llm/catalog.py`,
  `src/llm/catalog.yaml`, `src/config.py`, `src/agents/validator_agent.py`,
  `scripts/benchmark/{comm_judge,communication,report}.py`, `.env.example`, docstrings que listam
  papéis (`src/model_router.py:61`, `src/agent_runtime/context.py:41`).
- **Testes:** os que citam `reviewer` (17 arquivos, entre eles `tests/unit/test_prompt_policy.py`,
  `tests/unit/test_agent_runtime_definitions.py`, `tests/unit/llm/test_routing.py`,
  `tests/support/catalog_fixtures.py`) e os que usam `agent_tasks`.
- **Contratos:** `catalog.local.yaml` com seção `reviewer` passa a ser chave desconhecida, e a
  validação estrita do catálogo para a inicialização com mensagem que cita o papel removido
  (ADR 017 §9). A chave `reviewer` do relatório de comunicação muda de nome.
- **Schema de banco:** nenhum. Eventos antigos com `agent_id = "reviewer"` continuam no banco, e a
  leitura de métricas de comunicação aceita os dois rótulos.
- **ADR 020:** juízes = `validator`; julgados = `developer`. Saem os pontos de conferência de
  despacho de `reviewer`/`base` (§4) e a ressalva "conflitos de `reviewer`/`base` no despacho".

## Aprovações

**Aprovada pelo pesquisador em 2026-10-13** ("pode seguir com todas as correções e limpezas"), com as propostas do design §5: `base` mantido como papel interno e os 3 `sandbox_run` do `base` tratados como diagnóstico manual. A exclusão de `agents/reviewer/` está autorizada.

Aprovações que eram necessárias:

- **Exclusão de arquivos** (`agents/reviewer/`): aprovação do pesquisador (AGENTS.md §1.5).
- As decisões em aberto do `design.md` §5.
