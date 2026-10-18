# Especificação: llm-providers

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md), [`v16-anthropic-provider`](../../changes/archive/v16-anthropic-provider/proposal.md), [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md), [`v18.5-model-catalog-locality`](../../changes/archive/v18.5-model-catalog-locality/proposal.md), [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md), [`v18.6-remove-unused-agents`](../../changes/archive/v18.6-remove-unused-agents/proposal.md), [`v18.7-layer-cycles`](../../changes/archive/v18.7-layer-cycles/proposal.md), [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md), [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)

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
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
O provedor SHALL levantar `ProviderRefusalError` com a categoria quando a resposta for uma recusa, SHALL levantar `ProviderQuotaExhausted` sem retentativa quando o erro for classificado como esgotamento de cota ou gasto, e SHALL retentar apenas erros de conexão, 429 não classificado como cota e 5xx, emitindo `connection_retry` a cada retentativa.

#### Scenario: Recusa por classificador de segurança
- **WHEN** a resposta tem `stop_reason == "refusal"` com categoria `bio`
- **THEN** `ProviderRefusalError` é levantado informando o modelo e a categoria

#### Scenario: Erro de cliente
- **WHEN** a API retorna 400 sem marcador de cota
- **THEN** o erro é propagado sem retentativa

#### Scenario: Saldo esgotado na Anthropic
- **GIVEN** um cliente Anthropic simulado que responde 400 com a mensagem `Your credit balance is too low to access the Anthropic API`
- **WHEN** `generate` é chamado
- **THEN** `ProviderQuotaExhausted` é levantado com `provider="anthropic"`, o modelo e `status_code=400`
- **AND** o cliente foi chamado uma única vez e nenhum `connection_retry` foi emitido

### Requirement: Catálogo versionado e validado
_Origem: [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md), alterado por [`v18.6-remove-unused-agents`](../../changes/archive/v18.6-remove-unused-agents/proposal.md)_
O sistema SHALL carregar `src/llm/catalog.yaml` com `yaml.safe_load` e validá-lo por esquema
estrito antes de qualquer chamada de LLM, e SHALL interromper a inicialização, com mensagem
que cita o arquivo, o campo e o `id`, quando houver chave desconhecida, provedor não
registrado, `id` duplicado, valor fora do enum ou papel sem modelo na preferência
(ADR 017 §1, §9). Um papel removido (`reviewer`) SHALL ser rejeitado com mensagem que o identifica
como removido.
(Antes: seis papéis obrigatórios, incluindo `reviewer`.)

#### Scenario: Catálogo versionado válido
- **WHEN** o teste carrega o `src/llm/catalog.yaml` do repositório
- **THEN** a validação passa
- **AND** todos os cinco papéis (`researcher`, `developer`, `summarizer`, `validator`, `base`) têm ao menos um modelo na preferência

#### Scenario: Catálogo local com papel removido
- **GIVEN** um `catalog.local.yaml` com `papeis.reviewer`
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro que cita `reviewer` como papel removido

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
- **GIVEN** um catálogo local que redeclara `google/gemini-4-argon` com `trust: self_hosted`
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
- **AND** `google/gemini-4-argon` aparece nos descartados com motivo `politica`

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
- **GIVEN** `DEVELOPER_PROVIDER=google` e `DEVELOPER_MODEL=gemini-4-argon`
- **WHEN** a sessão inicia
- **THEN** o Developer recebe o pin `google/gemini-4-argon` com `origem="pin_legado"`
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
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
O sistema SHALL, quando a versão efetiva de um `provedor/modelo` mudar dentro da sessão, gravar o evento `versao_modelo_alterada` (provedor, modelo, versão anterior e nova), acrescentá-lo a `payload["eventos_versao_modelo"]` e emitir `WARNING`. A política `ON_MODEL_VERSION_CHANGE` (`src/config.py`; variável de ambiente de mesmo nome; `retomar` padrão | `parar`; outro valor falha na inicialização) SHALL valer somente com `LLM_ROUTING=strict`; no modo flexível a sessão apenas registra, avisa e continua.

Com `LLM_ROUTING=strict` e `ON_MODEL_VERSION_CHANGE=retomar`, versão alterada ou `desconhecida`, ou modelo indisponível, após a primeira chamada do papel SHALL, no próximo ponto de verificação de limites, gravar um checkpoint e continuar a sessão:

