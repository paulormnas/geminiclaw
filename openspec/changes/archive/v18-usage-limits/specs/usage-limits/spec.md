# Delta: usage-limits

## ADDED Requirements

### Requirement: Orçamento definido pelo pesquisador
O sistema SHALL executar toda sessão sob um orçamento de tokens, tempo, retentativas da mesma
tarefa e retentativas de conexão, com defaults configuráveis e ajuste por opções da CLI.

#### Scenario: Orçamento pela CLI
- **WHEN** o pesquisador executa com `--max-tokens 100000 --max-minutes 30`
- **THEN** a sessão grava e exibe esse orçamento e os demais limites com os valores de `config`

### Requirement: Contabilização completa
O sistema SHALL contabilizar os tokens de todos os agentes, inclusive o Curator, o tempo da
sessão, as retentativas por tarefa e as retentativas de conexão com provedores e com o
sandbox.

#### Scenario: Tokens do Curator
- **WHEN** o Curator consome 5 000 tokens
- **THEN** o consumo da sessão aumenta em 5 000

#### Scenario: Retentativa de conexão
- **WHEN** um provedor responde 503 e a chamada é repetida
- **THEN** o contador de retentativas de conexão da sessão aumenta em 1

### Requirement: Parada graciosa por tokens e tempo
O sistema SHALL, ao atingir o limite de tokens (descontada a reserva de fechamento) ou de
tempo, parar de despachar trabalho, concluir ou cancelar o que está em andamento e executar o
fechamento.

#### Scenario: Limite de tokens
- **WHEN** o consumo atinge `max_tokens × (1 − closing_reserve_pct)`
- **THEN** nenhuma nova chamada de exploração é feita
- **AND** o fechamento é executado com a reserva, e `motivo_parada="limite_tokens"`

#### Scenario: Limite de tempo
- **WHEN** o tempo da sessão atinge `max_minutes`
- **THEN** subtarefas em andamento têm até `LIMIT_GRACE_SECONDS` para terminar, as demais são canceladas, e `motivo_parada="limite_tempo"`

### Requirement: Retentativas abandonam a tarefa, não a sessão
O sistema SHALL abandonar apenas a tarefa que atingir o limite de retentativas, mantendo o
restante da sessão em execução.

#### Scenario: Tarefa abandonada
- **GIVEN** um DAG com duas ramificações independentes
- **WHEN** uma tarefa da primeira atinge `max_task_retries`
- **THEN** ela é marcada `abandonada` e a segunda ramificação continua

#### Scenario: Todas abandonadas
- **WHEN** todas as tarefas pendentes são abandonadas
- **THEN** a sessão fecha com `motivo_parada="limite_retentativas"`

### Requirement: Parada por retentativas de conexão
O sistema SHALL encerrar a sessão com fechamento quando as retentativas de conexão atingirem o
limite.

#### Scenario: Infraestrutura instável
- **WHEN** as retentativas de conexão atingem `max_connection_retries`
- **THEN** a sessão executa o fechamento com `motivo_parada="limite_conexao"`

### Requirement: Fechamento sempre registra o avanço
O sistema SHALL gravar o checkpoint determinístico mesmo quando a reserva de tokens se esgota.

#### Scenario: Reserva esgotada
- **WHEN** a reserva acaba antes do Curator concluir
- **THEN** o checkpoint é gravado e a consolidação do Curator fica pendente para a próxima execução

### Requirement: Fonte única de limites
O `AutonomousLoop` SHALL ler limites exclusivamente de `src/config.py`.

#### Scenario: Default de retentativas
- **GIVEN** nenhuma variável de ambiente definida
- **WHEN** o loop inicializa
- **THEN** o limite de retentativas por tarefa é o default de `config` (3)
