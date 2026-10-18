# Especificação: benchmark

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18.6-benchmark-harness`](../../changes/archive/v18.6-benchmark-harness/proposal.md), [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md), [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O benchmark SHALL classificar o `motivo_parada` de cada execução em `limite`, `erro`, `interrupcao`, `criterio_pesquisa`, `hipoteses_nao_testadas` ou `planos_rejeitados`. Somente `limite`, `erro` e `interrupcao` SHALL ser anomalia. `versao_modelo` SHALL ser `limite` (anomalia: a comparação exige sessões completas com a versão declarada; `v18.7-benchmark-fixes`). `planos_rejeitados` SHALL ter classe própria `planos_rejeitados`, identificável nos relatórios e não anomalia, como `hipoteses_nao_testadas`; os dois motivos só ocorrem na bateria com `ON_PLAN_REJECTIONS=parar` e `ON_MODEL_VERSION_CHANGE=parar`. `limite_custo` SHALL ser `limite`; `limite_cota_provedor` SHALL ser `limite` e listado no relatório com o provedor e o modelo do evento `cota_provedor_esgotada`; `saturacao` SHALL ser `criterio_pesquisa`; `limite_ciclos` e `limite_execucoes`, presentes só em resultados antigos, SHALL continuar `limite`. `hipoteses_nao_testadas` SHALL ser tratado como parada de pesquisa, listado no relatório e nunca contado como erro. O resumo de interações SHALL contar os motivos de reprovação de subtarefa registrados (ADR 021 §5, "Mudanças OpenSpec exigidas").

#### Scenario: Classificação
- **WHEN** `stop_class` recebe `limite_tokens`, `limite_custo`, `limite_cota_provedor`, `limite_ciclos`, `erro`, `interrompida_pesquisador`, `solucao_encontrada`, `saturacao`, `hipoteses_nao_testadas`, `versao_modelo` e `planos_rejeitados`
- **THEN** devolve `limite`, `limite`, `limite`, `limite`, `erro`, `interrupcao`, `criterio_pesquisa`, `criterio_pesquisa`, `hipoteses_nao_testadas`, `limite` e `planos_rejeitados`

#### Scenario: Bateria usa a política parar para planos rejeitados
- **GIVEN** um ambiente base com `ON_PLAN_REJECTIONS=explorar`
- **WHEN** `build_env` monta o ambiente do subprocesso de uma combinação
- **THEN** o ambiente devolvido tem `ON_PLAN_REJECTIONS == "parar"` e o ambiente base não é alterado

#### Scenario: Saturação não é anomalia
- **GIVEN** uma execução com `stop_reason = "saturacao"` e `exit 0`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado

#### Scenario: Planos rejeitados não é anomalia
- **GIVEN** uma execução com `stop_reason = "planos_rejeitados"` e `status="exit 3"`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado e o relatório a lista como `planos_rejeitados`

#### Scenario: Limite de custo é anomalia
- **GIVEN** uma execução com `stop_reason = "limite_custo"`
- **WHEN** `anomalies()` avalia a execução
- **THEN** a lista contém o problema de sessão fechada por `limite_custo` antes de concluir

#### Scenario: Parada por hipótese não testada não é anomalia
- **GIVEN** uma execução com `stop_reason = "hipoteses_nao_testadas"` e `exit 0`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado

#### Scenario: Parada por cota é anomalia identificada
- **GIVEN** uma execução com `stop_reason = "limite_cota_provedor"` e um evento `cota_provedor_esgotada` com `provedor="google"` e `modelo="gemini-4-argon"`
- **WHEN** o relatório é gerado
- **THEN** a execução aparece como anomalia de parada e o texto cita `google/gemini-4-argon`

#### Scenario: Relatório lista a parada
- **GIVEN** duas execuções da combinação `c1`, uma fechada por `hipoteses_nao_testadas`
- **WHEN** o relatório é gerado
- **THEN** há uma seção que cita `c1` e a repetição afetada

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
registrado, a execução cujo provedor já atingiu o teto **na sua rodada** (repetição): o gasto de cada rodada começa do zero e o
teto não é acumulado entre rodadas. A matriz oficial da V18.6 SHALL usar US$ 14 por provedor e por rodada. Referência: pedido do
pesquisador, 2026-10-14 (limite por rodada, não pelo teste completo).

#### Scenario: Teto do Google atingido
- **GIVEN** `budget_usd.google = 14.0` e gasto de US$ 14,20 em combinações com `google/...` na rodada 1
- **WHEN** a próxima combinação da rodada 1 que usa `google` vai rodar
- **THEN** ela é registrada como `skipped` com "orçamento de google esgotado"

#### Scenario: Nova rodada zera o gasto
- **GIVEN** o teto do Google esgotado na rodada 1
- **WHEN** uma combinação que usa `google` vai rodar na rodada 2 sem gasto nela
- **THEN** ela roda

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

### Requirement: Tabela de egresso com a grandeza limitada
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
A tabela de métricas de operação do relatório (`render_operation`) SHALL trazer as colunas "Egresso total (bytes)", "Saídas novas (bytes)" e "Limite de saídas (bytes)", nessa ordem, preenchidas com `egresso.bytes_total`, `egresso.bytes_limitados` e `egresso.limite_bytes` (`sem limite` quando nulo). Resultado sem `bytes_limitados` (execução anterior a esta mudança) SHALL mostrar `-` na coluna de saídas novas. A coluna "Cadeia de execuções" SHALL mostrar a primeira causa não nula de `cadeia.motivos` entre parênteses quando o resultado for `divergente`.

#### Scenario: Colunas de egresso
- **GIVEN** um resultado com `bytes_total=3942301`, `bytes_limitados=412000` e `limite_bytes=2000000`
- **WHEN** `render_operation` gera a tabela
- **THEN** a linha da combinação contém `| 3942301 | 412000 | 2000000 |` nas três colunas de egresso

#### Scenario: Resultado antigo
- **GIVEN** um resultado gravado antes desta mudança, sem `bytes_limitados`
- **WHEN** `render_operation` gera a tabela
- **THEN** a coluna "Saídas novas (bytes)" mostra `-` e a tabela é gerada sem erro

#### Scenario: Modo sem limite
- **GIVEN** um resultado com `limite_bytes` nulo
- **WHEN** `render_operation` gera a tabela
- **THEN** a coluna "Limite de saídas (bytes)" mostra `sem limite`

#### Scenario: Causa da cadeia divergente
- **GIVEN** um resultado com `cadeia.resultado="divergente"` e `cadeia.motivos.arquivos_alterados=2`
- **WHEN** `render_operation` gera a tabela
- **THEN** a coluna "Cadeia de execuções" mostra `divergente (arquivos_alterados)`

### Requirement: Teto de custo da sessão declarado na matriz
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
A matriz do benchmark SHALL declarar `SESSION_MAX_COST_USD` em `env` (o teto por sessão, distinto do `budget_usd` por provedor e por rodada do runner), e o runner SHALL recusar, antes de qualquer execução e sem apagar nada, a matriz sem esse valor ou com valor não positivo (ADR 021 §5.4).

#### Scenario: Matriz sem teto de custo
- **GIVEN** uma matriz cujo `env` não tem `SESSION_MAX_COST_USD`
- **WHEN** o runner valida a matriz
- **THEN** o runner termina com erro que cita `SESSION_MAX_COST_USD` e nenhuma execução começa

#### Scenario: Matriz com teto
- **GIVEN** `env.SESSION_MAX_COST_USD = "5"`
- **WHEN** uma combinação roda
- **THEN** o subprocesso recebe `SESSION_MAX_COST_USD=5`
