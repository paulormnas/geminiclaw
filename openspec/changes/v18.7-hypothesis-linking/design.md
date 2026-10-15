# Design: v18.7-hypothesis-linking

## 1. Ordem no laço

Hoje `prepare_cycle` roda antes da validação do DAG (`src/autonomous_loop.py:1060` e `1211`). A derivação de `PREPARA` percorre o DAG e pressupõe um grafo de dependências válido (ADR 021 §3.1). A nova ordem, por ciclo:

1. plano aprovado pelo Validator (inalterado; `apply_metrics` já roda dentro do planejamento, `src/orchestrator.py:2058`, então a métrica M está resolvida quando a sessão a define no plano);
2. poda das dependências já concluídas numa sessão retomada (`autonomous_loop.py:1205-1209`, movida para antes);
3. `TaskScheduler.validate_dag(tasks)` sobre o plano completo; DAG inválido volta ao Researcher como hoje (`autonomous_loop.py:1212-1215`), sem chamar `prepare_cycle`;
4. `prepare_cycle`: gravação das declarações, classificação de papel (§2), derivação (§3, §4), governança e retiradas (§6), fila do replanejamento (§7);
5. `validate_dag` das subtarefas mantidas (as retiradas levam junto o que depende delas, então o subgrafo continua válido; a checagem confirma).

## 2. Papel do experimento

### 2.1 Campo no plano

`AgentTask.papel: str = ""` (`src/orchestrator.py:77-110`) e o mapeamento do plano (`src/orchestrator.py:2305-2321`) copiam `papel` quando o valor é `teste`, `preparacao` ou `referencia`; qualquer outro valor é descartado e registrado como `papel_invalido` no retorno ao Researcher (§8). O Validator do plano trata `papel` como campo opcional do orquestrador, ao lado de `hypothesis_ref` (`validator_agent.py:95-97`): ausência ou valor inválido nunca reprovam o plano.

`AgentTask` ganha também `papel_decidido: str = ""` (o papel final, após a classificação) e `papel_fonte: str = ""` (`declarado`, `hypothesis_ref`, `task_type`, `sinal_de_teste`, `estrutura_dag`, `residual`), usados pela ingestão, pela revisão e pelo retorno ao Researcher.

### 2.2 Classificação

Função pura `classify_role(task, plan_tasks, metric: MetricRef | None, resolved_ref: bool) -> RoleDecision` em `src/exploration_roles.py` (módulo novo, sem grafo), aplicada a cada subtarefa não concluída, nesta ordem (ADR 021 §2):

| Regra | Condição | Papel | `papel_fonte` |
|---|---|---|---|
| 1 | `papel` declarado válido | o declarado | `declarado` |
| 2 | `hypothesis_ref` resolvido para hipótese aceita | `teste` | `hypothesis_ref` |
| 3 | `task_type` em (`eda`, `synthesis`) | `preparacao` | `task_type` |
| 4 | sinal de teste (§2.3) | `teste` (hipótese do sistema, §4) | `sinal_de_teste` |
| 5 | alguma subtarefa do plano depende dela (direta) | `preparacao` | `estrutura_dag` |
| 6 | qualquer outro caso | `preparacao` ligada ao `Problema` | `residual` |

Uma subtarefa da regra 4 com dependentes continua `teste` (ex.: `treinar_rf` que alimenta `comparar_modelos`). `referencia` só vem da regra 1. A regra 1 vence a 3 (ver questão 4).

### 2.3 Sinal de teste

`MetricRef` = `id`, `nome` e `sinonimos` da `Metrica` do `Problema` resolvida por `KnowledgeService.criterion_for(problem)` (`service.py:237`). Sinal de teste quando:

- algum critério de `validation_criteria` tem comparação numérica (mesmo parser do revisor, `_CRITERION_VALUE_PATTERN`, `validator_agent.py:122`) cuja grandeza, normalizada por `normalize_domain_term` e pelos aliases do revisor (`_METRIC_ALIASES`), é o nome ou um sinônimo de M, aceitando os qualificadores `test_`/`teste` e sem qualificador (`cv`, `treino` e `validacao` não contam, como em `v18.6-review-evidence`); ou
- `approach.tipo == "algoritmo"`.

Limiares sobre outras grandezas ("proporção de nulos <= 0") não contam. Sem `MetricRef` (métrica do Problema não resolvida), só a `abordagem` de tipo `algoritmo` dá sinal de teste (questão 3).

## 3. Ligações derivadas

### 3.1 Preparação → hipóteses servidas