- versão nova informada: a sessão continua com o mesmo modelo e a nova versão fica registrada na proveniência;
- versão `desconhecida` ou modelo indisponível: o papel passa ao próximo modelo elegível da lista `preferencia` do papel no catálogo (`src/llm/catalog.yaml`), respeitando a elegibilidade do ADR 017, a família do Validator diferente da do Developer (ADR 020) e a localidade (ADR 019), e o evento `modelo_substituido` (papel, modelo anterior, modelo novo, motivo) é gravado;
- sem modelo elegível: a sessão fecha com `motivo_parada="versao_modelo"` e checkpoint, retomável.

Com `LLM_ROUTING=strict` e `ON_MODEL_VERSION_CHANGE=parar`, versão alterada ou `desconhecida` após a primeira chamada do papel SHALL encerrar a execução no próximo ponto de verificação de limites, com fechamento e `motivo_parada="versao_modelo"`, mantendo a sessão retomável (comportamento anterior; usado pela bateria do benchmark).
(Antes: o modo `strict` sempre fechava com `versao_modelo`.)

#### Scenario: Troca de versão em modo flexível
- **GIVEN** `LLM_ROUTING` diferente de `strict`
- **WHEN** duas chamadas ao mesmo modelo retornam versões diferentes
- **THEN** o evento é gravado e a sessão continua, qualquer que seja `ON_MODEL_VERSION_CHANGE`

#### Scenario: Versão nova informada com a política retomar
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=retomar` e um provedor simulado que informa `v1` na primeira chamada e `v2` na segunda
- **WHEN** o próximo ponto de verificação de limites é alcançado
- **THEN** o checkpoint é gravado, o evento `versao_modelo_alterada` registra provedor, modelo, `anterior="v1"` e `nova="v2"`, e novas subtarefas continuam sendo despachadas
- **AND** os registros de proveniência posteriores ao evento trazem a versão `v2` e a sessão não fecha

#### Scenario: Versão desconhecida com substituição de modelo
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=retomar`, um catálogo de teste em que o papel Researcher tem `preferencia` com os modelos `m1` e `m2` (ambos elegíveis), e um provedor simulado que deixa de informar a versão de `m1`
- **WHEN** o próximo ponto de verificação de limites é alcançado
- **THEN** o papel Researcher passa a usar `m2` e o evento `modelo_substituido` registra `papel="researcher"`, `anterior="m1"`, `novo="m2"` e `motivo="versao_desconhecida"`
- **AND** a sessão não fecha

#### Scenario: Substituição respeita a família do Validator
- **GIVEN** as condições do cenário anterior para o papel Validator, em que o próximo modelo da `preferencia` é da mesma família do Developer e o seguinte é de família diferente
- **WHEN** o ponto de verificação é alcançado
- **THEN** o Validator passa ao modelo de família diferente e `modelo_substituido` registra esse modelo

#### Scenario: Substituição respeita a localidade
- **GIVEN** as condições do cenário "Versão desconhecida com substituição de modelo", com dados de pesquisa contaminados e o próximo modelo da `preferencia` na nuvem sem `aceita_dados_brutos`
- **WHEN** o ponto de verificação é alcançado
- **THEN** esse modelo é descartado e o seguinte elegível pela localidade é escolhido

#### Scenario: Sem modelo elegível
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=retomar` e um papel cujos modelos restantes na `preferencia` são todos inelegíveis
- **WHEN** a versão do modelo atual deixa de ser informada e o ponto de verificação é alcançado
- **THEN** a sessão fecha com `motivo_parada="versao_modelo"` com checkpoint e continua retomável, e nenhum evento `modelo_substituido` é gravado

#### Scenario: Troca de versão em modo strict com a política parar
- **GIVEN** `LLM_ROUTING=strict` e `ON_MODEL_VERSION_CHANGE=parar`
- **WHEN** a versão de um modelo muda durante a sessão
- **THEN** nenhuma nova subtarefa é despachada
- **AND** o fechamento é executado com `motivo_parada="versao_modelo"`

#### Scenario: Versão desconhecida em modo strict com a política parar
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=parar` e um servidor compatível que não informa versão
- **WHEN** a primeira chamada desse papel termina
- **THEN** a sessão entra em fechamento no próximo ponto de verificação com `motivo_parada="versao_modelo"`

