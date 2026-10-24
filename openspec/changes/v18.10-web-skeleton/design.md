# Design: v18.10-web-skeleton

## 1. Estrutura

```
src/web/
  __init__.py
  __main__.py        # uv run python -m src.web  → Uvicorn em WEB_HOST:WEB_PORT
  app.py             # create_app(settings, store_factory, clock) — injetável nos testes
  auth.py            # PasswordVerifier, SessionStore (memória), LoginThrottle
  security.py        # middleware: Host, Origin, CSRF, cabeçalhos
  deps.py            # dependências FastAPI: sessão atual, GraphStore
  static.py          # StaticFiles de WEB_STATIC_DIR + fallback index.html
  password.py        # uv run python -m src.web.password
  routes/session.py
  routes/projects.py
  models.py          # Pydantic: entrada e saída da API
frontend/
  package.json  pnpm-lock.yaml  .nvmrc  tsconfig.json  vite.config.ts  eslint.config.js
  index.html
  src/
    main.tsx  App.tsx  routes.tsx
    api/client.ts  api/schema.d.ts (gerado)  api/queries.ts
    styles/tokens.css  styles/global.css
    components/   (Button, TextField, Select, Dialog, StatusBadge, EmptyState, ErrorState, Spinner, Layout, Sidebar, ProjectSwitcher, ThemeToggle)
    pages/        (LoginPage, ProjectsPage, ProjectDetailPage, ProjectFormPage)
    test/         (setup.ts, server.ts com MSW, handlers.ts)
```

Camadas: `[tool.importlinter]` passa a ter `"cli | web"` na primeira linha. `src/web` importa `knowledge`, `db`, `config`, `logger`, `utils`; nunca `cli`, `orchestration`, `agents` nem `agent_runtime` diretamente (contrato `forbidden` adicional com `allow_indirect_imports = true`, para que a web não execute agentes no próprio processo; a importação indireta é liberada porque `v18.10-web-chat` usa um pacote intermediário que chega ao orquestrador só para lançar processos, e a garantia passa a ser verificada também em tempo de execução naquela mudança).

## 2. API

Todas as rotas `/api/*`, exceto `POST /api/session/login`, exigem sessão; as que mudam estado exigem `X-CSRF-Token`.

| Método e rota | Corpo / parâmetros | Resposta |
|---|---|---|
| `POST /api/session/login` | `{senha}` | 200 `{csrf_token, expira_em}` + cookie `gc_session`; 401 `{erro:"credenciais_invalidas"}`; 429 `{erro:"bloqueado", tentar_em_segundos}` |
| `POST /api/session/logout` | — | 204, cookie apagado |
| `GET /api/session` | — | 200 `{autenticado:true, expira_em}`; 401 |
| `GET /api/projects` | `status?` | 200 `[{projeto_id, titulo, status, criado_em}]` |
| `POST /api/projects` | `{titulo, objetivo, dominios?: string[]}` | 201 `{projeto_id}`; 422 com o campo |
| `GET /api/projects/{id}` | — | 200 `ProjectDetail` (título, objetivo, status, domínios, Problema ativo resumido, contagem de sessões); 404 |
| `PATCH /api/projects/{id}` | `{titulo?, objetivo?, status?}` | 200 `ProjectDetail`; 422; 404 |

Sem `DELETE`: a interface oferece "Pausar", "Concluir" e "Arquivar" (`PATCH status`); `arquivado` = não explorar mais. `GET /api/projects` omite os arquivados, a menos que `status=arquivado` ou `incluir_arquivados=1`. "Desarquivar" volta a `pausado`. Erros seguem `{erro: <código>, mensagem: <texto curto>, campo?: <nome>}`; nenhum traceback ou caminho sai na resposta.

## 3. Autenticação (ADR 027 §4)

