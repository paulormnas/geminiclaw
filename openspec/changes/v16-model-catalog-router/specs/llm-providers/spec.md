# Delta: llm-providers

## ADDED Requirements

### Requirement: Catálogo versionado e validado
O sistema SHALL carregar `src/llm/catalog.yaml` com `yaml.safe_load` e validá-lo por esquema
estrito antes de qualquer chamada de LLM, e SHALL interromper a inicialização, com mensagem
que cita o arquivo, o campo e o `id`, quando houver chave desconhecida, provedor não
registrado, `id` duplicado, valor fora do enum ou papel sem modelo na preferência
(ADR 017 §1, §9).

#### Scenario: Catálogo versionado válido
- **WHEN** o teste carrega o `src/llm/catalog.yaml` do repositório
- **THEN** a validação passa
- **AND** todos os seis papéis (`researcher`, `developer`, `reviewer`, `summarizer`, `validator`, `base`) têm ao menos um modelo na preferência

#### Scenario: Campo extra
- **GIVEN** um catálogo com `custo: 1` numa entrada de modelo
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro que cita `custo` e o `id` da entrada

#### Scenario: Provedor não registrado
- **GIVEN** uma entrada `mistral/large` e nenhum provedor `mistral` registrado
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro que lista os provedores registrados

### Requirement: Catálogo local só acrescenta modelos
O sistema SHALL aceitar um `catalog.local.yaml` opcional contendo apenas a chave `modelos`,
SHALL recusar entradas cujo `id` já exista e qualquer chave `papeis`, e SHALL registrar um
`WARNING` com o caminho e o sha256 do arquivo ao carregá-lo (ADR 017 §8).

#### Scenario: Acréscimo aceito
- **GIVEN** um catálogo local com `openai_compatible/llama-3.3-70b`, `trust: self_hosted`
- **WHEN** o catálogo é carregado
- **THEN** o modelo fica disponível para pin
- **AND** um `WARNING` cita o caminho e o sha256 do arquivo local

#### Scenario: Tentativa de rebaixar trust
- **GIVEN** um catálogo local que redeclara `google/gemini-3.8-flash` com `trust: self_hosted`
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro de `id` duplicado

### Requirement: Endpoint remoto exige https
O sistema SHALL recusar na inicialização uma entrada `openai_compatible` cujo endpoint
esteja fora de loopback e de faixas privadas e não use `https`, independentemente de `trust`
(ADR 017 §8).

#### Scenario: http para host público
- **GIVEN** `OPENAI_BASE_URL=http://gpu.exemplo.org/v1` e uma entrada `openai_compatible` elegível
- **WHEN** a sessão inicia
- **THEN** a inicialização para com erro que pede `https`

#### Scenario: http em rede privada
- **GIVEN** `OPENAI_BASE_URL=http://192.168.0.20:8080/v1`
- **WHEN** a sessão inicia
- **THEN** o endpoint é aceito

### Requirement: Política de dados explícita
O sistema SHALL ler `LLM_DATA_POLICY` (`self_hosted_only` ou `third_party_allowed`, padrão
`self_hosted_only`) e, sob `self_hosted_only`, SHALL descartar todo modelo `trust: third_party`
antes de qualquer outra regra, mesmo com credencial presente. A política SHALL aparecer no
banner e no payload da sessão (ADR 017 §3).

#### Scenario: Chave de nuvem não basta
- **GIVEN** `LLM_DATA_POLICY` ausente, `GEMINI_API_KEY` definida e `ollama/qwen3:8b` disponível
- **WHEN** o papel `developer` é resolvido
- **THEN** o modelo resolvido é `ollama/qwen3:8b`
- **AND** `google/gemini-3.8-flash` aparece nos descartados com motivo `politica`

#### Scenario: Nenhum modelo sob a política
- **GIVEN** `LLM_DATA_POLICY=self_hosted_only` e nenhum provedor local disponível
- **WHEN** a sessão inicia
- **THEN** a sessão não começa
- **AND** a mensagem cita o papel, os descartados com motivo e sugere `LLM_DATA_POLICY=third_party_allowed`

