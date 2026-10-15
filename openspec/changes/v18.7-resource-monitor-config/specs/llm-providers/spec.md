# Delta: llm-providers

## ADDED Requirements

### Requirement: Prioridade padrão de provedores sem perfil de máquina
Com `LLM_PROVIDER_PRIORITY` vazio, a lista de permissão e a ordem de provedores SHALL ser uma única padrão, `google,anthropic,openai,ollama,openai_compatible`, em qualquer máquina; `parse_priority` MUST NOT depender de perfil de deployment. Quem quiser outra ordem SHALL declará-la em `LLM_PROVIDER_PRIORITY` (ADR 023 §1.1, item 3; altera ADR 017 §4).

#### Scenario: Prioridade padrão
- **GIVEN** `LLM_PROVIDER_PRIORITY` vazio
- **WHEN** `parse_priority("")` é chamado
- **THEN** devolve `("google", "anthropic", "openai", "ollama", "openai_compatible")`

#### Scenario: Provedores locais primeiro por declaração
- **GIVEN** `LLM_PROVIDER_PRIORITY=ollama,openai_compatible,google`
- **WHEN** a resolução de sessão calcula a disponibilidade
- **THEN** a prioridade usada é `("ollama", "openai_compatible", "google")`

#### Scenario: Assinatura sem perfil
- **WHEN** `parse_priority` é inspecionado
- **THEN** aceita um único parâmetro (`raw`) e `src.config` não define `DEPLOYMENT_PROFILE`
