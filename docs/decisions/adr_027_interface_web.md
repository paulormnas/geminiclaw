# ADR 027 — Interface Web do Pesquisador: SPA em TypeScript e API FastAPI Local

**Status:** Proposto (2026-10-24; aguarda aprovação do pesquisador)
**Data:** 2026-10-24
**Autores:** Arquiteto de Soluções, Analista de Segurança e Designer de Produto (GeminiClaw)
**Roadmaps relacionados:** [`roadmaps/roadmap_V18.10.md`](../../roadmaps/roadmap_V18.10.md)
**ADRs relacionados:** ADR 005 (persistência), ADR 012 §8 (decisões reservadas), ADR 014 (nada gerado por LLM executa no host), ADR 015 §11 (acesso do pesquisador ao grafo), ADR 019 (localidade dos dados), ADR 023 (pesquisa em segundo plano, eventos, gate persistente, caixa de entrada), ADR 024 (organização do código e regra de camadas)

**O que este ADR muda em outros ADRs e regras:**

| Documento | Mudança |
|---|---|
| ADR 015 §11 | A "visualização completa por serviço de frontend (a discutir)" passa a ser a navegação do grafo na web (§6.5), só leitura e sem LLM. Alterar o grafo continua com o Curator; a web só cria e edita o nó `Projeto` pelas funções tipadas existentes (§6.1). |
| ADR 023, alternativa B | O "serviço permanente com API HTTP" volta, mas só como **interface** (loopback, autenticado); o canal entre a sessão e quem a acompanha continua o PostgreSQL. A web é mais um terminal no sentido do ADR 023 §4.3: só ela e o REPL respondem o gate (§6.6). |
| ADR 024 §3 | Novo pacote de topo `src/web/`, na mesma camada de `src/cli/` e independente dele (`cli \| web`). |
| AGENTS.md §1, §7 e §9 | Diretório do frontend: `frontend/`; gerenciador `pnpm`; testes do frontend entram na verificação antes do commit quando `frontend/` muda. |
| `.agents/rules/frontend-dev.md` e `designer.md` | Stack, diretório e testes definidos (§2–§5); o frontend **não** é containerizado nem roda na `geminiclaw-net`: é estático, servido pelo backend. |

---

## Contexto

### Decisões do pesquisador (2026-10-24)

- Interface web como trilha própria, em paralelo aos experimentos E0–E3 no Raspberry Pi.
- **SPA em JavaScript/TypeScript** no diretório próprio do frontend (AGENTS.md §1); **backend Python (FastAPI)** com a API e os estáticos.
- Tudo roda no **Mac** do pesquisador (Docker Desktop com `geminiclaw-postgres` e `geminiclaw-qdrant`); o Pi fica só com as baterias, sem distorcer medições.
- Backend **só em loopback ou Tailscale**, **com autenticação**: o chat toca o gate persistente.
- Escopo: (a) CRUD de projetos; (b) chat com o sistema no projeto selecionado; (c) visualizador de artefatos; (d) painel com o resumo dos bancos; (e) navegação do grafo do projeto.
- A trilha web **só lê** o grafo pelo `GraphStore` e não altera o esquema; mudança de esquema da trilha 1 avisa a trilha 2.
- Ordem: este ADR e as specs → esqueleto (CRUD + autenticação) → painel, artefatos e grafo em paralelo → chat por último.

### O que já existe

- **Projetos** (`src/knowledge/projects.py`): `create_project`, `list_projects`, `get_project`, estados `ativo`, `pausado` e `concluido`; não há edição nem exclusão.
- **Grafo** (`src/knowledge/graph_store.py`): leitura por `get_node`, `find_nodes`, `list_nodes`, `neighbors`, `project_subgraph`, `read_query` (papel `knowledge_reader`, transação `READ ONLY`); o invólucro `ReadOnlyGraphStore` (`src/knowledge/read_only.py`) levanta em qualquer método de escrita.
- **Sessões** (ADR 023, implementado): processo próprio, `session_events` com escrita imediata, gate persistente (`gate_requests`, só `TerminalGate.answer` resolve, `resolvido_por ∈ {terminal, cli}`), caixa de entrada (`session_inbox`), presença (`terminal_presence`, `tipo ∈ {repl, direto}`, um REPL por vez), consulta só leitura ao Researcher em processo filho (`src/cli/terminal_consult.py`).
- **Artefatos:** `outputs/<slug-da-sessão>/` com `artifacts/`, `plan.json`, `manifest.json`, pastas por subtarefa; `OutputManager.list_artifacts` e `resolve_session_dir`.
- **Ferramentas no Mac:** Node 25 e `pnpm` instalados; nenhum framework web Python no `pyproject.toml` (só `httpx`).

