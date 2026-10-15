# Delta: hypothesis-loop

Convenções dos cenários: grafo `InMemoryGraphStore` com o vocabulário semeado; `Problema` confirmado `P` com `Metrica` `acuracia` aprovada (sinônimos `accuracy`, `test_accuracy`); planos entregues como JSON a `split_plan`, sem Researcher real; aprovação do `assisted` por `Approver` injetado; critérios qualitativos da revisão por `LLMProvider` falso com parecer fixo. Nenhum cenário chama provedor pago.

## MODIFIED Requirements

### Requirement: Hipóteses formais no plano
_Origem: ADR 021 §1, §2.1 e §3 (antes: [`v18-hypothesis-loop`](../../../archive/v18-hypothesis-loop/proposal.md))_
O Researcher SHALL declarar as hipóteses do plano e SHOULD referenciar em cada subtarefa de teste a hipótese que ela testa (`hypothesis_ref`) e declarar o `papel` de cada subtarefa. O sistema SHALL gravar as hipóteses declaradas como nós `Hipotese` ligados ao problema. A falta de `hypothesis_ref` ou de `papel` MUST NOT reprovar o plano nem retirar a subtarefa: o sistema SHALL derivar a ligação e registrá-la.
(Antes: cada subtarefa SHALL referenciar a hipótese que testa, e a subtarefa sem referência era retirada por `sem_hipotese`.)

#### Scenario: Plano com hipótese
- **WHEN** o Researcher gera um plano com a hipótese `h1` e duas subtarefas com `hypothesis_ref="h1"`
- **THEN** existe `Hipotese(status="proposta")` com `SOBRE->Problema`
- **AND** os experimentos das duas subtarefas têm `TESTA->` essa hipótese

#### Scenario: Hipótese repetida
- **GIVEN** uma hipótese do projeto com similaridade 0,94 à nova
- **WHEN** o plano é gravado
- **THEN** a hipótese existente é reutilizada

#### Scenario: Plano em passos finos executa
- **GIVEN** modo `auto` e o plano `eda` (`task_type="eda"`), `preprocessar_dados` (`model_impl`, sem `hypothesis_ref`, critérios "proporção de nulos <= 0"), `baseline_majoritario` (`validation`, `papel="referencia"`), `treinar_knn` (`hypothesis_ref="h1"`, critério "acurácia no teste >= 0.9") e `treinar_rf` (sem `hypothesis_ref`, `approach={"nome": "random forest", "tipo": "algoritmo"}`), as três últimas dependentes de `preprocessar_dados`
- **WHEN** `prepare_cycle` roda
- **THEN** `CycleOutcome.dropped` é vazio
- **AND** as cinco subtarefas estão em `CycleOutcome.tasks`
- **AND** `retiradas_por_motivo` do evento `hypothesis_cycle` é `{}`

#### Scenario: Plano sem papel não é reprovado
- **GIVEN** um plano em que nenhuma subtarefa tem `papel` e uma tem `papel = "exploratoria"`
- **WHEN** o Validator checa a estrutura do plano
- **THEN** o plano não é reprovado por causa de `papel`
- **AND** a subtarefa com `papel = "exploratoria"` é classificada como se não tivesse o campo, e o retorno ao Researcher registra `papel_invalido`

### Requirement: Resultado negativo na revisão
_Origem: ADR 021 §8.1 e §8.2 (antes: [`v18.6-auto-metrics-and-stop-reasons`](../../../archive/v18.6-auto-metrics-and-stop-reasons/proposal.md))_
O revisor SHALL devolver `outcome = "resultado_negativo"` quando a subtarefa tem hipótese resolvida (declarada ou do sistema), todos os artefatos esperados foram resolvidos e as únicas reprovações são comparações determinísticas com a métrica presente e numérica, com os demais critérios aprovados. Em qualquer outro caso de reprovação, inclusive falha de execução e artefato ou `metrics.json` ausente, o `outcome` SHALL ser `reprovado`. O revisor MUST NOT registrar o motivo `sem_hipotese`. Quando a hipótese da subtarefa tem `origem = "sistema"`, o revisor SHALL registrar o motivo `hipotese_do_sistema` em `motivos`, no resultado e no evento `subtask_review`, sem alterar `status` nem `outcome`.
(Antes: o revisor registrava `sem_hipotese` quando só faltava a hipótese para o resultado ser negativo.)

#### Scenario: Acurácia abaixo do alvo numa subtarefa com hipótese
- **GIVEN** a subtarefa `treinar_rl` com `hypothesis_id` resolvido, artefatos presentes e `metrics.json` com `accuracy` 0.933
- **WHEN** o revisor avalia "acurácia no teste >= 0.95"
- **THEN** `outcome` é `resultado_negativo`
- **AND** o evento `subtask_review` registra `outcome = "resultado_negativo"`

#### Scenario: Métrica ausente não é resultado negativo
- **GIVEN** a mesma subtarefa com `metrics.json` sem acurácia
- **WHEN** o revisor avalia o mesmo critério
- **THEN** `outcome` é `reprovado`

