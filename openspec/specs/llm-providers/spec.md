# Especificação: llm-providers

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md), [`v16-anthropic-provider`](../../changes/archive/v16-anthropic-provider/proposal.md), [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md), [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)

## Requirements

### Requirement: Registro único de provedores
_Origem: [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md)_
O sistema SHALL resolver todo provedor LLM a partir de um único registro, consultado tanto
pela seleção global (`get_provider`) quanto pelo roteamento por papel (`ModelRouter`).

#### Scenario: Seleção global usa o registro
- **GIVEN** `LLM_PROVIDER=ollama` e `LLM_MODEL=qwen3:8b`
- **WHEN** `get_provider()` é chamado
- **THEN** retorna a instância criada pela fábrica registrada como `ollama`
- **AND** chamadas seguintes retornam a mesma instância

#### Scenario: Roteamento por papel usa o registro
- **GIVEN** `RESEARCHER_PROVIDER=openai_compatible` e `RESEARCHER_MODEL=llama-3.1-8b`
- **WHEN** `ModelRouter.get_provider("researcher")` é chamado
- **THEN** retorna um provedor `openai_compatible` com `model_name == "llama-3.1-8b"`

#### Scenario: Alias legado
- **WHEN** um provedor é pedido pelo nome `local`
- **THEN** o registro resolve para o provedor `ollama`

#### Scenario: Provedor desconhecido
- **WHEN** um provedor é pedido pelo nome `inexistente`
- **THEN** o sistema levanta `ValueError` cuja mensagem lista os provedores disponíveis

### Requirement: Adicionar provedor sem editar código central
_Origem: [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md)_
O sistema SHALL permitir adicionar um provedor apenas implementando `LLMProvider` e
registrando uma fábrica, sem alterar `factory.py` nem `model_router.py`.

#### Scenario: Provedor de teste registrado
- **GIVEN** um provedor fictício registrado com `register_provider("fake", ...)` em um teste
- **WHEN** `ModelRouter.get_provider` é chamado para um papel configurado com `fake`
- **THEN** o provedor fictício é retornado

### Requirement: Dependência opcional ausente não quebra outros provedores
_Origem: [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md)_
O sistema SHALL importar o pacote de cada provedor somente quando aquele provedor for
instanciado.

#### Scenario: Pacote google-genai não instalado
- **GIVEN** que `google.genai` não pode ser importado
- **WHEN** o provedor `ollama` é pedido
- **THEN** a instância é criada normalmente
- **AND** pedir o provedor `google` levanta erro indicando `uv sync --extra google`

### Requirement: Provedor compatível com a API da OpenAI
_Origem: [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md)_
O sistema SHALL oferecer o provedor `openai_compatible`, que conversa com qualquer servidor que
implemente `/v1/chat/completions`, com suporte a tool calling e streaming, usando `httpx`.

#### Scenario: Resposta com tool call
- **GIVEN** um servidor que responde `choices[0].message.tool_calls` com uma chamada
- **WHEN** `generate` é chamado com `tools`
- **THEN** o `LLMResponse` contém um `ToolCall` com `name` e `arguments` como `dict`
- **AND** `finish_reason == "tool_calls"`

#### Scenario: Argumentos de tool call inválidos
- **GIVEN** um tool call cujos argumentos não são JSON válido
- **WHEN** a resposta é convertida
- **THEN** o `ToolCall` traz `arguments == {"_raw": <texto original>}` e um aviso é registrado

#### Scenario: Uso de tokens
- **WHEN** a resposta inclui `usage`
- **THEN** `LLMResponse.usage` contém `prompt_tokens`, `completion_tokens` e `total_tokens`

#### Scenario: Limite de taxa
- **GIVEN** o servidor responde 429 e depois 200
- **WHEN** `generate` é chamado
- **THEN** a chamada é repetida com backoff e retorna a resposta de sucesso
- **AND** a retentativa é registrada na telemetria

#### Scenario: Chave de API não vaza
- **WHEN** as configurações de um provedor são registradas em log ou convertidas em texto
- **THEN** o valor de `api_key` não aparece