Para cada `preparacao`, `served(task)` = conjunto das hipóteses (aceitas ou do sistema) testadas por subtarefas `teste` que dependem dela, direta ou transitivamente, no plano atual. Se `hypothesis_ref` estiver preenchido numa preparação declarada, a hipótese referida entra também no conjunto. Conjunto vazio → destino `Problema`.

A aresta só pode ser escrita depois que o `Experimento` da preparação existe. Por isso:

- **No mesmo ciclo:** `prepare_cycle` grava `task.prepara_ids` (lista de IDs de hipótese, ou vazia para o `Problema`); `_ingest_subtask` (`autonomous_loop.py:1941`) passa `SubtaskInput.papel` e `SubtaskInput.prepara_ids`; a ingestão cria `Experimento-PREPARA->` cada hipótese, ou `->Problema` com a lista vazia, com `origem = "derivado"`.
- **Incremental:** quando um `teste` de um ciclo posterior depende de uma preparação já concluída (`done_results`), `prepare_cycle` pede à ingestão `link_preparation(subtarefa_id, hypothesis_ids)`, que acrescenta as arestas ao `Experimento` existente (busca por `subtarefa_id`, como `ingestion.py:636`) pela mesma fila resiliente do `FactIngestor`. Sem `Experimento` (preparação sem código nem métricas, que a ingestão não materializa, `ingestion.py:625-626`), nada é escrito e o evento registra `preparacao_sem_experimento`.
- A aresta `->Problema` de uma preparação que depois passa a servir hipóteses permanece (registro histórico; nada é apagado).

### 3.2 Referência → Problema

Na ingestão de um `Experimento` com `papel = "referencia"`, cada `Resultado` com `MEDE->M` recebe `Resultado-REFERENCIA_DE->Problema` (`origem = "afirmado"`). Resultados de outras métricas não recebem a aresta. Sem nenhum `Resultado` de M, o evento `referencia_sem_metrica` é registrado com a subtarefa. O experimento `referencia` não tem `TESTA` nem `PREPARA`. O valor não entra no veredito (ADR 021 §3.2).

## 4. Hipótese do sistema

### 4.1 Quando é criada

Para uma subtarefa `teste` sem hipótese aceita:

- regra 4 do §2.2 (sem `hypothesis_ref`); ou
- `hypothesis_ref` recusado na gravação por `id_inexistente` ou `sem_enunciado` (falha de formato, ADR 021 §3.3); ou
- `papel: "teste"` declarado sem `hypothesis_ref`.

Referências recusadas por `hipotese_abandonada`, `equivalente_a_hipotese_abandonada` ou `oportunidade_nao_aprovada` não derivam hipótese: seguem as regras do §6.

### 4.2 Conteúdo

`HypothesisBook.system_hypothesis(task, problem, metric, approach) -> SystemHypothesisOutcome` (`src/knowledge/hypotheses.py`):

- **Abordagem A:** a declarada em `task.approach`, gravada/reutilizada por `_Writer.abordagem` e resolvida para a canônica. Sem `approach`, uma `Abordagem` `tipo = "outro"` com o nome da subtarefa e a descrição "abordagem não declarada no plano" (questão 2); o retorno ao Researcher pede que declare a abordagem.
- **Métrica M:** `MetricRef.id`.
- **Chave:** `structured_key(problem.id, A_canonica, M)` (`v18.7-graph-exploration-relations`).
- **Referência R** (fixada na criação):
  1. o `Resultado` validado mais recente (por `criado_em`) com `REFERENCIA_DE->Problema` e `MEDE->M` → `origem_referencia = "referencia_medida"`, `valor` e `resultado_id`;
  2. senão, o valor numérico do baseline no `criterio_sucesso` do `Problema`, se existir → `criterio_problema`. Hoje o critério só tem `baseline_descricao` (texto, `src/knowledge/problem.py:53`), então este passo só vale quando o critério ganhar um baseline numérico (questão 1);
  3. senão, `valor = null` e `origem_referencia = "indisponivel"`.
  A comparação com o melhor resultado validado até então vai para a trilha de auditoria da hipótese (`record_audit_note`, chave `melhor_ate_entao`), como informação.
- **Enunciado:** o texto livre `task.hypothesis` quando é afirmativo e cita M (§9.3); senão o modelo fixo, com texto saneado e limitado a `HYPOTHESIS_TEXT_MAX_CHARS`:
  `A abordagem "<A>" melhora a métrica "<M>" do Problema "<título>" em relação à referência <R>.` com `<R>` = `<valor> (<origem_referencia>)` ou `não disponível`.