#### Scenario: Valor inválido de ON_MODEL_VERSION_CHANGE
- **GIVEN** `ON_MODEL_VERSION_CHANGE=talvez`
- **WHEN** `src/config.py` é importado
- **THEN** a inicialização falha com `ConfigurationError` que cita `ON_MODEL_VERSION_CHANGE` e os valores `retomar` e `parar`

### Requirement: Modo de independência do julgamento
_Origem: [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md)_
O sistema SHALL ler `LLM_JUDGE_INDEPENDENCE` (`required`, `preferred`, `off`). Sem valor, o modo
SHALL ser `required` com `LLM_DATA_POLICY=third_party_allowed` e `preferred` com
`self_hosted_only`. Valor inválido MUST impedir a inicialização (ADR 020 §2).

#### Scenario: Padrão em política de terceiros
- **GIVEN** `LLM_DATA_POLICY=third_party_allowed` e a variável ausente
- **WHEN** a sessão resolve o mapa
- **THEN** o modo é `required` com `origem_modo = "padrao_politica"`

#### Scenario: Padrão só local
- **GIVEN** `LLM_DATA_POLICY=self_hosted_only` e a variável ausente
- **WHEN** a sessão resolve o mapa
- **THEN** o modo é `preferred`

#### Scenario: Valor inválido
- **GIVEN** `LLM_JUDGE_INDEPENDENCE=sim`
- **WHEN** a sessão inicia
- **THEN** a inicialização falha com mensagem que lista `required`, `preferred` e `off`

### Requirement: Família do Validator diferente da do Developer
_Origem: [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md)_
Com modo `required` ou `preferred`, o roteador SHALL resolver o `validator` para um modelo de
`familia_modelo` diferente da do modelo resolvido para o `developer`, descartando os demais com o
motivo `mesma_familia_julgamento`, inclusive quando o modelo de outra família está num grupo de
preferência inferior (ADR 020 §3 e §4).

#### Scenario: Preferido da mesma família
- **GIVEN** `developer` resolvido para `anthropic/claude-sonnet-5-5` e a preferência do `validator`
  `[anthropic/claude-sonnet-5-5, google/gemini-4-argon]`, ambos disponíveis
- **WHEN** o mapa é resolvido
- **THEN** o `validator` é `google/gemini-4-argon`
- **AND** `anthropic/claude-sonnet-5-5` aparece em `descartados` com `mesma_familia_julgamento`

#### Scenario: Sem modelo elegível em `required`
- **GIVEN** só modelos da família `claude` disponíveis e modo `required`
- **WHEN** o mapa é resolvido
- **THEN** a sessão falha com `NoEligibleModelError`
- **AND** a sugestão cita `LLM_JUDGE_INDEPENDENCE=preferred`

#### Scenario: Sem modelo elegível em `preferred`
- **GIVEN** só modelos da família `qwen` e modo `preferred`
- **WHEN** o mapa é resolvido
- **THEN** o `validator` é o preferido do catálogo
- **AND** o registro tem `atendida = false` e o banner mostra o aviso

#### Scenario: Modo `off`
- **GIVEN** modo `off` e o mesmo modelo preferido para `developer` e `validator`
- **WHEN** o mapa é resolvido
- **THEN** os dois papéis usam o mesmo modelo, como antes desta mudança

### Requirement: Pins na regra de independência
_Origem: [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md)_
O roteador SHALL resolver primeiro os papéis com pin, SHALL fazer os papéis julgados sem pin
descartarem as famílias dos juízes com pin e SHALL tratar dois pins em conflito pela tabela do
design §3.

#### Scenario: Só o juiz com pin
- **GIVEN** `VALIDATOR_MODEL=anthropic/claude-sonnet-5-5`, `developer` sem pin, preferência do
  `developer` `[anthropic/claude-sonnet-5-5, google/gemini-4-argon]`, modo `required`
- **WHEN** o mapa é resolvido
- **THEN** o `validator` é `anthropic/claude-sonnet-5-5` e o `developer` é `google/gemini-4-argon`

#### Scenario: Dois pins em conflito, `strict`
- **GIVEN** `VALIDATOR_MODEL` e `DEVELOPER_MODEL` da família `claude`, `LLM_ROUTING=strict`, modo `required`
- **WHEN** o mapa é resolvido
- **THEN** a sessão falha com `PinError`