---

## Decisão

### 1. Arquitetura

```
navegador ── HTTP(S) ──► FastAPI (src/web, 127.0.0.1) ──► PostgreSQL (relacional + AGE), Qdrant
   SPA estática (frontend/dist) servida pelo mesmo processo        ▲
                                                                   │ eventos, gate, caixa de entrada
                                          processo da sessão (ADR 023) ─┘
```

Um processo Python (`uv run python -m src.web`) serve a API em `/api/*` e os arquivos estáticos do build do frontend em `/`. Mesma origem para a SPA e a API: sem CORS. O processo da web nunca executa o orquestrador nem agentes: inicia sessões pelo mecanismo de processo próprio do ADR 023 e lê o que elas gravam, como o REPL. A consulta ao Researcher roda no processo filho já existente, só leitura.

### 2. Frontend

| Item | Escolha |
|---|---|
| Diretório | `frontend/` na raiz do repositório; nenhum `.js/.ts` fora dele |
| Linguagem | TypeScript em modo estrito |
| Framework | React (função + hooks) |
| Build e servidor de desenvolvimento | Vite (proxy de `/api` para o backend em loopback) |
| Gerenciador de pacotes | `pnpm`, com `packageManager` fixado no `package.json` e `pnpm-lock.yaml` versionado; Node na versão LTS fixada em `frontend/.nvmrc` |
| Rotas | React Router |
| Dados do servidor | TanStack Query (cache, refetch e polling) sobre um cliente `fetch` próprio e tipado |
| Grafo | Cytoscape.js |
| Markdown dos artefatos | `react-markdown` sem HTML bruto (plugins de HTML desligados) |
| Estilo | CSS puro com tokens em variáveis CSS (`frontend/src/styles/tokens.css`) e CSS Modules; sem biblioteca de UI nem Tailwind |
| Gráficos do painel | SVG próprio para os poucos gráficos de barras e contagens; biblioteca de gráficos só se uma spec futura pedir |

Versões exatas ficam no lockfile; a spec do esqueleto lista os pacotes. Toda dependência nova do frontend passa por spec, como as do backend.

### 3. Backend

- **FastAPI** com **Uvicorn**, adicionados por `uv add`; **argon2-cffi** para o hash da senha. Nenhuma outra dependência de servidor.
- Pacote `src/web/` na camada de topo, ao lado de `src/cli/` e independente dele (`cli | web` no contrato do `import-linter`). O que o REPL e a web precisarem fazer igual (iniciar pesquisa, consulta ao Researcher, comandos à sessão) sai de `src/cli/` para um pacote abaixo dos dois, na mudança do chat (§6.6).
- Contratos da API em modelos Pydantic; o frontend gera os tipos TypeScript a partir do OpenAPI publicado pelo backend (`openapi-typescript`, dependência de desenvolvimento do frontend), e um teste do backend falha se o esquema versionado (`frontend/src/api/schema.d.ts`) estiver desatualizado.
- Endpoints síncronos (pool do `src/db.py` e `GraphStore` existentes); sem ORM novo.

### 4. Autenticação e exposição de rede