- **Arestas:** `SOBRE->Problema`, `PROPOE->A`, criadas pelo orquestrador (`Actor` `orquestrador`), `justificativa_criacao = "derivada pelo sistema da subtarefa <nome> (<motivo>)"`.
- **Status inicial:** `proposta`; a governança do §5 decide.
- **Evento:** `hipotese_derivada` com `subtarefa`, `hipotese_id`, `motivo` (`sem_hypothesis_ref`, `ref_id_inexistente`, `ref_sem_enunciado`, `papel_teste_declarado`), `reutilizada` (bool) e `reaberta` (bool).

### 4.3 Deduplicação pela chave

Antes de criar, `find_nodes("Hipotese", {"projeto_id": ..., "chave_estruturada": key})`:

| Hipótese existente com a chave | Efeito |
|---|---|
| nenhuma | cria |
| não abandonada (qualquer status, inclusive `validada`/`refutada`) | reutiliza: a subtarefa é novo teste da mesma hipótese (variação, réplica; ADR 021 §4.1, §4.3) |
| `abandonada` com `abandonada_por = "sistema"` | reabre (§4.5) e reutiliza |
| `abandonada` com `abandonada_por = "pesquisador"` (inclusive leitura compatível) | subtarefa retirada com `hipotese_equivalente_a_hipotese_abandonada` |
| `abandonada` com `abandonada_por = "agente"` | conforme a questão 2 do design de `v18.7-graph-exploration-relations` (proposta: reabre como `proposta`) |

Duas subtarefas do mesmo plano com a mesma chave usam a mesma hipótese. A deduplicação por similaridade (`HYPOTHESIS_DEDUP_SIMILARITY`) continua valendo só para hipóteses declaradas; hipótese declarada semelhante a uma do sistema é tratada na questão 5.

### 4.4 Ciclo de vida

`ExplorationSession` mantém `system_origin: dict[str, set[str]]` (hipótese do sistema → subtarefas de origem no plano corrente), refeito a cada `prepare_cycle` e salvo no checkpoint da sessão junto com o plano (`recorder.set_plan`), para sobreviver à retomada.

Uma hipótese do sistema com `n_tentativas` ausente ou 0 vai a `abandonada`, `abandonada_por = "sistema"`, `motivo_abandono` ∈ (`subtarefa_retirada`, `removida_pelo_replanejamento`, `tentativas_esgotadas_sem_execucao`), quando **todas** as subtarefas de origem:

- foram retiradas pela governança (§6), exceto por `hipotese_aguarda_aprovacao` e, enquanto existir, `hipotese_adiada_por_prioridade` (a hipótese continua pendente, não sem trabalho); ou
- saíram da fila num replanejamento (§7); ou
- ficaram `abandonada` no DAG por retentativas esgotadas (`autonomous_loop.py:1298`, `1615`).

Hipótese do sistema com tentativas não é abandonada por esses eventos: já tem evidência, e o status segue o veredito (§5.3).

### 4.5 Reabertura

Quando um plano posterior produz a mesma chave de uma hipótese abandonada pelo sistema, ela volta a `em_teste` se já tinha sido aprovada antes (sempre no `semi` e no `auto`; no `assisted`, só se `ApprovalPort.previously_approved(hypothesis_id, session_chain)` devolver verdadeiro, isto é, se existe no gate persistente um pedido `aprovar_hipotese` daquele id, `estado = 'autorizada'` e `resolvido_por` humano), ou a `proposta` no `assisted` sem esse registro. A trilha de auditoria do grafo nunca é usada como prova de aprovação (parecer de segurança, item 1). Interface: `ApprovalPort` de `src/human_approval.py`, de `v18.7-persistent-human-gate` (design §2.4 daquela mudança). Se esta mudança for mergeada antes daquela, ela cria `src/human_approval.py` com o `Protocol` exatamente como lá descrito e usa a implementação provisória `NoGateApprovalPort` (envolve o `Approver` injetado; `previously_approved` devolve sempre `False`), de modo que no `assisted` a reabertura volta sempre a `proposta` até a troca por `PersistentGateApprover`. `abandonada_por` e `motivo_abandono` são limpos, o histórico fica na auditoria e o evento `hipotese_derivada` sai com `reaberta = true`.

## 5. Governança, concluídas e transições

### 5.1 Aprovação por modo