### Requirement: Provedor Anthropic no registro
_Origem: [`v16-anthropic-provider`](../../changes/archive/v16-anthropic-provider/proposal.md)_
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
_Origem: [`v16-anthropic-provider`](../../changes/archive/v16-anthropic-provider/proposal.md)_
O provedor MUST NOT enviar `temperature`, `thinking` nem `tool_choice` forçado, e SHALL garantir
`max_tokens` mínimo de 16.000 porque o raciocínio adaptativo consome o limite de saída.

#### Scenario: Temperatura do contrato ignorada
- **WHEN** `generate(..., temperature=0.9)` é chamado
- **THEN** a requisição à API não contém `temperature`

### Requirement: Ciclo de ferramentas com pensamento assinado
_Origem: [`v16-anthropic-provider`](../../changes/archive/v16-anthropic-provider/proposal.md)_
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
_Origem: [`v16-anthropic-provider`](../../changes/archive/v16-anthropic-provider/proposal.md)_
O provedor SHALL levantar `ProviderRefusalError` com a categoria quando a resposta for uma recusa,
e SHALL retentar apenas erros de conexão, 429 e 5xx, emitindo `connection_retry` a cada retentativa.

#### Scenario: Recusa por classificador de segurança
- **WHEN** a resposta tem `stop_reason == "refusal"` com categoria `bio`
- **THEN** `ProviderRefusalError` é levantado informando o modelo e a categoria

#### Scenario: Erro de cliente
- **WHEN** a API retorna 400
- **THEN** o erro é propagado sem retentativa

### Requirement: Catálogo versionado e validado
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
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

#### Scenario: Chave duplicada
- **GIVEN** uma entrada de modelo com a chave `trust` repetida
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro de chave duplicada (a última não vence em silêncio)

### Requirement: Catálogo local só acrescenta modelos
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
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
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
O sistema SHALL recusar, na inicialização do catálogo e na criação do provedor, o `base_url` de
**todo** provedor que tenha endpoint configurado e ao menos um modelo no catálogo efetivo
(`openai`, `openai_compatible`, `ollama`, `anthropic` e os que vierem) quando o host estiver
fora de loopback e de faixas privadas e o esquema não for `https`, independentemente de `trust`.
Endereços link-local (`169.254.0.0/16`, `fe80::/10`) MUST NOT contar como rede privada. O provedor
`openai_compatible` SHALL usar variáveis próprias (`OPENAI_COMPATIBLE_BASE_URL`,
`OPENAI_COMPATIBLE_API_KEY`), sem compartilhar `OPENAI_BASE_URL`/`OPENAI_API_KEY` com o provedor
`openai`, para que a chave real da OpenAI nunca seja enviada a um servidor compatível
(ADR 017 §8).

#### Scenario: http para host público
- **GIVEN** `OPENAI_COMPATIBLE_BASE_URL=http://gpu.exemplo.org/v1` e uma entrada `openai_compatible` no catálogo
- **WHEN** a sessão inicia
- **THEN** a inicialização para com erro que pede `https`

#### Scenario: http em rede privada
- **GIVEN** `OPENAI_COMPATIBLE_BASE_URL=http://192.168.0.20:8080/v1`
- **WHEN** a sessão inicia
- **THEN** o endpoint é aceito

#### Scenario: Provedor openai com endpoint http público
- **GIVEN** `OPENAI_BASE_URL=http://gpu.exemplo.org/v1` e o catálogo versionado (que tem modelos `openai`)
- **WHEN** o catálogo é carregado ou o provedor `openai` é criado
- **THEN** a inicialização para com erro que pede `https`, mesmo sem nenhuma entrada `openai_compatible`

#### Scenario: Ollama remoto sem https
- **GIVEN** `OLLAMA_BASE_URL=http://gpu.exemplo.org:11434`
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro que pede `https`

#### Scenario: Endpoint link-local
- **GIVEN** `OLLAMA_BASE_URL=http://169.254.169.254/`
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro que pede `https`

#### Scenario: Variáveis do openai_compatible separadas
- **GIVEN** `OPENAI_API_KEY` e `OPENAI_BASE_URL` definidas e `OPENAI_COMPATIBLE_*` ausentes
- **WHEN** o provedor `openai_compatible` é criado
- **THEN** ele não recebe a chave nem o endpoint do provedor `openai`

