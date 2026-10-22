# Delta: curator

## REMOVED Requirements

### Requirement: Veredito calculado sem LLM
**Motivo:** ADR 026. O cálculo determinístico passa a ser o do `RegistroResultado` (`evidence-scoring`).

## ADDED Requirements

### Requirement: Qualificação de registros
O Curator SHALL dispor de `result_records` (leitura) e `qualify_record` (escrita). `qualify_record` SHALL recusar a escrita quando:
- `evidencia` não cita um `Resultado` do registro;
- a qualificação é `reparo` e não há `atingiu_alvo` nem `delta_pai > 0`;
- a qualificação é `restricao` e não há tentativa abaixo do alvo nem falha atribuída à abordagem.

A escrita SHALL alterar apenas `qualificacao`, `limite_aplicabilidade` e `licao`.

#### Scenario: Reparo sem efeito medido
- **GIVEN** um registro com `atingiu_alvo = false` e `delta_pai = -0.01`
- **WHEN** o Curator chama `qualify_record` com `reparo`
- **THEN** a ferramenta recusa e explica a condição

#### Scenario: Restrição válida
- **GIVEN** um registro com `n_abaixo_alvo = 2`
- **WHEN** o Curator qualifica como `restricao` citando um `Resultado` do registro
- **THEN** o registro passa a `qualificacao = "restricao"` e os campos factuais não mudam

### Requirement: Atalhos derivados de registros
O orquestrador SHALL manter `Abordagem-FUNCIONOU_PARA->Problema` quando um registro do par tem `n_atingiu_alvo >= HYPOTHESIS_MIN_REPLICAS`, e `FALHOU_PARA` quando tem `n_abaixo_alvo >= HYPOTHESIS_MIN_REFUTATIONS` e `n_atingiu_alvo == 0`, com `registro_id` na aresta. Quando a condição deixa de valer, SHALL marcar o atalho como `contestada`, sem apagá-lo.

#### Scenario: Atalho sem Curator
- **GIVEN** `CURATOR_ENABLED=false` e um registro com `n_atingiu_alvo = 2`
- **WHEN** o segundo resultado é ingerido
- **THEN** existe `FUNCIONOU_PARA` do par com `registro_id` do registro

### Requirement: Descoberta de funcionamento baseada em registro
O Curator SHALL só gravar `Descoberta` `funciona`, `nao_funciona` ou `condicional` com `BASEADA_EM` um `RegistroResultado` que cumpra a condição de validação ou de refutação da regra.

#### Scenario: Descoberta sem registro
- **WHEN** o Curator tenta gravar `funciona` sem `BASEADA_EM` um registro validado
- **THEN** a ferramenta recusa
