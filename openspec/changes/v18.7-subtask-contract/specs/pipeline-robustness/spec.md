# Delta: pipeline-robustness

Os cenários com revisor LLM usam o `FakeRecordingProvider` (ajuda compartilhada de `v18.7-benchmark-fixes`), provedor falso que grava `messages` e `system` e devolve o parecer roteirizado; nenhum depende de provedor pago.

## ADDED Requirements

### Requirement: Revisão separa critérios de aceite e regras de integridade
A revisão de subtarefa SHALL receber o contrato completo da tentativa (itens 1 a 9), as regras de integridade com ids (`metricas_calculadas`, `sem_ajuste_no_teste`, `seed_registrada`, `divergencia_honesta`, `afirmacoes_verificaveis`, `egresso`) e a evidência em disco (ADR 022 §3). Um problema de aceite SHALL reprovar só se citar o id de um critério do contrato enviado; um problema de integridade SHALL reprovar só se citar o id de uma regra da lista. Qualquer outro problema MUST ir para `observacoes` e MUST NOT reprovar. O `ReviewResult` SHALL guardar o `contract_sha256` do contrato usado.

#### Scenario: Critério fraco vira observação
- **GIVEN** um contrato com os critérios `c1` e `c2` e um parecer roteirizado `{"status": "fail", "issues": [{"tipo": "aceite", "item": "c7", "texto": "o critério deveria exigir validação cruzada"}], "observacoes": []}`
- **WHEN** a subtarefa é revisada
- **THEN** o resultado é `pass`
- **AND** `observacoes` contém "o critério deveria exigir validação cruzada"

#### Scenario: Integridade reprova sempre
- **GIVEN** todos os critérios atendidos e o parecer roteirizado `{"status": "fail", "issues": [{"tipo": "integridade", "regra": "sem_ajuste_no_teste", "texto": "hiperparâmetros escolhidos pela acurácia no teste"}]}`
- **WHEN** a subtarefa é revisada
- **THEN** o resultado é `fail` com esse problema em `issues`

#### Scenario: Formato antigo do parecer
- **GIVEN** o parecer roteirizado `{"status": "fail", "issues": ["matriz de confusão salva: arquivo vazio", "faltou discutir limitações"]}` e o critério `c2` "matriz de confusão salva"
- **WHEN** a subtarefa é revisada
- **THEN** o resultado é `fail` com o primeiro problema como aceite de `c2`
- **AND** o segundo vai para `observacoes` com o registro `issue_sem_tipo`

#### Scenario: Hash do contrato no parecer
- **WHEN** uma tentativa é revisada
- **THEN** `ReviewResult.contract_sha256` é igual a `SubtaskContract.sha256()` da tentativa e o evento `subtask_review` tem o mesmo valor em `contrato_sha256`

### Requirement: Integridade revisada mesmo com métricas aprovadas
Com `REVIEW_INTEGRITY_ALWAYS=true` (padrão, `src/config.py`), o sistema SHALL chamar a revisão LLM de integridade para toda subtarefa do Developer concluída com sucesso, inclusive quando todos os critérios foram decididos pelas métricas, enviando o script executado da subtarefa como trecho de origem `codigo` cortado em `REVIEW_SCRIPT_MAX_CHARS` (padrão 6000). Uma métrica do item 7 apontada como literal por `read_literal_findings` SHALL reprovar por `metricas_calculadas` sem chamada ao LLM.

#### Scenario: Só critérios de métrica, aprovados
- **GIVEN** o critério único "acurácia no teste >= 0.90", `metrics.json` com `acuracia` 0.93 e `REVIEW_INTEGRITY_ALWAYS=true`
- **WHEN** a subtarefa é revisada
- **THEN** o provedor falso recebe uma chamada cuja mensagem contém o script da subtarefa e as regras de integridade

#### Scenario: Integridade desligada
- **GIVEN** a mesma situação com `REVIEW_INTEGRITY_ALWAYS=false`
- **WHEN** a subtarefa é revisada
- **THEN** o resultado é `pass` sem nenhuma chamada ao provedor

#### Scenario: Métrica literal
- **GIVEN** `metricas_literais.json` da sessão aponta `acuracia` de `treinar_modelo_a` como literal
- **WHEN** a subtarefa é revisada
- **THEN** o resultado é `fail` com `{"tipo": "integridade", "regra": "metricas_calculadas"}` e o provedor falso não é chamado

