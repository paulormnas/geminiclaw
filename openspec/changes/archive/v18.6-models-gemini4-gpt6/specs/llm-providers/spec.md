# Delta: llm-providers

## ADDED Requirements

### Requirement: Catálogo com Gemini 4 e GPT-6
O catálogo padrão (versão 5) SHALL declarar `google/gemini-4-argon` (família `gemini`) e `openai/gpt-6.1-sol` (família `gpt`),
SHALL NOT declarar `google/gemini-3.8-flash` nem `openai/gpt-5.6-terra`, e as listas de preferência por papel SHALL usar os novos
modelos nas posições dos antigos, mantendo uma família diferente na preferência do `validator` (ADR 020).
`GOOGLE_FALLBACK_MODEL` SHALL ter como padrão `gemini-4-argon`, e o alias obsoleto de visão (`OCR_PROVIDER=gemini`) SHALL
equivaler a `VISION_MODEL=google/gemini-4-argon`. Referência: ADR 017, ADR 020 §5.

#### Scenario: Modelos novos no catálogo
- **WHEN** o catálogo padrão é carregado
- **THEN** `google/gemini-4-argon` e `openai/gpt-6.1-sol` existem, com `familia_modelo` `gemini` e `gpt`
- **AND** `google/gemini-3.8-flash` e `openai/gpt-5.6-terra` não existem

#### Scenario: Catálogo local com modelo removido
- **GIVEN** um `catalog.local.yaml` que referencia `google/gemini-3.8-flash`
- **WHEN** o catálogo é carregado
- **THEN** a inicialização falha com mensagem que cita o modelo desconhecido

#### Scenario: Validator de outra família
- **GIVEN** `developer` fixado em `google/gemini-4-argon` e o catálogo padrão
- **WHEN** a sessão resolve os papéis
- **THEN** o `validator` não é da família `gemini`

#### Scenario: Padrões trocados
- **WHEN** a configuração é carregada sem `GOOGLE_FALLBACK_MODEL` no ambiente
- **THEN** o valor é `gemini-4-argon`
- **AND** `VISION_MODEL=gemini` (obsoleto) resolve para `google/gemini-4-argon` com `WARNING`

### Requirement: Preço com vigência
`Price` SHALL aceitar `promo_until` (último dia UTC do preço promocional) e `after_promo` (preço a partir do dia seguinte), e a
estimativa de custo SHALL escolher o preço pela data UTC da chamada. `google/gemini-4-argon` SHALL declarar entrada 2,00,
saída 10,00 e cache 0,10 (US$ por 1M tokens) até 2026-11-30 e 4,00, 20,00 e 0,20 depois. `openai/gpt-6.1-sol` SHALL declarar
2,00, 10,00 e cache 0,10 até 272 000 tokens de entrada e 4,00, 15,00 e 0,20 acima (a chamada inteira). Preço vencido sem
`after_promo` MUST usar o último preço conhecido e emitir `WARNING`; `LLM_PRICING_OVERRIDES` SHALL continuar vencendo.

#### Scenario: Dentro da promoção
- **GIVEN** 1 000 000 tokens de entrada e 100 000 de saída do `gemini-4-argon` em 2026-11-30
- **WHEN** o custo é estimado
- **THEN** o custo é US$ 3,00

#### Scenario: Depois da promoção
- **GIVEN** a mesma chamada em 2026-12-01
- **WHEN** o custo é estimado
- **THEN** o custo é US$ 6,00

#### Scenario: Contexto longo do GPT-6.1 Sol
- **GIVEN** 300 000 tokens de entrada e 10 000 de saída do `gpt-6.1-sol`
- **WHEN** o custo é estimado
- **THEN** o custo é US$ 1,35 (4,00 × 0,3 + 15,00 × 0,01)

#### Scenario: Cache do GPT-6.1 Sol
- **GIVEN** 1 000 tokens de entrada, 800 deles em cache, e nenhuma saída
- **WHEN** o custo é estimado
- **THEN** 800 tokens são cobrados a US$ 0,10 e 200 a US$ 2,00 por 1M

#### Scenario: Vigência vencida sem preço posterior
- **GIVEN** um preço com `promo_until` no passado e sem `after_promo`
- **WHEN** o custo é estimado
- **THEN** o último preço conhecido é usado e um `WARNING` é emitido
