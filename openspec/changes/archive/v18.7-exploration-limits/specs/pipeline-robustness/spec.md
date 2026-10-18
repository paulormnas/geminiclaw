# Delta: pipeline-robustness

Esta capacidade não está na tabela de mudanças do ADR 021, mas dois requisitos atuais aplicam o teto de execuções que o ADR 021 §5.1 remove e um mede progresso por nomes de subtarefa (§5.6); sem este delta, a spec consolidada contradiria `hypothesis-loop` e `agent-runtime`.

## MODIFIED Requirements

### Requirement: Disjuntor de progresso por mudança de erro
O sistema SHALL considerar progresso, na exploração com projeto, qualquer aumento no número de `Experimento` executados na sessão ou de `Resultado` desses experimentos no grafo, ou mudança na assinatura dos erros das subtarefas falhas entre ciclos; sem projeto (laço de ciclo único), SHALL continuar valendo o aumento no conjunto de subtarefas bem-sucedidas. O sistema SHALL encerrar a sessão por falta de progresso somente após `CIRCUIT_BREAKER_STALL_CYCLES` ciclos consecutivos sem progresso; ciclos de espera por pedido pendente ao pesquisador MUST NOT contar (ADR 021 §5.6).

#### Scenario: Erro diferente é progresso
- **GIVEN** nenhum `Experimento` novo nos ciclos 1 e 2, com erros de revisão sobre critérios distintos
- **WHEN** o ciclo 2 termina
- **THEN** o disjuntor não dispara

#### Scenario: Dois ciclos idênticos
- **GIVEN** `CIRCUIT_BREAKER_STALL_CYCLES=2` e três ciclos sem `Experimento` nem `Resultado` novos e com a mesma assinatura de erros
- **WHEN** o ciclo 3 termina
- **THEN** a sessão encerra com o evento `circuit_breaker` contendo `stalled_cycles=2`

#### Scenario: Assinatura ignora números e caminhos
- **GIVEN** duas falhas com o mesmo critério e valores numéricos diferentes no texto
- **WHEN** as assinaturas são calculadas
- **THEN** as assinaturas são iguais

## REMOVED Requirements

### Requirement: Limites de execução separados e com fechamento
Removido pelo ADR 021 §5.1: execuções de agente são contadas e relatadas (spec `agent-runtime`), sem limite nem fechamento com `limite_execucoes`.

### Requirement: Limite de execuções de agente por sessão
Removido pelo ADR 021 §5.1, junto com o requisito anterior.
