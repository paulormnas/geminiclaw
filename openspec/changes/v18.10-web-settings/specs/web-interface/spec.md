# Delta: web-interface

## ADDED Requirements

### Requirement: Sobreposição do pesquisador com lista fechada
`src/config.py` SHALL carregar `RESEARCHER_ENV_FILE` depois do `.env`, aceitando só os nomes da lista fechada, e MUST falhar na inicialização com nome fora da lista (ADR 027 §6.8).

#### Scenario: Sobreposição vale
- **GIVEN** `.env` com `SESSION_MAX_COST_USD=20` e a sobreposição com `SESSION_MAX_COST_USD=5`
- **WHEN** a configuração é carregada
- **THEN** `SESSION_MAX_COST_USD` é 5

#### Scenario: Nome proibido no arquivo
- **GIVEN** a sobreposição com `DATABASE_URL=postgresql://x`
- **WHEN** a configuração é carregada
- **THEN** levanta `ConfigurationError` citando `DATABASE_URL` e `RESEARCHER_ENV_FILE`

### Requirement: Leitura sem revelar segredos
`GET /api/settings` SHALL devolver valor e origem de cada variável da lista e MUST NOT devolver o valor de chaves de API, só `definido` e os 4 últimos caracteres.

#### Scenario: Chave mascarada
- **GIVEN** `ANTHROPIC_API_KEY=sk-ant-abcdef1234`
- **WHEN** `GET /api/settings`
- **THEN** a linha tem `definido=true`, `ultimos4="1234"`, não tem `valor`, e o corpo da resposta não contém `abcdef`

### Requirement: Gravação validada, com senha
`PUT /api/settings` SHALL exigir sessão, CSRF, `Origin` e a senha, SHALL validar cada valor com as regras de `src/config.py` antes de gravar e MUST gravar de forma atômica com permissão `0600`.

#### Scenario: Gravar limite
- **WHEN** `PUT {"alteracoes":{"SESSION_MAX_MINUTES":"60"},"senha":"<correta>"}`
- **THEN** 200; o arquivo tem `SESSION_MAX_MINUTES=60`, modo `0600`, e a linha mostra `origem="pesquisador"`

#### Scenario: Sem senha
- **WHEN** o mesmo pedido sem `senha`
- **THEN** 403 e o arquivo não muda

#### Scenario: Valor inválido
- **WHEN** `SESSION_MAX_COST_USD` é `-1`
- **THEN** 422 com o nome e a mensagem de `src/config.py`, e nada é gravado

#### Scenario: Nome fora da lista
- **WHEN** `alteracoes` tem `EGRESS_MODE` ou `OPENAI_COMPATIBLE_BASE_URL`
- **THEN** 422 e nada é gravado

#### Scenario: Injeção de linha
- **WHEN** o valor de `GEMINI_API_KEY` contém `\nDATABASE_URL=x`
- **THEN** 422 e o arquivo não ganha linha nova

#### Scenario: Restaurar
- **WHEN** `alteracoes` tem `{"SESSION_MAX_MINUTES": null}`
- **THEN** a linha some do arquivo e a origem volta a `env` ou `padrao`

#### Scenario: Log sem valores
- **WHEN** uma chave é gravada
- **THEN** o log registra o nome `GEMINI_API_KEY` e não contém o valor

### Requirement: Modelos disponíveis por provedor
`GET /api/models` SHALL listar os modelos oferecidos por cada provedor configurado, marcados `no_catalogo`, `novo` ou `indisponivel` contra `src/llm/catalog.yaml`, e MUST mostrar a falha de um provedor sem esconder os outros (ADR 017; decisão de 2026-10-24).

#### Scenario: Cruzamento com o catálogo
- **GIVEN** provedor simulado que oferece `m-a` (no catálogo) e `m-novo` (fora), e o catálogo com `m-velho` não oferecido
- **WHEN** `GET /api/models`
- **THEN** `m-a` vem `no_catalogo`, `m-novo` vem `novo` e `m-velho` vem `indisponivel`

#### Scenario: Provedor sem chave
- **GIVEN** Anthropic sem chave e Google com chave
- **THEN** Anthropic vem `ok=false` com `erro="sem_chave"` e a lista do Google vem completa

#### Scenario: Cache
- **GIVEN** `MODEL_DISCOVERY_CACHE_SECONDS=3600` e relógio simulado
- **WHEN** a lista é pedida duas vezes em 10 minutos e depois com `atualizar=1`
- **THEN** o provedor simulado é chamado uma vez e depois mais uma

#### Scenario: Modelo fora do catálogo recusado
- **WHEN** `PUT /api/settings` define qualquer `{PAPEL}_MODEL` com um modelo `novo` ou `indisponivel`
- **THEN** 422 com `modelo_fora_do_catalogo` e nada é gravado

#### Scenario: Modelo novo só informativo
- **GIVEN** MSW com um modelo `novo`
- **THEN** a página o mostra desabilitado, com a dica "fora do catálogo: inclua em `src/llm/catalog.yaml`"

#### Scenario: Validator da mesma família do Developer
- **GIVEN** `DEVELOPER_MODEL` da família X
- **WHEN** `VALIDATOR_MODEL` é definido com modelo da família X
- **THEN** 422 citando o ADR 020

### Requirement: Página de configurações
O frontend SHALL mostrar os grupos, a origem de cada valor, as chaves mascaradas e o aviso de que a mudança vale para a próxima pesquisa, e SHALL pedir a senha ao salvar.

#### Scenario: Salvar pede senha
- **GIVEN** MSW com a lista
- **WHEN** o pesquisador muda um limite e clica Salvar
- **THEN** abre o diálogo de senha listando a mudança, e a requisição leva `senha` e `X-CSRF-Token`

#### Scenario: Campo de chave
- **THEN** o campo de chave é `type="password"` com `autocomplete="off"` e mostra `••••1234` antes de "Trocar"
