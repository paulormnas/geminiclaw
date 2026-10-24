# Delta: web-interface

## ADDED Requirements

### Requirement: Servidor só em loopback
O servidor web SHALL escutar apenas em endereço de loopback (`127.0.0.1`, `::1`, `localhost`) e MUST recusar a inicialização com outro `WEB_HOST` (ADR 027 §4.1).

#### Scenario: Endereço externo recusado
- **GIVEN** `WEB_HOST=0.0.0.0`
- **WHEN** `src.web` inicia
- **THEN** a inicialização falha com `ConfigurationError` citando `WEB_HOST` e `tailscale serve`, sem abrir a porta

#### Scenario: Nome da tailnet sem cookie seguro
- **GIVEN** `WEB_ALLOWED_HOSTS=127.0.0.1,mac.tailnet.ts.net` e `WEB_COOKIE_SECURE=false`
- **WHEN** `src.web` inicia
- **THEN** a inicialização falha citando `WEB_COOKIE_SECURE=true`

#### Scenario: Sessões esgotadas
- **GIVEN** `WEB_MAX_SESSIONS=1` e uma sessão ativa
- **WHEN** chega um novo login correto
- **THEN** a resposta é 429 `sessoes_esgotadas` e a sessão existente continua válida

#### Scenario: Sem hash de senha
- **GIVEN** `WEB_PASSWORD_HASH` ausente
- **WHEN** `src.web` inicia
- **THEN** a inicialização falha com mensagem que indica `uv run python -m src.web.password`

### Requirement: Login por senha com sessão em cookie
O backend SHALL autenticar por senha verificada contra `WEB_PASSWORD_HASH` (argon2id) e SHALL emitir cookie `gc_session` `HttpOnly` e `SameSite=Strict`, com o token CSRF só no corpo da resposta (ADR 027 §4.2–§4.3).

#### Scenario: Senha correta
- **GIVEN** o hash da senha "s3nha"
- **WHEN** `POST /api/session/login {"senha":"s3nha"}` com `Origin` permitido
- **THEN** a resposta é 200 com `csrf_token`, o cookie (`gc_session`, ou `__Host-gc_session` com `Secure` quando `WEB_COOKIE_SECURE=true`) tem `HttpOnly` e `SameSite=Strict`, e o token CSRF não está em nenhum cookie

#### Scenario: Senha errada
- **WHEN** o login usa outra senha
- **THEN** a resposta é 401 `{"erro":"credenciais_invalidas"}` e nenhum cookie é emitido

#### Scenario: Rota protegida sem sessão
- **WHEN** `GET /api/projects` sem cookie
- **THEN** a resposta é 401

#### Scenario: Expiração por inatividade
- **GIVEN** `WEB_SESSION_IDLE_MINUTES=60` e um relógio simulado
- **WHEN** passam 61 minutos sem requisição
- **THEN** a próxima requisição com o cookie recebe 401

#### Scenario: Logout
- **WHEN** `POST /api/session/logout` com sessão e CSRF válidos
- **THEN** a resposta é 204 e o mesmo cookie passa a receber 401

### Requirement: Bloqueio de tentativas
Depois de `WEB_LOGIN_MAX_FAILURES` falhas em `WEB_LOGIN_WINDOW_SECONDS`, o login SHALL responder 429 por `WEB_LOGIN_LOCK_SECONDS`, inclusive com a senha correta (ADR 027 §4.5).

#### Scenario: Quinta falha bloqueia
- **GIVEN** 5 logins errados em 60 s
- **WHEN** chega o login com a senha correta
- **THEN** a resposta é 429 com `tentar_em_segundos` > 0; depois de 300 s simulados, o login correto responde 200

### Requirement: CSRF, origem e host
Requisições que mudam estado MUST trazer `X-CSRF-Token` da sessão e `Origin` em `WEB_ALLOWED_ORIGINS`; toda requisição MUST trazer `Host` em `WEB_ALLOWED_HOSTS` (ADR 027 §4.4).