`HypothesisCycle.select` trata `origem = "sistema"` como hipótese de agente: no `assisted` entra no lote de aprovação (`_select_assisted`, `hypothesis_cycle.py:353`) pela interface `ApprovalPort` (§4.5), com o rótulo de origem "sistema" e, quando o enunciado veio do texto livre, `enunciado_fonte = "texto_livre"` no item mostrado ao pesquisador (§9.3). Com `PersistentGateApprover`, a aprovação é um pedido `aprovar_hipotese` por hipótese no gate persistente, nunca o `terminal_approver`; com a provisória `NoGateApprovalPort`, sem TTY o item fica pendente (parecer de segurança, item 2); no `semi` e no `auto`, segue o caminho autônomo (ADR 021 §3.6). Enquanto `v18.7-exploration-limits` não remove o teto, a prioridade e `HYPOTHESES_PER_CYCLE` valem também para ela.

### 5.2 Hipótese concluída recebe testes

`select` deixa de excluir `validada` e `refutada` (`hypothesis_cycle.py:326`): elas entram em `execute` sem mudar de status no meio do ciclo. Continuam fora: `abandonada` com `abandonada_por = "pesquisador"` (motivo `hipotese_abandonada_pelo_pesquisador`) e as rejeitadas no lote deste ciclo (`hipotese_rejeitada_pelo_pesquisador`).

### 5.3 Transições ao fim do ciclo

`sync_statuses` (`hypothesis_cycle.py:407`) passa a percorrer todas as hipóteses do projeto não abandonadas, com `floor = DECISION_EVAL_MIN_VERDICT`:

| Status atual | Veredito | Novo status |
|---|---|---|
| `proposta`/`em_teste`/`inconclusiva` | `>= floor` | `validada` |
| `proposta`/`em_teste`/`inconclusiva` | `<= -floor` | `refutada` |
| `validada` | `<= -floor` | `refutada` |
| `refutada` | `>= floor` | `validada` |
| `validada`/`refutada` | entre `-floor` e `floor` | `em_teste` |
| demais | — | inalterado |

`proposta` só transita se tiver tentativas (hipótese ainda não selecionada não tem veredito calculado). Cada transição grava `record_audit_note` com `status_anterior`, `status_novo`, `veredito_novo` e `veredito_anterior` (o `veredito_novo` da transição anterior dessa hipótese, ou `null`). Só roda em `after_cycle`, nunca no meio do ciclo.

### 5.4 Revisão dos efeitos (ADR 021 §4.4)

Quando uma hipótese concluída volta a `em_teste` ou muda de lado:

- **Oportunidade:** reabertura (`em_teste`) leva a `Oportunidade` ligada por `GEROU` de `concluida` para `em_investigacao`, pelo orquestrador; mudança de lado mantém `concluida`. Exige acrescentar a transição `concluida -> em_investigacao` às permitidas ao orquestrador em `validation.py` (`OPPORTUNITY_ORCHESTRATOR_TRANSITIONS`), condicionada a uma flag explícita da chamada `revert_on_reopen` usada só por este caminho, com nota de auditoria (ver Segurança).
- **Decisões:** decisões com `ESCOLHEU->` a hipótese e `resultado_posterior` preenchido: na reabertura, `resultado_posterior` volta a `null` (avaliada de novo quando o veredito passar do limiar); na mudança de lado, recebe o novo valor (`acertada` ↔ `nao_acertada`). `evaluate_decisions` passa a reavaliar as decisões cuja hipótese escolhida transitou no ciclo. Toda mudança tem nota de auditoria com o veredito.
- **Atalhos:** arestas `FUNCIONOU_PARA`/`FALHOU_PARA` cujo `descoberta_id` aponta para uma `Descoberta` com `SOBRE->` a hipótese passam a `status = "contestada"` (`set_edge_status`), como a spec `curator` já prevê para evidência que muda. O Curator pode reconfirmá-las depois pelo caminho existente (`service.py:612`).

## 6. Motivos que impedem a execução

`prepare_cycle` passa a aplicar só os motivos do ADR 021 §6. Códigos gravados em `CycleOutcome.dropped` e em `retiradas_por_motivo`:

| Código | Quando |
|---|---|
| `hipotese_rejeitada_pelo_pesquisador` | teste de hipótese rejeitada no lote deste ciclo; preparação que só a servia |
| `hipotese_aguarda_aprovacao` | teste de hipótese pendente no `assisted`; preparação que só servia hipóteses pendentes |
| `hipotese_abandonada_pelo_pesquisador` | teste de hipótese `abandonada` pelo pesquisador (substitui `hipotese_ja_concluida_ou_abandonada`) |
| `hipotese_hipotese_abandonada` | `hypothesis_ref` com `id` de hipótese abandonada pelo pesquisador |
| `hipotese_equivalente_a_hipotese_abandonada` | enunciado declarado ou chave derivada equivalente a hipótese abandonada pelo pesquisador |
| `hipotese_oportunidade_nao_aprovada` | inalterado |
| `hipotese_adiada_por_prioridade` | inalterado até `v18.7-exploration-limits` |
| `hipotese_direcao_restrita` | definido em `v18.7-exploration-limits`; aqui só entra na regra de cascata |
| `depende_de_subtarefa_retirada` | ver abaixo |

