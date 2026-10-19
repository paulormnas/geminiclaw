# Delta: evidence-scoring

## ADDED Requirements

### Requirement: Falha de abordagem avaliada no laboratório
O laboratório do veredito SHALL ter o cenário N-abordagem-3 (a mesma falha de abordagem em três configurações) e N-abordagem-ruido (falhas de abordagem reproduzidas em uma hipótese que depois funciona), as variantes de `completa2` com `approach_failure_q` em 0,5, 0,7 e 1,0, e a simulação com `p_falha_abordagem` e o tipo de hipótese `abordagem_falha`. Para cada `q`, o relatório SHALL trazer a conclusão da hipótese de abordagem plantada, a falsa refutação das hipóteses `verdadeira` quando o agente falha por incapacidade e a falsa validação (ADR 025 §4.1; design §7).

#### Scenario: Valores do veredito para N-abordagem-4
- **GIVEN** quatro falhas de abordagem com a mesma assinatura em quatro configurações, no modelo v2 com os demais valores padrão
- **WHEN** o veredito é calculado com `approach_failure_q` = 0,3, 0,5, 0,7 e 1,0
- **THEN** os vereditos são −0,141, −0,250, −0,340 e −0,444, com tolerância de 0,001

#### Scenario: Reprodução mínima continua indecisa
- **GIVEN** duas falhas de abordagem na mesma configuração e `approach_failure_q` = 0,7
- **WHEN** o veredito é calculado
- **THEN** é −0,170 (tolerância 0,001) e a hipótese continua indecisa no limiar 0,3

#### Scenario: Falsa refutação medida
- **GIVEN** uma hipótese `verdadeira` simulada com `p_falha_abordagem` > 0 e `approach_failure_q` = 1,0
- **WHEN** a simulação mede a falsa refutação por `q`
- **THEN** o relatório traz a taxa para cada valor de `q` ao lado da conclusão correta da abordagem plantada

#### Scenario: Sem mudança de valor no sistema
- **WHEN** a avaliação offline termina
- **THEN** `VERDICT_APPROACH_FAILURE_Q` em `src/config.py` continua 0,3 até aprovação do pesquisador, registrada em PR próprio com a revisão do ADR 015 §9.9
