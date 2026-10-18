# Especificação: usage-limits

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18-usage-limits`](../../changes/archive/v18-usage-limits/proposal.md), [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

## Requirements

### Requirement: Orçamento definido pelo pesquisador
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O sistema SHALL executar toda sessão sob um orçamento de tokens, tempo, custo em US$ (total e, opcionalmente, por provedor), retentativas da mesma tarefa e retentativas de conexão, com padrões configuráveis em `src/config.py` e ajuste por opções da CLI (`--max-tokens`, `--max-minutes`, `--max-cost-usd`). Cada limite de quantidade SHALL poder ser ajustado livremente para cima e SHALL ser desligado somente pelo modo sem limite confirmado pelo pesquisador; valor `<= 0` ou vazio SHALL falhar na inicialização (ADR 021 §5.4, rejeitada L).

#### Scenario: Orçamento pela CLI
- **WHEN** o pesquisador executa com `--max-tokens 100000 --max-minutes 30 --max-cost-usd 3`
- **THEN** a sessão grava em `payload["budget"]` e exibe esse orçamento e os demais limites com os valores de `config`

#### Scenario: Zero não desliga
- **GIVEN** `SESSION_MAX_COST_USD=0` no ambiente
- **WHEN** a configuração é carregada
- **THEN** a inicialização falha com mensagem que indica o modo sem limite como único jeito de desligar o limite

### Requirement: Contabilização completa
_Origem: [`v18-usage-limits`](../../changes/archive/v18-usage-limits/proposal.md)_
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
_Origem: [`v18-usage-limits`](../../changes/archive/v18-usage-limits/proposal.md)_
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
_Origem: [`v18-usage-limits`](../../changes/archive/v18-usage-limits/proposal.md)_
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
_Origem: [`v18-usage-limits`](../../changes/archive/v18-usage-limits/proposal.md)_
O sistema SHALL encerrar a sessão com fechamento quando as retentativas de conexão atingirem o
limite.

#### Scenario: Infraestrutura instável
- **WHEN** as retentativas de conexão atingem `max_connection_retries`
- **THEN** a sessão executa o fechamento com `motivo_parada="limite_conexao"`

### Requirement: Fechamento sempre registra o avanço
_Origem: [`v18-usage-limits`](../../changes/archive/v18-usage-limits/proposal.md)_
O sistema SHALL gravar o checkpoint determinístico mesmo quando a reserva de tokens se esgota.

#### Scenario: Reserva esgotada
- **WHEN** a reserva acaba antes do Curator concluir
- **THEN** o checkpoint é gravado e a consolidação do Curator fica pendente para a próxima execução

### Requirement: Fonte única de limites
_Origem: [`v18-usage-limits`](../../changes/archive/v18-usage-limits/proposal.md)_
O `AutonomousLoop` SHALL ler limites exclusivamente de `src/config.py`.

#### Scenario: Default de retentativas
- **GIVEN** nenhuma variável de ambiente definida
- **WHEN** o loop inicializa
- **THEN** o limite de retentativas por tarefa é o default de `config` (3)

### Requirement: Parada por cota ou gasto esgotado no provedor
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
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
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
O contador de retentativas de conexão lido pelo `UsageTracker` com o id da sessão mestra SHALL incluir as retentativas emitidas pelos provedores durante a execução de agentes em processo e do planejamento.

#### Scenario: Limite de conexão com agente em processo
- **GIVEN** `SESSION_MAX_CONNECTION_RETRIES=3` e um provedor simulado que responde 503 em todas as chamadas, executado dentro do `AgentRuntime` com telemetria em banco de teste
- **WHEN** o laço autônomo executa o ciclo
- **THEN** a sessão fecha com `motivo_parada="limite_conexao"`

### Requirement: Limite de custo por sessão
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O sistema SHALL somar o custo estimado de todas as chamadas da sessão, por provedor, inclusive as da consulta do terminal ao Researcher (origem `consulta_terminal`, de `v18.7-session-events-terminal`; decisão do pesquisador, 2026-10-15), e SHALL, ao atingir `SESSION_MAX_COST_USD × (1 − SESSION_CLOSING_RESERVE_PCT)` no total, ou o valor de um provedor em `SESSION_MAX_COST_USD_BY_PROVIDER`, parar de despachar trabalho e fechar a sessão com `motivo_parada = "limite_custo"`, checkpoint e consolidação (ADR 021 §5.4). Padrões: `SESSION_MAX_COST_USD=20.0`; `SESSION_MAX_COST_USD_BY_PROVIDER` vazio (só o total). O motivo `limite_cota_provedor` de `v18.7-benchmark-fixes` SHALL continuar existindo, com precedência menor que `limite_custo` no mesmo ponto de verificação.

#### Scenario: Teto total atingido
- **GIVEN** `max_cost_usd = 2.0`, `closing_reserve_pct = 0.05` e um leitor de custo simulado que devolve `{"anthropic": 1.20, "openai": 0.71}`
- **WHEN** o laço verifica os limites antes de um novo ciclo
- **THEN** `LimitStatus.cost_exhausted` é verdadeiro (1.91 ≥ 1.90) e a sessão fecha com `motivo_parada = "limite_custo"`

#### Scenario: Teto por provedor
- **GIVEN** `SESSION_MAX_COST_USD_BY_PROVIDER="google=1.0"`, `max_cost_usd = 10.0` e custo `{"google": 1.0, "anthropic": 0.2}`
- **WHEN** os limites são verificados
- **THEN** a sessão fecha com `limite_custo` e `cost_exhausted_provider = "google"`

#### Scenario: Formato inválido
- **WHEN** `SESSION_MAX_COST_USD_BY_PROVIDER="google=abc"`
- **THEN** a inicialização falha com erro de configuração

#### Scenario: Precedência sobre a cota do provedor
- **GIVEN** no mesmo ponto de verificação o custo da sessão atingiu o teto e há parada pendente `limite_cota_provedor`
- **WHEN** `LimitStatus.stop_reason` é calculado
- **THEN** o motivo é `limite_custo`

### Requirement: Modelo sem preço impede o início
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
Fora do modo sem limite, a sessão MUST NOT iniciar quando um modelo alcançável pelo roteamento, isto é, da alocação por papel ou de reserva (`GOOGLE_FALLBACK_MODEL` e equivalentes de cada provedor), tem localidade diferente de `local` e não tem preço conhecido (`get_price` devolve `None`); a mensagem SHALL citar o modelo e `LLM_PRICING_OVERRIDES`. Modelos `local` SHALL ter custo 0. Durante a sessão, uma chamada não local sem preço SHALL emitir `custo_nao_estimado` uma vez por modelo.

#### Scenario: Alocação com modelo sem preço
- **GIVEN** o papel `developer` alocado a `openai/modelo-sem-preco` e nenhuma entrada em `LLM_PRICING_OVERRIDES`
- **WHEN** a sessão vai iniciar sem `--unlimited`
- **THEN** a sessão não inicia e a mensagem cita `openai/modelo-sem-preco` e `LLM_PRICING_OVERRIDES`

#### Scenario: Modelo de reserva sem preço
- **GIVEN** todos os papéis em modelos com preço e `GOOGLE_FALLBACK_MODEL` apontando para um modelo não local sem preço
- **WHEN** a sessão vai iniciar sem `--unlimited`
- **THEN** a sessão não inicia e a mensagem cita o modelo de reserva e `LLM_PRICING_OVERRIDES`

#### Scenario: Modelo local
- **GIVEN** todos os papéis e modelos de reserva em modelos de localidade `local`
- **WHEN** a sessão inicia
- **THEN** ela inicia e o custo da sessão é 0

### Requirement: Variáveis de teto removidas falham na inicialização
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
Se `HYPOTHESES_PER_CYCLE`, `MAX_EXPLORATION_CYCLES`, `SOLUTION_MIN_VERDICT`, `MAX_AGENT_RUNS_PER_SESSION`, `MAX_CONTAINERS_PER_SESSION`, `MAX_PLANNING_RUNS_PER_SESSION`, `OPERATIONAL_THRESHOLD_AGENT_RUNS_PCT`, `OPERATIONAL_THRESHOLD_CONTAINER_COUNT_PCT` ou `OPERATIONAL_THRESHOLD_COST_USD` estiver definida no ambiente, a importação de `src/config.py` SHALL falhar com `ConfigurationError`, pelo mecanismo `check_removed_variables` de `v18.7-resource-monitor-config`, com um erro que lista cada variável encontrada e a ação a tomar, em vez de ignorá-la (ADR 021 §5.1; AGENTS.md §1.6).

#### Scenario: Teto de ciclos antigo no .env
- **GIVEN** `MAX_EXPLORATION_CYCLES=20` e `OPERATIONAL_THRESHOLD_COST_USD=5` no ambiente
- **WHEN** `src/config.py` é importado
- **THEN** a importação levanta erro que cita as duas variáveis, "ADR 021 §5.1" e `OPERATIONAL_THRESHOLD_COST_USAGE_PCT`
