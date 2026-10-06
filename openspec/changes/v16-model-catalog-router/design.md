# Design: Catálogo de Modelos e Roteador por Papel

## 0. Estado atual (verificado em `dev`, commit `40419ea`, 2026-10-01)

| Ponto | Onde | Situação |
|---|---|---|
| Mapa papel → provedor/modelo | `src/model_config.py:22-50`, `:53-87` | Padrões fixos para `researcher`, `validator`, `developer`, `base`, `summarizer`, `reviewer`; override por `{PAPEL}_PROVIDER`/`{PAPEL}_MODEL`. |
| Roteador | `src/model_router.py:26-67` | Cache por `(provedor, modelo)`; `role=None` cai no singleton; `model=` troca só o modelo. |
| Singleton global | `src/llm/factory.py:10-17`; usos em `src/llm/agent_loop.py:172`, `src/autonomous_loop.py:179-180` | Lê `LLM_PROVIDER`/`LLM_MODEL`. |
| Variáveis legadas | `src/config.py:65-74`, `:83-86`, `:129-137` | `LLM_PROVIDER`, `LLM_MODEL`, `DEFAULT_MODEL`; `GEMINI_API_KEY` obrigatória com `LLM_PROVIDER=google`; perfil `pi5` troca `LLM_PROVIDER` para `ollama`. |
| Modelo lido pelos agentes | `agents/researcher/agent.py:144-148`, `agents/developer/agent.py:104-108`, `agents/reviewer/agent.py:57` | `AGENT_MODEL`/`{PAPEL}_MODEL`/`LLM_MODEL`/`DEFAULT_MODEL`. |
| Dica do plano | `src/orchestrator.py:66`, `:584-585`, `:790`; `src/autonomous_loop.py:485`, `:720`, `:855` | `preferred_model` só com nome de modelo. |
| CLI | `src/cli.py:129-130` | `--model` com padrão `DEFAULT_MODEL` ("Modelo Gemini"). |
| Health check | `src/llm/providers/*.py` | Ollama consulta `/api/tags` sem verificar o modelo; Google **gera texto** (`ping`, `google.py:288-297`), o que custa tokens; Anthropic consulta `models.retrieve`; `openai_compatible` consulta `/models`. |
| Fallback no 429 do Google | `src/llm/providers/google.py:14`, `:57-61`, `:165`; `GOOGLE_FALLBACK_MODEL` | Troca de modelo dentro do provedor por um período. |
| Preços | `src/llm/pricing.py` | Tabela por `provedor/modelo`; independe do catálogo. |
| `pyyaml` | `uv.lock` | Só transitiva; precisa virar dependência direta. |

## 1. Formato do catálogo (`src/llm/catalog.yaml`)

```yaml
versao: 1                       # inteiro; sobe a cada mudança de conteúdo
modelos:
  - id: google/gemini-3.8-flash # provedor/modelo; divide no primeiro "/"
    provedor: google            # precisa estar registrado (registry.available_providers)
    trust: third_party          # self_hosted | third_party
    ferramentas: true           # tool calling
    saida_estruturada: true
    janela_contexto: <tokens>   # inteiro > 0, conforme documentação do provedor
  - id: ollama/qwen3:8b
    provedor: ollama
    trust: self_hosted
    ferramentas: true
    saida_estruturada: true
    janela_contexto: <tokens>
papeis:
  researcher:
    requisitos: {ferramentas: true}
    preferencia: [anthropic/claude-sonnet-5-5, google/gemini-3.8-flash, ollama/qwen3:8b]
  developer:
    requisitos: {ferramentas: true}
    preferencia: [google/gemini-3.8-flash, ollama/qwen3:8b]
  validator:
    requisitos: {saida_estruturada: true}
    preferencia: [anthropic/claude-sonnet-5-5, ollama/qwen3:8b]
  reviewer: {...}
  summarizer: {...}
  base: {...}
aliases_papel:
  planner: researcher
```

- Campos de `modelos[]`: só os da tabela acima. `requisitos` aceita `ferramentas`,
  `saida_estruturada` (booleanos) e `janela_contexto_min` (inteiro).