- `PasswordVerifier`: `argon2.PasswordHasher` com parâmetros padrão da biblioteca; verifica em tempo constante; falha de configuração (hash ausente ou malformado) impede a inicialização com `ConfigurationError`.
- `SessionStore`: dicionário `token → {criado_em, ultimo_uso, csrf}` sob trava; `token = secrets.token_urlsafe(32)`; limpeza de expiradas a cada acesso; no máximo `WEB_MAX_SESSIONS` (padrão 10) — a mais antiga sai.
- `LoginThrottle`: contagem global de falhas em janela deslizante (um usuário só; o IP é sempre loopback atrás do `tailscale serve`).
- Cookie: `HttpOnly`, `SameSite=Strict`, `Path=/`. Nenhum cabeçalho `X-Forwarded-*` é confiado (todo processo local fala de `127.0.0.1`, inclusive o `tailscale serve`). Com `WEB_COOKIE_SECURE=true`, o cookie se chama `__Host-gc_session` e leva `Secure`; com `false`, `gc_session` sem `Secure`. A inicialização falha se `WEB_ALLOWED_HOSTS` tiver nome que não seja de loopback (o da tailnet) e `WEB_COOKIE_SECURE` não for `true`: o acesso pela tailnet é sempre HTTPS pelo `tailscale serve`.
- `WEB_MAX_SESSIONS` atingido: o login novo é recusado (429 `sessoes_esgotadas`), nunca derruba uma sessão existente.
- `WEB_HOST=localhost` é resolvido na inicialização e todos os endereços resolvidos precisam ser de loopback.
- **GET, HEAD e OPTIONS nunca mudam estado** (regra de código e teste que percorre as rotas).
- Middleware de segurança (ordem): `Host` em `WEB_ALLOWED_HOSTS` → 400; em métodos não seguros, **inclusive `POST /api/session/login`** (contra CSRF de login), `Origin` presente e em `WEB_ALLOWED_ORIGINS` → senão 403; sessão válida → senão 401; `X-CSRF-Token` igual ao da sessão (`hmac.compare_digest`) → senão 403.
- Cabeçalhos em toda resposta: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` nas rotas `/api`.

## 4. Configuração (`src/config.py`, `.env.example`)

| Variável | Padrão | Validação |
|---|---|---|
| `WEB_HOST` | `127.0.0.1` | só `127.0.0.1`, `::1` ou `localhost`; outro valor falha na inicialização |
| `WEB_PORT` | `8765` | 1024–65535 |
| `WEB_PASSWORD_HASH` | — (obrigatória para `src.web`) | começa com `$argon2id$` |
| `WEB_ALLOWED_HOSTS` | `127.0.0.1,localhost` | lista; o nome da máquina na tailnet é acrescentado pelo pesquisador |
| `WEB_ALLOWED_ORIGINS` | derivada de `WEB_ALLOWED_HOSTS` e `WEB_PORT` (`http://h:porta`) | lista de origens completas |
| `WEB_COOKIE_SECURE` | `false` | `true` obrigatório quando `WEB_ALLOWED_HOSTS` tem nome fora do loopback |
| `WEB_SESSION_IDLE_MINUTES` | `60` | ≥ 1 |
| `WEB_SESSION_MAX_HOURS` | `12` | ≥ 1 |
| `WEB_MAX_SESSIONS` | `10` | ≥ 1 |
| `WEB_LOGIN_MAX_FAILURES` / `WEB_LOGIN_WINDOW_SECONDS` / `WEB_LOGIN_LOCK_SECONDS` | `5` / `300` / `300` | ≥ 1 |
| `WEB_STATIC_DIR` | `frontend/dist` | sem a pasta, `/` responde 503 com a dica de `pnpm --dir frontend build`; a API funciona |

As variáveis `WEB_*` só são exigidas quando `src.web` inicia: o REPL e as sessões não mudam.

## 5. Frontend

