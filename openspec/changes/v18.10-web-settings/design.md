# Design: v18.10-web-settings

## 1. Lista fechada (revisada contra o `.env` do Mac em 2026-10-24; o desenvolvedor confere nomes e validações em `src/config.py` na tarefa 0.1)

Critério: valores que o pesquisador ajusta no dia a dia, que só mudam o comportamento da **próxima** pesquisa (cada processo de sessão lê a configuração ao iniciar) e que não mexem em infraestrutura, egresso, isolamento ou dados já gravados. Nenhum deles exige reiniciar o sistema; a consulta do REPL já aberto passa a usá-los ao reabrir o REPL, e a web relê a sobreposição a cada consulta que ela inicia.

| Grupo | Variáveis | Validação (a mesma de `src/config.py`) |
|---|---|---|
| Limites da sessão | `SESSION_MAX_MINUTES`, `SESSION_MAX_TOKENS`, `SESSION_MAX_COST_USD`, `SESSION_MAX_COST_USD_BY_PROVIDER`, `SESSION_CLOSING_RESERVE_PCT`, `LIMIT_GRACE_SECONDS`, `AGENT_TIMEOUT_SECONDS`, `CODE_SANDBOX_TIMEOUT_SECONDS` | números > 0, ou `0` onde já significa sem limite |
| Execução | `SESSION_DEFAULT_MODE` (só `semi`/`auto` pela web; `assisted` continua válido no `.env`), `MAX_SUBTASKS_PER_TASK`, `MAX_CONCURRENT_AGENTS`, `MAX_PLANNING_ITERATIONS`, `MAX_PLAN_RETRIES`, `MAX_RETRY_PER_SUBTASK`, `SESSION_MAX_TASK_RETRIES`, `TRIAGE_MODE`, `TRIAGE_CONFIDENCE_THRESHOLD`, `OPERATIONAL_THRESHOLD_SESSION_DURATION_PCT`, `OPERATIONAL_THRESHOLD_TOKEN_USAGE_PCT` | enum ou faixa atual |
| Modelos e provedores | `RESEARCHER_MODEL`, `DEVELOPER_MODEL`, `VALIDATOR_MODEL`, `REVIEWER_MODEL`, `SUMMARIZER_MODEL` (e os demais `{PAPEL}_MODEL` existentes), `GOOGLE_FALLBACK_MODEL`, `LLM_PROVIDER_PRIORITY`, `ON_MODEL_VERSION_CHANGE`, `ANTHROPIC_EFFORT`, `ANTHROPIC_REFUSAL_FALLBACK`, `OLLAMA_ENABLE_THINKING`, `OLLAMA_NUM_CTX`, `MAX_LOCAL_LLM_CONCURRENT`, `LLM_REQUESTS_PER_MINUTE`, `LLM_RATE_LIMIT_COOLDOWN_SECONDS`, `CONTEXT_COMPRESSION_MODE` | modelo escolhido da lista do §1.1; demais pelas regras atuais; a independência do Validator (ADR 020: família diferente da do Developer) é conferida antes de gravar |
| Ferramentas dos agentes | `SKILL_DEEP_SEARCH_ENABLED`, `SKILL_WEB_READER_ENABLED`, `SKILL_DOCUMENT_PROCESSOR_ENABLED`, `SKILL_MEMORY_ENABLED`, `QUICK_SEARCH_STRATEGY`, `DEEP_SEARCH_MAX_PAGES_PER_DOMAIN`, `SEARCH_CACHE_TTL_SECONDS`, `DEEP_SEARCH_CACHE_TTL_SECONDS` | booleano ou faixa atual |
| Cache de LLM | `LLM_CACHE_ENABLED`, `LLM_CACHE_TTL_SECONDS`, `LLM_CACHE_MAX_ENTRIES` | idem |
| Consulta e exibição | `TERMINAL_CONSULT_MAX_TOKENS`, `TERMINAL_EVENT_DETAIL` | idem |
| Chaves de API | `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_COMPATIBLE_API_KEY`, `BRAVE_API_KEY` | texto de 1 a 512 caracteres, sem espaço nem quebra de linha |

