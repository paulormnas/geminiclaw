# Delta: operation-metrics

## MODIFIED Requirements

### Requirement: Modo sem limite explícito
O sistema SHALL oferecer o modo sem limite apenas por opção explícita do pesquisador, por sessão (`--unlimited`) ou por projeto, e SHALL exigir confirmação no início de cada execução, no terminal (ADR 023 §1) ou pelo gate persistente quando a sessão já roda em segundo plano. O modo SHALL NOT ser ativado por padrão, por variável de ambiente, por configuração ou por qualquer agente. O texto da confirmação SHALL dizer que tokens, tempo, custo e volume de egresso não interrompem a sessão e que, sem limites, não há parada automática garantida: a sessão segue até o objetivo (conforme a política), a falta de caminho, a saturação, o pesquisador ou uma falha. O texto SHALL dizer também que, no `auto`, a sessão pode rodar indefinidamente e que só `wait_for_health` e `SANDBOX_MIN_FREE_BYTES` protegem o hardware (ADR 021 §5.4, §5.5; parecer de segurança, item 5).

#### Scenario: Ativação por sessão confirmada
- **WHEN** o pesquisador executa `geminiclaw --unlimited "<prompt>"` e digita "sem limite" na confirmação
- **THEN** a sessão inicia com `UsageBudget(unlimited=True)`, `max_cost_usd = None`, e `payload["budget"]` registra `unlimited=true`, a origem `cli` e o instante da confirmação

#### Scenario: Texto da confirmação
- **WHEN** a confirmação é exibida
- **THEN** o texto contém "custo" e "não há parada automática garantida"
- **AND** o texto contém "indefinidamente", `wait_for_health` e `SANDBOX_MIN_FREE_BYTES`

#### Scenario: Confirmação ausente
- **WHEN** o pesquisador executa com `--unlimited` e responde outra coisa, ou não há terminal interativo
- **THEN** a sessão não inicia e a CLI sai com mensagem acionável
- **AND** a sessão não é iniciada no modo limitado em seu lugar

#### Scenario: Agente não ativa o modo
- **GIVEN** uma sessão limitada
- **WHEN** um agente produz plano, resposta ou mensagem pedindo execução sem limite
- **THEN** o orçamento da sessão permanece igual ao do início

#### Scenario: Opções incompatíveis
- **WHEN** o pesquisador combina `--unlimited` com `--max-tokens`, `--max-minutes`, `--max-egress-bytes` ou `--max-cost-usd`
- **THEN** a CLI recusa o orçamento com erro e não inicia a sessão

### Requirement: Limites removidos e mantidos no modo sem limite
No modo sem limite, o sistema SHALL NOT parar a sessão por tokens, tempo, custo ou volume de egresso, e SHALL manter os limites de retentativas da mesma tarefa e de conexão, a parada pelo objetivo do `Problema` conforme a política, a falta de caminhos, as rejeições consecutivas do Validator, o disjuntor de progresso zero, a estagnação com intervenção e a saturação (ADR 021 §5.4, §5.5).

#### Scenario: Tokens, tempo e custo não param
- **GIVEN** uma sessão no modo sem limite
- **WHEN** o consumo ultrapassa `SESSION_MAX_TOKENS`, o tempo ultrapassa `SESSION_MAX_MINUTES` e o custo ultrapassa `SESSION_MAX_COST_USD`
- **THEN** a sessão continua despachando trabalho

#### Scenario: Retentativas continuam limitadas
- **GIVEN** uma sessão no modo sem limite
- **WHEN** as retentativas de conexão atingem `max_connection_retries`
- **THEN** a sessão fecha com `motivo_parada="limite_conexao"`

#### Scenario: Objetivo atingido
- **GIVEN** uma sessão `auto` no modo sem limite e política `parar`
- **WHEN** o objetivo é atingido
- **THEN** a sessão fecha com `motivo_parada="solucao_encontrada"`

#### Scenario: Saturação continua valendo
- **GIVEN** uma sessão `auto` no modo sem limite com a saturação do `limiar` confirmada depois das intervenções
- **WHEN** a paciência se esgota
- **THEN** a sessão fecha com `motivo_parada="saturacao"`

### Requirement: Avisos G5 sobre o orçamento efetivo
O sistema SHALL calcular os percentuais dos avisos operacionais da Spec G5 sobre o orçamento efetivo da sessão, inclusive o custo (`OPERATIONAL_THRESHOLD_COST_USAGE_PCT`, padrão 0.80, fração de `max_cost_usd`), SHALL omitir os avisos de tokens, tempo e custo no modo sem limite e MUST NOT emitir aviso de execuções de agente (não há limite de execuções, ADR 021 §5.1).

#### Scenario: Override da CLI respeitado
- **GIVEN** `SESSION_MAX_TOKENS=500000` e a sessão iniciada com `--max-tokens 100000`
- **WHEN** o consumo chega a 80 000 tokens
- **THEN** o aviso de `token_usage_pct` (0,80) é emitido

#### Scenario: Aviso de custo por percentual
- **GIVEN** `--max-cost-usd 5` e `OPERATIONAL_THRESHOLD_COST_USAGE_PCT=0.80`
- **WHEN** o custo estimado chega a US$ 4,00
- **THEN** o aviso de `cost_usage_pct` (0,80) é emitido

## ADDED Requirements

### Requirement: Custo e execuções nas métricas de operação
O grupo `custo_recursos` SHALL registrar `custo_limite_usd` (ou `null` no modo sem limite), `custo_por_provedor` (US$ por provedor, `null` para provedor só com chamadas sem preço), `custo_limite_por_provedor` e `execucoes_agente` (`planejamento`, `execucao`). `describe_stop_reason` SHALL descrever `limite_custo` ("limite de custo da sessão atingido") e `saturacao` ("a melhora possível ficou abaixo do erro da medida depois das intervenções"), mantendo a descrição de `limite_cota_provedor` de `v18.7-benchmark-fixes`.

#### Scenario: Custo por provedor
- **GIVEN** uma sessão com custo `{"anthropic": 1.2, "google": 0.4}` e `max_cost_usd = 10`
- **WHEN** as métricas são agregadas
- **THEN** `custo_recursos.custo_por_provedor` é `{"anthropic": 1.2, "google": 0.4}` e `custo_limite_usd` é 10

#### Scenario: Descrição dos motivos
- **WHEN** `describe_stop_reason` recebe `limite_custo`, `saturacao` e `limite_cota_provedor`
- **THEN** os três textos são não vazios e distintos
