# Delta: llm-providers

## ADDED Requirements

### Requirement: Provedor Anthropic no registro
O sistema SHALL oferecer o provedor `anthropic` no registro de provedores, selecionável por papel
via `<PAPEL>_PROVIDER=anthropic` e `<PAPEL>_MODEL`.

#### Scenario: Criação pelo registro
- **GIVEN** `ANTHROPIC_API_KEY` definida
- **WHEN** `create_provider("anthropic", "claude-sonnet-5-5")` é chamado
- **THEN** uma instância de `AnthropicProvider` é retornada

#### Scenario: Chave ausente
- **GIVEN** `ANTHROPIC_API_KEY` não definida
- **WHEN** `create_provider("anthropic", "claude-sonnet-5-5")` é chamado
- **THEN** um erro explícito menciona `ANTHROPIC_API_KEY`

#### Scenario: Pacote opcional ausente
- **GIVEN** o extra `anthropic` não instalado
- **WHEN** o provedor `anthropic` é criado
- **THEN** o erro orienta `uv sync --extra anthropic` e os demais provedores seguem funcionando

### Requirement: Respeitar as restrições dos modelos Claude atuais
O provedor MUST NOT enviar `temperature`, `thinking` nem `tool_choice` forçado, e SHALL garantir
`max_tokens` mínimo de 16.000 porque o raciocínio adaptativo consome o limite de saída.

#### Scenario: Temperatura do contrato ignorada
- **WHEN** `generate(..., temperature=0.9)` é chamado
- **THEN** a requisição à API não contém `temperature`

### Requirement: Ciclo de ferramentas com pensamento assinado
O provedor SHALL devolver à API, sem alteração, os blocos de pensamento da resposta anterior
enquanto a mensagem do assistente não tiver sido editada, e SHALL agrupar resultados de
ferramentas consecutivos em um único turno `user`, com os `tool_result` primeiro.

#### Scenario: Ida e volta de uma chamada de ferramenta
- **GIVEN** uma resposta com um bloco de pensamento e um `tool_use`
- **WHEN** a mensagem volta ao histórico com o resultado da ferramenta
- **THEN** a próxima requisição reenvia o bloco de pensamento com a mesma assinatura

#### Scenario: Mensagem editada pela compressão de contexto
- **GIVEN** uma mensagem do assistente cujo texto foi reescrito
- **WHEN** o histórico é convertido
- **THEN** os blocos de pensamento guardados são descartados

### Requirement: Recusa e falhas explícitas
O provedor SHALL levantar `ProviderRefusalError` com a categoria quando a resposta for uma recusa,
e SHALL retentar apenas erros de conexão, 429 e 5xx, emitindo `connection_retry` a cada retentativa.

#### Scenario: Recusa por classificador de segurança
- **WHEN** a resposta tem `stop_reason == "refusal"` com categoria `bio`
- **THEN** `ProviderRefusalError` é levantado informando o modelo e a categoria

#### Scenario: Erro de cliente
- **WHEN** a API retorna 400
- **THEN** o erro é propagado sem retentativa