### Requirement: Trust de nuvem não pode ser self_hosted
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
O sistema SHALL recusar, no catálogo versionado e no local, `trust: self_hosted` para provedores
que só existem em nuvem (`google`, `anthropic`, `openai`), com erro que cita arquivo, campo e `id`,
porque o rótulo autodeclarado contornaria `LLM_DATA_POLICY=self_hosted_only` (ADR 017 §3, §8).

#### Scenario: Modelo de nuvem rotulado self_hosted
- **GIVEN** um catálogo local com `id: google/gemini-9`, `provedor: google`, `trust: self_hosted`
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro que cita o arquivo, `trust` e o `id`

### Requirement: Política de dados explícita
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
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
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
O sistema SHALL considerar um `(provedor, modelo)` disponível somente quando houver
credencial ou endpoint, o provedor estiver em `LLM_PROVIDER_PRIORITY` e o health check passar
dentro de `LLM_HEALTH_CHECK_TIMEOUT_SECONDS`. O health check MUST NOT gerar texto, SHALL usar
`LLM_HEALTH_CHECK_TIMEOUT_SECONDS` também dentro dos provedores (sem timeouts fixos) e, para
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
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
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
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
O sistema SHALL resolver todos os papéis uma vez, antes do banner e da primeira chamada de
LLM, SHALL gravar o mapa resolvido, a política, o modo de roteamento e a versão e o hash do
catálogo em `payload["llm_routing"]`, e MUST NOT trocar o modelo de um papel durante a sessão
(ADR 017 §6, §10).

#### Scenario: Mapa no payload
- **WHEN** uma sessão inicia
- **THEN** `payload["llm_routing"]["papeis"]` tem uma entrada por papel com `id`, `trust` e `origem`
- **AND** `payload["llm_routing"]["catalogo"]["hash"]` é o sha256 do catálogo efetivo

#### Scenario: Início de sessão na telemetria
- **WHEN** uma sessão inicia
- **THEN** um evento `session_start` registra `catalog_hash`, `catalog_version`, `llm_data_policy` e `llm_routing`
- **AND** nenhuma chave, cabeçalho ou URL com credenciais aparece no evento

#### Scenario: 429 não troca o modelo resolvido
- **GIVEN** o provedor do Researcher responde 429 duas vezes
- **WHEN** a chamada é repetida
- **THEN** a retentativa usa o mesmo `id` (salvo o fallback do Google descrito no design §4)
- **AND** o consumo conta no orçamento da sessão

### Requirement: Pin provedor/modelo e modo estrito
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
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
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
O sistema SHALL tratar `preferred_model` de uma subtarefa como dica no formato
`provedor/modelo`, aceita somente se o modelo existir no catálogo, atender aos requisitos e à
política e estiver disponível; caso contrário SHALL ignorá-la com `WARNING`. Em
`LLM_ROUTING=strict`, a dica SHALL ser sempre ignorada, e a dica MUST NOT sobrepor um pin do
pesquisador (a dica é texto gerado pelo LLM do planejamento) (ADR 017 §7).

#### Scenario: Dica sem provedor
- **GIVEN** uma subtarefa do Developer com `preferred_model="qwen3:8b"`
- **WHEN** a subtarefa é despachada
- **THEN** o Developer usa o modelo resolvido da sessão e um `WARNING` cita a dica ignorada

#### Scenario: Dica não sobrepõe pin
- **GIVEN** `RESEARCHER_MODEL=ollama/qwen3:8b` (pin) e uma subtarefa do Researcher com `preferred_model="ollama/qwen3.5:4b"` válida
- **WHEN** a subtarefa é despachada
- **THEN** o Researcher usa o pin `ollama/qwen3:8b` e um `WARNING` cita a dica ignorada

#### Scenario: Dica válida
- **GIVEN** `preferred_model="ollama/qwen3:8b"`, disponível e com `ferramentas: true`
- **WHEN** a subtarefa do Developer é despachada
- **THEN** essa subtarefa usa `ollama/qwen3:8b`

### Requirement: Um único caminho de seleção
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
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
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md)_
O sistema SHALL exibir no banner, para cada papel, `provedor/modelo` e `trust`, além da
política, do modo de roteamento e da versão e do hash curto do catálogo, e MUST NOT registrar
chaves, cabeçalhos ou URLs com credenciais no banner, nos logs ou na telemetria (ADR 017 §9,
§10).

