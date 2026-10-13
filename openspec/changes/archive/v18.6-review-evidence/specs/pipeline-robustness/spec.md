# Delta: pipeline-robustness

## ADDED Requirements

### Requirement: Qualificador de conjunto no nome de métrica
O sistema SHALL separar o nome base e o qualificador de conjunto (`teste`, `cv`, `treino`,
`validacao`) de um nome de métrica, removendo no máximo uma palavra da primeira ou da última
posição. O revisor e a ingestão no grafo SHALL usar a mesma regra. Um critério sobre uma
métrica sem conjunto explícito SHALL aceitar só valores com qualificador `teste` ou vazio.

#### Scenario: `test_accuracy` satisfaz critério de acurácia
- **GIVEN** `metrics.json` com `{"metrics": {"test_accuracy": 0.95}}`
- **WHEN** o revisor avalia o critério "acurácia no teste >= 0.95"
- **THEN** o critério é atendido com valor real 0.95

#### Scenario: Validação cruzada não vale como teste
- **GIVEN** `metrics.json` com `{"metrics": {"cv_accuracy_mean": 0.97}}`
- **WHEN** o revisor avalia o critério "acurácia >= 0.95"
- **THEN** o critério é reprovado por métrica ausente
- **AND** a mensagem lista `cv_accuracy_mean` entre as chaves existentes

#### Scenario: Critério que cita o conjunto
- **GIVEN** `metrics.json` com `cv_accuracy` 0.96 e `test_accuracy` 0.90
- **WHEN** o revisor avalia "acurácia de validação cruzada >= 0.95"
- **THEN** o critério é atendido com valor real 0.96

#### Scenario: Ingestão liga resultado de teste à métrica canônica
- **GIVEN** o vocabulário com a `Metrica` `acuracia` e sinônimo `accuracy`
- **WHEN** a ingestão grava um `Resultado` de `test_accuracy`
- **THEN** existe `Resultado-MEDE->Metrica(acuracia)` e o `Resultado` tem `qualificador = "teste"`

#### Scenario: Ingestão não liga validação cruzada à métrica do teste
- **WHEN** a ingestão grava um `Resultado` de `cv_accuracy_mean`
- **THEN** nenhuma aresta `MEDE` liga esse `Resultado` à `Metrica` `acuracia`

#### Scenario: Qualificador desligado
- **GIVEN** `REVIEW_METRIC_QUALIFIERS=false`
- **WHEN** o revisor avalia "acurácia >= 0.95" contra `test_accuracy` 0.96
- **THEN** o critério é reprovado por métrica ausente, como antes desta mudança

### Requirement: Leitura tolerante de `metrics.json`
O sistema SHALL aceitar o envelope `metricas` como sinônimo de `metrics` e SHALL achatar um
nível de grupos numéricos em chaves `grupo.metrica`, sem incluir chaves de metadado nem
booleanos.

#### Scenario: Envelope em português
- **GIVEN** `metrics.json` com `{"metricas": {"accuracy": 0.96}}`
- **WHEN** `metrics_of` é chamado
- **THEN** o resultado é `{"accuracy": 0.96}`

#### Scenario: Métricas por modelo
- **GIVEN** `{"metrics": {"logistic_regression": {"accuracy": 0.93}, "random_forest": {"accuracy": 0.97}}}`
- **WHEN** `metrics_of` é chamado
- **THEN** o resultado contém `logistic_regression.accuracy` 0.93 e `random_forest.accuracy` 0.97

#### Scenario: Envelope oficial vence
- **GIVEN** um arquivo com `metrics` e `metricas`
- **WHEN** `metrics_of` é chamado
- **THEN** só o conteúdo de `metrics` é devolvido

### Requirement: Critérios com várias comparações e métricas em vários grupos
O sistema SHALL avaliar cada comparação de um critério quantitativo. O sistema SHALL encaminhar
ao revisor LLM, sem reprovar por métrica ausente, o critério que tem comparação sem métrica
conhecida ou cuja métrica aparece em mais de um grupo sem que o critério nomeie o grupo.

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
- **GIVEN** métricas `logistic_regression.accuracy` 0.93 e `random_forest.accuracy` 0.97
- **WHEN** o revisor avalia "acurácia >= 0.95"
- **THEN** o critério vai ao revisor LLM com a tabela das duas métricas como evidência

#### Scenario: Grupo nomeado
- **GIVEN** as mesmas métricas
- **WHEN** o revisor avalia "acurácia do Random Forest >= 0.95"
- **THEN** o critério é atendido com valor real 0.97, sem chamada ao LLM para esse critério

### Requirement: Perfil estrutural de artefatos de dados
O sistema SHALL enviar ao revisor, para cada CSV, TSV ou JSON classificado como
`dado_de_pesquisa`, um perfil estrutural calculado no nó e rotulado `esquema_agregado`, sem
nenhum valor de célula. O sistema SHALL omitir a contagem de nulos de uma coluna quando ela está
entre 1 e `LOCALITY_MIN_GROUP_SIZE - 1`.