### Requirement: Chaves de métrica exigidas e critério ambíguo
A revisão SHALL avaliar o critério com limiar sobre a métrica `m` pela chave sem qualificador `m` quando ela existe; pela chave qualificada que o critério citar; pela única chave qualificada `g.m` quando só existe uma. Com duas ou mais chaves `g.m`, sem `m` e sem chave citada, o sistema SHALL registrar `criterio_ambiguo` (ADR 022 §2.7): o resultado MUST NOT contar como evidência, a subtarefa MUST NOT ser retentada na mesma volta, a tentativa SHALL ser devolvida ao contador de tentativas e o caso SHALL voltar ao Researcher como observação. O Validator MUST NOT escolher entre chaves qualificadas.

#### Scenario: Chave sem qualificador presente
- **GIVEN** `metrics.json` com `acuracia` 0.91, `modelo_a.acuracia` 0.91 e `modelo_b.acuracia` 0.95
- **WHEN** o critério "acurácia no teste >= 0.90" é avaliado
- **THEN** o critério é atendido com valor real 0.91, sem chamada ao LLM para ele

#### Scenario: Ambiguidade
- **GIVEN** `metrics.json` só com `modelo_a.acuracia` 0.91 e `modelo_b.acuracia` 0.95, e o critério "acurácia no teste >= 0.90"
- **WHEN** a subtarefa é revisada
- **THEN** `outcome` é `criterio_ambiguo` e o evento `subtask_review` lista `modelo_a.acuracia` e `modelo_b.acuracia`
- **AND** o contador de tentativas de `treinar_modelo_a` volta ao valor de antes da tentativa
- **AND** o `feedback` do replanejamento seguinte contém "critério c1 de `treinar_modelo_a` é ambíguo"
- **AND** o checkpoint da subtarefa é `falhou` com `causa_falha = "ambigua"`

#### Scenario: Critério cita a chave qualificada
- **GIVEN** o mesmo `metrics.json` e o critério "modelo_b.acuracia >= 0.93"
- **WHEN** o critério é avaliado
- **THEN** ele é atendido com valor real 0.95

### Requirement: Devolução da tentativa uma vez por subtarefa
A devolução da tentativa por `criterio_ambiguo` SHALL acontecer no máximo uma vez por `task_name` em cada sessão (design §8.1, parecer de segurança item 4). A partir da segunda ocorrência de `criterio_ambiguo` da mesma subtarefa na sessão, a tentativa MUST ser consumida normalmente e o evento `subtask_review` SHALL registrar `devolucao_recusada = true`; o desfecho continua `criterio_ambiguo` e a observação continua indo ao Researcher.

#### Scenario: Ambiguidade repetida
- **GIVEN** `treinar_modelo_a` já teve uma tentativa devolvida por `criterio_ambiguo` na sessão e o replanejamento devolve o mesmo critério ambíguo
- **WHEN** a nova tentativa é revisada com o mesmo `metrics.json` só com `modelo_a.acuracia` e `modelo_b.acuracia`
- **THEN** `outcome` é `criterio_ambiguo` e o contador de tentativas de `treinar_modelo_a` fica uma unidade acima do valor de antes da tentativa
- **AND** o evento `subtask_review` dessa revisão tem `devolucao_recusada = true`

### Requirement: Colisão de artefatos entre subtarefas
A validação do plano SHALL apontar como problema corrigível `colisao_artefato` o mesmo nome de arquivo em `expected_artifacts` de duas subtarefas sem dependência direta ou transitiva entre elas, citando o nome e as duas subtarefas, e SHALL emitir o aviso `artefato_atualizado`, sem reprovar, quando uma depende da outra (ADR 022 §8). `metrics.json` e `params.json` MUST ficar fora da regra. A verificação SHALL ser desligável por `PLAN_ARTIFACT_COLLISION_CHECK` (padrão `true`).

#### Scenario: Colisão real
- **GIVEN** `treinar_modelo_a` e `treinar_modelo_b`, ambas com `results.csv` e sem dependência entre si
- **WHEN** o plano é validado
- **THEN** o resultado é `revision_needed` com o problema `colisao_artefato: results.csv em treinar_modelo_a, treinar_modelo_b`, sem chamada ao LLM