#### Scenario: Banner
- **WHEN** uma sessão inicia com o mapa resolvido
- **THEN** o banner tem uma linha por papel no formato `<papel>  <provedor/modelo>  (<trust>)`
- **AND** não contém nenhum valor de variável `*_API_KEY`

### Requirement: Localidade e aceitação de dados brutos declaradas no catálogo
_Origem: [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)_
O sistema SHALL aceitar em cada entrada do catálogo os campos `localidade` (`no_no` ou
`fora_do_no`, padrão `fora_do_no`) e `aceita_dados_brutos` (padrão `false`), e SHALL tratar
toda entrada `no_no` como `aceita_dados_brutos: true`. O sistema MUST NOT inferir esses valores
a partir da URL do endpoint.

#### Scenario: Padrões seguros
- **GIVEN** uma entrada `google/gemini-2.5-pro` sem `localidade` nem `aceita_dados_brutos`
- **WHEN** o catálogo é carregado
- **THEN** a entrada tem `localidade=fora_do_no` e `aceita_dados_brutos=false`

#### Scenario: Modelo no nó
- **GIVEN** uma entrada `ollama/qwen3:8b` com `localidade: no_no` e sem `aceita_dados_brutos`
- **WHEN** o catálogo é carregado
- **THEN** o valor efetivo de `aceita_dados_brutos` é `true`

#### Scenario: Endpoint em loopback não muda a declaração
- **GIVEN** uma entrada `openai_compatible` com `localidade: fora_do_no` e endpoint `http://127.0.0.1:8080`
- **WHEN** o catálogo é carregado
- **THEN** a localidade continua `fora_do_no`
- **AND** um `WARNING` informa que o endpoint está em loopback e pode ser túnel ou proxy

#### Scenario: Declaração no nó com endpoint remoto
- **GIVEN** uma entrada com `localidade: no_no` e endpoint `https://gpu.exemplo.org`
- **WHEN** o catálogo é carregado
- **THEN** um `WARNING` cita o `id` e o host, e a declaração é mantida

### Requirement: Coerência entre trust, localidade e dados brutos
_Origem: [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)_
O sistema SHALL recusar na inicialização, com mensagem que cita o arquivo e o `id`, qualquer
entrada com `aceita_dados_brutos: true` e `trust: third_party`, com `localidade: no_no` e
`trust: third_party`, ou com `localidade: no_no` e `aceita_dados_brutos: false` explícito.

#### Scenario: Terceiro declarando dados brutos
- **WHEN** o catálogo contém uma entrada `trust: third_party` com `aceita_dados_brutos: true`
- **THEN** a inicialização para com erro que cita a entrada

#### Scenario: Catálogo local que aceita dados brutos
- **GIVEN** um `catalog.local.yaml` que acrescenta uma entrada `self_hosted` com `aceita_dados_brutos: true`
- **WHEN** o catálogo é carregado
- **THEN** a entrada é aceita e um `WARNING` específico cita seu `id`

### Requirement: Família do modelo
_Origem: [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)_
O sistema SHALL exigir em cada entrada do catálogo o campo `familia_modelo`, texto minúsculo
não vazio, usado apenas para orientar preferência.

#### Scenario: Família ausente
- **WHEN** uma entrada do catálogo não declara `familia_modelo`
- **THEN** a inicialização para com erro que cita a entrada

### Requirement: Desempate por família no Validator
_Origem: [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)_
O sistema SHALL resolver o Validator depois dos papéis que escrevem afirmações verificadas
(Researcher, Developer, Summarizer e Curator) e, entre elegíveis da **mesma posição** de
preferência, SHALL preferir modelo de `familia_modelo` diferente das famílias desses papéis. Um modelo de posição inferior MUST NOT substituir o da
primeira posição com elegível. A escolha SHALL ser registrada no perfil de alocação.

#### Scenario: Empate resolvido por família
- **GIVEN** Researcher, Developer, Summarizer e Curator resolvidos para modelos da família `qwen`
- **AND** a primeira posição de preferência do Validator com `ollama/qwen3:8b` e `ollama/gemma3:12b`, ambos elegíveis
- **WHEN** o roteador resolve o Validator
- **THEN** o escolhido é `ollama/gemma3:12b`
- **AND** `allocation_profile.papeis.validator.desempate.aplicado` é `true`