### Requirement: Disponibilidade sem geração de texto
O sistema SHALL considerar um `(provedor, modelo)` disponível somente quando houver
credencial ou endpoint, o provedor estiver em `LLM_PROVIDER_PRIORITY` e o health check passar
dentro de `LLM_HEALTH_CHECK_TIMEOUT_SECONDS`. O health check MUST NOT gerar texto e, para
provedores locais, SHALL confirmar que o modelo está instalado. O resultado SHALL ser
reutilizado durante a sessão (ADR 017 §4).

#### Scenario: Modelo Ollama não instalado
- **GIVEN** o Ollama responde em `/api/tags` sem o modelo `qwen3:8b`
- **WHEN** a disponibilidade é calculada
- **THEN** `ollama/qwen3:8b` fica indisponível com motivo `modelo_nao_instalado`

#### Scenario: Provedor fora da lista de permissão
- **GIVEN** `LLM_PROVIDER_PRIORITY=ollama,google` e `ANTHROPIC_API_KEY` definida
- **WHEN** a disponibilidade é calculada
- **THEN** nenhum modelo `anthropic/*` fica disponível

#### Scenario: Health check do Google sem geração
- **WHEN** o health check do provedor `google` roda com o cliente simulado
- **THEN** nenhuma chamada a `generate_content` é feita

#### Scenario: Erro sanitizado
- **GIVEN** um health check que falha com corpo de resposta contendo a chave
- **WHEN** o motivo é registrado
- **THEN** o log contém só a classe da exceção e o código HTTP

### Requirement: Roteador puro por papel
O sistema SHALL resolver cada papel por uma função sem I/O
`resolve(papel, catalogo, disponiveis, politica, overrides, routing)` que filtra por política,
requisitos, lista de permissão e disponibilidade e escolhe o primeiro elegível da preferência,
SHALL resolver `planner` como `researcher`, e SHALL registrar os descartados com motivo
(ADR 017 §2, §5).

#### Scenario: Requisito de ferramentas
- **GIVEN** o primeiro modelo da preferência do `researcher` tem `ferramentas: false`
- **WHEN** o papel é resolvido
- **THEN** ele é descartado com motivo `requisito:ferramentas` e o próximo elegível vence

#### Scenario: Alias de papel
- **WHEN** `resolve("planner", ...)` é chamado
- **THEN** o resultado é igual ao de `resolve("researcher", ...)`

#### Scenario: Validator sem exigência de trust
- **GIVEN** `LLM_DATA_POLICY=third_party_allowed` e a preferência do Validator começando por um modelo `third_party` disponível
- **WHEN** o Validator é resolvido
- **THEN** o modelo `third_party` vence

### Requirement: Resolução única por sessão
O sistema SHALL resolver todos os papéis uma vez, antes do banner e da primeira chamada de
LLM, SHALL gravar o mapa resolvido, a política, o modo de roteamento e a versão e o hash do
catálogo em `payload["llm_routing"]`, e MUST NOT trocar o modelo de um papel durante a sessão
(ADR 017 §6, §10).

#### Scenario: Mapa no payload
- **WHEN** uma sessão inicia
- **THEN** `payload["llm_routing"]["papeis"]` tem uma entrada por papel com `id`, `trust` e `origem`
- **AND** `payload["llm_routing"]["catalogo"]["hash"]` é o sha256 do catálogo efetivo

#### Scenario: 429 não troca o modelo resolvido
- **GIVEN** o provedor do Researcher responde 429 duas vezes
- **WHEN** a chamada é repetida
- **THEN** a retentativa usa o mesmo `id` (salvo o fallback do Google descrito no design §4)
- **AND** o consumo conta no orçamento da sessão

### Requirement: Pin provedor/modelo e modo estrito
O sistema SHALL aceitar `{PAPEL}_MODEL=provedor/modelo` como pin com precedência sobre a
preferência, sujeito à política e à lista de permissão. Com `LLM_ROUTING=strict`, um pin
inválido, indisponível ou em conflito SHALL impedir o início da sessão; com `flexible`, SHALL
gerar `WARNING` e seguir a preferência (ADR 017 §7).

