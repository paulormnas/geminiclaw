# Especificação: pipeline-robustness

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md), [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)

## Requirements

### Requirement: Normalização determinística do plano
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL normalizar o plano devolvido pelo planejador antes da validação, aplicando
somente reparos sem perda de informação (envelope de lista, tipo de `depends_on`,
`validation_criteria` e `expected_artifacts`, nomes de subtarefa, `task_type` e `agent_id`
com sinônimo conhecido) e registrando cada reparo no evento `plan_normalized`.

#### Scenario: Envelope de lista
- **GIVEN** o planejador devolve `{"tasks": [ {...}, {...} ]}`
- **WHEN** o plano é normalizado
- **THEN** o resultado é a lista de duas subtarefas
- **AND** o evento `plan_normalized` contém um reparo `unwrap_envelope`

#### Scenario: Dependência como texto
- **GIVEN** uma subtarefa com `"depends_on": "carregar_dados, limpar_dados"`
- **WHEN** o plano é normalizado
- **THEN** `depends_on` é `["carregar_dados", "limpar_dados"]` e o reparo `coerce_list` é registrado

#### Scenario: Nome fora do padrão atualiza as dependências
- **GIVEN** uma subtarefa `"Carregar Dados"` e outra com `"depends_on": ["Carregar Dados"]`
- **WHEN** o plano é normalizado
- **THEN** os nomes viram `carregar_dados` nas duas posições

#### Scenario: Nomes repetidos
- **GIVEN** duas subtarefas com `task_name` `treinar`
- **WHEN** o plano é normalizado
- **THEN** os nomes são `treinar` e `treinar_2`

#### Scenario: Conteúdo não é inventado
- **GIVEN** uma subtarefa `validation` sem critério com limiar numérico e outra sem
  `validation_criteria`
- **WHEN** o plano é normalizado
- **THEN** nenhum critério é acrescentado e os dois problemas aparecem em `unrecoverable`

#### Scenario: Normalizador desligado
- **GIVEN** `PLAN_NORMALIZER_ENABLED=false`
- **WHEN** o planejador devolve `depends_on` como texto
- **THEN** o plano chega ao Validator sem reparo

### Requirement: Laço de reprovação do plano com fim
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL encerrar o planejamento com erro explícito quando a mesma reprovação
determinística se repete `PLAN_REJECTION_STALL_LIMIT` vezes seguidas, e SHALL tratar o Validator
LLM como consultivo (aprovação com avisos) quando ele repete a mesma reprovação o mesmo número
de vezes e as checagens determinísticas passaram.

#### Scenario: Reprovação determinística repetida
- **GIVEN** `PLAN_REJECTION_STALL_LIMIT=2` e um planejador que devolve duas vezes o plano com a
  mesma subtarefa `validation` sem limiar numérico
- **WHEN** o ciclo de planejamento avalia a segunda reprovação
- **THEN** o planejamento termina com `PlanningStalled` citando a subtarefa e a correção pedida
- **AND** nenhuma nova execução do planejador é feita

#### Scenario: Reprovação diferente não conta como repetição
- **GIVEN** duas reprovações determinísticas com problemas distintos
- **WHEN** o ciclo avalia a segunda
- **THEN** o planejamento continua

#### Scenario: Validator LLM consultivo
- **GIVEN** um plano que passa nas checagens determinísticas e um Validator LLM que reprova duas
  vezes com os mesmos problemas
- **WHEN** a segunda reprovação é avaliada
- **THEN** o plano é aprovado com `approved_with_warnings=true`
- **AND** o evento `plan_validation` lista os problemas do Validator LLM

#### Scenario: Primeira reprovação do Validator LLM vale
- **GIVEN** um plano que passa nas checagens determinísticas
- **WHEN** o Validator LLM reprova pela primeira vez
- **THEN** o plano é devolvido ao planejador com os problemas