**Cascata.** Uma preparação é retirada quando todas as hipóteses de `served(task)` foram retiradas; recebe o motivo comum delas se for um só, senão `depende_de_subtarefa_retirada`. Uma preparação ligada só ao `Problema` nunca é retirada por motivo de hipótese. Um `teste` cuja hipótese não foi retirada, mas que depende de outro `teste` retirado (ex.: `comparar` da hipótese h3 depende de `treinar` da h1 rejeitada), é retirado com `depende_de_subtarefa_retirada`, porque a entrada não vai existir (questão 6). A cascata é recalculada até o ponto fixo.

`sem_hipotese`, `hipotese_id_inexistente` e `hipotese_sem_enunciado` deixam de ser produzidos; as duas últimas viram `hipotese_derivada` com o motivo correspondente e aviso ao Researcher.

## 7. Replanejamento substitui a fila

A fila de um ciclo é o conjunto de subtarefas do plano anterior que não foram concluídas nem retiradas (inclusive as que esperam aprovação e, enquanto `v18.7-exploration-limits` não as remove, as adiadas por prioridade). No `prepare_cycle` seguinte, cada `task_name` da fila ausente do plano novo sai com `removida_pelo_replanejamento`, registrada no evento `hypothesis_cycle` em `removidas_pelo_replanejamento` (lista de nomes, limitada a 50) e fora de `retiradas_por_motivo` (não é retirada pela governança). As hipóteses do sistema cujas subtarefas de origem saíram assim seguem o §4.4.

## 8. Retorno ao Researcher

`ExplorationSession.linkage_feedback() -> list[dict]`, produzido em `prepare_cycle` e entregue no replanejamento seguinte dentro de `prompt_block` como `wrap_data("ligacoes_e_retiradas_do_ciclo_anterior", ...)` (dado não confiável, porque contém nomes de subtarefa e enunciados escritos pelo LLM). Até `LINKAGE_FEEDBACK_MAX_ITEMS` itens, retiradas primeiro, cada um `{"subtarefa", "papel", "acao", "motivo", "hipoteses"}`. Frases curtas por tipo de ação:

| Ação | Texto |
|---|---|
| preparação ligada | "`<subtarefa>`: registrada como preparação de h1, h2." / "… preparação do Problema." |
| hipótese do sistema criada ou reutilizada | "`<subtarefa>`: teste sem hipótese declarada; hipótese do sistema `<id>` criada (reutilizada). Declare `hypothesis_ref` para usar a sua." |
| referência registrada | "`<subtarefa>`: registrada como referência do Problema." |
| baseline provável sem declaração | "`<subtarefa>`: executada como teste da hipótese do sistema `<id>`; se é um baseline, declare `papel: referencia`." quando o nome ou o `task_type` sugerem baseline (`baseline`, `dummy`, `majoritari` no nome) |
| referência sem métrica | "`<subtarefa>`: referência sem resultado da métrica M." |
| retirada | "`<subtarefa>`: não executada (`<motivo>`)." |
| removida pelo replanejamento | "`<subtarefa>`: removida da fila pelo plano novo." |
| formato | "`<subtarefa>`: `hypothesis_ref` `<ref>` inválido (`<motivo>`); seguiu como teste da hipótese do sistema." / "`papel` inválido ignorado." / "abordagem não declarada." |

`v18.7-subtask-contract` move esse bloco para o construtor de contexto do Researcher (ADR 022 §1); o conteúdo é o definido aqui.

## 9. Revisão, resultado negativo e texto livre

### 9.1 Motivos da revisão

`ReviewResult.motivos` deixa de receber `sem_hipotese` (`validator_agent.py:931-932` sai). Quando a subtarefa revisada testa uma hipótese `origem = "sistema"`, `motivos` recebe `hipotese_do_sistema` (aprovada ou reprovada; só registro, sem efeito no status). O laço passa `task.hypothesis_origin` ao revisor junto com `hypothesis_id`.

### 9.2 Resultado negativo de hipótese do sistema

As condições de `v18.6-hypothesis-closure` §1 valem sem mudança, e agora alcançam os testes das hipóteses do sistema (que sempre têm `hypothesis_id`): artefatos esperados todos resolvidos, só comparações determinísticas com a métrica presente e numérica, demais critérios aprovados pelo revisor LLM. Falha de execução (`agent_status != "success"`), artefato ausente, `metrics.json` ausente ou ilegível continuam `reprovado` (ADR 021 §8.2). Uma preparação ou referência com limiar não atingido continua `reprovado`, sem motivo extra.

