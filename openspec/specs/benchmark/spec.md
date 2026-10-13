# Especificação: benchmark

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md)

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
O runner SHALL não expandir o pin `*` para os papéis `validator` e `reviewer`, SHALL recusar a
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