#### Scenario: Perfil de CSV
- **GIVEN** um CSV com cabeçalho e 150 linhas de dados em 5 colunas, sem nulos
- **WHEN** a evidência do revisor é montada
- **THEN** o trecho do artefato contém "150 linhas de dados, 5 colunas" e os nomes das colunas
- **AND** nenhum valor de célula do arquivo aparece no trecho
- **AND** a origem do trecho é `esquema_agregado`

#### Scenario: Perfil de JSON
- **GIVEN** `eda_summary.json` com `{"n": 150, "classes": ["a", "b", "c"]}`
- **WHEN** a evidência do revisor é montada
- **THEN** o perfil contém "n: número" e "classes: lista[3] de texto"
- **AND** nem `150` nem `"a"` aparecem no trecho

#### Scenario: Nulos em grupo pequeno
- **GIVEN** `LOCALITY_MIN_GROUP_SIZE=10` e uma coluna com 3 nulos
- **WHEN** o perfil é calculado
- **THEN** a coluna aparece com "nulos: omitido"

#### Scenario: Arquivo acima do limite de leitura
- **GIVEN** `REVIEW_PROFILE_MAX_BYTES=1000` e um CSV de 50 KB
- **WHEN** o perfil é calculado
- **THEN** a contagem aparece como "≥ N linhas (lidas até o limite)"

#### Scenario: Perfil desligado
- **GIVEN** `REVIEW_ARTIFACT_PROFILE=false`
- **WHEN** a evidência é montada
- **THEN** o CSV aparece como hoje: trecho do conteúdo rotulado `dado_de_pesquisa`

### Requirement: Instrução do revisor sobre tamanho de arquivo
A instrução do revisor SHALL declarar que o tamanho em bytes não é evidência de conteúdo e
SHALL mandar usar o perfil estrutural para conferir linhas, colunas e chaves.

#### Scenario: Instrução contém as regras
- **WHEN** o prompt de sistema do revisor é montado
- **THEN** ele contém a regra sobre tamanho em bytes e a regra sobre o perfil

### Requirement: Script executado resolve o `.py` esperado
O comparador de artefatos SHALL resolver um único `.py` esperado e ainda não resolvido de uma
subtarefa para o `script.py` executado na pasta dessa subtarefa, com camada `script` e
`name_mismatch` verdadeiro. Com dois ou mais `.py` esperados e não resolvidos, a camada `script`
SHALL não resolver nenhum.

#### Scenario: Um script esperado
- **GIVEN** a subtarefa `eda` espera `eda_iris.py` e a pasta `eda/` tem `script.py`
- **WHEN** os artefatos são resolvidos
- **THEN** `eda_iris.py` resolve para `eda/script.py` com camada `script`

#### Scenario: Dois scripts esperados
- **GIVEN** a subtarefa espera `treino.py` e `avaliacao.py` e a pasta tem só `script.py`
- **WHEN** os artefatos são resolvidos
- **THEN** os dois ficam `missing`

#### Scenario: Script de outra subtarefa
- **GIVEN** a subtarefa `treino` espera `treino.py` e só a pasta `eda/` tem `script.py`
- **WHEN** os artefatos são resolvidos
- **THEN** `treino.py` fica `missing`

### Requirement: Modelos serializados na camada de extensão
O comparador SHALL incluir `.joblib` e `.pkl` na camada `extension`.

#### Scenario: Nome de modelo diferente
- **GIVEN** a subtarefa espera `dummy_baseline.joblib` e gravou `dummy_most_frequent.joblib`
- **WHEN** os artefatos são resolvidos
- **THEN** o esperado resolve com camada `extension`

## MODIFIED Requirements

### Requirement: Limiar numérico obrigatório em subtarefa confirmatória
O Validator SHALL reprovar de forma determinística um plano com subtarefa `reproduction`, ou
`validation` com `hypothesis_ref` preenchido, sem critério quantitativo. Subtarefa `validation`
sem `hypothesis_ref` SHALL passar pela checagem estrutural, com aviso `validation_sem_hipotese`
no evento `plan_validation`.
(Antes: toda subtarefa `validation` exigia limiar numérico. Alteração sujeita à questão 8.1 do
design.)

#### Scenario: Baseline sem hipótese
- **GIVEN** um plano com a subtarefa `baseline_majoritario` do tipo `validation`, sem
  `hypothesis_ref` e sem limiar numérico
- **WHEN** o Validator checa a estrutura
- **THEN** o plano não é reprovado por essa subtarefa
- **AND** o evento `plan_validation` contém o aviso `validation_sem_hipotese`

#### Scenario: Teste de hipótese sem limiar
- **GIVEN** uma subtarefa `validation` com `hypothesis_ref` `h1` e sem limiar numérico
- **WHEN** o Validator checa a estrutura
- **THEN** o plano é reprovado de forma determinística, com a correção sugerida