### 9.3 Campo livre `hypothesis`

- `preparacao` e `referencia`: a ingestão não cria `Hipotese` a partir do texto (`ingestion.py:592-612` passa a exigir `papel` ausente ou `teste`).
- `teste` sem `hypothesis_ref`: o texto vira o enunciado da hipótese do sistema quando é afirmativo e cita M; nesse caso a nota de auditoria da criação e o evento `hipotese_derivada` registram `enunciado_fonte = "texto_livre"` (no modelo fixo do §4.2, `enunciado_fonte = "modelo"`), e o item de aprovação do `assisted` mostra a fonte (parecer de segurança, item 4). "Afirmativo": a primeira palavra normalizada não está em `HYPOTHESIS_TEXT_NEGATION_PREFIXES`. "Cita M": contém o nome ou um sinônimo normalizado de M. Senão vale o modelo fixo do §4.2.
- Sem exploração ativa (`HYPOTHESIS_LOOP_ENABLED=false` ou projeto sem `Problema` confirmado), o comportamento da V17 continua, exceto que `task_type` `eda` e `synthesis` nunca criam hipótese provisória.

## 10. Dados por ciclo e eventos

O evento `hypothesis_cycle` (`exploration.py:398-409`) mantém os campos atuais e ganha:

```json
{
  "papeis": {"teste": 3, "preparacao": 2, "referencia": 1},
  "papel_fonte": {"declarado": 2, "hypothesis_ref": 1, "task_type": 1, "sinal_de_teste": 1, "estrutura_dag": 1, "residual": 0},
  "testes_por_origem": {"pesquisador": 0, "researcher": 1, "curator": 0, "oportunidade": 0, "sistema": 2},
  "ligacoes_prepara": 3,
  "hipoteses_sistema_criadas": 1,
  "hipoteses_sistema_reutilizadas": 1,
  "hipoteses_sistema_reabertas": 0,
  "hipoteses_sistema_abandonadas": 0,
  "removidas_pelo_replanejamento": []
}
```

Eventos novos: `hipotese_derivada` (§4.2), `hipotese_sistema_abandonada` (`hipotese_id`, `motivo_abandono`), `hipotese_transicao` (`hipotese_id`, `status_anterior`, `status_novo`, `veredito_novo`), `referencia_sem_metrica`, `preparacao_sem_experimento`. Só IDs, nomes de subtarefa, códigos e números (sem enunciado). A agregação por sessão e o relatório são de `v18.7-exploration-metrics`.

## 11. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `LINKAGE_FEEDBACK_MAX_ITEMS` | `30` | máximo de itens do retorno ao Researcher (§8); mínimo 1 |
| `HYPOTHESIS_TEXT_NEGATION_PREFIXES` | `nao,sem,nenhum,nenhuma,nunca` | primeiras palavras (normalizadas, sem acento) que tornam o texto livre não afirmativo (§9.3) |

Continuam em uso sem mudança: `DECISION_EVAL_MIN_VERDICT` (transições, §5.3), `HYPOTHESIS_DEDUP_SIMILARITY` (só hipóteses declaradas), `HYPOTHESIS_TEXT_MAX_CHARS`, `NEGATIVE_RESULT_AS_PROGRESS`. Ambas as variáveis novas vão para `src/config.py` e `.env.example`. Não há chave para voltar à retirada por `sem_hipotese`: o comportamento foi rejeitado no ADR 021 (alternativa A).

## 12. Testes sem provedor pago

- **Plano:** dicionários JSON passados a `split_plan`/`normalize_plan` e convertidos em `AgentTask` como no orquestrador; nenhum Researcher real.
- **Grafo:** `InMemoryGraphStore` com o vocabulário semeado (`tests/support/hypothesis_world.py`, `exploration_world.py`), `Problema` confirmado com `Metrica` `acuracia` aprovada (sinônimos `accuracy`, `test_accuracy`).
- **Aprovação no `assisted`:** `Approver` injetado que devolve decisões fixas (como em `tests/unit/hypothesis_loop/test_governance.py`).
- **Revisão:** critérios quantitativos são avaliados de forma determinística a partir de `metrics.json` escrito no `tmp_path`; critérios qualitativos usam um `LLMProvider` falso que devolve um parecer JSON fixo (`tests/support/session_fakes.py`).
- **Laço:** `tests/support/task_loop.py` com agentes falsos que gravam `metrics.json` e artefatos.
- **Integração AGE:** um teste com marcador `integration` executa um ciclo com preparação, teste e referência e confere `PREPARA`, `TESTA` e `REFERENCIA_DE` no grafo real.