#### Scenario: Sem token CSRF
- **WHEN** `POST /api/projects` com cookie válido e sem `X-CSRF-Token`
- **THEN** a resposta é 403 e nenhum projeto é criado

#### Scenario: Origem estranha
- **WHEN** `POST /api/projects` com cookie, CSRF válido e `Origin: https://exemplo.invalid`
- **THEN** a resposta é 403

#### Scenario: Login sem Origin
- **WHEN** `POST /api/session/login` com a senha correta e sem `Origin`
- **THEN** a resposta é 403 e nenhum cookie é emitido

#### Scenario: GET nunca muda estado
- **WHEN** um teste percorre todas as rotas `GET` registradas com sessão válida
- **THEN** nenhuma escreve no grafo nem no banco (`InMemoryGraphStore` e conexão simulada sem escrita)

#### Scenario: Host fora da lista
- **WHEN** `GET /api/session` com `Host: atacante.invalid`
- **THEN** a resposta é 400

### Requirement: Cabeçalhos de segurança e erros sem detalhe interno
Toda resposta SHALL trazer a CSP do design §3, `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`; respostas de erro MUST NOT conter traceback, caminho de arquivo ou credencial.

#### Scenario: Cabeçalhos presentes
- **WHEN** `GET /` e `GET /api/session`
- **THEN** ambas trazem `Content-Security-Policy` com `script-src 'self'` e `frame-ancestors 'none'`

#### Scenario: Exceção interna
- **GIVEN** o `GraphStore` levanta `RuntimeError("/Users/x/segredo")`
- **WHEN** `GET /api/projects`
- **THEN** a resposta é 500 `{"erro":"interno"}` sem o texto da exceção, e o log não contém o cookie

### Requirement: SPA servida pelo backend
O backend SHALL servir `WEB_STATIC_DIR` em `/` e devolver `index.html` para rotas do frontend que não sejam `/api/*` nem arquivos existentes.

#### Scenario: Rota do frontend
- **GIVEN** `frontend/dist/index.html`
- **WHEN** `GET /p/abc/projetos`
- **THEN** a resposta é 200 com o conteúdo do `index.html`

#### Scenario: Build ausente
- **GIVEN** `WEB_STATIC_DIR` inexistente
- **WHEN** `GET /`
- **THEN** a resposta é 503 com a dica `pnpm --dir frontend build`, e `GET /api/session` continua respondendo

### Requirement: CRUD de projetos sem exclusão física
A API SHALL criar, listar, ler e editar (`titulo`, `objetivo`, `status ∈ {ativo, pausado, concluido, arquivado}`) projetos pelas funções de `src/knowledge/projects.py`, com ator `pesquisador`, e MUST NOT oferecer exclusão (ADR 027 §6.1).

#### Scenario: Criar
- **WHEN** `POST /api/projects {"titulo":"Iris","objetivo":"Classificar espécies"}`
- **THEN** a resposta é 201 com `projeto_id`, e o nó `Projeto` tem `status="ativo"` e auditoria com ator `pesquisador`

#### Scenario: Título vazio
- **WHEN** `POST /api/projects {"titulo":"","objetivo":"x"}`
- **THEN** a resposta é 422 com `campo="titulo"`

#### Scenario: Editar e concluir
- **GIVEN** um projeto ativo sem sessão viva
- **WHEN** `PATCH /api/projects/{id} {"status":"concluido"}`
- **THEN** a resposta é 200 com `status="concluido"` e a listagem com `status=ativo` não o traz

#### Scenario: Concluir com pesquisa em execução
- **GIVEN** uma sessão viva do projeto
- **WHEN** `PATCH {"status":"concluido"}`
- **THEN** a resposta é 409 com o apelido da sessão viva e o projeto continua `ativo`

#### Scenario: Arquivar
- **GIVEN** um projeto sem sessão viva
- **WHEN** `PATCH {"status":"arquivado"}`
- **THEN** `GET /api/projects` não o traz, `GET /api/projects?incluir_arquivados=1` traz, e `PATCH {"status":"pausado"}` o desarquiva

