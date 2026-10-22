# Delta: evidence-scoring

## REMOVED Requirements

### Requirement: Veredito de −1 a +1
**Motivo:** ADR 026 §1. O estado da hipótese passa a vir da regra de réplicas (`hypothesis-loop`).

### Requirement: Pesos objetivos
**Motivo:** ADR 026 §1. Não há mais pesos `q·m·d·b`.

### Requirement: Tentativas sem resultado tratadas por causa
**Motivo:** substituído por "Tentativa válida" abaixo.

### Requirement: Detalhamento auditável
**Motivo:** substituído pelo próprio `RegistroResultado`, cujos campos são contagens auditáveis.

### Requirement: Parâmetros configuráveis
**Motivo:** as variáveis `VERDICT_*` são removidas.

## ADDED Requirements

### Requirement: Registro de resultado mantido pelo orquestrador
O sistema SHALL manter um `RegistroResultado` por par (Problema, Abordagem, `config_normalizada`). Ele SHALL ser recalculado na ingestão de cada `Resultado` da métrica do critério, com os campos do design §2, e escrito apenas com `criado_por = "orquestrador"` (ADR 026 §2).

#### Scenario: Duas réplicas acima do alvo
- **GIVEN** um Problema com critério `acuracia >= 0.93` e uma abordagem com dois experimentos de teste, sementes 1 e 2, `acuracia` de teste 0.94 e 0.95
- **WHEN** o segundo `Resultado` é ingerido
- **THEN** o registro do par tem `melhor_valor = 0.95`, `n_replicas_independentes = 2`, `n_atingiu_alvo = 2` e `atingiu_alvo = true`

#### Scenario: Diferença para a configuração anterior
- **GIVEN** uma abordagem com um registro de `melhor_valor = 0.88` e, depois, uma nova configuração que produz 0.91
- **WHEN** os registros são recalculados
- **THEN** o registro da nova configuração tem `delta_pai = 0.03` (com tolerância de 1e-9) e o primeiro não tem `delta_pai`

#### Scenario: Agente não escreve fatos do registro
- **WHEN** o Curator tenta alterar `melhor_valor` de um registro
- **THEN** a porta do grafo recusa a escrita com `KnowledgeServiceError`

### Requirement: Tentativa válida
Uma tentativa SHALL ser válida quando o experimento produziu `Resultado` da métrica do critério, sem qualificador ou com `teste` ou `cv`, e com `status_validacao` diferente de `nao_validado`, inclusive com `status = falha` e `assinatura_falha = criterio_nao_atendido` e com `status = divergente_documentado`. Tentativas sem esse `Resultado` SHALL NOT mudar as contagens de réplicas.

#### Scenario: Falha com valor abaixo do alvo
- **GIVEN** um experimento `falha` com `criterio_nao_atendido` e `acuracia` de teste 0.62, para o alvo 0.93
- **WHEN** o `Resultado` é ingerido
- **THEN** `n_abaixo_alvo` do registro aumenta em 1

#### Scenario: Sem métricas
- **GIVEN** um experimento `falha` com `sem_metricas`
- **WHEN** é ingerido
- **THEN** nenhum registro muda e a falha continua registrada no `Experimento`

#### Scenario: Resultado não verificado ignorado
- **GIVEN** um `Resultado` com `status_validacao = nao_validado`
- **WHEN** a hipótese é recalculada
- **THEN** a tentativa conta em `n_tentativas`, mas não em `n_atingiu_alvo` nem em `n_abaixo_alvo`

#### Scenario: Métrica de treino ignorada
- **GIVEN** um `Resultado` com qualificador `treino` igual a 0.99
- **WHEN** é ingerido
- **THEN** `melhor_valor` não considera esse valor