- **Cliente da API:** `fetch` com `credentials: 'same-origin'`; guarda o `csrf_token` só em memória (estado do React); 401 leva à tela de login preservando a rota de destino; erros viram `ApiError {status, erro, mensagem, campo}`.
- **Tipos:** `pnpm --dir frontend gen:api` roda `openapi-typescript` sobre `frontend/openapi.json`, que o backend exporta por `uv run python -m src.web.openapi`; teste do backend compara o esquema exportado com o arquivo versionado.
- **Design system:** [`docs/design-system/README.md`](../../../docs/design-system/README.md) ("Bancada") é obrigatório; o esqueleto implementa os tokens, as fontes, os componentes base, a paleta de comandos (`⌘K`) e a página `/_design`.
- **Tokens (Designer):** `tokens.css` define as variáveis do design system em `:root` (escuro) e em `[data-theme="light"]`; `prefers-color-scheme: light` aplica o claro quando não há escolha salva. Contrastes conferidos por teste (`tokens.test.ts` calcula a razão WCAG dos pares texto/fundo declarados e exige ≥ 4,5).
- **Componentes e estados:** cada componente de formulário e de estado tem os estados padrão, foco, desabilitado, carregando e erro; `StatusBadge` mostra rótulo e cor para `ativo`, `pausado`, `concluido`.
- **Telas:** Login; Projetos (tabela com filtro de estado e busca por título, vazio com chamada para criar); Detalhe (título, objetivo, domínios, Problema ativo, ações Editar/Pausar/Concluir/Reativar com diálogo de confirmação para Concluir); Formulário (criar/editar, validação de título ≤ 200 e objetivo ≤ 20 000 antes de enviar, erros do servidor no campo).
- **Seletor de projeto:** a barra lateral guarda o projeto selecionado na URL (`/p/:projetoId/...`); as seções futuras (Painel, Conversa, Artefatos, Grafo) aparecem desabilitadas com o texto "em breve" até as mudanças próprias.
- **Scripts do `package.json`:** `dev`, `build`, `test` (`vitest run --coverage`), `typecheck` (`tsc --noEmit`), `lint`, `gen:api`. Cobertura mínima de 70% das linhas (limite no `vite.config.ts`, falha abaixo).

## 6. Impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador & laço | Nenhum. |
| Agentes & prompts | Nenhum. |
| Sandboxes & containers | Nenhum nesta mudança (modo local); containers e lançador ficam em `v18.10-web-containers` (ADR 027 §9). `docker-compose.yml` não muda aqui. |
| Persistência | Só `update_node` em `Projeto` (propriedades existentes) e criação pelo caminho atual; sem schema. |
| Segurança | Porta HTTP nova em loopback; autenticação, CSRF, `Host`/`Origin`, CSP (§7). |
| Testes & telemetria | Suíte pytest nova (`tests/unit/web/`, `tests/integration/web/`) e suíte Vitest; logs JSON por requisição sem dados sensíveis. |

## 7. Segurança (parecer do Analista, STRIDE)

| Ameaça | Risco | Mitigação (vira requisito) |
|---|---|---|
| S — outro processo local usa a porta | Médio: qualquer processo do usuário alcança o loopback | Senha obrigatória; nenhuma rota aberta além do login e dos estáticos |
| S — site malicioso no navegador do pesquisador (CSRF, DNS rebinding) | Alto sem mitigação | `SameSite=Strict`, `Origin` e `X-CSRF-Token` obrigatórios; `Host` em lista |
| T — edição do projeto por agente | Baixo | A web não carrega agentes (contrato `forbidden`); ator sempre `pesquisador` |
| R — quem editou o projeto | Médio | Auditoria do `GraphStore` com ator `pesquisador` e `sessao_id` da CLI/web (`web` como origem na nota de auditoria) |
| I — vazamento por erro | Médio | Respostas de erro sem traceback nem caminho; logs sem segredos |
| I — exposição na rede | Alto se escutar em 0.0.0.0 | `WEB_HOST` só loopback; remoto apenas por `tailscale serve` (HTTPS) |
| D — força bruta | Médio | Bloqueio após 5 falhas; argon2id custoso por tentativa |
| E — XSS com conteúdo do grafo (título/objetivo vindos de LLM em outras rotas) | Alto nas próximas mudanças | React sem `dangerouslySetInnerHTML` (regra de ESLint `react/no-danger` como erro); CSP sem `unsafe-inline` |

Risco residual aceito: o bloqueio de login é global, então um processo local pode bloquear o pesquisador por 5 minutos (negação de serviço local, documentada); sessões em memória e senha única; processos locais com o mesmo usuário podem ler o `.env` (mesma condição do ADR 023 §4.3).

## 8. Riscos

- **Ferramentas do frontend no Pi:** o Pi não roda a web; nenhum teste do Pi depende do Node.
- **Deriva do esquema OpenAPI:** teste de comparação impede.
- **`update_node` em `Projeto` concorrente com a sessão:** a sessão não edita título, objetivo nem estado do `Projeto` (`record_objective_reached_by_session` grava no `Problema`); o desenvolvedor confirma no código antes de implementar (tarefa 0.1). Concluir ou pausar um projeto com pesquisa em execução é recusado com 409 e a lista das sessões vivas.

## 9. Questões em aberto

2. **Porta padrão** `8765`: aceitar ou outra.
Decididas em 2026-10-24: aprovar ADR e specs; escrita de `Projeto` pela web; arquivar em vez de apagar.