#### Scenario: Pin em conflito com a política (flexível)
- **GIVEN** `LLM_DATA_POLICY=self_hosted_only`, `LLM_ROUTING=flexible` e `RESEARCHER_MODEL=anthropic/claude-sonnet-5-5`
- **WHEN** a sessão inicia
- **THEN** um `WARNING` explica o conflito e o Researcher usa o primeiro elegível da preferência

#### Scenario: Pin em conflito (estrito)
- **GIVEN** o mesmo pin com `LLM_ROUTING=strict`
- **WHEN** a sessão inicia
- **THEN** a sessão não começa e a mensagem cita o pin e o motivo

#### Scenario: Variáveis legadas
- **GIVEN** `DEVELOPER_PROVIDER=google` e `DEVELOPER_MODEL=gemini-3.8-flash`
- **WHEN** a sessão inicia
- **THEN** o Developer recebe o pin `google/gemini-3.8-flash` com `origem="pin_legado"`
- **AND** um `WARNING` de obsolescência é registrado

### Requirement: Dica de modelo do plano validada
O sistema SHALL tratar `preferred_model` de uma subtarefa como dica no formato
`provedor/modelo`, aceita somente se o modelo existir no catálogo, atender aos requisitos e à
política e estiver disponível; caso contrário SHALL ignorá-la com `WARNING`. Em
`LLM_ROUTING=strict`, a dica SHALL ser sempre ignorada (ADR 017 §7).

#### Scenario: Dica sem provedor
- **GIVEN** uma subtarefa do Developer com `preferred_model="qwen3:8b"`
- **WHEN** a subtarefa é despachada
- **THEN** o Developer usa o modelo resolvido da sessão e um `WARNING` cita a dica ignorada

#### Scenario: Dica válida
- **GIVEN** `preferred_model="ollama/qwen3:8b"`, disponível e com `ferramentas: true`
- **WHEN** a subtarefa do Developer é despachada
- **THEN** essa subtarefa usa `ollama/qwen3:8b`

### Requirement: Um único caminho de seleção
O sistema SHALL obter todo provedor de LLM pelo roteador: `get_provider()` sem papel SHALL
delegar para `researcher`, e os módulos de agente MUST NOT ler `AGENT_MODEL`,
`{PAPEL}_MODEL`, `LLM_MODEL` ou `DEFAULT_MODEL` diretamente.

#### Scenario: Sem papel
- **WHEN** `get_provider()` é chamado dentro de uma sessão
- **THEN** a instância devolvida é a do `researcher` no mapa resolvido

#### Scenario: Leitura direta proibida
- **WHEN** o teste de política varre `agents/` e `src/`
- **THEN** nenhuma leitura de `AGENT_MODEL`, `LLM_MODEL` ou `DEFAULT_MODEL` é encontrada fora de `src/llm/routing.py` (que só as lista para o aviso de obsolescência)

### Requirement: Auditoria sem segredos
O sistema SHALL exibir no banner, para cada papel, `provedor/modelo` e `trust`, além da
política, do modo de roteamento e da versão e do hash curto do catálogo, e MUST NOT registrar
chaves, cabeçalhos ou URLs com credenciais no banner, nos logs ou na telemetria (ADR 017 §9,
§10).

#### Scenario: Banner
- **WHEN** uma sessão inicia com o mapa resolvido
- **THEN** o banner tem uma linha por papel no formato `<papel>  <provedor/modelo>  (<trust>)`
- **AND** não contém nenhum valor de variável `*_API_KEY`

## REMOVED Requirements

### Requirement: Provedor global por LLM_PROVIDER
**Motivo:** substituído pela resolução por papel; `LLM_PROVIDER`, `LLM_MODEL` e
`DEFAULT_MODEL` deixam de existir (ADR 017, Consequências). Durante a transição, sua presença
gera apenas um `WARNING` único.

#### Scenario: Variável removida presente
- **GIVEN** `LLM_PROVIDER=ollama` no ambiente
- **WHEN** a sessão inicia
- **THEN** um `WARNING` informa que a variável é ignorada e o mapa resolvido não é afetado por ela
