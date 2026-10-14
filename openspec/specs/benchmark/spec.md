# Especificação: benchmark

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md), [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)

## Requirements

### Requirement: Reset isolado dos bancos de benchmark
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL recriar o banco PostgreSQL de benchmark e apagar as coleções do sistema no Qdrant
antes de cada execução somente quando `--reset-stores` é passado, `--confirm-target` coincide
com o alvo de `BENCHMARK_DATABASE_URL`, o nome do banco contém `BENCHMARK_DB_MARKER` e difere do
banco de `DATABASE_URL` do `.env`. Faltando qualquer condição, o runner MUST recusar com erro
explícito antes de qualquer escrita.

#### Scenario: Reset sem a flag
- **GIVEN** `BENCHMARK_DATABASE_URL` válida
- **WHEN** o runner roda sem `--reset-stores`
- **THEN** nenhum banco é apagado
- **AND** cada resultado tem `isolated: false` e o runner avisa no início

#### Scenario: Alvo não confirmado
- **GIVEN** `--reset-stores` e `--confirm-target outro@host`
- **WHEN** o runner inicia
- **THEN** o runner termina com erro que mostra o alvo esperado (sem senha), sem apagar nada

#### Scenario: Banco sem a marca
- **GIVEN** `BENCHMARK_DATABASE_URL` aponta para o banco `geminiclaw`
- **WHEN** o runner inicia com `--reset-stores`
- **THEN** o runner recusa, citando `BENCHMARK_DB_MARKER`

#### Scenario: Banco igual ao de desenvolvimento
- **GIVEN** `BENCHMARK_DATABASE_URL` e `DATABASE_URL` com o mesmo banco `geminiclaw_bench`
- **WHEN** o runner inicia com `--reset-stores`
- **THEN** o runner recusa

#### Scenario: Reset completo
- **GIVEN** o banco de benchmark com nós no grafo, linhas em `execution_records` e pontos no Qdrant
- **WHEN** o reset roda com as guardas satisfeitas
- **THEN** depois do reset o grafo tem só o vocabulário, `execution_records` está vazia e as
  coleções do sistema não existem ou estão vazias
- **AND** a `Metrica` `acuracia` existe aprovada, com o sinônimo `accuracy`

### Requirement: Arquivo de segurança antes do reset
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O reset SHALL gravar o `pg_dump` do banco de benchmark e um snapshot de cada coleção do sistema
no Qdrant antes de apagar. Falha no arquivo de segurança MUST interromper o reset, salvo com
`--no-pre-reset-dump`.

#### Scenario: Dump gravado
- **WHEN** o reset roda
- **THEN** `<results>.d/<combinação>/r<r>/pre_reset/` contém o dump e os snapshots listados no `ResetReport`

#### Scenario: Dump falha
- **GIVEN** o `pg_dump` indisponível
- **WHEN** o reset roda sem `--no-pre-reset-dump`
- **THEN** o reset termina com erro e o banco não é apagado

### Requirement: Projeto semeado exige métrica canônica
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
`seed_project` MUST falhar com erro explícito quando a `Metrica` do `Problema` semeado não existe
como termo aprovado no vocabulário.

#### Scenario: Vocabulário vazio
- **GIVEN** um grafo sem a `Metrica` `acuracia` aprovada
- **WHEN** `seed_project` é chamado
- **THEN** ele lança erro citando `scripts/seed_vocabulary.py`
- **AND** nenhum projeto é criado

### Requirement: Série de crescimento das memórias
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL amostrar, a cada `BENCHMARK_STORE_SAMPLE_SECONDS` durante a execução e também no
início e no fim, as linhas por tabela, o tamanho do banco, os pontos por coleção do Qdrant e os
nós e arestas do grafo por rótulo, e SHALL gravar a série em `store_timeline`.

#### Scenario: Série com início e fim
- **GIVEN** `BENCHMARK_STORE_SAMPLE_SECONDS=1` e uma execução simulada de 3 s que grava 2 nós
- **WHEN** a execução termina
- **THEN** `store_timeline` tem ao menos 3 amostras
- **AND** a última amostra tem 2 nós a mais que a primeira