### Requirement: Resolução tolerante de artefatos
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL resolver cada artefato esperado em camadas (`exact`, `glob`, `normalized`,
`extension`), na pasta da subtarefa antes das demais, e SHALL considerar ausente apenas o que
nenhuma camada resolve. Resolução por `normalized` ou `extension` SHALL aprovar com
`name_mismatch` e registrar o par esperado → real. Com `ARTIFACT_MATCH_MODE=strict`, só valem
`exact` e `glob`.

#### Scenario: Prefixo diferente do esperado
- **GIVEN** a subtarefa espera `eda_hist.png` e `eda_box.png` e a pasta tem `iris_hist.png` e
  `iris_box.png`
- **WHEN** os artefatos são resolvidos
- **THEN** ambos resolvem na camada `extension`, a revisão não reprova por artefato ausente e o
  evento `subtask_review` traz `eda_hist.png → <subtarefa>/iris_hist.png` e o segundo par

#### Scenario: Padrão glob
- **GIVEN** a subtarefa espera `eda_*.png` e a pasta tem `eda_hist.png`
- **WHEN** os artefatos são resolvidos
- **THEN** a camada é `glob` e não há `name_mismatch`

#### Scenario: Menos arquivos que o esperado
- **GIVEN** a subtarefa espera três `.png` e a pasta tem dois
- **WHEN** os artefatos são resolvidos
- **THEN** pelo menos um esperado fica `missing` e a revisão reprova listando o que falta e o
  que existe

#### Scenario: Código nunca casa por extensão
- **GIVEN** a subtarefa espera `modelo.py` e a pasta tem `outro.py`
- **WHEN** os artefatos são resolvidos
- **THEN** o esperado fica `missing`

#### Scenario: Cada arquivo resolve um esperado
- **GIVEN** dois `.png` esperados e um único `.png` em disco
- **WHEN** os artefatos são resolvidos
- **THEN** um esperado é resolvido e o outro fica `missing`

#### Scenario: Saída da pasta da sessão
- **GIVEN** um artefato esperado `../../etc/passwd` ou um link simbólico para fora da sessão
- **WHEN** os artefatos são resolvidos
- **THEN** o esperado fica `missing` e nenhum arquivo externo é lido

#### Scenario: Modo estrito
- **GIVEN** `ARTIFACT_MATCH_MODE=strict` e o caso `iris_*.png` no lugar de `eda_*.png`
- **WHEN** os artefatos são resolvidos
- **THEN** os esperados ficam `missing`

### Requirement: Propagação dos nomes reais entre subtarefas
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL registrar o mapa esperado → real em `SubtaskOutput.artifact_aliases` e
informá-lo no contexto das subtarefas dependentes e nas retentativas.

#### Scenario: Contexto da subtarefa seguinte
- **GIVEN** `eda` resolveu `eda_hist.png` como `eda/iris_hist.png` e `modelo` depende de `eda`
- **WHEN** o contexto de `modelo` é montado
- **THEN** ele contém `eda_hist.png → eda/iris_hist.png`

### Requirement: Revisão de critérios quantitativos por métrica nomeada
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL exigir `metrics.json` na revisão somente quando ao menos um critério cita uma
métrica de `_METRIC_ALIASES` com operador e valor, SHALL procurá-lo na pasta da própria
subtarefa e, depois, de suas dependências, e SHALL avaliar todos os critérios mapeáveis.

#### Scenario: Critério de contagem não exige métricas
- **GIVEN** o critério "pelo menos 3 gráficos gerados" e nenhum `metrics.json`
- **WHEN** a subtarefa é revisada
- **THEN** a revisão não reprova por falta de `metrics.json` e o critério segue para o revisor LLM

#### Scenario: `metrics.json` de outra subtarefa
- **GIVEN** o critério "acurácia >= 0.9", nenhum `metrics.json` na pasta da subtarefa e um
  `metrics.json` na pasta de uma subtarefa não listada em `depends_on`
- **WHEN** a subtarefa é revisada
- **THEN** a revisão reprova com a mensagem de arquivo ausente

#### Scenario: Dois critérios, um falha
- **GIVEN** `metrics.json` com acurácia 0,95 e f1 0,70, e os critérios "acurácia >= 0.9" e
  "f1 >= 0.8"