#### Scenario: Projeto arquivado recusa pesquisa
- **GIVEN** um projeto `arquivado`
- **WHEN** o REPL pede `nova-pesquisa` ou `retomar` nele
- **THEN** a pesquisa é recusada com a mensagem "projeto arquivado; desarquive para explorar" e nenhum processo de sessão é criado

#### Scenario: Sem DELETE
- **WHEN** `DELETE /api/projects/{id}`
- **THEN** a resposta é 405 e o nó continua no grafo

#### Scenario: Projeto inexistente
- **WHEN** `GET /api/projects/naoexiste`
- **THEN** a resposta é 404 `{"erro":"projeto_nao_encontrado"}`

### Requirement: Camadas da web
`src/web` SHALL ficar na camada de topo junto de `src/cli` (`cli | web`) e MUST NOT importar `src.cli`, `src.orchestration`, `src.agent_runtime` nem `src.agents` (ADR 027 §3).

#### Scenario: Contrato do import-linter
- **WHEN** `uv run lint-imports`
- **THEN** os contratos passam, e um módulo de teste temporário em `src/web` que importe `src.agents` faz o contrato `forbidden` falhar

### Requirement: Esquema da API versionado
O esquema OpenAPI exportado pelo backend SHALL ser igual ao `frontend/openapi.json` versionado.

#### Scenario: Esquema desatualizado
- **GIVEN** uma rota nova sem regenerar o arquivo
- **WHEN** o teste de esquema roda
- **THEN** falha indicando `uv run python -m src.web.openapi` e `pnpm --dir frontend gen:api`

### Requirement: Frontend testado sem backend real
O frontend SHALL ter testes Vitest com Testing Library e MSW, sem rede, com cobertura de linhas ≥ 70% em `frontend/src`, `tsc --noEmit` e ESLint sem erros (ADR 027 §7).

#### Scenario: Login redireciona
- **GIVEN** MSW responde 401 em `/api/projects` e 200 no login
- **WHEN** o usuário abre `/projetos`, digita a senha e envia
- **THEN** a tela de projetos aparece com a lista simulada

#### Scenario: Erro de campo vindo do servidor
- **GIVEN** MSW responde 422 `campo="titulo"`
- **WHEN** o formulário é enviado
- **THEN** a mensagem aparece ligada ao campo Título por `aria-describedby`

#### Scenario: Estados de carregamento, vazio e erro
- **WHEN** a lista de projetos está carregando, vazia ou com erro 500
- **THEN** aparecem, respectivamente, o indicador com `role="status"`, o estado vazio com "Criar projeto" e o estado de erro com "Tentar de novo"

#### Scenario: CSRF enviado
- **WHEN** o formulário de criação é enviado depois do login
- **THEN** a requisição capturada pelo MSW traz `X-CSRF-Token` igual ao recebido no login

#### Scenario: Sem HTML bruto
- **WHEN** `pnpm --dir frontend lint`
- **THEN** a regra `react/no-danger` está como erro, e um componente de teste com `dangerouslySetInnerHTML` falha o lint

### Requirement: Tokens de design e acessibilidade
Os estilos SHALL usar só os tokens de `tokens.css`; os pares texto/fundo declarados MUST ter contraste ≥ 4,5:1 nos temas escuro e claro; o tema escuro é o padrão sem preferência do sistema (ADR 027 §5).

#### Scenario: Contraste
- **WHEN** `tokens.test.ts` roda
- **THEN** todos os pares declarados têm razão ≥ 4,5 nos dois temas

#### Scenario: Tema
- **GIVEN** `matchMedia('(prefers-color-scheme: light)')` falso e nada salvo
- **WHEN** a aplicação monta
- **THEN** `document.documentElement.dataset.theme` é `dark`; depois do botão de tema, é `light` e a escolha persiste ao remontar

#### Scenario: Teclado
- **WHEN** o usuário navega a barra lateral e o formulário só com Tab, Shift+Tab e Enter
- **THEN** todos os controles são alcançados em ordem e o foco é visível (classe de foco com o token `--color-focus`)