#### Scenario: Dois pins em conflito, `flexible`
- **GIVEN** o mesmo caso com `LLM_ROUTING=flexible`
- **WHEN** o mapa é resolvido
- **THEN** o pin do `developer` é mantido, o pin do `validator` é ignorado com `WARNING`
- **AND** o `validator` vem da preferência, de outra família

### Requirement: Conferência no despacho
_Origem: [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md)_
O sistema SHALL conferir, a cada dica de plano aceita e troca para o modelo de reserva no 429, que o
juiz (`validator`) e o julgado (`developer`) em uso não compartilham família, e SHALL registrar o
evento `independencia_julgamento` com a decisão.

#### Scenario: Dica do Developer na família do juiz
- **GIVEN** `validator` da família `claude`, modo `required` e uma subtarefa do `developer` com
  `preferred_model: anthropic/claude-sonnet-5-5`
- **WHEN** a dica é avaliada
- **THEN** a dica é rejeitada e a subtarefa usa o modelo resolvido do `developer`
- **AND** o evento registra `decisao = "rejeitado"` e `motivo = "mesma_familia_julgamento"`

#### Scenario: Modo `off` não confere a reserva
- **GIVEN** modo `off`, `developer` e `validator` da família `gemini` e uma reserva `gemini`
- **WHEN** ocorre 429 no `developer`
- **THEN** a reserva é usada

#### Scenario: Reserva do 429 na família do juiz em `required`
- **GIVEN** `validator` da família `gemini`, `developer` de outra família e uma reserva do `developer` da família `gemini`
- **WHEN** ocorre 429 no `developer`
- **THEN** a reserva não é usada e o 429 segue o cooldown e as retentativas

### Requirement: Registro da independência
_Origem: [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md)_
O payload da sessão SHALL conter `independencia_julgamento` com modo, origem do modo, modelo, família
e origem da família de `validator` e `developer`, e `atendida`. O banner e o relatório final SHALL
mostrar a linha de julgamento.

#### Scenario: Registro na inicialização
- **WHEN** a sessão inicia com `validator` `gemini` e `developer` `claude`
- **THEN** o payload tem `independencia_julgamento.atendida = true` e as duas famílias
- **AND** o banner contém "gemini (validator)" e "claude (developer)"

### Requirement: Conferência na retomada
_Origem: [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md)_
Ao retomar uma sessão, o sistema SHALL carregar as famílias julgadas registradas na sessão original
e SHALL aplicar a conferência e o modo ao juiz resolvido na retomada antes de reverificar
afirmações pendentes.

#### Scenario: Catálogo mudou entre as execuções
- **GIVEN** uma sessão original com `developer` `claude` e uma retomada em que o `validator` resolve
  para `claude`, modo `required`
- **WHEN** a sessão é retomada
- **THEN** a retomada falha com `NoEligibleModelError` antes de reverificar afirmações

### Requirement: Preferência dos juízes no catálogo
_Origem: [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md)_
O catálogo versionado SHALL listar, na preferência de `validator`, ao menos um modelo de
nuvem de cada família do catálogo antes de qualquer modelo local.

#### Scenario: Teste do catálogo
- **WHEN** o catálogo versionado é carregado no teste
- **THEN** a preferência de `validator` contém `claude`, `gemini` e `gpt` antes de `qwen`

### Requirement: Variável de modelo obsoleta
_Origem: [`v18.6-remove-unused-agents`](../../changes/archive/v18.6-remove-unused-agents/proposal.md)_
Com `REVIEWER_MODEL` definida no ambiente, o sistema SHALL registrar `WARNING` na inicialização
informando que o papel foi removido, e SHALL seguir sem usá-la.

#### Scenario: `REVIEWER_MODEL` definida
- **GIVEN** `REVIEWER_MODEL=anthropic/claude-haiku-5-5`
- **WHEN** a sessão inicia
- **THEN** o log tem um `WARNING` que cita `REVIEWER_MODEL` e o papel removido

### Requirement: Rótulo da revisão de subtarefa
_Origem: [`v18.6-remove-unused-agents`](../../changes/archive/v18.6-remove-unused-agents/proposal.md) (substitui o requisito "Rótulo de papel da revisão de subtarefa" de [`v18.6-validator-independence`](../../changes/archive/v18.6-validator-independence/proposal.md))_
A chamada LLM e o evento da revisão de subtarefa SHALL ser registrados com o papel `validator` e
`funcao = "revisao_subtarefa"`.
(Antes: a chamada já usava o papel `validator` desde a `v18.6-validator-independence`, mas o evento `subtask_review` registrava `agent_id = "reviewer"`.)

