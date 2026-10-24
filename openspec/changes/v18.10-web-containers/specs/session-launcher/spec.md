# Delta: session-launcher

## ADDED Requirements

### Requirement: Fila de pedidos de início
O sistema SHALL guardar pedidos de início de pesquisa em `session_start_requests`, com no máximo um pedido aberto por projeto, e MUST aceitar só os modos `semi` e `auto` (ADR 027 §9).

#### Scenario: Segundo pedido no mesmo projeto
- **GIVEN** um pedido `pendente` no projeto P
- **WHEN** outro pedido é criado para P
- **THEN** a criação falha com `pedido_em_andamento` e só existe um pedido aberto

#### Scenario: Modo assisted recusado no banco
- **WHEN** um `INSERT` direto usa `modo='assisted'`
- **THEN** o banco recusa pelo `CHECK`

### Requirement: Lançador no host inicia como o REPL
O lançador SHALL assumir um pedido por vez com `FOR UPDATE SKIP LOCKED`, revalidar o pedido, aplicar as verificações do REPL e iniciar a sessão por `LaunchSpec` e `spawn_session`, MUST NOT aceitar modo sem limite, e MUST rodar fora de container.

#### Scenario: Pedido válido vira sessão
- **GIVEN** projeto ativo com Problema confirmado e nenhuma outra pesquisa viva
- **WHEN** um pedido `semi` é assumido
- **THEN** `spawn_session` é chamado com `foreground=False`, o arquivo de lançamento tem modo `0600`, e o pedido termina `lancado` com o `session_id`

#### Scenario: Outra pesquisa viva sem confirmação
- **GIVEN** uma sessão viva no Mac
- **WHEN** um pedido sem `confirmacoes.outra_em_execucao` é assumido
- **THEN** o pedido termina `recusado`, `motivo='outra_em_execucao'`, `detalhes` com as sessões, e nada é iniciado

#### Scenario: Confirmação aceita
- **WHEN** um novo pedido traz `confirmacoes.outra_em_execucao=true`
- **THEN** a sessão é iniciada

#### Scenario: Projeto arquivado
- **GIVEN** projeto com `status='arquivado'`
- **THEN** o pedido termina `recusado` com `motivo='projeto_arquivado'`

#### Scenario: Pedido velho expira
- **GIVEN** pedido `pendente` criado há mais de `LAUNCHER_REQUEST_TTL_SECONDS`
- **WHEN** o lançador sobe
- **THEN** o pedido vira `expirado` e nenhuma sessão é iniciada

#### Scenario: Lançador morre com pedido assumido
- **GIVEN** pedido `assumido` há mais de `LAUNCHER_CLAIM_TIMEOUT_SECONDS`
- **THEN** o pedido vira `falhou` com `motivo='lancador_interrompido'` e não é relançado

#### Scenario: Processo da sessão não registra
- **WHEN** o processo sai antes de registrar a sessão
- **THEN** o pedido vira `falhou` com `motivo='processo_nao_registrou'`, e o banco não recebe o log

#### Scenario: Dois lançadores
- **GIVEN** um lançador com a trava
- **WHEN** outro inicia
- **THEN** o segundo sai com erro que cita `logs/launcher.lock`

#### Scenario: Dois consumidores na fila
- **GIVEN** dois pedidos de projetos diferentes e duas conexões assumindo ao mesmo tempo
- **THEN** cada pedido é assumido uma vez só