- **WHEN** a subtarefa é revisada
- **THEN** a revisão reprova e o feedback lista os dois critérios com o valor real de cada um

#### Scenario: Métrica nomeada ausente
- **GIVEN** o critério "auc >= 0.9" e `metrics.json` sem `auc`
- **WHEN** a subtarefa é revisada
- **THEN** a revisão reprova citando que a métrica `auc` não está no arquivo

### Requirement: Disjuntor de progresso por mudança de erro
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL considerar progresso qualquer aumento no conjunto de subtarefas bem-sucedidas
ou mudança na assinatura dos erros das subtarefas falhas entre ciclos, e SHALL encerrar a
sessão por falta de progresso somente após `CIRCUIT_BREAKER_STALL_CYCLES` ciclos consecutivos
sem progresso.

#### Scenario: Erro diferente é progresso
- **GIVEN** nenhum sucesso nos ciclos 1 e 2, com erros de revisão sobre critérios distintos
- **WHEN** o ciclo 2 termina
- **THEN** o disjuntor não dispara

#### Scenario: Dois ciclos idênticos
- **GIVEN** `CIRCUIT_BREAKER_STALL_CYCLES=2` e três ciclos com o mesmo conjunto de sucessos e a
  mesma assinatura de erros
- **WHEN** o ciclo 3 termina
- **THEN** a sessão encerra com o evento `circuit_breaker` contendo `stalled_cycles=2`

#### Scenario: Primeiro ciclo
- **WHEN** o primeiro ciclo termina com falhas
- **THEN** o disjuntor não dispara

#### Scenario: Assinatura ignora números e caminhos
- **GIVEN** duas falhas com o mesmo critério e valores numéricos diferentes no texto
- **WHEN** as assinaturas são calculadas
- **THEN** as assinaturas são iguais

### Requirement: Limites de execução separados e com fechamento
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL contar execuções de planejamento e de subtarefa em contadores distintos, com
limite de execuções de subtarefa não menor que `n * (1 + SESSION_MAX_TASK_RETRIES) + 2` para um
plano de `n` subtarefas, e SHALL fechar a sessão com consolidação e `motivo_parada`
`limite_execucoes` ao atingir qualquer limite, sem lançar exceção não tratada.

#### Scenario: Planejamento não consome o limite de subtarefas
- **GIVEN** `MAX_AGENT_RUNS_PER_SESSION=30` e 12 execuções de planejamento
- **WHEN** as subtarefas começam a executar
- **THEN** o contador de execução está em 0

#### Scenario: Limite acompanha o plano
- **GIVEN** `MAX_AGENT_RUNS_PER_SESSION=30`, `SESSION_MAX_TASK_RETRIES=3` e um plano de 10
  subtarefas
- **WHEN** o limite efetivo é calculado
- **THEN** o limite é 42

#### Scenario: Limite de planejamento atingido
- **GIVEN** `MAX_PLANNING_RUNS_PER_SESSION=20` e 20 execuções de planejamento feitas
- **WHEN** um novo ciclo de planejamento tenta executar o planejador
- **THEN** a sessão fecha com `motivo_parada="limite_execucoes"` e o evento `limit_reached`
  traz `limit="agent_runs"` e `kind="planning"`

#### Scenario: Limite de execução atingido
- **GIVEN** o contador de execução igual ao limite efetivo
- **WHEN** uma subtarefa tenta executar
- **THEN** a sessão fecha com checkpoint e consolidação, e nenhuma exceção chega ao chamador

### Requirement: Relatório a partir de dados estruturados
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL construir `ReportData` a partir do disco e da telemetria sem passar números por
LLM, SHALL renderizar `relatorio_final.md` de forma determinística a partir de `ReportData` e
`Narrative`, e SHALL gravar `report_data.json` ao lado. O Summarizer SHALL produzir apenas a
narrativa em JSON, sem ferramentas.

#### Scenario: Tabela de resultados
- **GIVEN** dois `metrics.json` com `accuracy` 0,967 e 0,953
- **WHEN** o relatório é renderizado
- **THEN** a tabela de Resultados contém exatamente esses dois valores, com o caminho de origem

