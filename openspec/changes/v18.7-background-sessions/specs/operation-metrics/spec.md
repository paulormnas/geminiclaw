# Delta: operation-metrics

## MODIFIED Requirements

### Requirement: Avisos periódicos de consumo
_Origem: [`v18.5-operation-metrics`](../../../archive/v18.5-operation-metrics/proposal.md); modificado por `v18.7-background-sessions` (ADR 023 §1.10)_
No modo sem limite, o sistema SHALL avisar o pesquisador do consumo acumulado a cada
`UNLIMITED_NOTICE_INTERVAL_MINUTES` minutos ou a cada `UNLIMITED_NOTICE_TOKEN_STEP` tokens, o
que ocorrer primeiro, em todos os modos de sessão. O aviso SHALL ser registrado no log e na saída da sessão e
MUST NOT bloquear nem ler o terminal em nenhum modo (o processo da sessão não lê a entrada padrão); a variável
`OPERATIONAL_THRESHOLD_WAIT_SECONDS` deixa de existir.

#### Scenario: Aviso por tempo
- **GIVEN** `UNLIMITED_NOTICE_INTERVAL_MINUTES=15`
- **WHEN** passam 15 minutos desde o início ou o último aviso
- **THEN** a saída da sessão mostra tempo, tokens, custo (ou "não informado"), bytes de egresso e ciclos concluídos
- **AND** o evento `unlimited_notice` é registrado e `operation_metrics.modo_sem_limite.avisos_emitidos` aumenta

#### Scenario: Aviso por tokens
- **GIVEN** `UNLIMITED_NOTICE_TOKEN_STEP=500000`
- **WHEN** o total de tokens cruza 500 000
- **THEN** um aviso é emitido, mesmo antes do intervalo de tempo

#### Scenario: Aviso no modo assistido não pergunta
- **GIVEN** uma sessão `assisted` no modo sem limite
- **WHEN** um aviso é emitido
- **THEN** a sessão continua sem esperar resposta e sem ler a entrada padrão

#### Scenario: Cadência inválida
- **WHEN** `UNLIMITED_NOTICE_INTERVAL_MINUTES` ou `UNLIMITED_NOTICE_TOKEN_STEP` é zero ou negativo
- **THEN** a inicialização falha com erro de configuração
