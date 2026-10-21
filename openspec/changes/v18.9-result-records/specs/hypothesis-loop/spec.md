# Delta: hypothesis-loop

## MODIFIED Requirements

### Requirement: Transições de status nos dois sentidos ao fim do ciclo
Ao fim de cada ciclo, e nunca no meio dele, o sistema SHALL aplicar a todas as hipóteses não abandonadas a regra de réplicas sobre os registros das abordagens que elas `PROPOE`. A hipótese SHALL passar a `validada` quando `n_atingiu_alvo >= HYPOTHESIS_MIN_REPLICAS`, e a `refutada` quando `n_abaixo_alvo >= HYPOTHESIS_MIN_REFUTATIONS` e `n_atingiu_alvo == 0`. Uma hipótese concluída que deixa de cumprir sua condição SHALL voltar a `em_teste`. Cada transição SHALL ser registrada no evento `hipotese_transicao` com `status_anterior`, `status_novo`, `regra`, `n_atingiu_alvo` e `n_abaixo_alvo`. Os efeitos de reabertura (oportunidades, decisões e atalhos contestados) SHALL ser mantidos. (Antes: regra do veredito com `DECISION_EVAL_MIN_VERDICT`.)

#### Scenario: Validação por duas réplicas
- **GIVEN** `HYPOTHESIS_MIN_REPLICAS=2` e `h1` `em_teste` cujo registro tem `n_atingiu_alvo = 2`
- **WHEN** o ciclo termina
- **THEN** `h1` passa a `validada` e o evento tem `regra = "replicas_atingiram_alvo"`

#### Scenario: Refutação
- **GIVEN** `HYPOTHESIS_MIN_REFUTATIONS=2` e `h2` com `n_abaixo_alvo = 2` e `n_atingiu_alvo = 0`
- **WHEN** o ciclo termina
- **THEN** `h2` passa a `refutada`

#### Scenario: Uma réplica só
- **GIVEN** `h3` com `n_atingiu_alvo = 1`
- **WHEN** o ciclo termina
- **THEN** `h3` não muda de status

#### Scenario: Reabertura
- **GIVEN** `h2` `refutada` e uma nova tentativa válida que atinge o alvo
- **WHEN** o ciclo termina
- **THEN** `h2` volta a `em_teste` com `regra = "reabertura"`
- **AND** as arestas `FALHOU_PARA` derivadas de `h2` passam a `status = "contestada"`

### Requirement: Conferência do veredito no início da sessão
Com projeto ativo, o sistema SHALL conferir antes do primeiro planejamento se a `Metrica` do `Problema` está aprovada no vocabulário. Se não estiver, SHALL registrar o evento `metrica_indisponivel` com o motivo e a correção e avisar ao pesquisador. Em nenhum modo a sessão MUST terminar por isso. (Antes: o evento se chamava `veredito_indisponivel`.)

#### Scenario: Modo auto sem métrica aprovada
- **GIVEN** um projeto cujo `Problema` usa uma `Metrica` `candidato`
- **WHEN** a sessão inicia no modo `auto`
- **THEN** o prompt de planejamento exige a chave `metricas`
- **AND** o evento `metrica_indisponivel` é registrado com `modo = "auto"`

## ADDED Requirements

### Requirement: Variáveis do veredito removidas
O sistema SHALL falhar na carga da configuração com `ConfigurationError`, citando o ADR 026, quando qualquer variável `VERDICT_*`, `KNOWLEDGE_SHORTCUT_MIN_VERDICT` ou `DECISION_EVAL_MIN_VERDICT` estiver definida no ambiente.

#### Scenario: Variável antiga no .env
- **GIVEN** `VERDICT_PRIOR=0.5` no ambiente
- **WHEN** `src.config` é importado
- **THEN** a carga falha com mensagem que cita `ADR 026` e a variável