#### Scenario: Metadados de execução
- **GIVEN** telemetria com 5 execuções do desenvolvedor, 2 do Researcher e 3 eventos `sandbox_run`
- **WHEN** o relatório é renderizado
- **THEN** a seção de metadados mostra duração, tokens, custo, execuções por papel
  (`developer: 5`, `researcher: 2`), 3 execuções no sandbox e os modelos por papel
- **AND** o relatório não contém a palavra "Containers"

#### Scenario: Narrativa inválida
- **GIVEN** um Summarizer que devolve texto que não é JSON de `Narrative` duas vezes
- **WHEN** a síntese termina
- **THEN** `relatorio_final.md` existe, os campos narrativos dizem `[narrativa indisponível: ...]`
  e `report_data.json` tem `narrativa_indisponivel=true`

#### Scenario: Reparo da narrativa
- **GIVEN** um Summarizer que falha na primeira tentativa e devolve JSON válido na segunda
- **WHEN** a síntese termina
- **THEN** a narrativa do relatório é a da segunda tentativa e `narrativa_indisponivel` é falso

#### Scenario: Seções fixas
- **WHEN** qualquer relatório é renderizado
- **THEN** as nove seções aparecem na ordem: Resumo Executivo, Contexto e Objetivo, Metodologia,
  Resultados, Análise das Divergências, Decisões do Pesquisador, Limitações Identificadas,
  Próximos Passos Sugeridos, Metadados de Execução

#### Scenario: Sessão sem interações com o pesquisador
- **GIVEN** `researcher_interactions` vazio
- **WHEN** o relatório é renderizado
- **THEN** "Decisões do Pesquisador" declara que a sessão foi totalmente autônoma

### Requirement: Evento por execução no sandbox
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
O sistema SHALL emitir o evento `sandbox_run` a cada execução de código no sandbox, com
`task_name`, `exit_code`, `duration_ms` e `timed_out`, sem o conteúdo do script.

#### Scenario: Execução com falha
- **WHEN** o script de uma subtarefa termina com código 1
- **THEN** o evento `sandbox_run` traz `exit_code=1` e não contém o texto do script

### Requirement: Limite de execuções de agente por sessão
_Origem: [`v16-pipeline-robustness`](../../changes/archive/v16-pipeline-robustness/proposal.md)_
(Origem: `v16-in-process-agents` e `src/orchestrator.py`, V12.5.2.) O sistema SHALL aplicar o
limite de execuções de agente com os contadores e o fechamento descritos em "Limites de execução
separados e com fechamento"; o comportamento anterior (exceção `RuntimeError` descritiva na
chamada que ultrapassa o limite) é substituído.

#### Scenario: Mensagem do limite
- **WHEN** o limite de execução é atingido
- **THEN** o evento e o `motivo_parada` identificam o contador (`planning` ou `execution`), o
  valor atingido e o limite efetivo

### Requirement: Qualificador de conjunto no nome de métrica
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
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
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
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
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
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
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
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
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
A instrução do revisor SHALL declarar que o tamanho em bytes não é evidência de conteúdo e
SHALL mandar usar o perfil estrutural para conferir linhas, colunas e chaves.

#### Scenario: Instrução contém as regras
- **WHEN** o prompt de sistema do revisor é montado
- **THEN** ele contém a regra sobre tamanho em bytes e a regra sobre o perfil

### Requirement: Script executado resolve o `.py` esperado
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
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
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
O comparador SHALL incluir `.joblib` e `.pkl` na camada `extension`.

#### Scenario: Nome de modelo diferente
- **GIVEN** a subtarefa espera `dummy_baseline.joblib` e gravou `dummy_most_frequent.joblib`
- **WHEN** os artefatos são resolvidos
- **THEN** o esperado resolve com camada `extension`

### Requirement: Limiar numérico obrigatório em subtarefa confirmatória
_Origem: [`v18.6-review-evidence`](../../changes/archive/v18.6-review-evidence/proposal.md)_
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