1. **Só loopback.** O servidor escuta em `WEB_HOST`, padrão `127.0.0.1`; um endereço que não seja de loopback faz a inicialização falhar. O acesso por outros aparelhos do pesquisador é por **`tailscale serve`**, que publica HTTPS na tailnet e encaminha para o loopback; o backend nunca escuta na interface do Tailscale nem em `0.0.0.0`.
2. **Um usuário, senha com hash.** `WEB_PASSWORD_HASH` (argon2id) no `.env`; sem ele o servidor não inicia. Um comando (`uv run python -m src.web.password`) lê a senha sem eco e imprime o hash. A senha em texto nunca é lida do ambiente.
3. **Sessão por cookie.** O login gera um identificador aleatório de 256 bits, guardado só na memória do servidor (sem tabela nova), enviado em cookie `HttpOnly`, `SameSite=Strict`, `Path=/`; com acesso pela tailnet, `WEB_COOKIE_SECURE=true` é obrigatório e o cookie vira `__Host-` com `Secure` (nenhum cabeçalho `X-Forwarded-*` é confiado). Atingido o máximo de sessões, o login novo é recusado. Expira por inatividade (`WEB_SESSION_IDLE_MINUTES`, padrão 60) e por idade (`WEB_SESSION_MAX_HOURS`, padrão 12); reiniciar o servidor encerra as sessões; logout apaga a sessão no servidor.
4. **CSRF e origem.** GET nunca muda estado. Toda requisição que muda estado, inclusive o login, exige o cabeçalho `X-CSRF-Token` igual ao token da sessão (entregue no login, nunca em cookie legível) e `Origin` dentro de `WEB_ALLOWED_ORIGINS`; o `Host` precisa estar em `WEB_ALLOWED_HOSTS` (proteção contra *DNS rebinding*).
5. **Tentativas de login.** Depois de `WEB_LOGIN_MAX_FAILURES` (padrão 5) falhas em `WEB_LOGIN_WINDOW_SECONDS` (padrão 300), o login fica bloqueado por `WEB_LOGIN_LOCK_SECONDS` (padrão 300), com resposta 429; a resposta de senha errada não diz se o motivo foi senha ou bloqueio antes do limite.
6. **Cabeçalhos.** CSP `default-src 'self'` sem `unsafe-inline` em scripts, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; sem CORS.
7. **Logs.** Nunca gravam senha, hash, cookie, token CSRF nem corpo de requisição; registram rota, código e duração.

### 5. Design

- **Tokens semânticos** (`tokens.css`): cores por função (`--color-bg`, `--color-surface`, `--color-text`, `--color-text-muted`, `--color-accent`, `--color-success`, `--color-warning`, `--color-danger`, `--color-focus`), espaçamento em escala de 4 px, raio, tipografia (escala e família do sistema), movimento. Nenhum valor de cor ou espaçamento fora dos tokens.
- **Tema:** escuro por padrão quando o sistema não declara preferência; segue `prefers-color-scheme` quando declara; o pesquisador pode trocar e a escolha fica no navegador. `prefers-reduced-motion` desliga animações, inclusive a do layout do grafo.
- **Layout:** barra lateral com o seletor de projeto e as seções (Projetos, Painel, Conversa, Artefatos, Grafo); conteúdo à direita; em telas estreitas, a barra vira menu. Alvos: monitor de 1080p, tablet e telefone pelo Tailscale.
- **Acessibilidade:** WCAG AA (contraste 4,5:1 no texto), navegação completa por teclado, foco visível, rótulos em todos os controles. O grafo em canvas tem **alternativa acessível**: lista dos nós filtrados e dos vizinhos do nó selecionado, navegável por teclado.
- **Estados documentados** por componente: padrão, foco, ativo, desabilitado, carregando, vazio e erro; estados de sessão com rótulo além da cor (`executando`, `aguarda_pesquisador`, `suspensa`, `interrompida`, `encerrada`).

### 6. Funcionalidades