**Ficam de fora, com o motivo:**

| Variáveis | Motivo |
|---|---|
| `DATABASE_URL`, `POSTGRES_*`, `QDRANT_URL`, `KNOWLEDGE_*`, `BENCHMARK_*`, `LONG_TERM_MEMORY_DB`, `OUTPUT_BASE_DIR` | infraestrutura e dados; mudar perde ou mistura dados |
| `OLLAMA_BASE_URL`, `OPENAI_BASE_URL`, `OPENAI_COMPATIBLE_BASE_URL`, `DEEP_SEARCH_DOMAINS` | destino de rede: decisão de egresso (ADR 019) |
| `LLM_DATA_POLICY`, `EGRESS_*` | localidade e egresso dos dados de pesquisa (ADR 019) |
| `EMBEDDING_MODEL`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_OFFLINE` | trocar o modelo de embedding invalida os vetores já gravados no Qdrant |
| `SKILL_CODE_ENABLED`, `SKILL_HUMAN_FEEDBACK_ENABLED`, `CODE_SANDBOX_MEMORY_LIMIT`, `CODE_SANDBOX_SETUP_TIMEOUT_SECONDS`, `DOCKER_*` | isolamento do sandbox e canal humano (ADR 014, ADR 023) |
| `MIN_AVAILABLE_MEMORY_MB`, `TEMPERATURE_LIMIT`, `HEALTH_CHECK_ENABLED`, `AGENT_RUNTIME` | proteção da máquina |
| `GITHUB_*`, `APP_NAME`, `LOG_LEVEL`, `WEB_*`, `BASE_MODEL`, `KNOWLEDGE_GRAPH_NAME` | governança, identidade e infraestrutura; `BASE_MODEL` fica de fora até o desenvolvedor confirmar o uso (tarefa 0.1) |
| modo sem limite, `VERDICT_*` e variáveis de experimento | decisões reservadas ou medição da dissertação |

## 1.1 Modelos disponíveis por provedor (decisão do pesquisador, 2026-10-24)

Para que a escolha de modelo acompanhe o que os provedores oferecem, um módulo novo, `src/llm/model_discovery.py`, consulta a **lista de modelos** de cada provedor configurado, sem enviar nenhum dado de pesquisa (só a chave do próprio provedor):

| Provedor | Fonte |
|---|---|
| Google (Gemini) | API de listagem de modelos do Gemini |
| Anthropic | endpoint de listagem de modelos da API |
| OpenAI | endpoint de listagem de modelos da API |
| `openai_compatible` (vLLM do servidor LLAMA) | `GET {base}/v1/models` do endereço já configurado no `.env` |
| Ollama | `GET {base}/api/tags` |

- O resultado é cruzado com o catálogo (`src/llm/catalog.yaml`, ADR 017) e cada modelo vem marcado: `no_catalogo` (preço, papéis e família conhecidos), `novo` (oferecido pelo provedor e ausente do catálogo) ou `indisponivel` (no catálogo e não oferecido mais).
- Cache em memória por `MODEL_DISCOVERY_CACHE_SECONDS` (padrão 3600) e botão "Atualizar". Falha de um provedor (sem chave, rede, 401) aparece como erro daquele provedor, sem esconder os outros, e nunca vira lista vazia silenciosa.
- **Modelo `novo` (decisão do pesquisador, 2026-10-24, opção c):** aparece na lista só como informação, sem poder ser escolhido: fora do catálogo é provável que as requisições não funcionem (parâmetros, papéis e família desconhecidos), e o limite de custo não o enxergaria. Para usá-lo, alguém o inclui no `src/llm/catalog.yaml` por PR. `indisponivel` também não pode ser escolhido. Só `no_catalogo` é aceito em `PUT /api/settings`, para qualquer papel; a independência do Validator usa a família do catálogo.
- Também disponível na CLI (`geminiclaw models list`), para o mesmo uso fora da web, e para manter `docs/` e o catálogo atualizados.

## 2. Arquivo de sobreposição

- `RESEARCHER_ENV_FILE` (padrão `config/researcher.env`), formato `NOME=valor`, uma por linha, criado com `0600`; gravação atômica (arquivo temporário no mesmo diretório + `os.replace`) sob trava de arquivo, para o REPL e a web não se atropelarem.
- `src/config.py` lê o `.env` (como hoje) e depois a sobreposição, que **só** pode conter nomes da lista; nome fora da lista → `ConfigurationError` na inicialização (falha explícita, nunca ignorado).
- Os nomes negados ao processo da sessão (`SESSION_ENV_DENYLIST`) continuam negados: a sobreposição é carregada antes desse filtro.
- O arquivo não guarda comentários nem histórico; cada gravação registra no log (sem valores) quais nomes mudaram.

## 3. Contrato

| Rota | Resposta |
|---|---|
| `GET /api/models?atualizar=0` | `{provedores: [{provedor, ok, erro?, modelos: [{id, nome, estado: no_catalogo\|novo\|indisponivel, familia?, preco?}]}], consultado_em}` |
| `GET /api/settings` | `[{nome, grupo, valor?, definido: bool, origem: "padrao"\|"env"\|"pesquisador", segredo: bool, ultimos4?}]`. Para segredos, `valor` nunca vem; vem só `definido` e os 4 últimos caracteres |
| `PUT /api/settings` | `{alteracoes: {NOME: valor\|null}, senha}` → 200 com a lista atualizada; `null` remove a sobreposição; 422 com o nome e a mensagem de validação; 403 sem senha correta |

- Toda gravação exige sessão, CSRF, `Origin` e **a senha** (como as decisões reservadas), contando no bloqueio de tentativas.
- A validação reutiliza as funções de `src/config.py` sobre um ambiente simulado; um valor que faria a inicialização falhar é recusado antes de gravar.
- O processo da web relê a sobreposição só para mostrar os valores; o próprio servidor web não depende deles.

## 4. Frontend

Página `/configuracoes` com três grupos em cartões; cada linha com nome legível, nome técnico em mono, valor efetivo, a origem (`padrão`, `.env`, `você`) e "Restaurar" quando a origem é `você`. Chaves aparecem como `••••abcd` com "Trocar" (campo de senha, sem autocompletar). "Salvar" abre o diálogo que pede a senha e lista o que muda. Aviso fixo: "Vale para a próxima pesquisa; a que está rodando não muda."

## 5. Impacto nos 6 eixos

Orquestrador e agentes: leem a configuração como hoje. Sandbox: nenhum. Persistência: só o arquivo de sobreposição. Segurança: §6. Testes: unidade com diretório temporário e `monkeypatch` do ambiente.

## 6. Segurança

| Ameaça | Mitigação |
|---|---|
| I — chave exposta ao navegador ou em log | `valor` de segredo nunca sai da API; só os 4 últimos; logs só com nomes; resposta de erro não ecoa o valor |
| T — sessão de login sequestrada troca a chave por uma do atacante (desvia custo e dados) | senha exigida em toda gravação; destino (`*_BASE_URL`) fora da lista |
| T — injeção no arquivo (`\n` no valor cria outra variável) | valores com quebra de linha, `\0` ou `=` no nome recusados; nome só da lista |
| E — elevar privilégio pela configuração (desligar egresso, sandbox, gate) | essas variáveis estão fora da lista; nome fora da lista no arquivo derruba a inicialização |
| R — quem mudou | log estruturado com nomes alterados e o canal `web` |
| Leitura do arquivo por outro processo do usuário | `0600`; mesmo risco residual do `.env` (ADR 023 §4.3) |

## 7. Questões em aberto

Decidido em 2026-10-24: modelos na lista; busca de modelos por provedor; lista revisada contra o `.env`.

Decidido também: modelo fora do catálogo não pode ser escolhido (opção c).
