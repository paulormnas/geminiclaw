# Delta: benchmark

Testes com resultados e eventos gravados em arquivo (sem executar sessões).

A classificação dos motivos de parada não muda aqui (é editada por `v18.7-benchmark-fixes` e `v18.7-exploration-limits`).

## ADDED Requirements

### Requirement: Motivos de reprovação sem lista fixa no resumo
O resumo de interações SHALL contar os motivos de reprovação de subtarefa que estiverem registrados, sem lista fixa: com o fim de `sem_hipotese` (ADR 021 §8.1), passam a aparecer, por exemplo, `hipotese_do_sistema` e `direcao_restrita`.

#### Scenario: Motivos genéricos no resumo
- **GIVEN** eventos `subtask_review` reprovados com `motivos = ["direcao_restrita"]` e `["hipotese_do_sistema"]`
- **WHEN** `summarize_events` resume os eventos
- **THEN** `subtask_reviews.motivos` é `{"direcao_restrita": 1, "hipotese_do_sistema": 1}`

### Requirement: Exploração por combinação no relatório
Cada resultado do benchmark SHALL guardar o grupo `exploracao` das métricas de operação, e o relatório SHALL mostrar, por combinação, a média por execução de experimentos `teste`, `preparacao` e `referencia`, de testes aprovados (modelos treinados), da proporção de testes de hipóteses do sistema, de `PREPARA` derivadas e de hipóteses do sistema abandonadas, além das execuções fechadas por `hipoteses_nao_testadas` (ADR 021 §8.4 e "Revisão"). Resultado sem o grupo SHALL aparecer como `n/d`.

#### Scenario: Tabela de exploração
- **GIVEN** duas execuções de `c1` com `proporcao_testes_sistema` 0.5 e 0.25 e `hipoteses_sistema_abandonadas` 1 e 0
- **WHEN** o relatório é gerado
- **THEN** a seção de exploração mostra para `c1` a proporção média 0.375 e 0.5 hipótese abandonada por execução

#### Scenario: Resultado antigo
- **GIVEN** um resultado anterior a esta mudança, sem `exploracao`
- **WHEN** o relatório é gerado
- **THEN** a linha da combinação mostra `n/d` e nenhum erro é lançado

### Requirement: Tokens do contrato por execução
O resumo de eventos SHALL registrar `subtask_attempts` (`total`, `com_hash`, `tokens_contrato_total`) e o relatório SHALL mostrar, por combinação, os tokens estimados do contrato por execução (média, desvio padrão, mínimo e máximo) e a fração da entrada (ADR 022 §6.3). Uma execução com `contrato_divergente` SHALL receber o aviso de placar `contrato_divergente`, que MUST NOT contar como anomalia de parada.

#### Scenario: Média por execução
- **GIVEN** três execuções de `c1` com `tokens_estimados_total` 20 000, 22 000 e 24 000
- **WHEN** o relatório é gerado
- **THEN** a média de tokens do contrato de `c1` é 22 000

#### Scenario: Divergência não interrompe
- **GIVEN** uma execução com um evento `contrato_divergente` e `exit 0`
- **WHEN** o placar e as anomalias são calculados
- **THEN** o placar traz o aviso `contrato_divergente` e `anomalies()` não reporta problema por isso