1. **Projetos (CRUD).** Criar (`create_project`), listar, ver, editar título, objetivo e estado (`ativo`, `pausado`, `concluido`) por uma função tipada nova em `src/knowledge/projects.py`, com ator `pesquisador`. **Não há exclusão física:** o "excluir" da interface é concluir ou pausar, porque sessões, experimentos e registros apontam para o projeto (proveniência, ADR 019). Essas são as **únicas escritas no grafo** feitas pela web, e nenhuma muda o esquema.
2. **Painel.** Resumo global e por projeto: contagens por rótulo e por estado de todos os rótulos do esquema (lidos de `src/knowledge/schema.py`), sessões por estado, custo e tokens por sessão quando registrados, última atividade. Consultas fixas, só leitura.
3. **Artefatos.** Lista, por sessão do projeto, os arquivos de `outputs/<sessão>/`, com visualização por tipo: texto e JSON como texto; Markdown renderizado sem HTML; CSV em tabela das primeiras linhas; imagens raster em `<img>`; SVG e HTML só em `<iframe sandbox>` servidos com `Content-Security-Policy: sandbox`; demais tipos só para baixar. Caminho resolvido dentro da pasta da sessão, sem links simbólicos, com limite de tamanho para pré-visualização.
4. **Leitura somente.** Painel, artefatos e grafo usam `ReadOnlyGraphStore` sobre o papel `knowledge_reader` e conexões relacionais com `default_transaction_read_only = on`.
5. **Grafo.** Subgrafo do projeto com filtros por rótulo, estado e domínio; detalhe do nó (propriedades, vizinhos, histórico de auditoria); expansão por vizinhos; sem Cypher livre vindo do navegador. Quando o subgrafo passa de `WEB_GRAPH_MAX_NODES`, a resposta diz quantos nós ficaram de fora e a interface pede filtro: nunca corta em silêncio.
6. **Conversa.** No projeto selecionado, o pesquisador: conversa com o Researcher em modo consulta só leitura (o mesmo processo filho do REPL); inicia pesquisa (equivalente a `nova-pesquisa`); acompanha os eventos de `session_events` em tempo real (Server-Sent Events alimentados por consulta periódica ao banco); envia orientação e comandos pela caixa de entrada; responde pedidos do gate. A resposta a pedidos de `DECISOES_RESERVADAS` exige a senha de novo (uma sessão sequestrada não basta). A web resolve o gate como **origem humana própria** (`Source.WEB`, `resolvido_por = 'web'`), o que exige ampliar a restrição de `gate_requests.resolvido_por` (alteração de schema relacional, não do grafo; aprovação na spec do chat). O texto do pesquisador e as respostas são dados exibidos como texto, nunca HTML.

### 6.7 Limites

Todo limite da web informa o que ficou de fora e oferece como ver o restante na própria web (paginar ou "carregar mais"), não só filtrar ou baixar; os padrões vêm de medição no `geminiclaw_bench`, não de estimativa (revisão adversarial de 2026-10-24).

### 7. Testes

- **Backend:** pytest. Unidade com `TestClient` do FastAPI (`httpx`, já presente), `InMemoryGraphStore`, `FakeGate` e provedor LLM simulado; integração (`integration`) com PostgreSQL real em banco de teste. Nenhum teste escreve no `geminiclaw_bench`.
- **Frontend:** Vitest com jsdom, Testing Library e MSW (respostas da API simuladas, sem rede nem backend real); `tsc --noEmit` e ESLint; cobertura mínima de 70% das linhas em `frontend/src` (regra do `frontend-dev.md`). Comandos: `pnpm --dir frontend test`, `pnpm --dir frontend typecheck`, `pnpm --dir frontend lint`, `pnpm --dir frontend build`.
- **Validação manual no Mac** com o `geminiclaw_bench` (21 projetos), em modo só leitura para painel, artefatos e grafo; o CRUD é validado no banco `geminiclaw` de desenvolvimento.

### 8. Aprovações necessárias

- **Dependências novas:** `fastapi`, `uvicorn`, `argon2-cffi` (backend, via `uv add`); pacotes do frontend listados na spec do esqueleto (via `pnpm`).
- **`AGENTS.md`:** §1 (diretório `frontend/` e `pnpm`), §6 (comandos), §7 (estrutura com `frontend/` e `src/web/`) e §9 (testes do frontend antes do commit quando `frontend/` muda).
- **Regras de papéis:** `frontend-dev.md` e `designer.md` atualizadas com a stack (sem container).
- **`pyproject.toml`:** contrato do `import-linter` com `cli | web` no topo.
- **Schema relacional (só na mudança do chat):** `gate_requests.resolvido_por` aceita `web`; e, conforme a Questão 2 do chat, `terminal_presence.tipo` aceita `web`. Nenhuma alteração do esquema do grafo.

---

## Consideradas e Rejeitadas