#### Scenario: Amostra com falha
- **GIVEN** o Qdrant indisponível durante uma amostra
- **WHEN** a amostra é coletada
- **THEN** a amostra tem o campo `erro` e o benchmark continua

#### Scenario: Relatório de crescimento
- **GIVEN** um resultado com `store_timeline`
- **WHEN** o relatório é gerado
- **THEN** ele mostra o crescimento total e a taxa por minuto de nós do grafo, pontos do Qdrant e
  linhas de `agent_events`, `egress_log` e `execution_records`

### Requirement: Acurácia oficial a partir de resultado validado
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL registrar `accuracy_validated` como a maior acurácia de teste entre os
`Resultado`s da sessão com `status_validacao = "validado"`, aresta `MEDE` para a métrica do
`Problema` e qualificador vazio ou `teste`. Sem resultado elegível, o valor MUST ser `null`. A
acurácia lida do texto SHALL ficar em `acuracia_declarada_texto` e nunca ser usada como acurácia
oficial.

#### Scenario: Contagem não vira acurácia
- **GIVEN** uma sessão sem modelo treinado cujo relatório diz "accuracy: 1.0 (duplicatas)" e cujo
  grafo tem só `Resultado`s de EDA
- **WHEN** o placar é calculado
- **THEN** `accuracy_validated` é `null`
- **AND** `acuracia_declarada_texto` é 1.0

#### Scenario: Resultado não validado não conta
- **GIVEN** `Resultado` de acurácia 0.97 com `status_validacao = "nao_validado"` e outro de 0.93 validado
- **WHEN** o placar é calculado
- **THEN** `accuracy_validated` é 0.93

#### Scenario: Validação cruzada não conta
- **GIVEN** `Resultado` validado com qualificador `cv` e valor 0.98
- **WHEN** o placar é calculado
- **THEN** esse valor não entra em `accuracy_validated`

### Requirement: Checklist a partir de subtarefas aprovadas
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL calcular o checklist só com subtarefas aprovadas pelo revisor, artefatos
resolvidos, o plano gravado e o grafo, conforme a tabela do design §4.2. O checklist por texto
SHALL ficar em `checks_texto`.

#### Scenario: Plano cita algoritmos que não rodaram
- **GIVEN** um plano com "random forest" e "svm" e só a subtarefa de EDA aprovada
- **WHEN** o checklist é calculado
- **THEN** `two_algorithms` é falso em `checks_validated`
- **AND** `two_algorithms` é verdadeiro em `checks_texto`

### Requirement: Anomalias do placar
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL marcar `acuracia_perfeita` quando `accuracy_validated` é 1.0, `sem_mede` quando
há `Resultado`s na sessão e nenhum com `MEDE` para a métrica do `Problema`, e
`vocabulario_nao_semeado` quando a `Metrica` do `Problema` não está aprovada. Essas marcas SHALL
não interromper o runner com `--fail-fast`.

#### Scenario: Acurácia perfeita
- **GIVEN** `accuracy_validated` 1.0
- **WHEN** as anomalias são calculadas
- **THEN** a lista contém `acuracia_perfeita` e o runner segue para a próxima execução

### Requirement: Arquivamento da sessão
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL arquivar, ao fim de cada execução, a pasta da sessão, o log, os eventos da sessão e
o grafo do projeto em `<results>.d/<combinação>/r<r>/`, e SHALL gravar o caminho em `archive_dir`.

#### Scenario: Arquivos presentes
- **WHEN** uma execução termina
- **THEN** a pasta da repetição contém `sessao.tar.gz`, `run.log`, `eventos.json` e `grafo_projeto.json`

### Requirement: Repetições com agregados
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL executar cada combinação `--repeat N` vezes, com reset antes de cada execução
quando `--reset-stores` está ativo, e SHALL retomar uma matriz interrompida pela chave
`(nome, repeticao)`. O relatório SHALL mostrar média, desvio padrão amostral, mínimo e máximo de
tempo, custo, acurácia validada e subtarefas aprovadas, e a contagem por motivo de parada.