#### Scenario: Telemetria da revisão
- **WHEN** `review_result` chama o modelo
- **THEN** o registro da chamada e o evento `subtask_review` têm papel `validator`

### Requirement: Resolvedor de provedor registrado na partida
_Origem: [`v18.7-layer-cycles`](../../changes/archive/v18.7-layer-cycles/proposal.md)_
`src.llm.factory.get_provider()` SHALL obter o provedor pela função registrada com `set_provider_resolver`; `src.egress.routing.install_provider_resolver()` SHALL registrar `ModelRouter.get_provider`, e `main()` de `src/cli/main.py` SHALL chamá-la antes de ler os argumentos. Sem resolvedor registrado, `get_provider()` MUST lançar `RuntimeError` com a mensagem "resolvedor de provedor não registrado: a partida deve registrar o roteador com filtro de egresso" e MUST NOT criar provedor (ADR 017; ADR 024 §4).

#### Scenario: Sem registro, falha explícita
- **GIVEN** nenhum resolvedor registrado (`monkeypatch.setattr(factory, "_resolver", None)`, desfazendo o registro da fixture de `tests/conftest.py`) e `ModelRouter.get_provider` substituído por um dublê que conta chamadas
- **WHEN** o código chama `get_provider()`
- **THEN** é lançado `RuntimeError` com a mensagem do requisito e o dublê não foi chamado

#### Scenario: Partida registra o roteador
- **GIVEN** nenhum resolvedor registrado e `sys.argv` igual a `["geminiclaw", "--help"]`
- **WHEN** o teste chama `main()` de `src/cli/main.py` (capturando o `SystemExit` da ajuda) e depois `get_provider()`
- **THEN** o provedor devolvido é um `GatedProvider` do papel `researcher` (`provider.dest.papel == "researcher"`), igual ao de `ModelRouter.get_provider("researcher")`

### Requirement: Provedor interno sem depender do filtro
_Origem: [`v18.7-layer-cycles`](../../changes/archive/v18.7-layer-cycles/proposal.md)_
`LLMProvider` SHALL oferecer `unwrap()`, que devolve o próprio provedor; o `GatedProvider` SHALL devolver o provedor interno. `src.llm.metering.provider_name` SHALL usar `unwrap()` e MUST NOT importar `src.egress` (ADR 024 §4).

#### Scenario: Nome do provedor com e sem filtro
- **GIVEN** um provedor simulado `FakeProvider` e o mesmo provedor envolvido por `GatedProvider`
- **WHEN** o teste chama `provider_name` com cada um
- **THEN** os dois resultados são `fake`

### Requirement: Prioridade padrão de provedores sem perfil de máquina
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
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

### Requirement: Esgotamento de cota distinto de limite de taxa
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
Os provedores de nuvem (`google`, `anthropic`, `openai`, `openai_compatible`) SHALL classificar como esgotamento de cota ou gasto o erro com status 429, 400, 402 ou 403 cuja mensagem contenha, sem diferenciar maiúsculas, um dos marcadores do provedor (`LLM_QUOTA_MARKERS_GOOGLE`, padrão `spending cap`; `LLM_QUOTA_MARKERS_ANTHROPIC`, padrão `credit balance is too low`; `LLM_QUOTA_MARKERS_OPENAI`, padrão `insufficient_quota`; `LLM_QUOTA_MARKERS_OPENAI_COMPATIBLE`, padrão vazio). Nesse caso o provedor SHALL levantar `ProviderQuotaExhausted` (provedor, modelo, status, detalhe truncado em 300 caracteres) sem retentar e sem trocar para o modelo de reserva, e SHALL registrar o esgotamento para a sessão corrente. Um 429 sem marcador SHALL continuar retentado como hoje. `is_retryable_error` SHALL devolver `False` para `ProviderQuotaExhausted`.

#### Scenario: Teto de gasto do Google
- **GIVEN** um `genai.Client` simulado cujo `generate_content` levanta erro 429 `RESOURCE_EXHAUSTED` com mensagem contendo `spending cap`, e `GOOGLE_FALLBACK_MODEL` diferente do modelo principal
- **WHEN** `GoogleProvider.generate` é chamado
- **THEN** `ProviderQuotaExhausted` é levantado com `provider="google"` e `status_code=429`
- **AND** `generate_content` foi chamado uma única vez e nunca com o modelo de reserva

