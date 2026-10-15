# Delta: usage-limits

Testes sem chamada paga: `UsageTracker` com `token_reader`, `cost_reader` e `clock` injetados; alocação de modelos simulada.

## MODIFIED Requirements

### Requirement: Orçamento definido pelo pesquisador
O sistema SHALL executar toda sessão sob um orçamento de tokens, tempo, custo em US$ (total e, opcionalmente, por provedor), retentativas da mesma tarefa e retentativas de conexão, com padrões configuráveis em `src/config.py` e ajuste por opções da CLI (`--max-tokens`, `--max-minutes`, `--max-cost-usd`). Cada limite de quantidade SHALL poder ser ajustado livremente para cima e SHALL ser desligado somente pelo modo sem limite confirmado pelo pesquisador; valor `<= 0` ou vazio SHALL falhar na inicialização (ADR 021 §5.4, rejeitada L).

#### Scenario: Orçamento pela CLI
- **WHEN** o pesquisador executa com `--max-tokens 100000 --max-minutes 30 --max-cost-usd 3`
- **THEN** a sessão grava em `payload["budget"]` e exibe esse orçamento e os demais limites com os valores de `config`

#### Scenario: Zero não desliga
- **GIVEN** `SESSION_MAX_COST_USD=0` no ambiente
- **WHEN** a configuração é carregada
- **THEN** a inicialização falha com mensagem que indica o modo sem limite como único jeito de desligar o limite

## ADDED Requirements

### Requirement: Limite de custo por sessão
O sistema SHALL somar o custo estimado de todas as chamadas da sessão, por provedor, e SHALL, ao atingir `SESSION_MAX_COST_USD × (1 − SESSION_CLOSING_RESERVE_PCT)` no total, ou o valor de um provedor em `SESSION_MAX_COST_USD_BY_PROVIDER`, parar de despachar trabalho e fechar a sessão com `motivo_parada = "limite_custo"`, checkpoint e consolidação (ADR 021 §5.4). Padrões: `SESSION_MAX_COST_USD=10.0`; `SESSION_MAX_COST_USD_BY_PROVIDER` vazio (só o total). O motivo `limite_cota_provedor` de `v18.7-benchmark-fixes` SHALL continuar existindo, com precedência menor que `limite_custo` no mesmo ponto de verificação.

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
Fora do modo sem limite, a sessão MUST NOT iniciar quando um modelo da alocação por papel tem localidade diferente de `local` e não tem preço conhecido (`get_price` devolve `None`); a mensagem SHALL citar o modelo e `LLM_PRICING_OVERRIDES`. Modelos `local` SHALL ter custo 0. Durante a sessão, uma chamada não local sem preço SHALL emitir `custo_nao_estimado` uma vez por modelo.

#### Scenario: Alocação com modelo sem preço
- **GIVEN** o papel `developer` alocado a `openai/modelo-sem-preco` e nenhuma entrada em `LLM_PRICING_OVERRIDES`
- **WHEN** a sessão vai iniciar sem `--unlimited`
- **THEN** a sessão não inicia e a mensagem cita `openai/modelo-sem-preco` e `LLM_PRICING_OVERRIDES`

#### Scenario: Modelo local
- **GIVEN** todos os papéis em modelos de localidade `local`
- **WHEN** a sessão inicia
- **THEN** ela inicia e o custo da sessão é 0

### Requirement: Variáveis de teto removidas falham na inicialização
Se `HYPOTHESES_PER_CYCLE`, `MAX_EXPLORATION_CYCLES`, `SOLUTION_MIN_VERDICT`, `MAX_AGENT_RUNS_PER_SESSION`, `MAX_CONTAINERS_PER_SESSION`, `MAX_PLANNING_RUNS_PER_SESSION`, `OPERATIONAL_THRESHOLD_AGENT_RUNS_PCT`, `OPERATIONAL_THRESHOLD_CONTAINER_COUNT_PCT` ou `OPERATIONAL_THRESHOLD_COST_USD` estiver definida no ambiente, a importação de `src/config.py` SHALL falhar com `ConfigurationError`, pelo mecanismo `check_removed_variables` de `v18.7-resource-monitor-config`, com um erro que lista cada variável encontrada e a ação a tomar, em vez de ignorá-la (ADR 021 §5.1; AGENTS.md §1.6).

#### Scenario: Teto de ciclos antigo no .env
- **GIVEN** `MAX_EXPLORATION_CYCLES=20` e `OPERATIONAL_THRESHOLD_COST_USD=5` no ambiente
- **WHEN** `src/config.py` é importado
- **THEN** a importação levanta erro que cita as duas variáveis, "ADR 021 §5.1" e `OPERATIONAL_THRESHOLD_COST_USAGE_PCT`