#### Scenario: Retomada
- **GIVEN** um arquivo de resultados com a repetição 1 de `sonnet`
- **WHEN** o runner roda com `--repeat 3`
- **THEN** ele executa só as repetições 2 e 3 de `sonnet`

#### Scenario: Agregado ignora nulos
- **GIVEN** três repetições com `accuracy_validated` 0.95, `null` e 0.97
- **WHEN** o relatório é gerado
- **THEN** a média de acurácia é 0.96 e a coluna de nulos mostra 1

### Requirement: Juiz declarado por combinação
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O runner SHALL não expandir o pin `*` para o papel `validator`, SHALL recusar a
combinação cujo `validator` não está declarado ou tem a família do `developer`, salvo quando marcada
com `"independencia_julgamento": "off"`, e SHALL registrar a marca no resultado
(ADR 020 §7).

#### Scenario: Juiz não declarado
- **GIVEN** a combinação `{"roles": {"*": "anthropic/claude-haiku-5-5"}}`
- **WHEN** o runner valida a matriz
- **THEN** a combinação é recusada antes de rodar, com a mensagem que pede o `VALIDATOR`

#### Scenario: Juiz da mesma família
- **GIVEN** `{"*": "anthropic/claude-haiku-5-5", "VALIDATOR": "anthropic/claude-sonnet-5-5"}`
- **WHEN** o runner valida a matriz
- **THEN** a combinação é recusada (família `claude` nos dois)

#### Scenario: Combinação de controle
- **GIVEN** a mesma combinação com `"independencia_julgamento": "off"`
- **WHEN** o runner executa
- **THEN** o subprocesso recebe `LLM_JUDGE_INDEPENDENCE=off` e o resultado registra `controle: true`

### Requirement: Custo com tokens em cache da OpenAI
_Origem: [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)_
O provedor OpenAI SHALL repassar `cached_tokens` das respostas Chat Completions e Responses, e a
tabela de preços SHALL ter `cached_input` para os modelos OpenAI da matriz.

#### Scenario: Responses com cache
- **GIVEN** uma resposta simulada da API Responses com `input_tokens_details.cached_tokens = 800` de 1000
- **WHEN** o custo é estimado
- **THEN** 800 tokens são cobrados pelo preço `cached_input` e 200 pelo preço de entrada

### Requirement: Classificação dos motivos de parada
_Origem: [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)_
O benchmark SHALL classificar o `motivo_parada` de cada execução em `limite`, `erro`, `interrupcao`, `criterio_pesquisa` ou
`hipoteses_nao_testadas`. Somente `limite`, `erro` e `interrupcao` SHALL ser anomalia. `hipoteses_nao_testadas` SHALL ser
tratado como parada de pesquisa, listado no relatório e nunca contado como erro. O resumo de interações SHALL contar os
motivos de reprovação de subtarefa (`sem_hipotese`).

#### Scenario: Parada por hipótese não testada não é anomalia
- **GIVEN** uma execução com `stop_reason = "hipoteses_nao_testadas"` e `exit 0`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado

#### Scenario: Classificação
- **WHEN** `stop_class` recebe `limite_tokens`, `erro`, `interrompida_pesquisador`, `solucao_encontrada` e `hipoteses_nao_testadas`
- **THEN** devolve `limite`, `erro`, `interrupcao`, `criterio_pesquisa` e `hipoteses_nao_testadas`

#### Scenario: Relatório lista a parada
- **GIVEN** duas execuções da combinação `c1`, uma fechada por `hipoteses_nao_testadas`
- **WHEN** o relatório é gerado
- **THEN** há uma seção que cita `c1` e a repetição afetada

#### Scenario: Reprovação sem hipótese no resumo
- **GIVEN** um evento `subtask_review` com `motivos = ["sem_hipotese"]`
- **WHEN** `summarize_events` resume os eventos
- **THEN** `subtask_reviews.motivos` é `{"sem_hipotese": 1}`