#### Scenario: Artefato ausente não é resultado negativo
- **GIVEN** a acurácia 0.933 e um artefato esperado `missing`
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado`

#### Scenario: Recurso desligado
- **GIVEN** `NEGATIVE_RESULT_AS_PROGRESS=false`
- **WHEN** o revisor avalia o primeiro cenário
- **THEN** `outcome` é `reprovado`

#### Scenario: Resultado negativo de hipótese do sistema
- **GIVEN** a subtarefa `treinar_rf` testando a hipótese do sistema `hs1`, artefatos presentes e `metrics.json` com `accuracy` 0.80
- **WHEN** o revisor avalia "acurácia no teste >= 0.9"
- **THEN** `outcome` é `resultado_negativo`
- **AND** `motivos` é `["hipotese_do_sistema"]`

#### Scenario: Hipótese do sistema com artefato ausente
- **GIVEN** a mesma subtarefa com `accuracy` 0.80 e o artefato esperado `modelo_rf.joblib` `missing`
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado`
- **AND** `motivos` é `["hipotese_do_sistema"]`

#### Scenario: Hipótese do sistema com critério qualitativo reprovado
- **GIVEN** a mesma subtarefa com `accuracy` 0.80, artefatos presentes e o critério "gráfico de importância gerado", e o provedor falso devolve `{"status": "fail"}` para esse critério
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado`

#### Scenario: Falha de execução não é resultado negativo
- **GIVEN** a subtarefa `treinar_rf` da hipótese do sistema `hs1` com `agent_status = "error"`
- **WHEN** a ingestão grava o `Experimento`
- **THEN** o `Experimento` tem `status = "falha"`
- **AND** nenhum `Resultado` dessa subtarefa tem `REFUTA->hs1`

#### Scenario: Preparação com limiar não atingido
- **GIVEN** a subtarefa `preprocessar_dados` com `papel_decidido = "preparacao"`, sem hipótese, e `metrics.json` com `proporcao_nulos` 0.1
- **WHEN** o revisor avalia "proporção de nulos <= 0"
- **THEN** `outcome` é `reprovado`
- **AND** `motivos` é vazio

## ADDED Requirements

### Requirement: Papel do experimento decidido por ordem fixa
_Origem: ADR 021 §2_
O sistema SHALL decidir o papel (`teste`, `preparacao`, `referencia`) de cada subtarefa não concluída nesta ordem: (1) `papel` declarado válido; (2) `hypothesis_ref` resolvido para hipótese aceita → `teste`; (3) `task_type` `eda` ou `synthesis` → `preparacao`; (4) sinal de teste → `teste`, mesmo com dependentes; (5) subtarefa com dependentes no plano → `preparacao`; (6) demais → `preparacao` ligada ao `Problema`. Sinal de teste SHALL ser um critério de validação com limiar numérico sobre a métrica principal M do Problema (nome ou sinônimo, sem qualificador ou com qualificador de teste) ou `approach.tipo = "algoritmo"`. O papel `referencia` MUST vir só da declaração. O sistema SHALL gravar o papel no `Experimento` da subtarefa.

#### Scenario: Pré-processamento é preparação
- **GIVEN** `preprocessar_dados` (`model_impl`, sem `hypothesis_ref`, sem `approach`, critério "proporção de nulos <= 0") com três subtarefas dependentes
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "preparacao"` e `papel_fonte = "estrutura_dag"`

#### Scenario: Teste que alimenta comparação continua teste
- **GIVEN** `treinar_rf` sem `hypothesis_ref`, com critério "accuracy >= 0.9" e a dependente `comparar_modelos`
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "teste"` e `papel_fonte = "sinal_de_teste"`

#### Scenario: Limiar sobre outra grandeza não é sinal de teste
- **GIVEN** `dividir_treino_teste` sem `hypothesis_ref`, `approach={"nome": "split estratificado", "tipo": "protocolo"}`, critério "proporção de teste >= 0.2" e sem dependentes
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "preparacao"` e `papel_fonte = "residual"`

#### Scenario: Limiar de validação cruzada não é sinal de teste
- **GIVEN** uma subtarefa sem `hypothesis_ref`, sem `approach` e com o critério "cv_accuracy >= 0.8"
- **WHEN** o papel é decidido
- **THEN** `papel_fonte` não é `sinal_de_teste`

