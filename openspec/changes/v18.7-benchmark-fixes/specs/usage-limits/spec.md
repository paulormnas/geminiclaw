# Delta: usage-limits

## ADDED Requirements

### Requirement: Parada por cota ou gasto esgotado no provedor
_Origem: `v18.7-benchmark-fixes` (achado 4 da bateria V18.6); relacionado ao ADR 019 §11 e ao ADR 010._
O sistema SHALL encerrar a sessão com fechamento e `motivo_parada="limite_cota_provedor"` no primeiro ponto de verificação de limites depois que qualquer provedor registrar `ProviderQuotaExhausted` para a sessão, sem despachar nova subtarefa, sem replanejar e sem chamar LLM no fechamento (consolidação pendente para a retomada). O `AgentRuntime` SHALL devolver `AgentResult(status="error", error_category="cota_provedor")` para o agente interrompido. O sistema SHALL gravar uma única vez o evento `cota_provedor_esgotada` com `provedor`, `modelo`, `status` e `detalhe` (truncado em 300 caracteres), e o checkpoint SHALL trazer `motivo_parada` e `cota_provedor` (`provedor`, `modelo`, `status`). `limite_cota_provedor` SHALL ter precedência sobre `limite_conexao` quando os dois ocorrerem.

#### Scenario: Teto de gasto durante a execução de subtarefas
- **GIVEN** uma sessão autônoma com duas subtarefas no plano e um provedor simulado do Developer que levanta `ProviderQuotaExhausted` na primeira chamada
- **WHEN** o laço autônomo executa o ciclo
- **THEN** a sessão fecha com `motivo_parada="limite_cota_provedor"`
- **AND** o Researcher não é chamado de novo para replanejar e a segunda subtarefa não é despachada
- **AND** o Summarizer não é chamado e o checkpoint traz `consolidation_pending=true` e `cota_provedor.provedor` igual ao provedor simulado

#### Scenario: Cota esgotada no planejamento
- **GIVEN** um provedor simulado do Researcher que levanta `ProviderQuotaExhausted`
- **WHEN** o laço autônomo inicia o primeiro ciclo
- **THEN** a sessão fecha com `motivo_parada="limite_cota_provedor"` sem contar o ciclo como plano rejeitado

#### Scenario: Precedência sobre limite de conexão
- **GIVEN** um `UsageTracker` com retentativas de conexão no limite e um esgotamento de cota registrado para a sessão
- **WHEN** `check()` é chamado
- **THEN** `stop_reason` é `limite_cota_provedor`

#### Scenario: Evento único
- **GIVEN** três chamadas simultâneas que levantam `ProviderQuotaExhausted` na mesma sessão
- **WHEN** os erros são registrados
- **THEN** há exatamente um evento `cota_provedor_esgotada` na sessão

#### Scenario: Mensagem acionável
- **WHEN** a sessão fecha com `limite_cota_provedor` para o provedor `google`, modelo `gemini-4-argon`
- **THEN** a CLI imprime o motivo, o provedor, o modelo e o comando `geminiclaw resume --session <id>`

#### Scenario: Nova sessão não herda a parada
- **GIVEN** uma sessão anterior no mesmo processo fechada por `limite_cota_provedor`
- **WHEN** uma nova sessão começa
- **THEN** `quota_stop_for` da nova sessão devolve `None`

### Requirement: Retentativas de conexão de agentes em processo contam para a sessão
_Origem: `v18.7-benchmark-fixes`; torna efetivo o requisito "Parada por retentativas de conexão" de `v18-usage-limits`._
O contador de retentativas de conexão lido pelo `UsageTracker` com o id da sessão mestra SHALL incluir as retentativas emitidas pelos provedores durante a execução de agentes em processo e do planejamento.

#### Scenario: Limite de conexão com agente em processo
- **GIVEN** `SESSION_MAX_CONNECTION_RETRIES=3` e um provedor simulado que responde 503 em todas as chamadas, executado dentro do `AgentRuntime` com telemetria em banco de teste
- **WHEN** o laço autônomo executa o ciclo
- **THEN** a sessão fecha com `motivo_parada="limite_conexao"`
