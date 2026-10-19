# Delta: evidence-scoring

## ADDED Requirements

### Requirement: Modelo v2 da equação de confiança
O sistema SHALL calcular o veredito pelo modelo v2 quando `VERDICT_MODEL = v2` (padrão) e pelo modelo `adr015` (equação anterior, sem alteração) quando `VERDICT_MODEL = adr015`, com a mesma assinatura de `compute_verdict` e o mesmo `VerdictResult` (ADR 025 §4.2; ADR 015 §9, revisado).

#### Scenario: Retorno ao modelo anterior
- **GIVEN** `VERDICT_MODEL=adr015`
- **WHEN** o veredito de uma hipótese é calculado
- **THEN** o resultado é idêntico ao da equação do ADR 015 §9.5 (exemplo completo do §9.6: `α` = 3,225, `β` = 1,8, veredito 0,17 ± 0,005)

#### Scenario: Modelo desconhecido
- **WHEN** `VERDICT_MODEL` tem um valor diferente de `v2` e `adr015`
- **THEN** o carregamento da configuração falha com erro que cita o valor e os dois aceitos

#### Scenario: Equivalência com o laboratório
- **WHEN** o veredito do modelo v2 com os valores padrão é calculado para os 46 cenários do catálogo de `scripts/verdict_lab` e para 30 sequências simuladas
- **THEN** coincide com o da variante `completa2` do laboratório com diferença ≤ 1e-12

### Requirement: Independência por tipo de evidência
O sistema SHALL, no modelo v2, atribuir o fator `d` pelo tipo da evidência para a hipótese, em ordem cronológica: variação (configuração nunca executada em nenhum nó) `VERDICT_D_VARIATION` = 1,0; réplica em outro nó `VERDICT_D_REPLICA_NODE` = 0,5; dataset novo `VERDICT_D_NEW_DATASET` = 1,0; sessão nova `VERDICT_D_NEW_SESSION` = 0,5; semente nova `VERDICT_D_NEW_SEED` = 0,2.

#### Scenario: Variação pesa mais que réplica em outro nó
- **GIVEN** a configuração A no nó 1, a configuração B no nó 1, a configuração A no nó 2 e a configuração A no nó 2 com outra semente, no mesmo dataset e uma sessão por nó
- **WHEN** o veredito é calculado
- **THEN** os `d` são 1,0, 1,0, 0,5 e 0,2
- **AND** o detalhamento traz o `tipo` `variacao`, `variacao`, `replica_no` e `semente`

#### Scenario: A mesma configuração em três nós não conclui
- **GIVEN** a mesma configuração, com resultado 0,96 acima do alvo 0,95, em três nós
- **WHEN** o veredito é calculado com os valores padrão
- **THEN** o veredito é 0,111 ± 0,001 (abaixo de `DECISION_EVAL_MIN_VERDICT`)

### Requirement: Variação útil
O sistema SHALL, no modelo v2, considerar útil a variação que é a primeira evidência com valor da hipótese ou supera o melhor valor anterior, no sentido da métrica, em mais que `VERDICT_USEFUL_VARIATION_EPSILON` (padrão 0); a variação positiva que não é útil recebe `d = VERDICT_D_VARIATION_NO_GAIN` (padrão 0) e a negativa que não é útil recebe `VERDICT_D_NEW_SEED`.

#### Scenario: Qualquer melhora conta
- **GIVEN** a configuração A com 0,96 e, depois, a configuração B com 0,9601
- **WHEN** o veredito é calculado
- **THEN** B tem `d` = 1,0

#### Scenario: Volume sem evolução não soma
- **GIVEN** vinte variações positivas com o mesmo valor 0,951
- **WHEN** o veredito é calculado
- **THEN** só a primeira tem `d` = 1,0 e as outras 19 têm `d` = 0
- **AND** o veredito é igual ao de uma única variação (0,040 ± 0,001)