## 13. Análise de impacto nos 6 eixos

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Alto | Ordem DAG → governança; nova classificação; retiradas só por decisão humana ou integridade; fila substituída no replanejamento; abandono por retentativas avisa a exploração |
| Agentes & Prompts | Médio | Campo `papel` no formato do plano; linhas contraditórias do Researcher (`exploration.py:108-109`) e do Validator (`validator_agent.py:88-97`) corrigidas; bloco de retorno ao Researcher. Reescrita completa fica com `v18.7-agent-system-prompts` |
| Sandboxes & Containers | Nenhum | — |
| Persistência de Estado | Alto | Hipóteses do sistema, `PREPARA`, `REFERENCIA_DE`, transições nos dois sentidos, reversão de `Oportunidade`, decisões reavaliadas, atalhos contestados; checkpoint guarda `system_origin` |
| Segurança & Hardening | Médio | Hipótese rejeitada ou abandonada pelo pesquisador continua bloqueando (garantido também no grafo); nova transição de `Oportunidade` pelo orquestrador; texto do LLM no retorno ao Researcher vai delimitado |
| Testes & Telemetria | Médio | Evento `hypothesis_cycle` ampliado e cinco eventos novos; `subtask_review.motivos` muda; testes existentes que esperam `sem_hipotese` e `hipotese_ja_concluida_ou_abandonada` são atualizados |

## 14. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.** Os pontos 1, 3, 4 e 5 de "Pontos para o parecer" estão adequados. Achados:

1. **Médio: reabertura no `assisted`.** A reabertura em `em_teste` (§4.5) depende de uma nota de auditoria gravada pela própria sessão. Requisito: a aprovação anterior é conferida no gate persistente, por um pedido `aprovar_hipotese` autorizado para aquele id, e não na trilha de auditoria. Sem esse registro, a hipótese volta a `proposta`.
2. **Médio: aprovação da hipótese do sistema.** No `assisted`, passa pelo gate persistente (`aprovar_hipotese`) assim que `v18.7-persistent-human-gate` existir, e não pelo `terminal_approver`. Até lá, sem TTY, fica pendente, como já está escrito.
3. **Baixo: `revert_on_reopen` fora do alcance dos agentes.** Nenhuma ferramenta de agente (Curator) nem campo do plano chega a esse caminho; um teste confirma.
4. **Baixo: origem do enunciado.** O enunciado da hipótese do sistema que vem de `task.hypothesis` é texto de LLM. A auditoria registra a fonte (`enunciado_fonte = "texto_livre"`), e o pedido de aprovação a mostra ao pesquisador.

Rastreio dos achados: item 1 e item 2 no requisito "Aprovação da hipótese do sistema por modo" e no cenário "Reabertura no assistido sem aprovação no gate" (`specs/hypothesis-loop`, tarefa 6.7); item 3 no requisito "Reversão de Oportunidade fora do alcance dos agentes" (tarefa 7.5); item 4 no requisito "Fonte do enunciado da hipótese do sistema registrada" (tarefa 5.5).

Pontos para o parecer:

1. **Decisões reservadas.** A hipótese do sistema nunca é aprovada por agente no `assisted` (passa pela `ApprovalPort`: pedido `aprovar_hipotese` no gate persistente; com a provisória `NoGateApprovalPort`, sem TTY fica pendente). Hipótese rejeitada ou abandonada pelo pesquisador não volta por `id`, por enunciado nem por chave derivada; a regra é aplicada em `prepare_cycle` e garantida no grafo (`v18.7-graph-exploration-relations` §2.3).
2. **Reversão de `Oportunidade`.** O orquestrador passa a poder fazer `concluida -> em_investigacao`, só pela reabertura da hipótese gerada, com auditoria. A aprovação da oportunidade continua só do pesquisador.
3. **Texto não confiável.** `task.hypothesis`, nomes de subtarefa e de abordagem vêm do LLM: são saneados (`clean_free_text`, `sanitize_text`) e limitados antes de virar enunciado ou nome de nó, e o retorno ao Researcher vai em `wrap_data`. Nenhum ID vindo do plano é usado sem conferência no grafo.
4. **Telemetria.** Os eventos novos levam só IDs, códigos, números e nomes de subtarefa (já presentes em `plan_generated`), nenhum enunciado.
5. **Exaustão.** Sem a retirada por `sem_hipotese`, um plano com muitos testes executa mais; o limite de subtarefas por ciclo (`max_subtasks`, `autonomous_loop.py:1128-1131`) e os limites de uso continuam valendo.