#### Scenario: Atualização intencional
- **GIVEN** `comparar_modelos` depende de `treinar_modelo_a` e as duas têm `results.csv`
- **WHEN** o plano é validado
- **THEN** não há `colisao_artefato` e `warnings` contém `artefato_atualizado`

### Requirement: Teto dos campos do contrato e nomes de artefato
A validação do plano SHALL apontar como problema corrigível `campo_do_contrato_longo: <task_name>.<campo>` todo item 2, 3, 4 ou 8 que, renderizado, passe de `CONTRACT_FIELD_MAX_CHARS` (padrão 1500); esses itens MUST NOT ser cortados (ADR 022 §6.2). O normalizador do plano SHALL apontar `nome_de_artefato_invalido` para item de `expected_artifacts` que não case com `^[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,127}$`, contenha `..` ou comece por barra.

#### Scenario: Critérios longos demais
- **GIVEN** uma subtarefa com critérios que somam 1600 caracteres e `CONTRACT_FIELD_MAX_CHARS=1500`
- **WHEN** o plano é validado
- **THEN** o resultado é `revision_needed` com `campo_do_contrato_longo: <task_name>.validation_criteria`

#### Scenario: Nome de artefato com caminho relativo
- **WHEN** o plano tem `expected_artifacts: ["../fora.csv"]`
- **THEN** o normalizador aponta `nome_de_artefato_invalido` para `../fora.csv`

### Requirement: Campo longo do contrato nunca é despachado
Antes de montar o contrato de cada tentativa, o sistema SHALL conferir de novo o teto `CONTRACT_FIELD_MAX_CHARS` nos itens 2, 3, 4 e 8, inclusive quando o plano foi aceito com avisos por `PLAN_REJECTION_STALL_LIMIT` (design §8.1, parecer de segurança item 3). Subtarefa com campo acima do teto SHALL ser retirada com o motivo `campo_do_contrato_longo`, contado em `retiradas_por_motivo` do evento `hypothesis_cycle`, e MUST NOT ser despachada; o campo MUST NOT ser cortado nem enviado a provedor.

#### Scenario: Plano aceito com avisos e campo longo
- **GIVEN** um plano aceito com avisos depois de `PLAN_REJECTION_STALL_LIMIT` rejeições, em que `treinar_modelo_a` tem critérios que somam 1600 caracteres, e `CONTRACT_FIELD_MAX_CHARS=1500`
- **WHEN** o ciclo despacha as subtarefas com o `FakeRecordingProvider`
- **THEN** nenhuma chamada gravada pelo provedor contém o texto dos critérios de `treinar_modelo_a`
- **AND** o evento `hypothesis_cycle` tem `campo_do_contrato_longo` em `retiradas_por_motivo` com `treinar_modelo_a`

### Requirement: Observações do revisor ao Researcher
As `observacoes` das revisões de um ciclo e os casos `criterio_ambiguo` SHALL entrar no `feedback` do replanejamento seguinte como dado delimitado, com o `task_name` de origem, até `REVIEW_OBSERVATIONS_MAX` (padrão 10) por ciclo, sem repetir texto igual.

#### Scenario: Observação no replanejamento
- **GIVEN** a revisão de `treinar_modelo_a` com a observação "o critério deveria exigir validação cruzada"
- **WHEN** o Researcher replaneja
- **THEN** o prompt do Researcher contém `treinar_modelo_a: o critério deveria exigir validação cruzada` dentro do bloco "RESULTADO DO CICLO ANTERIOR"

## MODIFIED Requirements

### Requirement: Critérios com várias comparações e métricas em vários grupos
_Origem: [`v18.6-review-evidence`](../../../archive/v18.6-review-evidence/proposal.md); modificado por `v18.7-subtask-contract` (ADR 022 §2.7)_
O sistema SHALL avaliar cada comparação de um critério quantitativo. O sistema SHALL encaminhar ao revisor LLM, sem reprovar por métrica ausente, o critério que tem comparação sem métrica conhecida. A métrica que aparece em mais de um grupo SHALL seguir a regra de "Chaves de métrica exigidas e critério ambíguo" e MUST NOT ir ao revisor LLM para escolha de grupo.

#### Scenario: Duas comparações conhecidas
- **GIVEN** `metrics.json` com `accuracy` 0.96 e `f1` 0.90
- **WHEN** o revisor avalia "acurácia >= 0.95 e f1 >= 0.92"
- **THEN** o critério é reprovado, citando `f1` com valor real 0.90

