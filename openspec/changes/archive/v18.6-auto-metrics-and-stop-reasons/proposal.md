# Proposta: Métricas definidas pelo agente no modo `auto` e motivos de parada explícitos

**ID:** `v18.6-auto-metrics-and-stop-reasons` · **Versão:** V18.6 ·
**Capacidades:** `hypothesis-loop`, `vocabulary`, `pipeline-robustness`, `operation-metrics`, `benchmark`
**ADRs de origem:** [ADR 015](../../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) (`Metrica`,
vocabulário controlado, §4 autoria e §8 aprovação de termos), [ADR 020](../../../../docs/decisions/adr_020_independencia_validator.md)
(o Validator é de família diferente da do Developer), [ADR 010](../../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md)
(exploração contínua), [ADR 012](../../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md).
**Origem dos requisitos:** decisões do pesquisador em 2026-10-13, que substituem as três hipóteses conservadoras
adotadas na implementação de [`v18.6-hypothesis-closure`](../v18.6-hypothesis-closure/design.md) (§8.1).
**Depende de:** `v18.6-hypothesis-closure` (mergeada, #146). **Aprovação da direção:** pesquisador, 2026-10-13
(inclui a alteração **aditiva** de schema).

## Por quê

A `v18.6-hypothesis-closure` deixou três questões abertas e adotou a resposta mais conservadora de cada uma. O
pesquisador decidiu o contrário em todas:

1. **Modo `auto` sem métrica aprovada.** Hoje a sessão não inicia (`erro` antes de planejar). O pesquisador quer que
   o Researcher **defina a métrica (ou o conjunto de métricas)** a alcançar, de acordo com o problema, que a
   definição entre no plano, e que outro agente (o Validator, família diferente da do Developer) confirme que ela
   faz sentido. Só então ela vale para o veredito das hipóteses.
2. **Hipóteses sem tentativa ao esgotar os ciclos ociosos.** Hoje a sessão fecha com `motivo_parada="erro"` e uma
   mensagem. O pesquisador quer um motivo de parada próprio, identificável nos benchmarks e em produção, que não
   se confunda com falha de infraestrutura.
3. **Resultado negativo sem hipótese.** Continua `reprovado`, mas o motivo (a falta de hipótese) passa a constar onde
   os motivos de reprovação aparecem.

## O que muda

### Novo

- **Definição de métricas pelo agente (modo `auto`).** Chave `metricas` no plano do Researcher
  (`nome`, `sentido`, `limiar`, `justificativa`, `delta_min` opcional). O Validator valida a definição na validação
  do plano (adequação ao tipo de problema, limiar plausível, sem métrica de vaidade ou vazamento). Só depois de
  validada a `Metrica` é gravada com origem `agente` e passa a valer para o veredito.
- **Propriedades aditivas de `Metrica`:** `origem_definicao` (`pesquisador` | `agente`), `aprovada_por`
  (`pesquisador` | `validator`) e `justificativa_definicao`.
- **Motivo de parada `hipoteses_nao_testadas`** em `ExplorationStop` e em `Sessao.motivo_parada`, evento
  `hipoteses_sem_tentativa` com o motivo, contador nas métricas de operação, linha explicativa no relatório e na CLI,
  e classificação própria no benchmark (parada de pesquisa, nunca anomalia nem erro).
- **Motivo `sem_hipotese`** em `ReviewResult.motivos`, no evento `subtask_review`, nas métricas de operação e no
  resumo de reprovações do benchmark.

### Modificado

- **Conferência do veredito no início da sessão:** no modo `auto`, a falta de métrica aprovada não impede mais a
  sessão: ela segue, pedindo a definição ao Researcher no primeiro plano. `assisted` e `semi` não mudam (avisam e
  seguem).
- **Ciclos ociosos esgotados com hipótese sem tentativa:** fecha com `hipoteses_nao_testadas` (antes `erro`) e **não**
  acrescenta resultado de erro à sessão.
- **Retomada:** `hipoteses_nao_testadas` não é retomável sem pesquisador (mesma recusa de `erro`, com mensagem própria).

### Removido

- O comportamento "sessão não inicia no modo `auto` sem métrica aprovada" e o teste dele
  (`test_modo_auto_sem_metrica_aprovada_termina_com_erro_sem_chamar_o_researcher`).

### Fora do escopo

- Veredito multimétrica: só a métrica **principal** (a primeira de `metricas`) alimenta `criterio_sucesso` e o
  veredito; as demais são gravadas, aprovadas e ligadas a `Resultado` por `MEDE`, mas não entram no cálculo.
- Comando `geminiclaw vocab` para ratificar ou revogar métricas aprovadas pelo agente (pendência registrada no PR).
- Mudar o status ou o comportamento de uma subtarefa sem hipótese além de registrar o motivo.
- Migração de dados antigos (as propriedades novas são opcionais; a ausência equivale a `pesquisador`).

## Impacto

- **Código:** `src/exploration.py`, `src/autonomous_loop.py`, `src/orchestrator.py`, `src/agents/validator_agent.py`,
  `src/knowledge/hypotheses.py` (parse de `metricas`), novo `src/knowledge/metric_definition.py`, `src/knowledge/schema.py`,
  `src/continuity.py`, `src/operation_metrics.py`, `src/config.py`, `scripts/benchmark/{run_benchmark,report,interactions}.py`.
- **Schema (aditivo):** enumeração `Sessao.motivo_parada` ganha `hipoteses_nao_testadas`; `Metrica` ganha três propriedades
  opcionais. Sem migração; nós antigos continuam válidos.
- **Contratos:** chave `metricas` no envelope do plano; `ValidatorAgent.validate_plan(..., metric_definition=...)`;
  `ValidationResult.metrics_approved`; `ReviewResult.motivos`; eventos `metricas_definidas`, `metricas_nao_aplicadas`,
  `hipoteses_sem_tentativa.motivo_parada`, `subtask_review.motivos`.
- **Custo:** a validação de métricas reaproveita a chamada de validação do plano (uma instrução a mais no prompt do Validator).
  Sem chamada extra de LLM.

## Aprovações necessárias

- **Alteração de schema do grafo (aditiva):** autorizada pelo pesquisador em 2026-10-13.
- Nenhuma alteração de Dockerfile, `docker-compose.yml`, exclusão de arquivos de produção ou `AGENTS.md`.