#### Scenario: Família diferente em posição inferior
- **GIVEN** a primeira posição do Validator só com `ollama/qwen3:8b` (elegível) e a segunda com `ollama/gemma3:12b`
- **AND** o autor da família `qwen`
- **WHEN** o roteador resolve o Validator
- **THEN** o escolhido é `ollama/qwen3:8b`

#### Scenario: Pin desliga o desempate
- **WHEN** `VALIDATOR_MODEL` fixa um modelo elegível
- **THEN** o modelo fixado é usado e `desempate.aplicado` é `false`

### Requirement: Perfil de alocação da sessão
_Origem: [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)_
O sistema SHALL gravar em `payload["allocation_profile"]`, antes do primeiro envio a um
modelo, o `provedor/modelo`, `trust`, `localidade`, `aceita_dados_brutos` efetivo,
`familia_modelo` e `versao_efetiva` de cada papel, além da versão e do hash do catálogo, e
SHALL exibi-lo no banner da sessão.

#### Scenario: Perfil no payload e no banner
- **WHEN** uma sessão inicia com Researcher em `google/gemini-2.5-pro` e Validator em `ollama/qwen3:8b`
- **THEN** o payload contém o perfil com os dois papéis e seus campos
- **AND** o banner mostra uma linha por papel com `trust`, `localidade` e aceitação de dados brutos

### Requirement: Versão efetiva registrada por chamada
_Origem: [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)_
O sistema SHALL registrar em cada chamada de LLM a `versao_efetiva`, obtida de
`response.model_version` (Google), de `model` e `system_fingerprint` da resposta (OpenAI
compatível) ou do `digest` de `/api/tags` (Ollama), e SHALL registrar o valor literal
`desconhecida` quando o provedor não informar.

#### Scenario: Google informa a versão
- **GIVEN** uma resposta simulada do Google com `model_version="gemini-2.5-pro-002"`
- **WHEN** a chamada é registrada
- **THEN** `token_usage.versao_efetiva` é `gemini-2.5-pro-002`

#### Scenario: Servidor compatível sem campo de modelo
- **GIVEN** uma resposta `openai_compatible` sem `model` nem `system_fingerprint`
- **WHEN** a chamada é registrada
- **THEN** `versao_efetiva` é `desconhecida`

#### Scenario: Ollama pelo digest
- **GIVEN** `/api/tags` devolvendo `digest="sha256:abc…"` para `qwen3:8b` no início da sessão
- **WHEN** uma chamada a `ollama/qwen3:8b` é registrada
- **THEN** `versao_efetiva` é `sha256:abc…`

### Requirement: Mudança de versão dentro da sessão
_Origem: [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md)_
O sistema SHALL, quando a versão efetiva de um `provedor/modelo` mudar dentro da sessão,
gravar o evento `versao_modelo_alterada`, acrescentá-lo a `payload["eventos_versao_modelo"]`
e emitir `WARNING`. Com `LLM_ROUTING=strict`, versão alterada ou `desconhecida` após a primeira
chamada do papel SHALL encerrar a execução no próximo ponto de verificação de limites, com
fechamento e `motivo_parada="versao_modelo"`, mantendo a sessão retomável.

#### Scenario: Troca de versão em modo flexível
- **GIVEN** `LLM_ROUTING` diferente de `strict`
- **WHEN** duas chamadas ao mesmo modelo retornam versões diferentes
- **THEN** o evento é gravado e a sessão continua

#### Scenario: Troca de versão em modo strict
- **GIVEN** `LLM_ROUTING=strict`
- **WHEN** a versão de um modelo muda durante a sessão
- **THEN** nenhuma nova subtarefa é despachada
- **AND** o fechamento é executado com `motivo_parada="versao_modelo"`

#### Scenario: Versão desconhecida em modo strict
- **GIVEN** `LLM_ROUTING=strict` e um servidor compatível que não informa versão
- **WHEN** a primeira chamada desse papel termina
- **THEN** a sessão entra em fechamento no próximo ponto de verificação com `motivo_parada="versao_modelo"`

## Requisitos removidos

- Dependência do Google Agent Development Kit (removido por [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md))
- Provedor global por LLM_PROVIDER (removido por [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md))
