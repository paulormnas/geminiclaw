# Delta: hypothesis-loop

## MODIFIED Requirements

### Requirement: Hipótese concluída pelo veredito
O sistema SHALL passar a hipótese a `validada` ou `refutada` quando `|veredito| ≥ DECISION_EVAL_MIN_VERDICT` (padrão 0,3), usando o veredito do modelo configurado (`VERDICT_MODEL`, padrão `v2`); o limiar dos atalhos de conhecimento segue a decisão do pesquisador (design §7, questão 1).

#### Scenario: Cinco variações que melhoram validam a hipótese
- **GIVEN** uma hipótese em teste com cinco variações validadas, cada uma melhor que a anterior, acima do alvo, sem baseline
- **WHEN** o ciclo sincroniza os status
- **THEN** a hipótese passa a `validada`

#### Scenario: Vinte variações sem evolução não validam
- **GIVEN** uma hipótese em teste com vinte variações com o mesmo valor acima do alvo
- **WHEN** o ciclo sincroniza os status
- **THEN** a hipótese continua `em_teste`