#### Scenario: EDA com abordagem preenchida
- **GIVEN** `eda` com `task_type = "eda"` e `approach={"nome": "análise exploratória", "tipo": "algoritmo"}`, sem `papel`
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "preparacao"` e `papel_fonte = "task_type"`

#### Scenario: Papel gravado no experimento
- **GIVEN** `baseline_majoritario` declarado com `papel = "referencia"` e executado com sucesso
- **WHEN** a ingestão grava o `Experimento`
- **THEN** o `Experimento` tem `papel = "referencia"` e nenhuma aresta `TESTA`

### Requirement: Preparação ligada às hipóteses que serve
_Origem: ADR 021 §3.1_
Depois da validação do DAG, o sistema SHALL ligar o `Experimento` de cada `preparacao` por `PREPARA` a toda hipótese testada por subtarefa que dependa dela, direta ou transitivamente, ou ao `Problema` quando não houver nenhuma. Quando um teste de um ciclo posterior depende de uma preparação já concluída, o sistema SHALL acrescentar a aresta `PREPARA` ao `Experimento` existente. `prepare_cycle` MUST NOT rodar sobre um plano cujo DAG é inválido.

#### Scenario: Preparação de duas hipóteses
- **GIVEN** `preprocessar_dados` com dependentes `treinar_knn` (testa `h1`) e `treinar_rf` (testa `h2`), e `comparar_modelos` (testa `h3`) dependente de `treinar_knn`
- **WHEN** o ciclo executa e a ingestão grava `preprocessar_dados`
- **THEN** o `Experimento` de `preprocessar_dados` tem `PREPARA->h1`, `PREPARA->h2` e `PREPARA->h3`, com `origem = "derivado"`

#### Scenario: Preparação sem hipótese dependente
- **GIVEN** `eda` sem dependentes
- **WHEN** a ingestão grava `eda`
- **THEN** o `Experimento` de `eda` tem `PREPARA->Problema` e nenhuma `PREPARA->Hipotese`
- **AND** nenhum nó `Hipotese` é criado a partir do campo `hypothesis` da `eda`

#### Scenario: Ligação incremental
- **GIVEN** `preprocessar_dados` concluída no ciclo 1 com `PREPARA->h1`, e o plano do ciclo 2 com `treinar_svm` (testa `h4`) dependente de `preprocessar_dados`
- **WHEN** `prepare_cycle` do ciclo 2 roda
- **THEN** o `Experimento` existente de `preprocessar_dados` ganha `PREPARA->h4`
- **AND** nenhum `Experimento` novo é criado para `preprocessar_dados`

#### Scenario: DAG inválido não chega à governança
- **GIVEN** um plano em que `a` depende de `b` e `b` depende de `a`
- **WHEN** o laço processa o plano
- **THEN** `prepare_cycle` não é chamado e o feedback ao Researcher cita o grafo de dependências inválido

### Requirement: Referência do Problema registrada
_Origem: ADR 021 §2 e §3.2_
Na ingestão de um `Experimento` com `papel = "referencia"`, o sistema SHALL ligar cada `Resultado` com `MEDE->M` ao `Problema` por `REFERENCIA_DE`, SHALL registrar o evento `referencia_sem_metrica` quando não houver `Resultado` de M, e MUST NOT usar esse valor no veredito.

#### Scenario: Baseline declarado
- **GIVEN** `baseline_majoritario` com `papel = "referencia"` e `metrics.json` com `accuracy` 0.62 e `tempo_s` 0.3
- **WHEN** a ingestão termina
- **THEN** o `Resultado` `accuracy` tem `REFERENCIA_DE->Problema`
- **AND** o `Resultado` `tempo_s` não tem `REFERENCIA_DE`
- **AND** o veredito de todas as hipóteses do projeto é o mesmo de antes da ingestão

#### Scenario: Referência sem a métrica
- **GIVEN** `baseline_majoritario` com `papel = "referencia"` e `metrics.json` só com `f1_macro` 0.4
- **WHEN** a ingestão termina
- **THEN** o evento `referencia_sem_metrica` é registrado com `subtarefa = "baseline_majoritario"`

### Requirement: Hipótese do sistema para teste sem hipótese aceita
_Origem: ADR 021 §3.3, §3.4 e §4.1_
Para uma subtarefa `teste` sem `hypothesis_ref`, com `hypothesis_ref` recusado por `id_inexistente` ou `sem_enunciado`, ou declarada `papel: "teste"` sem `hypothesis_ref`, o sistema SHALL usar uma `Hipotese` `origem = "sistema"` com `SOBRE->Problema` e `PROPOE->Abordagem`, enunciado no formato "a abordagem A melhora a métrica M do Problema P em relação à referência R", chave `(problema, abordagem canônica, métrica)` e referência R fixada na criação (resultado medido de `referencia` do Problema; senão o baseline numérico do critério; senão `indisponivel`). O sistema SHALL reutilizar a hipótese que já tem a mesma chave, SHALL registrar o evento `hipotese_derivada` com a subtarefa e o motivo, e MUST NOT retirar a subtarefa.

#### Scenario: Teste sem hipótese declarada
- **GIVEN** `treinar_rf` sem `hypothesis_ref`, `approach={"nome": "random forest", "tipo": "algoritmo"}` e um `Resultado` `accuracy` 0.62 com `REFERENCIA_DE->Problema`
- **WHEN** `prepare_cycle` roda
- **THEN** existe uma `Hipotese` com `origem = "sistema"`, `SOBRE->P`, `PROPOE->` a abordagem `random forest`, `chave_estruturada = "<P.id>|<abordagem.id>|<acuracia.id>"` e `referencia_fixada.valor = 0.62` com `origem_referencia = "referencia_medida"`
- **AND** `treinar_rf.hypothesis_id` é o `id` dessa hipótese
- **AND** o evento `hipotese_derivada` tem `subtarefa = "treinar_rf"` e `motivo = "sem_hypothesis_ref"`

#### Scenario: Referência fixada não muda
- **GIVEN** a hipótese do sistema do cenário anterior e, depois, um novo `Resultado` `accuracy` 0.70 com `REFERENCIA_DE->Problema`
- **WHEN** um plano posterior traz `treinar_rf` de novo sem `hypothesis_ref`
- **THEN** a mesma hipótese é reutilizada com `referencia_fixada.valor = 0.62`

#### Scenario: Sem referência medida
- **GIVEN** nenhum `Resultado` com `REFERENCIA_DE->Problema` e o critério do Problema sem baseline numérico
- **WHEN** a hipótese do sistema é criada
- **THEN** `referencia_fixada` tem `valor = null` e `origem_referencia = "indisponivel"`

#### Scenario: Referência inexistente no plano
- **GIVEN** `treinar_knn` com `hypothesis_ref = "h9"`, sem `h9` declarada no plano nem no grafo, e critério "accuracy >= 0.9"
- **WHEN** `prepare_cycle` roda
- **THEN** `treinar_knn` não está em `CycleOutcome.dropped`
- **AND** o evento `hipotese_derivada` tem `motivo = "ref_id_inexistente"`

#### Scenario: Variação reutiliza a hipótese
- **GIVEN** a hipótese do sistema de `random forest` e um plano posterior com `treinar_rf_200_arvores` sem `hypothesis_ref`, a mesma abordagem e `parameters = {"n_estimators": 200}`
- **WHEN** o ciclo executa
- **THEN** nenhuma hipótese nova é criada
- **AND** o novo `Experimento` tem `TESTA->` a mesma hipótese e `APLICOU {config: {"n_estimators": 200}}->` a abordagem

#### Scenario: Abordagens diferentes não se fundem
- **GIVEN** dois testes sem `hypothesis_ref` no mesmo plano, com abordagens `random forest` e `gradient boosting`
- **WHEN** `prepare_cycle` roda
- **THEN** existem duas hipóteses do sistema com chaves diferentes

#### Scenario: Texto livre afirmativo vira enunciado
- **GIVEN** `treinar_svm` sem `hypothesis_ref`, `approach={"nome": "svm", "tipo": "algoritmo"}` e `hypothesis = "SVM com kernel RBF supera a referência em acurácia"`
- **WHEN** a hipótese do sistema é criada
- **THEN** o `enunciado` é "SVM com kernel RBF supera a referência em acurácia"

#### Scenario: Texto livre negativo não vira enunciado
- **GIVEN** a mesma subtarefa com `hypothesis = "Não se testa hipótese; produz o modelo"`
- **WHEN** a hipótese do sistema é criada
- **THEN** o `enunciado` segue o formato fixo e contém "svm" e "acuracia" ou "acurácia"

### Requirement: Ciclo de vida da hipótese do sistema
_Origem: ADR 021 §3.5_
Uma hipótese do sistema sem tentativa SHALL ir a `abandonada` com `abandonada_por = "sistema"` e `motivo_abandono` quando todas as suas subtarefas de origem forem retiradas pela governança (exceto por `hipotese_aguarda_aprovacao` e, enquanto `v18.7-exploration-limits` não o remove, `hipotese_adiada_por_prioridade`), saírem da fila num replanejamento ou esgotarem as retentativas sem execução. Quando um plano posterior trouxer a mesma chave, o sistema SHALL reabri-la, preservando o histórico: em `em_teste` no `semi` e no `auto`; no `assisted`, em `em_teste` só quando `ApprovalPort.previously_approved` (interface comum de `v18.7-persistent-human-gate`) confirmar no gate persistente um pedido `aprovar_hipotese` daquele id autorizado por humano, e em `proposta` em qualquer outro caso. A trilha de auditoria do grafo MUST NOT servir de prova de aprovação. Hipótese abandonada pelo pesquisador MUST NOT ser reaberta pelo sistema.

#### Scenario: Retentativas esgotadas sem execução
- **GIVEN** a hipótese do sistema `hs1` com `n_tentativas = 0` e a única subtarefa de origem `treinar_rf` marcada `abandonada` no DAG por retentativas esgotadas
- **WHEN** o ciclo termina
- **THEN** `hs1` tem `status = "abandonada"`, `abandonada_por = "sistema"` e `motivo_abandono = "tentativas_esgotadas_sem_execucao"`
- **AND** `hs1` não aparece em `untested_hypotheses()`

#### Scenario: Reabertura pela chave
- **GIVEN** `hs1` abandonada pelo sistema, modo `auto`
- **WHEN** um plano posterior traz um teste sem `hypothesis_ref` com a mesma abordagem
- **THEN** `hs1` volta a `em_teste`, sem `abandonada_por`
- **AND** o evento `hipotese_derivada` tem `reaberta = true`

#### Scenario: Reabertura no assistido com aprovação no gate
- **GIVEN** modo `assisted`, `hs1` abandonada pelo sistema e um `FakeGate` com pedido `aprovar_hipotese` de `hs1.id`, `estado = "autorizada"` e `resolvido_por = "terminal"`
- **WHEN** um plano posterior traz um teste que deriva a chave de `hs1`
- **THEN** `hs1` volta a `em_teste`

#### Scenario: Reabertura no assistido sem aprovação no gate
- **GIVEN** modo `assisted`, `hs1` abandonada pelo sistema, uma nota de auditoria no grafo com `decisao = "aprovada"` para `hs1` e nenhum pedido `aprovar_hipotese` autorizado de `hs1.id` no gate
- **WHEN** um plano posterior traz um teste que deriva a chave de `hs1`
- **THEN** `hs1` volta a `proposta` e o teste é retirado com `hipotese_aguarda_aprovacao`

#### Scenario: Interface provisória antes do gate
- **GIVEN** modo `assisted`, a implementação provisória `NoGateApprovalPort` e `hs1` aprovada num ciclo anterior pelo `Approver` injetado
- **WHEN** `hs1` é reaberta pela chave
- **THEN** `previously_approved` devolve `False` e `hs1` volta a `proposta`

#### Scenario: Aguardar aprovação não abandona
- **GIVEN** modo `assisted`, a hipótese do sistema `hs2` pendente e a subtarefa retirada com `hipotese_aguarda_aprovacao`
- **WHEN** `prepare_cycle` termina
- **THEN** `hs2` continua `proposta`

#### Scenario: Abandono do pesquisador não reabre
- **GIVEN** uma hipótese do sistema com a chave `K` abandonada pelo pesquisador
- **WHEN** um plano posterior traz um teste que deriva a chave `K`
- **THEN** a subtarefa é retirada com `hipotese_equivalente_a_hipotese_abandonada`
- **AND** a hipótese continua `abandonada`

#### Scenario: Hipótese do sistema com tentativa não é abandonada
- **GIVEN** `hs1` com `n_tentativas = 2` e um replanejamento que remove da fila sua única subtarefa pendente
- **WHEN** `prepare_cycle` roda
- **THEN** `hs1` não muda de status

### Requirement: Aprovação da hipótese do sistema por modo
_Origem: ADR 021 §3.6_
No modo `assisted`, a hipótese do sistema SHALL aguardar a aprovação do pesquisador como as hipóteses de agentes, pedida e conferida pela interface comum `ApprovalPort` (`src/human_approval.py`) de `v18.7-persistent-human-gate`: com `PersistentGateApprover`, um pedido `aprovar_hipotese` por hipótese no gate persistente, e MUST NOT usar o `terminal_approver`. Se esta mudança for mergeada antes daquela, SHALL criar `src/human_approval.py` com o mesmo `Protocol` e usar a implementação provisória `NoGateApprovalPort` (envolve o `Approver` injetado; sem TTY, o item fica pendente). Nos modos `semi` e `auto`, SHALL seguir com a aprovação do plano pelo Validator, sem pedido ao pesquisador.

#### Scenario: Assistido
- **GIVEN** modo `assisted`, uma `ApprovalPort` que não responde e a hipótese do sistema `hs1` derivada no ciclo
- **WHEN** o ciclo chega à execução
- **THEN** o teste de `hs1` é retirado com `hipotese_aguarda_aprovacao`
- **AND** o item apresentado à `ApprovalPort` tem `origem = "sistema"`

#### Scenario: Aprovação pelo gate persistente
- **GIVEN** modo `assisted`, `PersistentGateApprover` sobre um `FakeGate` e a hipótese do sistema `hs1` derivada no ciclo
- **WHEN** o ciclo chega à execução
- **THEN** existe um pedido `aprovar_hipotese` com `referencia = hs1.id`, o `terminal_approver` não é chamado e o teste de `hs1` é retirado com `hipotese_aguarda_aprovacao`
- **AND** depois que o terminal responde `aprovar` e o pedido é consumido por `consume_authorized`, o teste de `hs1` entra em `CycleOutcome.tasks` no ciclo seguinte

#### Scenario: Automático
- **GIVEN** modo `auto` e a hipótese do sistema `hs1` derivada no ciclo
- **WHEN** o ciclo chega à execução
- **THEN** `hs1` está em `selection.execute` e tem `status = "em_teste"`
- **AND** o `Approver` não é chamado

### Requirement: Hipótese derivada de outra hipótese
_Origem: ADR 021 §4.2_
O sistema SHALL aceitar em `derivada_de` de uma hipótese declarada o `id` de uma `Hipotese` do projeto ou o `ref` de outra hipótese declarada antes no mesmo plano, e SHALL gravar `DERIVADA_DE` entre as duas. IDs inexistentes ou de outro projeto MUST ser ignorados.

#### Scenario: Refinamento
- **GIVEN** a hipótese do sistema `hs1` (kNN) no projeto
- **WHEN** o plano declara `h2` "padronizar os atributos melhora o kNN" com `derivada_de = ["<hs1.id>"]`
- **THEN** existe `h2-DERIVADA_DE->hs1`

#### Scenario: ID de outro projeto
- **WHEN** o plano declara `h3` com `derivada_de = ["<id de Hipotese de outro projeto>"]`
- **THEN** `h3` é criada sem aresta `DERIVADA_DE` para esse nó

### Requirement: Hipótese concluída recebe novos testes
_Origem: ADR 021 §4.3_
A governança SHALL deixar executar testes de hipóteses `validada` e `refutada`, sem mudar o status no meio do ciclo. Só MUST NOT executar testes de hipótese abandonada ou rejeitada pelo pesquisador (`abandonada_por = "pesquisador"`); a abandonada pelo agente não bloqueia e volta como `proposta` pela governança do modo (decisão do pesquisador, 2026-10-15).

#### Scenario: Replicação de hipótese validada
- **GIVEN** `h1` `validada` e um plano com `treinar_knn_seed2` (`hypothesis_ref = "<h1.id>"`)
- **WHEN** `prepare_cycle` roda
- **THEN** `treinar_knn_seed2` está em `CycleOutcome.tasks`
- **AND** `h1` continua `validada` até o fim do ciclo

#### Scenario: Hipótese abandonada pelo pesquisador
- **GIVEN** `h5` `abandonada` com `abandonada_por = "pesquisador"` e um plano com `hypothesis_ref = "<h5.id>"`
- **WHEN** `prepare_cycle` roda
- **THEN** a subtarefa é retirada com `hipotese_hipotese_abandonada`

#### Scenario: Hipótese abandonada pelo agente
- **GIVEN** `h6` `abandonada` com `abandonada_por = "agente"` (alternativa descartada pelo Researcher), modo `assisted` e um plano com `hypothesis_ref = "<h6.id>"`
- **WHEN** `prepare_cycle` roda
- **THEN** `h6` volta a `proposta` e a subtarefa é retirada com `hipotese_aguarda_aprovacao`
- **AND** a retirada não grava `abandonada_por = "pesquisador"`

### Requirement: Transições de status nos dois sentidos ao fim do ciclo
_Origem: ADR 021 §4.4_
Ao fim de cada ciclo, e nunca no meio dele, o sistema SHALL aplicar a todas as hipóteses não abandonadas a regra do veredito com `DECISION_EVAL_MIN_VERDICT`: `>= limiar` → `validada`; `<= -limiar` → `refutada`; uma hipótese concluída com veredito entre os dois SHALL voltar a `em_teste`. Cada transição SHALL ser registrada com o status e o veredito anteriores e novos. Quando uma hipótese concluída reabre, a `Oportunidade` ligada por `GEROU` SHALL voltar de `concluida` a `em_investigacao`; quando reabre ou muda de lado, as decisões com `ESCOLHEU->` ela SHALL ser reavaliadas e as arestas `FUNCIONOU_PARA`/`FALHOU_PARA` de descobertas `SOBRE->` ela SHALL passar a `status = "contestada"`.

#### Scenario: Replicação que contesta a validação
- **GIVEN** `DECISION_EVAL_MIN_VERDICT=0.3`, `h1` `validada` e, depois de uma replicação no ciclo, veredito 0.12
- **WHEN** o ciclo termina
- **THEN** `h1` volta a `em_teste`
- **AND** o evento `hipotese_transicao` tem `status_anterior = "validada"`, `status_novo = "em_teste"` e `veredito_novo = 0.12`

#### Scenario: Mudança de lado
- **GIVEN** `DECISION_EVAL_MIN_VERDICT=0.3`, `h1` `validada` e veredito −0.35 ao fim do ciclo (`<= -0.3`)
- **WHEN** o ciclo termina
- **THEN** `h1` fica `refutada`
- **AND** a decisão com `ESCOLHEU->h1` e `resultado_posterior = "acertada"` passa a `nao_acertada`

#### Scenario: Oportunidade reaberta
- **GIVEN** `DECISION_EVAL_MIN_VERDICT=0.3`, `Oportunidade` `concluida` com `GEROU->h1`, `h1` `validada`, e veredito 0.1 ao fim do ciclo (entre −0.3 e 0.3)
- **WHEN** o ciclo termina
- **THEN** a oportunidade fica `em_investigacao`
- **AND** a decisão com `ESCOLHEU->h1` fica com `resultado_posterior` vazio

#### Scenario: Atalho contestado pela reabertura
- **GIVEN** `Abordagem-FUNCIONOU_PARA {descoberta_id: d1}->Problema`, `d1` com `SOBRE->h1`, e `h1` reaberta no fim do ciclo
- **WHEN** os efeitos são revistos
- **THEN** a aresta `FUNCIONOU_PARA` tem `status = "contestada"`

#### Scenario: Nada muda no meio do ciclo
- **GIVEN** `h1` `validada` e o veredito recalculado para 0.1 depois da primeira subtarefa do ciclo
- **WHEN** a segunda subtarefa do mesmo ciclo é despachada
- **THEN** `h1` continua `validada`

### Requirement: Só decisão humana ou integridade impede a execução
_Origem: ADR 021 §1 e §6_
A governança SHALL retirar subtarefas somente pelos motivos `hipotese_rejeitada_pelo_pesquisador`, `hipotese_aguarda_aprovacao`, `hipotese_abandonada_pelo_pesquisador`, `hipotese_hipotese_abandonada`, `hipotese_equivalente_a_hipotese_abandonada`, `hipotese_oportunidade_nao_aprovada`, `hipotese_direcao_restrita` (quando definido), `hipotese_adiada_por_prioridade` (enquanto existir) e `depende_de_subtarefa_retirada`. Uma preparação SHALL ser retirada só quando todas as hipóteses que serve foram retiradas; preparação ligada só ao `Problema` MUST NOT ser retirada por motivo de hipótese. O sistema MUST NOT produzir `sem_hipotese`, `hipotese_id_inexistente`, `hipotese_sem_enunciado` nem `hipotese_ja_concluida_ou_abandonada`.

#### Scenario: Rejeição parcial não derruba a preparação compartilhada
- **GIVEN** modo `assisted`, `preprocessar_dados` servindo `h1` e `h2`, e o `Approver` rejeita `h1` e aprova `h2`
- **WHEN** `prepare_cycle` roda
- **THEN** `treinar_h1` é retirada com `hipotese_rejeitada_pelo_pesquisador`
- **AND** `preprocessar_dados` e `treinar_h2` ficam em `CycleOutcome.tasks`

#### Scenario: Preparação que só servia a hipótese rejeitada
- **GIVEN** `limpar_textos` servindo só `h1`, e o `Approver` rejeita `h1`
- **WHEN** `prepare_cycle` roda
- **THEN** `limpar_textos` é retirada com `hipotese_rejeitada_pelo_pesquisador`

#### Scenario: Teste que depende de teste retirado
- **GIVEN** `comparar` (testa `h3`, aprovada) dependente de `treinar_h1`, e `h1` rejeitada
- **WHEN** `prepare_cycle` roda
- **THEN** `comparar` é retirada com `depende_de_subtarefa_retirada`

#### Scenario: Motivos removidos
- **GIVEN** qualquer plano das cenas desta spec
- **WHEN** `prepare_cycle` roda
- **THEN** nenhum valor de `CycleOutcome.dropped` é `sem_hipotese`, `hipotese_id_inexistente`, `hipotese_sem_enunciado` ou `hipotese_ja_concluida_ou_abandonada`

### Requirement: Replanejamento substitui a fila
_Origem: ADR 021 §5.8_
Quando o Researcher replaneja, o plano novo SHALL substituir a fila: toda subtarefa do plano anterior não concluída e não retirada que esteja ausente do plano novo SHALL ser registrada com `removida_pelo_replanejamento` no evento `hypothesis_cycle`, fora de `retiradas_por_motivo`.

#### Scenario: Item removido da fila
- **GIVEN** modo `assisted`, o ciclo 1 com `treinar_svm` fora da execução por `hipotese_aguarda_aprovacao` (sua hipótese segue pendente, a subtarefa continua na fila), e o plano do ciclo 2 sem `treinar_svm`
- **WHEN** `prepare_cycle` do ciclo 2 roda
- **THEN** `removidas_pelo_replanejamento` contém `treinar_svm`
- **AND** `retiradas_por_motivo` não contém `removida_pelo_replanejamento`

#### Scenario: Hipótese do sistema da subtarefa removida
- **GIVEN** `treinar_svm` era a única origem da hipótese do sistema `hs3`, sem tentativa
- **WHEN** o ciclo 2 a remove da fila
- **THEN** `hs3` fica `abandonada` com `abandonada_por = "sistema"` e `motivo_abandono = "removida_pelo_replanejamento"`

### Requirement: Retiradas e ligações voltam ao Researcher
_Origem: ADR 021 §7_
O sistema SHALL entregar ao Researcher, no replanejamento seguinte e como dado delimitado (`<dado_nao_confiavel origem="ligacoes_e_retiradas_do_ciclo_anterior">`), até `LINKAGE_FEEDBACK_MAX_ITEMS` itens com a subtarefa, o papel, o motivo e o que o sistema fez, retiradas primeiro.

#### Scenario: Retorno do ciclo
- **GIVEN** o ciclo do cenário "Plano em passos finos executa", em que `treinar_rf` derivou a hipótese do sistema `hs1`
- **WHEN** o prompt do próximo plano é montado
- **THEN** o bloco `ligacoes_e_retiradas_do_ciclo_anterior` contém "preprocessar_dados", "preparação de", "treinar_rf" e o `id` de `hs1`
- **AND** contém "baseline_majoritario" com "referência do Problema"

#### Scenario: Baseline não declarado
- **GIVEN** `baseline_dummy` sem `papel`, sem `hypothesis_ref`, com critério "accuracy >= 0.3"
- **WHEN** o prompt do próximo plano é montado
- **THEN** o item de `baseline_dummy` sugere declarar `papel: referencia`

#### Scenario: Limite de itens
- **GIVEN** `LINKAGE_FEEDBACK_MAX_ITEMS=3`, duas retiradas e cinco ligações no ciclo
- **WHEN** o bloco é montado
- **THEN** o bloco tem 3 itens e as duas retiradas estão entre eles

### Requirement: Dados de ligação por ciclo
_Origem: ADR 021 §3.3 e §8.4_
O evento `hypothesis_cycle` SHALL trazer, além dos campos atuais, `papeis`, `papel_fonte`, `testes_por_origem`, `ligacoes_prepara`, `hipoteses_sistema_criadas`, `hipoteses_sistema_reutilizadas`, `hipoteses_sistema_reabertas`, `hipoteses_sistema_abandonadas` e `removidas_pelo_replanejamento`, só com contagens, IDs, códigos e nomes de subtarefa.

#### Scenario: Contagens do ciclo
- **GIVEN** o cenário "Plano em passos finos executa", com `h1` de `origem = "researcher"`
- **WHEN** o evento `hypothesis_cycle` é emitido
- **THEN** `papeis = {"teste": 2, "preparacao": 2, "referencia": 1}`
- **AND** `testes_por_origem` tem `researcher = 1` e `sistema = 1`
- **AND** `hipoteses_sistema_criadas = 1`
- **AND** o payload não contém o texto de nenhum enunciado

### Requirement: Hipóteses do sistema visíveis ao Curator e ao Researcher
_Origem: ADR 021 §3.7_
O contexto de hipóteses entregue ao Researcher e ao Curator SHALL identificar as hipóteses com `origem = "sistema"`, e o sistema MUST NOT fundir hipóteses por ação do Curator.

#### Scenario: Hipótese do sistema no contexto
- **GIVEN** a hipótese do sistema `hs1` `em_teste`
- **WHEN** `open_hypotheses_view()` é chamado
- **THEN** o item de `hs1` tem `origem = "sistema"`

### Requirement: Reversão de Oportunidade fora do alcance dos agentes
_Origem: ADR 021 §4.4; parecer de segurança, item 3_
A transição `concluida -> em_investigacao` de `Oportunidade` pelo orquestrador SHALL ser aceita pela validação do grafo só com a flag `revert_on_reopen`, passada exclusivamente pela revisão dos efeitos de `sync_statuses` ao fim do ciclo. Nenhuma ferramenta de agente (inclusive as do Curator), nenhum campo do plano e nenhuma saída de LLM MUST chegar a esse caminho, e a mesma transição sem a flag, ou por um `Actor` de agente, MUST ser recusada.

#### Scenario: Curator tenta reverter a oportunidade
- **GIVEN** uma `Oportunidade` `concluida`
- **WHEN** o `Actor` agente `Curator` atualiza `status` para `em_investigacao` por uma ferramenta de agente
- **THEN** a escrita é recusada e a oportunidade continua `concluida`

#### Scenario: Orquestrador sem a flag
- **GIVEN** uma `Oportunidade` `concluida`
- **WHEN** o `Actor` orquestrador atualiza `status` para `em_investigacao` sem `revert_on_reopen`
- **THEN** a escrita é recusada

#### Scenario: Plano com campo de reversão
- **GIVEN** um plano cujo JSON traz `"revert_on_reopen": true` numa subtarefa ou no envelope
- **WHEN** o plano é processado e o ciclo termina sem hipótese reaberta
- **THEN** nenhuma `Oportunidade` muda de status e o campo é descartado

### Requirement: Fonte do enunciado da hipótese do sistema registrada
_Origem: ADR 021 §8.3; parecer de segurança, item 4_
Quando o enunciado de uma hipótese do sistema vier do campo livre `hypothesis` da subtarefa (texto de LLM), o sistema SHALL registrar `enunciado_fonte = "texto_livre"` na nota de auditoria da criação e no evento `hipotese_derivada`, e SHALL registrar `enunciado_fonte = "modelo"` quando usar o formato fixo. No modo `assisted`, o item de aprovação SHALL mostrar a fonte ao pesquisador.

#### Scenario: Enunciado vindo do texto livre
- **GIVEN** a subtarefa `teste` `treinar_rf` sem `hypothesis_ref` e com `hypothesis = "random forest melhora a acuracia"`, sendo `acuracia` a métrica M
- **WHEN** `prepare_cycle` cria a hipótese do sistema
- **THEN** a nota de auditoria e o evento `hipotese_derivada` têm `enunciado_fonte = "texto_livre"`

#### Scenario: Fonte mostrada no assistido
- **GIVEN** modo `assisted` e a mesma hipótese
- **WHEN** o item é apresentado à `ApprovalPort`
- **THEN** o item traz `origem = "sistema"` e `enunciado_fonte = "texto_livre"`