#### Scenario: Comparação sem métrica conhecida
- **GIVEN** `metrics.json` com `accuracy` 0.96
- **WHEN** o revisor avalia "acurácia >= 0.95 e ganho sobre o baseline >= 0.01"
- **THEN** o critério não é reprovado por métrica ausente
- **AND** o critério é enviado ao revisor LLM e aparece em `undecided_criteria` no evento `subtask_review`

#### Scenario: Grupo não nomeado
- **GIVEN** métricas `logistic_regression.accuracy` 0.93 e `random_forest.accuracy` 0.97, sem `accuracy`
- **WHEN** o revisor avalia "acurácia >= 0.95"
- **THEN** o desfecho é `criterio_ambiguo` e o provedor falso não recebe esse critério

#### Scenario: Grupo nomeado
- **GIVEN** as mesmas métricas
- **WHEN** o revisor avalia "acurácia do Random Forest >= 0.95"
- **THEN** o critério é atendido com valor real 0.97, sem chamada ao LLM para esse critério

### Requirement: Propagação dos nomes reais entre subtarefas
_Origem: [`v16-pipeline-robustness`](../../../archive/v16-pipeline-robustness/proposal.md); modificado por `v18.7-subtask-contract` (ADR 022 §2.8)_
O sistema SHALL registrar o mapa esperado → real em `SubtaskOutput.artifact_aliases` e informá-lo no contexto das subtarefas dependentes e nas retentativas. O contrato de cada subtarefa SHALL listar no item 8 os artefatos que subtarefas posteriores consomem, com os consumidores, e o contrato das dependentes SHALL usar o nome real resolvido quando houver alias.

#### Scenario: Contexto da subtarefa seguinte
- **GIVEN** `eda` resolveu `eda_hist.png` como `eda/iris_hist.png` e `modelo` depende de `eda`
- **WHEN** o contexto de `modelo` é montado
- **THEN** ele contém `eda_hist.png → eda/iris_hist.png`

#### Scenario: Artefato consumido no contrato
- **GIVEN** `dividir_dados` com `split.csv` e `treinar_modelo_a` dependente que cita `split.csv`
- **WHEN** o contrato de `dividir_dados` é montado
- **THEN** o item 8 contém `split.csv: treinar_modelo_a`

### Requirement: Revisão de critérios quantitativos por métrica nomeada
_Origem: [`v16-pipeline-robustness`](../../../archive/v16-pipeline-robustness/proposal.md); modificado por `v18.7-subtask-contract` (ADR 022 §2.7, §3)_
O sistema SHALL exigir `metrics.json` na revisão somente quando ao menos um critério do contrato cita uma métrica conhecida com operador e valor, SHALL procurá-lo na pasta da própria subtarefa e, depois, de suas dependências, SHALL avaliar todos os critérios mapeáveis e SHALL usar como chaves exigidas as do item 7 do contrato enviado.

#### Scenario: Critério de contagem não exige métricas
- **GIVEN** o critério "pelo menos 3 gráficos gerados" e nenhum `metrics.json`
- **WHEN** a subtarefa é revisada
- **THEN** a revisão não reprova por falta de `metrics.json` e o critério segue para o revisor LLM

#### Scenario: `metrics.json` de outra subtarefa
- **GIVEN** o critério "acurácia >= 0.9", nenhum `metrics.json` na pasta da subtarefa e um `metrics.json` na pasta de uma subtarefa não listada em `depends_on`
- **WHEN** a subtarefa é revisada
- **THEN** a revisão reprova com a mensagem de arquivo ausente

#### Scenario: Dois critérios, um falha
- **GIVEN** `metrics.json` com acurácia 0,95 e f1 0,70, e os critérios "acurácia >= 0.9" e "f1 >= 0.8"
- **WHEN** a subtarefa é revisada
- **THEN** a revisão reprova e o feedback lista os dois critérios com o valor real de cada um

#### Scenario: Métrica nomeada ausente
- **GIVEN** o critério "auc >= 0.9" e `metrics.json` sem `auc`
- **WHEN** a subtarefa é revisada
- **THEN** a revisão reprova citando que a chave exigida `auc` não está no arquivo e listando as chaves existentes
