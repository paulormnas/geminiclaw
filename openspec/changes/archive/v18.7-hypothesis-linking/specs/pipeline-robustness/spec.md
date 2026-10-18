# Delta: pipeline-robustness

Cenários avaliados pela checagem estrutural determinística do Validator do plano (`validate_plan`), sem chamada ao LLM; quando a checagem estrutural passa, o teste usa um `LLMProvider` falso que aprova o plano.

## MODIFIED Requirements

### Requirement: Limiar numérico obrigatório em subtarefa confirmatória
_Origem: ADR 021 §2 (antes: [`v18.6-review-evidence`](../../../v18.6-review-evidence/proposal.md))_
O Validator SHALL reprovar de forma determinística um plano com subtarefa `reproduction`, ou `validation` com `hypothesis_ref` preenchido, sem critério quantitativo. Subtarefa `validation` declarada com `papel = "referencia"` SHALL passar pela checagem estrutural sem limiar numérico e sem aviso, e o evento `plan_validation` SHALL registrar o papel declarado. Subtarefa `validation` sem `hypothesis_ref` e sem `papel` SHALL passar pela checagem estrutural, com aviso `validation_sem_hipotese` no evento `plan_validation`. A ausência ou o valor inválido de `papel` MUST NOT reprovar o plano.
(Antes: o baseline era reconhecido só por não ter `hypothesis_ref` e sempre gerava o aviso `validation_sem_hipotese`.)

#### Scenario: Baseline declarado como referência
- **GIVEN** um plano com a subtarefa `baseline_majoritario` do tipo `validation`, `papel = "referencia"`, sem `hypothesis_ref` e sem limiar numérico
- **WHEN** o Validator checa a estrutura
- **THEN** o plano não é reprovado por essa subtarefa
- **AND** o evento `plan_validation` não contém o aviso `validation_sem_hipotese` para `baseline_majoritario`
- **AND** o evento `plan_validation` registra `papeis_declarados = {"baseline_majoritario": "referencia"}`

#### Scenario: Validation sem hipótese e sem papel
- **GIVEN** um plano com a subtarefa `diagnostico_classes` do tipo `validation`, sem `hypothesis_ref`, sem `papel` e sem limiar numérico
- **WHEN** o Validator checa a estrutura
- **THEN** o plano não é reprovado por essa subtarefa
- **AND** o evento `plan_validation` contém o aviso `validation_sem_hipotese`

#### Scenario: Teste de hipótese sem limiar
- **GIVEN** uma subtarefa `validation` com `hypothesis_ref` `h1` e sem limiar numérico
- **WHEN** o Validator checa a estrutura
- **THEN** o plano é reprovado de forma determinística, com a correção sugerida

#### Scenario: Papel inválido não reprova
- **GIVEN** uma subtarefa `model_impl` com `papel = "exploratoria"` e critérios válidos
- **WHEN** o Validator checa a estrutura
- **THEN** o plano não é reprovado por causa de `papel`