#### Scenario: Cinco melhoras concluem e três não
- **GIVEN** variações positivas crescentes acima do alvo, sem baseline
- **WHEN** o veredito é calculado com os valores padrão
- **THEN** com cinco variações (0,955 a 0,971, em passos de 0,004) é 0,405 ± 0,005 (≥ 0,3) e com três (0,955 a 0,963) é 0,218 ± 0,005 (< 0,3)

### Requirement: Penalidade de busca acumulada
O sistema SHALL, no modelo v2, calcular `b` das evidências positivas com `n_config` igual a 1 mais o número de variações, até a própria evidência e em ordem cronológica, que não foram úteis, sem contar as falhas, de modo que uma evidência posterior não altera o peso das anteriores.

#### Scenario: Evidência posterior não reduz as anteriores
- **GIVEN** três variações positivas que melhoram
- **WHEN** uma quarta variação sem ganho é acrescentada
- **THEN** os pesos `w` das três primeiras evidências não mudam

#### Scenario: Falhas não penalizam
- **GIVEN** duas falhas ambíguas de configurações distintas e uma evidência positiva de uma terceira configuração
- **WHEN** o veredito é calculado
- **THEN** o `b` da evidência positiva é 1,0

### Requirement: Alvo exigido e magnitude pela folga
O sistema SHALL, no modelo v2 com `VERDICT_REQUIRE_TARGET = true`, tratar como negativa a evidência que supera o baseline por `δ` mas não alcança o alvo, com `m = min(1, falta/δ)`; e, sem baseline e com alvo e `δ`, calcular `m = max(VERDICT_M_FLOOR_NO_BASELINE, min(1, folga/(2δ)))` na positiva e `m = min(1, falta/δ)` na negativa.

#### Scenario: Abaixo do alvo com baseline
- **GIVEN** baseline 0,333, `δ` = 0,01 e alvo 0,95
- **WHEN** o resultado validado é 0,80
- **THEN** a evidência é negativa
- **AND** com `VERDICT_MODEL=adr015` a mesma tentativa é positiva

#### Scenario: Piso da folga
- **GIVEN** alvo 0,95, `δ` = 0,01 e nenhum baseline
- **WHEN** o resultado é 0,951
- **THEN** a evidência é positiva com `m` = 0,5
- **AND** com resultado 0,98, `m` = 1,0

### Requirement: Réplica contrária pesa cheio
O sistema SHALL, no modelo v2, atribuir `d = VERDICT_D_REPLICA_AGAINST` (padrão 1,0) à evidência negativa em configuração já vista.

#### Scenario: Cinco melhoras e três réplicas contrárias
- **GIVEN** cinco variações positivas crescentes e a melhor configuração replicada em três outros nós abaixo do alvo
- **WHEN** o veredito é calculado
- **THEN** o veredito é < 0,3 (indeciso)

### Requirement: Teto de falsa validação da calibração
O sistema SHALL manter, nos valores padrão do modelo v2 e no limiar `DECISION_EVAL_MIN_VERDICT` = 0,3, falsa validação média de no máximo 2 % na simulação do laboratório (ADR 025 §4.2), conferida por um teste que roda a simulação reduzida e a documenta.

#### Scenario: Simulação reduzida
- **GIVEN** a simulação do laboratório com a grade padrão reduzida (3 pontos, 10 repetições, semente fixa) e os valores padrão do modelo v2
- **WHEN** o teste calcula a falsa validação (maior entre os tipos `falsa` e `sem_efeito`)
- **THEN** a falsa validação média é ≤ 0,02

## MODIFIED Requirements

### Requirement: Pesos objetivos
O sistema SHALL derivar cada peso de dados registrados (status do Validator, arquivos do contrato, métricas, baseline, `delta_min`, alvo, nó, sessão, semente, dataset e configuração), sem julgamento de LLM, tanto no modelo v2 quanto no `adr015`.

#### Scenario: Nenhum peso vem de LLM
- **WHEN** o veredito é calculado em qualquer modelo
- **THEN** nenhuma chamada a provedor LLM, rede ou banco é feita pelo módulo de cálculo