### Requirement: Versão dos modelos registrada por execução
O runner SHALL gravar em cada resultado, por papel da sessão, o modelo pedido (`provedor/modelo`), a `familia_modelo` e a
`versao_efetiva` informada pelo provedor (`desconhecida` quando não informada, sem deduzir do nome pedido), além de
`data_execucao` (UTC) e dos `precos` aplicados (entrada, saída, cache e `vigencia_ate`). O relatório SHALL mostrar a tabela
"Modelos e versões" por combinação, SHALL registrar o aviso `versao_desconhecida` no placar (sem tratá-lo como anomalia de
parada) e SHALL avisar quando a mesma combinação teve `versao_efetiva` diferente entre repetições. Referência: ADR 019 §6, ADR 020 §7.

#### Scenario: Versões gravadas
- **GIVEN** uma sessão com `allocation_profile` em que o `developer` é `google/gemini-4-argon` com `versao_efetiva` "gemini-4-argon-001"
- **WHEN** a execução termina
- **THEN** o resultado tem `modelos.developer = {pedido: "google/gemini-4-argon", familia: "gemini", versao_efetiva: "gemini-4-argon-001"}`
- **AND** `data_execucao` e `precos["google/gemini-4-argon"].vigencia_ate = "2026-11-30"`

#### Scenario: Versão não informada
- **GIVEN** o `validator` com `versao_efetiva = "desconhecida"`
- **WHEN** o resultado é gravado
- **THEN** o campo guarda `desconhecida` e o placar traz o aviso `versao_desconhecida` para o `validator`
- **AND** o aviso não conta como anomalia de parada

#### Scenario: Tabela no relatório
- **GIVEN** duas execuções da combinação `c1`
- **WHEN** o relatório é gerado
- **THEN** a seção "Modelos e versões" lista, para `c1`, cada papel com modelo pedido e versão efetiva

#### Scenario: Versões diferentes entre repetições
- **GIVEN** duas repetições de `c1` com `versao_efetiva` diferente para o `developer`
- **WHEN** o relatório é gerado
- **THEN** há um aviso que cita `c1`, o papel e as duas versões

#### Scenario: Resultado antigo sem os campos
- **GIVEN** um arquivo de resultados anterior a esta mudança
- **WHEN** o relatório é gerado
- **THEN** a execução aparece com versão `n/d` e nenhum erro é lançado

### Requirement: Orçamento por provedor da matriz
A matriz SHALL declarar `budget_usd` por provedor (`anthropic`, `openai`, `google`), e o runner SHALL pular, com motivo
registrado, a execução cujo provedor já atingiu o teto. A matriz oficial da V18.6 SHALL usar US$ 14 em cada um. Referência: pedido do pesquisador, 2026-10-14.

#### Scenario: Teto do Google atingido
- **GIVEN** `budget_usd.google = 14.0` e gasto acumulado de US$ 14,20 em combinações com `google/...`
- **WHEN** a próxima combinação que usa `google` vai rodar
- **THEN** ela é registrada como `skipped` com "orçamento de google esgotado"

#### Scenario: Matriz oficial
- **WHEN** `matrix_modelos_v18_6.json` é carregada
- **THEN** `budget_usd` tem `anthropic`, `openai` e `google` iguais a 14.0
- **AND** nenhuma combinação cita `gemini-3.8-flash` nem `gpt-5.6-terra`

### Requirement: Coleções do Qdrant recriadas sob demanda após o reset
Depois do reset, o sistema SHALL recriar as coleções do sistema no Qdrant quando elas forem necessárias, sem passo manual, de
modo que o reset possa apagá-las (o Qdrant de benchmark pode ser o mesmo de desenvolvimento, com `BENCHMARK_QDRANT_URL` igual
a `QDRANT_URL`).

#### Scenario: Índice semântico depois do reset
- **GIVEN** um Qdrant sem a coleção `KNOWLEDGE_COLLECTION` (recém-resetado)
- **WHEN** o índice semântico é inicializado
- **THEN** a coleção existe com a dimensão do modelo de embedding atual

#### Scenario: Indexador de documentos depois do reset
- **GIVEN** um Qdrant sem `geminiclaw_documents`
- **WHEN** o indexador de documentos é criado
- **THEN** a coleção é criada