#### Scenario: Limite por minuto do Google continua transitório
- **GIVEN** um `genai.Client` simulado que levanta 429 `RESOURCE_EXHAUSTED` com a mensagem `You exceeded your current quota, please check your plan and billing details` uma vez e depois responde com sucesso
- **WHEN** `GoogleProvider.generate` é chamado
- **THEN** a chamada é repetida e devolve a resposta de sucesso
- **AND** nenhum `ProviderQuotaExhausted` é levantado

#### Scenario: Cota da OpenAI lida no corpo do 429
- **GIVEN** um `httpx.MockTransport` que responde 429 com corpo `{"error": {"code": "insufficient_quota"}}`
- **WHEN** `OpenAIProvider.generate` é chamado
- **THEN** `ProviderQuotaExhausted` é levantado com `provider="openai"` sem retentativa

#### Scenario: Limite de taxa da OpenAI continua transitório
- **GIVEN** um `httpx.MockTransport` que responde 429 com corpo `{"error": {"code": "rate_limit_exceeded"}}` e depois 200
- **WHEN** `OpenAIProvider.generate` é chamado
- **THEN** a resposta de sucesso é devolvida após uma retentativa

#### Scenario: Marcadores configuráveis
- **GIVEN** `LLM_QUOTA_MARKERS_GOOGLE="monthly budget,spending cap"`
- **WHEN** a mensagem de um 429 do Google contém `Monthly Budget`
- **THEN** o erro é classificado como esgotamento de cota

### Requirement: Retentativa de conexão atribuída à sessão
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
`emit_connection_retry` SHALL gravar o evento com o `execution_id` resolvido na ordem: `AgentContext` corrente (`execution_id`, ou `session_id` na falta dele), `bound_execution_id()`, `EXECUTION_ID`/`SESSION_ID` do ambiente e, por fim, `"unknown"`. A resolução SHALL ser a mesma usada por `_task_env` do laço de agente.

#### Scenario: Agente em processo
- **GIVEN** um `AgentContext` vinculado com `execution_id="sessao-mestra-1"` e nenhuma variável `EXECUTION_ID` no ambiente
- **WHEN** um provedor emite `connection_retry`
- **THEN** o evento é gravado com `execution_id="sessao-mestra-1"`

#### Scenario: Planejamento fora do AgentContext
- **GIVEN** nenhum `AgentContext` e `bound_execution_id()` igual a `sessao-mestra-2`
- **WHEN** um provedor emite `connection_retry`
- **THEN** o evento é gravado com `execution_id="sessao-mestra-2"`

### Requirement: Resfriamento do limitador de taxa com teto
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
`AdaptiveRateLimiter.report_429` SHALL manter o crescimento exponencial atual do resfriamento (`src/rate_limiter.py:86`), resfriamento da n-ésima chamada consecutiva igual a `LLM_RATE_LIMIT_COOLDOWN_SECONDS * 2^(n-1)`, e SHALL limitá-lo a `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS` (padrão 300), isto é, `min(LLM_RATE_LIMIT_COOLDOWN_SECONDS * 2^(n-1), LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS)`. O orquestrador SHALL NOT chamar `report_429` para um resultado de agente com `error_category="cota_provedor"`.

#### Scenario: Teto do resfriamento
- **GIVEN** `LLM_RATE_LIMIT_COOLDOWN_SECONDS=30` e `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS=300`
- **WHEN** `report_429` é chamado 6 vezes seguidas, sem requisição bem-sucedida entre as chamadas
- **THEN** os resfriamentos aplicados são 30, 60, 120, 240, 300 e 300 segundos
- **AND** nenhum resfriamento passa de 300 segundos

#### Scenario: Cota não aciona o limitador
- **GIVEN** um `AgentResult` com `status="error"`, `error="429 RESOURCE_EXHAUSTED ... spending cap"` e `error_category="cota_provedor"`
- **WHEN** o orquestrador processa o resultado
- **THEN** `report_429` não é chamado

## Requisitos removidos

- Dependência do Google Agent Development Kit (removido por [`v16-provider-registry`](../../changes/archive/v16-provider-registry/proposal.md))
- Provedor global por LLM_PROVIDER (removido por [`v16-model-catalog-router`](../../changes/archive/v16-model-catalog-router/proposal.md))

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
