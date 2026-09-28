# Delta: session-continuity

## ADDED Requirements

### Requirement: Checkpoint incremental e atômico
O sistema SHALL gravar o avanço da sessão em `checkpoint.json` a cada mudança de plano, início
e fim de subtarefa, abandono de tarefa, checkpoint do Curator e fechamento, de forma atômica.

#### Scenario: Após cada subtarefa
- **WHEN** uma subtarefa termina
- **THEN** o checkpoint reflete seu status, tentativas, artefatos e resumo do resultado

#### Scenario: Queda durante a gravação
- **WHEN** a gravação é interrompida antes de concluir
- **THEN** o checkpoint anterior permanece íntegro e legível

### Requirement: Detecção de paradas inesperadas
O sistema SHALL detectar sessões interrompidas sem fechamento e registrá-las como tal.

#### Scenario: Queda de energia
- **GIVEN** uma sessão `active` sem batimento há mais de `SESSION_STALE_SECONDS`
- **WHEN** o sistema inicia
- **THEN** a sessão é marcada `interrompida`
- **AND** suas subtarefas em andamento são registradas como falhas de causa `infraestrutura`

### Requirement: Retomada a partir do checkpoint
O sistema SHALL retomar uma sessão a partir do seu checkpoint, em uma nova sessão ligada à
anterior, sem recomeçar do zero.

#### Scenario: Retomada após limite
- **GIVEN** uma sessão fechada por `limite_tokens` com 3 subtarefas concluídas e 2 pendentes
- **WHEN** o pesquisador executa `geminiclaw resume --session <id>`
- **THEN** uma nova sessão é criada com `continues_session_id=<id>`, orçamento novo e aresta `CONTINUA`
- **AND** as 3 subtarefas concluídas não são reexecutadas

#### Scenario: Continuar o projeto
- **WHEN** o pesquisador executa `geminiclaw continue --project <p>`
- **THEN** a sessão mais recente do projeto é retomada

#### Scenario: Pesquisa dada como resolvida
- **GIVEN** uma sessão fechada com `solucao_encontrada`
- **WHEN** o pesquisador tenta retomá-la
- **THEN** a CLI pede confirmação antes de continuar

### Requirement: Contexto de retomada completo
O sistema SHALL fornecer ao Researcher, na retomada, o estado do plano, as hipóteses abertas
com vereditos, os caminhos sem conclusão, a experiência relacionada do grafo e as
sinalizações pendentes.

#### Scenario: Caminho sem conclusão
- **GIVEN** um caminho registrado como sem conclusão com `proximo_passo_sugerido`
- **WHEN** a sessão é retomada
- **THEN** o contexto do Researcher contém esse caminho e o próximo passo sugerido

### Requirement: Artefatos anteriores legíveis, escrita isolada
O sistema SHALL permitir ler os artefatos das sessões anteriores da cadeia do mesmo projeto e
restringir a escrita à sessão atual.

#### Scenario: Leitura e escrita
- **WHEN** o Developer da sessão retomada lê um artefato da sessão anterior e tenta sobrescrevê-lo
- **THEN** a leitura funciona e a escrita na sessão anterior é recusada

### Requirement: Consolidação pendente concluída na retomada
O sistema SHALL executar a consolidação do Curator que ficou pendente na sessão anterior antes
do novo planejamento.

#### Scenario: Curator pendente
- **GIVEN** um checkpoint com `curator_pendente=true`
- **WHEN** a sessão é retomada
- **THEN** o Curator executa o fechamento da sessão anterior antes do replanejamento
