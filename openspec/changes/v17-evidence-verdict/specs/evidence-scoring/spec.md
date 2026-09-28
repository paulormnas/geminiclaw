# Delta: evidence-scoring

## ADDED Requirements

### Requirement: Veredito de −1 a +1
O sistema SHALL calcular, para cada hipótese, um veredito em [−1, +1] pela fórmula do ADR 015
§9.5, em que valores positivos indicam que funciona, negativos que não funciona, e a
confiança é o valor absoluto.

#### Scenario: Exemplo completo do ADR 015
- **GIVEN** as evidências E1–E6 do ADR 015 §9.6, δ = 0,05 e baseline R² = 0,70
- **WHEN** `compute_verdict` é chamado
- **THEN** `α = 3,225`, `β = 1,8` e o veredito é 0,17 ± 0,005 com leitura `funciona_fraca`

#### Scenario: Refutação robusta
- **GIVEN** 4 resultados negativos independentes com q = m = 1
- **WHEN** o veredito é calculado
- **THEN** o veredito é −0,44 ± 0,005 e o tipo de descoberta sugerido é `nao_funciona`

#### Scenario: Sem evidência
- **WHEN** não há tentativas
- **THEN** o veredito é 0 e a leitura é `insuficiente`

### Requirement: Pesos objetivos
O sistema SHALL derivar cada peso de dados registrados (status do Validator, arquivos do
contrato, métricas, baseline, `delta_min`, nó, sessão, semente, dataset e configuração), sem
julgamento de LLM.

#### Scenario: Qualidade da validação
- **WHEN** um resultado validado não tem semente registrada
- **THEN** seu `q` é 0,7

#### Scenario: Magnitude
- **GIVEN** δ = 0,05
- **WHEN** Δ = 0,05, Δ = 0,10 e Δ = 0,01
- **THEN** `m` é 0,5 (positivo), 1,0 (positivo) e 0,8 (negativo), respectivamente

#### Scenario: Independência
- **WHEN** três resultados vêm de um nó novo, de nova sessão no mesmo nó e de nova semente na mesma sessão
- **THEN** seus `d` são 1,0, 0,5 e 0,2

#### Scenario: Dataset novo vale como nó novo
- **WHEN** um resultado vem do mesmo nó, mas de um dataset ainda não usado para a hipótese
- **THEN** seu `d` é 1,0

#### Scenario: Penalidade de busca
- **GIVEN** 4 configurações tentadas e um positivo sem réplica em outra sessão ou nó
- **WHEN** o veredito é calculado
- **THEN** o `b` desse positivo é 0,59 ± 0,005
- **AND** após uma réplica positiva da mesma configuração em outro nó, o `b` passa a 1,0

### Requirement: Tentativas sem resultado tratadas por causa
O sistema SHALL tratar tentativas sem resultado conforme a causa: infraestrutura não afeta o
veredito; falha da abordagem reproduzida conta como evidência negativa fraca; ambígua reduz a
confiança pelo fator de conclusão.

#### Scenario: Queda de energia
- **WHEN** uma tentativa falha por infraestrutura
- **THEN** o veredito não muda e `n_tentativas` aumenta em 1

#### Scenario: Falha da abordagem reproduzida
- **GIVEN** duas falhas de abordagem com a mesma assinatura em sessões diferentes
- **WHEN** o veredito é calculado
- **THEN** ambas contam como evidências negativas com `q = 0,3` e `m = 1`

#### Scenario: Falha da abordagem isolada
- **GIVEN** uma única falha de abordagem
- **WHEN** o veredito é calculado
- **THEN** ela é tratada como ambígua

#### Scenario: Fator de conclusão
- **GIVEN** 6 tentativas conclusivas e 2 ambíguas
- **WHEN** o veredito é calculado
- **THEN** `f = 0,875`

### Requirement: Detalhamento auditável
O sistema SHALL devolver, junto ao veredito, a classificação e os fatores `q`, `m`, `d`, `b`,
`w` de cada tentativa.

#### Scenario: Explicação do veredito
- **WHEN** o veredito é calculado para 6 tentativas
- **THEN** `detalhes` contém 6 itens com classificação e fatores

### Requirement: Parâmetros configuráveis
O sistema SHALL ler todos os pesos, fatores e limiares de leitura de `src/config.py`.

#### Scenario: Ajuste de parâmetro
- **GIVEN** `VERDICT_Q_DIVERGENT=0.5`
- **WHEN** um resultado divergente documentado é avaliado
- **THEN** seu `q` é 0,5
