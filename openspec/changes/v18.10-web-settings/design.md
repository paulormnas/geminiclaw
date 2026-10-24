# Design: v18.10-web-settings

## 1. Lista fechada (proposta; o desenvolvedor confere nomes e validações contra `src/config.py` na tarefa 0.1)

| Grupo | Variáveis | Validação (a mesma de `src/config.py`) |
|---|---|---|
| Limites da sessão | `SESSION_MAX_MINUTES`, `SESSION_MAX_TOKENS`, `SESSION_MAX_COST_USD`, `SESSION_MAX_COST_USD_BY_PROVIDER`, `AGENT_TIMEOUT_SECONDS`, `MAX_SUBTASKS_PER_TASK`, `MAX_CONCURRENT_AGENTS` | números > 0 (ou `0` onde significa sem limite, como hoje) |
| Consulta | `TERMINAL_CONSULT_MAX_TOKENS`, `TERMINAL_EVENT_DETAIL` | idem |
| Modelos e provedores | `LLM_PROVIDER_PRIORITY`, `{PAPEL}_MODEL` (pins por papel), `GOOGLE_FALLBACK_MODEL`, `ON_MODEL_VERSION_CHANGE` | provedor e modelo existentes no catálogo (`src/llm/catalog.yaml`) |
| Chaves de API | `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_COMPATIBLE_API_KEY`, `BRAVE_API_KEY` | texto de 1 a 512 caracteres, sem espaço nem quebra de linha |

Ficam de fora, mesmo que pareçam inofensivas: tudo de banco (`DATABASE_URL`, `POSTGRES_*`, `QDRANT_*`), `OPENAI_COMPATIBLE_BASE_URL` e endereços de provedor (mudar o destino é decisão de egresso, ADR 019), `EGRESS_*`, `SANDBOX_*`, `WEB_*`, `MIN_AVAILABLE_MEMORY_MB`, `TEMPERATURE_LIMIT`, o modo sem limite e variáveis de experimento.

## 2. Arquivo de sobreposição

- `RESEARCHER_ENV_FILE` (padrão `config/researcher.env`), formato `NOME=valor`, uma por linha, criado com `0600`; gravação atômica (arquivo temporário no mesmo diretório + `os.replace`) sob trava de arquivo, para o REPL e a web não se atropelarem.
- `src/config.py` lê o `.env` (como hoje) e depois a sobreposição, que **só** pode conter nomes da lista; nome fora da lista → `ConfigurationError` na inicialização (falha explícita, nunca ignorado).
- Os nomes negados ao processo da sessão (`SESSION_ENV_DENYLIST`) continuam negados: a sobreposição é carregada antes desse filtro.
- O arquivo não guarda comentários nem histórico; cada gravação registra no log (sem valores) quais nomes mudaram.

## 3. Contrato

| Rota | Resposta |
|---|---|
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

1. A lista do §1 está boa? Em particular: incluir `{PAPEL}_MODEL` e `LLM_PROVIDER_PRIORITY` (mudam qual modelo responde) e `MAX_CONCURRENT_AGENTS`.