### A. Interface Python (Streamlit, Gradio, NiceGUI, FastHTML)
Sem JavaScript no repositório e mais rápida para o painel. **Rejeitada pelo pesquisador:** o chat com eventos em tempo real, a navegação do grafo e o visualizador de artefatos pedem controle fino de estado e de segurança (CSP, iframe isolado), difícil nesses frameworks, que rodam lógica de UI no servidor e reexecutam o script a cada interação.

### B. Servidor de páginas renderizadas no backend (Jinja + HTMX)
Uma linguagem só e quase nenhum build. **Rejeitada:** o grafo interativo e o chat com SSE exigiriam JavaScript à mão mesmo assim, sem tipos nem testes de componente.

### C. Next.js, Remix ou outro framework com servidor Node
**Rejeitada:** traria um segundo servidor (Node) com lógica própria, contra AGENTS.md §1 (JavaScript nunca executa lógica do backend). A SPA é estática.

### D. Frontend em container na `geminiclaw-net` (regra antiga do `frontend-dev.md`)
**Rejeitada:** o build é estático e servido pelo backend; um container a mais só serviria arquivos e traria outra porta a proteger.

### E. Autenticação por token no cabeçalho guardado no `localStorage`
**Rejeitada:** qualquer XSS lê o token. O cookie `HttpOnly` com CSRF por cabeçalho limita o estrago de um XSS ao tempo da página aberta.

### F. Sessões de login numa tabela do PostgreSQL
Sobreviveriam ao reinício. **Não adotada agora:** exige schema novo para um usuário só; reiniciar o servidor e entrar de novo é aceitável.

### G. Escutar na interface do Tailscale (100.x) com TLS próprio
**Rejeitada:** certificado e chave a gerenciar e uma interface a mais aberta; `tailscale serve` entrega HTTPS e mantém o backend só em loopback.

### H. npm, Yarn ou Bun
`npm` vem com o Node. **Rejeitados:** o `pnpm` já está no Mac, isola dependências (sem acesso a pacotes não declarados) e o lockfile é estável; o Bun mudaria também o runtime.

### I. Web reutilizando `resolvido_por = 'terminal'`
Sem schema novo. **Rejeitada:** perde-se de onde veio a decisão (repúdio, STRIDE R).

### J. Biblioteca de componentes (MUI, Chakra) ou Tailwind
**Rejeitada:** a regra do Designer exige tokens próprios como fonte de verdade; uma biblioteca impõe os seus e aumenta o pacote.

---

## Consequências

### Positivas
- O pesquisador vê o projeto inteiro (painel, grafo, artefatos) e conversa com o sistema num só lugar, do Mac ou de outro aparelho pela tailnet.
- Reaproveita o canal do ADR 023 (eventos, gate, caixa de entrada) sem infraestrutura nova.
- Só leitura no grafo por três barreiras (papel, transação e invólucro).

### Negativas / Trade-offs
- Um ecossistema novo (Node, `pnpm`, TypeScript) a manter, com atualização de dependências e auditoria (`pnpm audit`).
- Um processo HTTP aberto, ainda que em loopback: qualquer processo local do mesmo usuário alcança a porta; a senha é a barreira.
- Sessões de login perdidas no reinício.
- O código comum ao REPL e à web precisa sair de `src/cli/` (mudança do chat).

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.10-web-skeleton` | `web-interface` | §1–§5, §6.1, §7: `src/web/`, autenticação, cabeçalhos, estáticos, `frontend/` com tokens, layout e testes, CRUD de projetos, `AGENTS.md` e regras |
| `v18.10-web-dashboard` | `web-interface` | §6.2, §6.4 |
| `v18.10-web-artifacts` | `web-interface` | §6.3, §6.4 |
| `v18.10-web-graph` | `web-interface` | §6.4, §6.5 |
| `v18.10-web-chat` | `web-interface`, `researcher-consult` | §6.6: conversa, nova pesquisa, eventos por SSE, caixa de entrada, gate com `Source.WEB`, código comum fora de `src/cli/` |

---

## Revisão

Revisar depois do primeiro uso real com uma pesquisa acompanhada só pela web: atraso dos eventos, pedidos do gate respondidos pela web, memória do processo da web junto da sessão no Mac, e se as sessões de login em memória incomodam.