## 15. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Hipóteses do sistema genéricas inflam o grafo | Formato fixo com métrica e referência; chave estruturada evita duplicata; retorno ao Researcher pede `hypothesis_ref`; proporção medida por `v18.7-exploration-metrics` |
| Pré-processamento classificado como `teste` por ter limiar sobre M | Só limiar sobre M conta; pré-processamento costuma ter critérios sobre nulos e formato; teste com plano real da bateria V18.6 (tarefa 10.3) |
| Baseline não declarado vira hipótese do sistema refutada | Evidência negativa legítima (ADR 021 §2); aviso ao Researcher para declarar `papel: referencia` |
| Hipótese validada reabre por uma réplica fraca | Transição só ao fim do ciclo e com o mesmo limiar `DECISION_EVAL_MIN_VERDICT`; a independência da evidência já é descontada pela fórmula (ADR 015 §9) |
| Leitores que assumiam status final de hipótese | Evento `hipotese_transicao` e auditoria; teste do relatório com hipótese que mudou de lado |
| `prepare_cycle` mais lento em planos grandes | Classificação e cascata são lineares no número de subtarefas e arestas do plano (até `max_subtasks`); a busca pela chave é uma consulta por hipótese do sistema |
| Retomada perde `system_origin` | Salvo no checkpoint com o plano; sem ele, hipóteses do sistema sem tentativa e sem subtarefa no plano retomado são abandonadas pelo sistema (podem reabrir pela chave) |

## 16. Questões em aberto

1. **Referência R sem baseline numérico no critério.** O ADR 021 §3.3 manda usar "o baseline do critério do Problema" quando não há referência medida, mas o critério só tem `baseline_descricao` (texto). Proposta: R `indisponivel` (`valor = null`) até o critério ganhar um baseline numérico; o enunciado diz "referência não disponível". Alternativa: acrescentar `criterio_sucesso.baseline` (número) no rascunho do Problema, o que toca a spec `research-project` e combina com o objetivo tipado de `v18.7-exploration-limits`.
2. **Teste sem `approach`.** A chave precisa de uma abordagem. Proposta: `Abordagem` `tipo = "outro"` com o nome da subtarefa, mais aviso ao Researcher. Alternativa: chave com a abordagem vazia (`"<problema>|-|<metrica>"`), o que juntaria testes diferentes numa só hipótese.
3. **Projeto sem métrica M resolvida.** Proposta: só `approach.tipo = "algoritmo"` dá sinal de teste; a hipótese do sistema não é criada sem M e a subtarefa segue como `preparacao` ligada ao `Problema` (regra 6, "na dúvida, não inventa"), com aviso. Alternativa: usar a métrica citada no critério da subtarefa como M provisória.
4. **`papel` declarado contra `task_type`.** O ADR põe a declaração em primeiro lugar e diz que `eda`/`synthesis` são `preparacao` "sempre". Proposta: a declaração vence (uma EDA declarada `teste` derivaria hipótese do sistema). Alternativa: `eda`/`synthesis` são sempre `preparacao`, e a declaração contrária gera aviso.
5. **Hipótese declarada semelhante a uma do sistema.** Proposta: a deduplicação por similaridade reutiliza a hipótese do sistema (sem duplicar o nó; `origem` continua `sistema`). Alternativa: criar a hipótese declarada nova e ligá-la por `DERIVADA_DE` à do sistema, preservando a autoria do Researcher.
6. **Teste que depende de teste retirado.** O ADR 021 §6 diz que `depende_de_subtarefa_retirada` vale "só quando todas as hipóteses que a subtarefa serve foram retiradas", mas não trata o teste cuja hipótese segue aceita e cuja entrada vem de um teste retirado. Proposta: retirar com `depende_de_subtarefa_retirada` (a entrada não existe). Alternativa: executar sem a dependência e deixar a revisão reprovar.
7. **Sugestão de reformulação pelo Curator (ADR 021 §3.7).** As sugestões atuais são determinísticas (`src/knowledge/suggestions.py`). Proposta: nesta mudança, só garantir que as hipóteses do sistema aparecem com `origem = "sistema"` no contexto do Researcher e do Curator e que o Researcher pode declarar hipótese `derivada_de` uma do sistema; um tipo de sugestão `reformular_hipotese_do_sistema` fica para decisão. Alternativa: incluir já esse tipo, gerado para hipóteses do sistema com ao menos uma tentativa e sem hipótese derivada declarada.