- Os valores de `janela_contexto` e a lista inicial de modelos são preenchidos na implementação
  a partir da documentação de cada provedor e conferidos na revisão do PR. A ordem de
  preferência inicial reproduz o mapeamento usado hoje no Pi (Developer no Gemini; Researcher,
  Validator e Reviewer no Claude; demais no Gemini), com um modelo `ollama` ao final de cada
  lista para funcionar sob `self_hosted_only`.
- `catalog.local.yaml` (mesmo diretório, ou caminho em `LLM_CATALOG_LOCAL_PATH`; listado no
  `.gitignore`) só pode ter a chave `modelos`. Cada `id` precisa ser novo. Ao carregar, um
  `WARNING` registra o caminho e o sha256 do arquivo.

### Validação (para a inicialização, mensagem com arquivo, caminho do campo e `id`)

| Regra | Resultado |
|---|---|
| Chave desconhecida em qualquer nível | erro |
| `provedor` não registrado ou diferente do prefixo do `id` | erro |
| `id` duplicado (inclusive entre o versionado e o local) | erro |
| `trust` fora do enum; `janela_contexto` não inteiro positivo | erro |
| Papel sem nenhum modelo na `preferencia`, ou `preferencia` cita `id` inexistente | erro |
| Papel obrigatório ausente (`researcher`, `developer`, `reviewer`, `summarizer`, `validator`, `base`) | erro |
| `catalog.local.yaml` com `papeis` ou alterando um `id` existente | erro |
| Provedor com `base_url` (`openai`, `openai_compatible`, `ollama`, `anthropic`, ...) e ao menos um modelo no catálogo, com endpoint fora de loopback/rede privada (link-local não conta) e sem `https` | erro (na carga do catálogo e na criação do provedor) |
| `trust: self_hosted` em provedor só de nuvem (`google`, `anthropic`, `openai`) | erro |
| Chave repetida no mesmo mapeamento YAML | erro |

O catálogo efetivo recebe `catalog_hash` = sha256 do versionado concatenado ao local (se
houver), usado no banner, no payload e na telemetria.

## 2. Disponibilidade (`src/llm/availability.py`)

Um provedor está disponível na sessão quando as três condições valem, nesta ordem:

1. **Credencial/endpoint presentes** (`registry._resolve_api_key`/`_resolve_base_url`): Google,
   Anthropic e OpenAI exigem chave; Ollama e `openai_compatible` exigem `base_url`.
2. **Na lista de permissão** `LLM_PROVIDER_PRIORITY` (lista separada por vírgula). Ausente,
   usa o padrão do perfil: `DEPLOYMENT_PROFILE=pi5` → `ollama,openai_compatible,google,anthropic,openai`;
   `default` → `google,anthropic,openai,ollama,openai_compatible`. A ordem desta lista **não**
   muda a preferência do papel; só exclui o que não está nela.
3. **Health check** com timeout `LLM_HEALTH_CHECK_TIMEOUT_SECONDS` (padrão 5), sem geração de
   texto: Google passa a usar `models.get(model)`; Ollama confere que o **modelo** está em
   `/api/tags`; `openai_compatible` confere que o modelo está em `/models` quando o servidor
   lista modelos. O check é por `(provedor, modelo)` para os modelos que aparecem nas
   preferências e é feito uma vez por sessão (cache em memória).

Erros do health check são reduzidos a `classe da exceção + código HTTP`, sem corpo de resposta
nem cabeçalhos (ADR 017 §9).

## 3. Roteador puro (`src/llm/routing.py`)

```python
@dataclass(frozen=True)
class RoleResolution:
    papel: str
    id: str               # provedor/modelo
    trust: str
    origem: str           # "preferencia" | "pin" | "pin_legado"
    descartados: tuple[tuple[str, str], ...]  # (id, motivo) para auditoria

def resolve(papel, catalogo, disponiveis, politica, overrides, routing) -> RoleResolution
def resolve_session(catalogo, disponiveis, politica, overrides, routing) -> dict[str, RoleResolution]
```

Algoritmo de `resolve`:

1. Normaliza o papel (`aliases_papel`: `planner` → `researcher`; papel desconhecido → erro).
2. Monta os candidatos a partir da `preferencia` do papel, na ordem.
3. Descarta, registrando o motivo: `trust: third_party` sob `self_hosted_only` (antes de
   qualquer outra regra); requisito não atendido; provedor fora de `LLM_PROVIDER_PRIORITY`;
   `(provedor, modelo)` indisponível.
4. **Pin** (`overrides[papel]`, de `{PAPEL}_MODEL=provedor/modelo`): precisa existir no catálogo
   e passar pelas regras do passo 3. Se passar, vence a preferência (`origem="pin"`). Se não
   passar: em `flexible`, `WARNING` e segue a preferência; em `strict`, erro.
5. Primeiro candidato restante vence. Nenhum → `NoEligibleModelError` com o papel, a política
   e a lista `(id, motivo)` dos descartados, e a sugestão concreta (ex.: "defina
   `LLM_DATA_POLICY=third_party_allowed`" quando todos foram descartados pela política).

`resolve_session` chama `resolve` para os seis papéis e para os papéis registrados por mudanças
futuras (ex.: `curator`) que existirem no catálogo. Sem I/O: disponibilidade e catálogo entram
como argumentos.

### Transição de variáveis

| Entrada | Tratamento |
|---|---|
| `{PAPEL}_MODEL=provedor/modelo` | pin |
| `{PAPEL}_PROVIDER=p` + `{PAPEL}_MODEL=m` (sem `/`) | pin `p/m` com `WARNING` de obsolescência (`origem="pin_legado"`) |
| `{PAPEL}_MODEL=m` sem `/` e sem `{PAPEL}_PROVIDER` | erro acionável ("use provedor/modelo") |
| `LLM_PROVIDER`, `LLM_MODEL`, `DEFAULT_MODEL`, `AGENT_MODEL` | ignoradas com `WARNING` único na inicialização que lista as encontradas |

## 4. Integração com a sessão

- O orquestrador resolve o mapa **antes** de imprimir o banner e de qualquer chamada de LLM,
  guarda-o em `payload["llm_routing"]`:

  ```json
  {"politica": "third_party_allowed", "routing": "flexible",
   "catalogo": {"versao": 1, "hash": "…", "local": false},
   "papeis": {"researcher": {"id": "anthropic/claude-sonnet-5-5", "trust": "third_party", "origem": "preferencia"}, "…": {}}}
  ```

- `ModelRouter.get_provider(papel)` lê o mapa da sessão corrente (via `AgentContext` ou um
  `contextvars.ContextVar` definido pelo orquestrador). Fora de sessão (testes, CLI auxiliar),
  resolve na hora com os mesmos dados.
- `get_provider()` sem papel → `get_provider("researcher")`. O singleton de `factory.py` sai.
- `--model` da CLI passa a significar pin `provedor/modelo` para o papel `researcher`
  (compatível com o uso atual, que só afetava o modelo padrão).
- **Dica do plano** (`preferred_model`, formato `provedor/modelo`): aceita se o `id` existe,
  atende aos requisitos e à política e está disponível; caso contrário `WARNING` e o papel usa o
  modelo resolvido. Em `strict`, sempre ignorada. Uma dica sem `/` é ignorada com `WARNING`.
- **Credenciais:** a verificação de `GEMINI_API_KEY` sai do import de `config.py`; a falta de
  credencial só é erro se um papel do mapa resolvido precisa dela (na prática o provedor nem
  fica disponível, e o erro é o do passo 5).
- **Fallback do Google no 429** (`GOOGLE_FALLBACK_MODEL`): passa a ser aceito só se o modelo de
  fallback estiver no catálogo com o mesmo `trust` e atender aos requisitos do papel; em
  `strict` fica desligado. A troca é registrada na telemetria com o `id` efetivamente usado
  (ver questão em aberto 2).
- **Telemetria:** cada chamada já registra `llm_provider` e `llm_model`
  (`agent_loop.py:302-317`); passa a registrar também `catalog_hash` no evento de início de
  sessão (não por chamada).

## 5. Banner

Bloco novo, uma linha por papel: `researcher  anthropic/claude-sonnet-5-5  (third_party)`,
mais a política, o modo de roteamento e `catálogo v1 · <hash curto>`. Só `provedor/modelo`,
host do endpoint e hash: nunca chave, cabeçalho ou URL completa com credenciais.

## 6. Configuração (`src/config.py`, `.env.example`)

| Variável | Padrão | Uso |
|---|---|---|
| `LLM_DATA_POLICY` | `self_hosted_only` | Política de dados (ADR 017 §3) |
| `LLM_ROUTING` | `flexible` | `strict` torna pins e conflitos fatais e ignora dicas |
| `LLM_PROVIDER_PRIORITY` | por `DEPLOYMENT_PROFILE` (§2) | Lista de permissão |
| `LLM_HEALTH_CHECK_TIMEOUT_SECONDS` | 5 | Timeout por check |
| `LLM_CATALOG_LOCAL_PATH` | `src/llm/catalog.local.yaml` | Catálogo local opcional |
| `{PAPEL}_MODEL` | vazio | Pin `provedor/modelo` |

Removidas: `LLM_PROVIDER`, `LLM_MODEL`, `DEFAULT_MODEL` (e o bloco de `{PAPEL}_PROVIDER` do
`.env.example`, mantido só como comentário de transição).

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Resolução no início da sessão; mapa no payload; dica do plano validada. Sem troca no meio da sessão. |
| Agentes & Prompts | Agentes deixam de ler variáveis de modelo; nenhum prompt muda. |
| Sandboxes & Containers | Nenhum. |
| Persistência | Chave `llm_routing` no payload JSONB; nenhum schema. |
| Segurança | Política padrão restritiva; `https` obrigatório para endpoint remoto; catálogo local só acrescenta e é registrado por hash; logs sem segredos. |
| Testes & Telemetria | Roteador puro testável por unidade; teste do catálogo versionado; telemetria com `catalog_hash`. |

## 8. Segurança

Superfícies: (a) envio de prompts a terceiros sem decisão explícita — fechado pelo padrão
`self_hosted_only`; (b) catálogo local adulterado para redirecionar um papel — mitigado porque
o local não altera entradas nem papéis, só acrescenta, e o hash aparece no banner; um pin para
um modelo local continua sujeito à política; (c) chave enviada a host errado — a chave é resolvida por provedor e só vai ao `base_url` configurado do mesmo provedor; `openai` e `openai_compatible` têm variáveis próprias (`OPENAI_*` e `OPENAI_COMPATIBLE_*`), então a chave real da OpenAI nunca vai a um servidor compatível; todo `base_url` fora de loopback/rede privada (link-local excluído) exige `https`, validado na carga do catálogo e na criação do provedor (a versão anterior validava só entradas `openai_compatible`, o que deixava `openai`, `ollama` e `anthropic` sem proteção); (b') `trust` autodeclarado — `self_hosted` é recusado para provedores só de nuvem; (d) vazamento em erro de health check — mensagens sanitizadas. O Analista de
Segurança deve confirmar (b) e (c) no PR.

## 9. Riscos

- **Quebra do `.env` atual** (Pi e Mac): sem `LLM_DATA_POLICY=third_party_allowed`, só sobra o
  Ollama. Mitigação: mensagem do passo 5 diz exatamente o que definir; `.env.example`
  atualizado; nota no PR.
- **Health check lento** com provedor fora do ar: timeout curto e checks em paralelo
  (`asyncio.gather`).
- **Catálogo desatualizado**: modelo novo exige PR; o local cobre o uso imediato.

## 10. Questões em aberto para o pesquisador

1. **Ordem de preferência inicial** de cada papel: confirmar a proposta do §1 (mapeamento atual
   do Pi, Ollama ao final). `base` e `summarizer` ficam no Gemini?
2. **Fallback do Google no 429:** manter (restrito a modelo do catálogo com o mesmo `trust`,
   desligado em `strict`, como proposto) ou remover, já que o ADR 017 §6 exclui troca no meio da
   sessão?
3. **Validator e reprodutibilidade:** com o Validator no mesmo modelo do Researcher (Claude nos
   dois), aceitar por ora? O desempate por família de modelo só chega com
   `v18.5-model-catalog-locality`.
