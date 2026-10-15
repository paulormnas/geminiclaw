# Proposta: Ligação Rastreável entre Subtarefas e Hipóteses (registro em vez de bloqueio)

**ID:** `v18.7-hypothesis-linking` · **Versão:** V18.7 · **Capacidade:** `hypothesis-loop` (reutilizada de `v18-hypothesis-loop`), com delta `MODIFIED` em `pipeline-robustness`
**ADRs de origem:** [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §1 (princípio), §2 (papel do experimento e ordem de decisão), §3 (ligações derivadas, hipótese do sistema, deduplicação estruturada, ciclo de vida, aprovação por modo, Curator), §4 (variações, hipóteses derivadas, novos testes de hipótese concluída, transições de status), §5.8 (replanejamento substitui a fila), §6 (o que continua impedindo a execução), §7 (retorno ao Researcher) e §8.1–§8.3 (revisão, resultado negativo, campo `hypothesis`); §8.4 só na parte de emitir os dados por ciclo. Contexto: [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) §1 e §5 (o retorno ao Researcher entra no contrato do plano; as regras do papel vêm de fonte única).
**Depende de:** [`v18.7-graph-exploration-relations`](../v18.7-graph-exploration-relations/proposal.md) (schema: `papel`, `origem = "sistema"`, chave, referência fixada, `abandonada_por`, `PREPARA`, `REFERENCIA_DE`, `DERIVADA_DE -> Hipotese`).
**É pré-requisito de:** `v18.7-exploration-limits` (mergeada depois: faz rebase sobre a nova ordem de `prepare_cycle` e sobre `select`; esta mudança é dona da classificação de papel, das retiradas do ADR 021 §6, de `select` aceitar hipóteses concluídas e do campo `papel` no plano e em `AgentTask`; aquela, do fim do teto em `select` e da conferência de restrições), `v18.7-subtask-contract` (lê `AgentTask.papel_decidido` e a hipótese do sistema nos itens 1 e 4 do contrato e leva o retorno ao Researcher para o construtor do plano), `v18.7-exploration-metrics` (agrega por sessão os dados que esta mudança emite e substitui `reprovacoes_sem_hipotese`) e `v18.7-agent-system-prompts` (gera o texto do formato do plano, com `papel`, do esquema e reescreve os prompts a partir da fonte única).

## Por quê

Na bateria V18.6 (2026-10-15), as 6 execuções com Claude como Researcher/Developer fecharam sem treinar modelo. A cadeia, confirmada no código:

| Observação | Causa no código atual |
|---|---|
| Pré-processamento e baseline retirados por `sem_hipotese` | `prepare_cycle` retira toda subtarefa do Developer sem `hypothesis_ref` que não seja `eda`/`synthesis` (`src/exploration.py:376-377`, `_is_bound` em `src/exploration.py:295-308`) |
| Todas as demais subtarefas caem como `depende_de_subtarefa_retirada` | `_descendants_of` retira todo descendente transitivo de qualquer retirada (`src/exploration.py:310-321`, `394-396`) |
| Prompt e código se contradizem | O formato do plano diz que só quem testa precisa de `hypothesis_ref` (`src/exploration.py:108-109`); o Validator diz que o campo "nunca é motivo de reprovação" (`src/agents/validator_agent.py:95-97`); o código exige |
| O Researcher reenvia o mesmo plano | As retiradas não voltam a ele: o feedback do ciclo só lista concluídas e abandonadas por retentativa (`src/autonomous_loop.py:1926-1939`) |
| A EDA virou `Hipotese` `em_teste` | Sem `hypothesis_id`, a ingestão cria hipótese provisória a partir do texto livre `hypothesis` (`src/knowledge/ingestion.py:592-612`) |
| Hipótese validada não aceita replicação | `select` exclui `validada`/`refutada` (`src/knowledge/hypothesis_cycle.py:326`) e `sync_statuses` não as reavalia (`hypothesis_cycle.py:420`) |
| Toda hipótese `abandonada` bloqueia para sempre | `resolve_ref` e `_record_hypothesis` recusam qualquer `abandonada` (`src/knowledge/hypotheses.py:585-606`, `810`), sem distinguir quem abandonou |

O ADR 021 decide: a ligação é registrada, não exigida; o que o plano não declara o sistema deriva; só decisão humana ou regra de integridade impede a execução.

## O que muda

- **Novo:**
  - **Papel do experimento** (`teste`, `preparacao`, `referencia`) decidido por subtarefa pela ordem do ADR 021 §2: declarado no plano; `hypothesis_ref` resolvível; `eda`/`synthesis`; sinal de teste (limiar sobre a métrica principal M do Problema, ou `abordagem.tipo = "algoritmo"`); estrutura do DAG (tem dependentes); caso residual ligado ao `Problema`. Campo `papel` no formato do plano e em `AgentTask`; sua ausência nunca reprova o plano.
  - **Ligações derivadas:** `PREPARA` da preparação para toda hipótese testada por um descendente no DAG (incremental sobre o grafo em ciclos posteriores), ou para o `Problema`; `REFERENCIA_DE` dos resultados da métrica M do experimento `referencia`.
  - **Hipótese do sistema** (`origem = "sistema"`) para todo `teste` sem hipótese aceita: formato "a abordagem A melhora a métrica M do Problema P em relação à referência R", com R fixada na criação, `SOBRE->Problema`, `PROPOE->Abordagem`, deduplicada pela chave `(problema, abordagem canônica, métrica)`, evento `hipotese_derivada`.
  - **Ciclo de vida** da hipótese do sistema: sem tentativa, vai a `abandonada` com `abandonada_por = "sistema"` quando a subtarefa de origem é retirada, sai da fila num replanejamento ou esgota as tentativas sem execução; reabre pela mesma chave.
  - **Aprovação por modo:** no `assisted`, a hipótese do sistema aguarda o pesquisador; no `semi` e no `auto`, segue com a aprovação do plano pelo Validator.
  - **Hipótese derivada de hipótese** (`derivada_de` aceita IDs de `Hipotese` do projeto).
  - **Novos testes de hipótese concluída** e **transições de status nos dois sentidos** ao fim do ciclo, com revisão dos efeitos (oportunidade `GEROU`, decisões avaliadas, atalhos `FUNCIONOU_PARA`/`FALHOU_PARA`).
  - **Replanejamento substitui a fila:** item ausente do plano novo sai com `removida_pelo_replanejamento` (registro, não retirada).
  - **Retorno ao Researcher:** retiradas e ligações derivadas do ciclo voltam no replanejamento seguinte como dado delimitado.
  - **Dados por ciclo** no evento `hypothesis_cycle` (papéis, origens dos testes, ligações derivadas, hipóteses do sistema criadas, abandonadas e reabertas, removidas pelo replanejamento), para `v18.7-exploration-metrics` agregar.
- **Modificado:**
  - Requisito "Hipóteses formais no plano": a referência à hipótese passa a ser registro, não exigência.
  - Requisito "Resultado negativo na revisão": o motivo `sem_hipotese` deixa de existir; a revisão registra `hipotese_do_sistema`; resultado negativo de hipótese do sistema só com artefatos presentes e demais critérios aprovados (ADR 021 §8.1–§8.2).
  - Motivos de retirada (ADR 021 §6): `hipotese_ja_concluida_ou_abandonada` vira `hipotese_abandonada_pelo_pesquisador`; `depende_de_subtarefa_retirada` só quando todas as hipóteses que a subtarefa serve foram retiradas; `hipotese_hipotese_abandonada` e `hipotese_equivalente_a_hipotese_abandonada` só para abandono pelo pesquisador.
  - Campo livre `hypothesis` não cria `Hipotese` para `preparacao` e `referencia`; em `teste` sem `hypothesis_ref` vira o enunciado da hipótese do sistema quando é afirmativo e cita M.
  - `pipeline-robustness`, requisito "Limiar numérico obrigatório em subtarefa confirmatória": o cenário "Baseline sem hipótese" passa a ser o baseline declarado `papel = referencia`.
  - Ordem no laço: a validação do DAG (`TaskScheduler.validate_dag`) passa a rodar antes de `prepare_cycle` (hoje roda depois, `src/autonomous_loop.py:1060` e `1211`).
- **Removido:**
  - Retirada por `sem_hipotese` e a função `_is_bound` (`src/exploration.py:295-308`, `376-377`).
  - Retirada por `hipotese_id_inexistente` e `hipotese_sem_enunciado` (a subtarefa segue a derivação e o Researcher recebe o aviso).
  - Motivo de revisão `sem_hipotese` (`MOTIVO_SEM_HIPOTESE`, `src/agents/validator_agent.py:57`, `931-932`).
- **Fora do escopo:**
  - Fim de `HYPOTHESES_PER_CYCLE`, de `hipotese_adiada_por_prioridade`, de `MAX_EXPLORATION_CYCLES` e de `SOLUTION_MIN_VERDICT`; objetivo tipado; estagnação; restrições por direção (`hipotese_direcao_restrita`): `v18.7-exploration-limits`. Enquanto aquela mudança não entra, `hipotese_adiada_por_prioridade` continua existindo e é tratada aqui como retirada que não abandona hipótese.
  - Contadores por sessão, relatório e substituição de `reprovacoes_sem_hipotese` em `operation-metrics` e `benchmark`: `v18.7-exploration-metrics`.
  - Texto final dos prompts do Researcher e do Validator e teste de coerência: `v18.7-agent-system-prompts`. Aqui só as linhas que hoje contradizem o código.
  - Contrato da subtarefa do Developer com o papel: `v18.7-subtask-contract`.
  - Uso do valor medido da referência no termo `m` do veredito e calibração dos pesos: Etapa 2 (ADR 021 §3.2, §4.5).

## Impacto

- **Código:** `src/exploration.py` (classificação de papel, derivação, governança, retiradas, retorno ao Researcher, replanejamento), `src/knowledge/hypotheses.py` (hipótese do sistema, deduplicação pela chave, `derivada_de` com `Hipotese`, regras de abandono por autor), `src/knowledge/hypothesis_cycle.py` (`select` aceita concluídas; `sync_statuses` nos dois sentidos; revisão dos efeitos), `src/knowledge/ingestion.py` (`SubtaskInput.papel` e `prepara_ids`, `PREPARA`, `REFERENCIA_DE`, campo `hypothesis`), `src/knowledge/validation.py` (orquestrador reverte `Oportunidade` `concluida -> em_investigacao` só nesse caso), `src/agents/validator_agent.py` (motivos da revisão, `papel` no formato), `src/orchestrator.py` (`AgentTask.papel`, mapeamento do plano), `src/autonomous_loop.py` (ordem DAG/governança, abandono por retentativas, feedback), `src/config.py`, `.env.example`.
- **Contratos:** plano ganha `papel` por subtarefa (opcional); `AgentTask.papel`; `SubtaskInput.papel` e `SubtaskInput.prepara_ids`; evento novo `hipotese_derivada`; `hypothesis_cycle` ganha campos de ligação; `subtask_review.motivos` perde `sem_hipotese` e ganha `hipotese_do_sistema`; códigos de retirada renomeados (ver design §6).
- **Schema:** nenhum além do de `v18.7-graph-exploration-relations`.
- **Custo:** nenhuma chamada LLM nova. O bloco de retorno ao Researcher aumenta o prompt do plano em até `LINKAGE_FEEDBACK_MAX_ITEMS` linhas.

## Aprovações necessárias

- Nenhuma alteração de schema além da já pedida em `v18.7-graph-exploration-relations`, nenhum Dockerfile, `docker-compose.yml`, exclusão de arquivos ou `AGENTS.md`.
- **Regra de governança alterada:** o orquestrador passa a poder reverter uma `Oportunidade` de `concluida` para `em_investigacao` quando a hipótese que ela gerou reabre (ADR 021 §4.4). Hoje `OPPORTUNITY_ORCHESTRATOR_TRANSITIONS` só permite avançar (`src/knowledge/validation.py`). Pede parecer do Analista de Segurança e aprovação do pesquisador.
- **Decisão do pesquisador** sobre as questões em aberto do `design.md` §12.
