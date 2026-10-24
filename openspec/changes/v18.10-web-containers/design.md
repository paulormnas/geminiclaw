# Design: v18.10-web-containers

## 1. Visão

```
 Mac (host)                                               Docker (geminiclaw-net)
 ┌──────────────────────────────┐                         ┌──────────────────────────────────┐
 │ lançador  (uv run -m          │◀── session_start_ ──────│ geminiclaw-web (FastAPI)         │
 │  src.launcher)                │    requests (Postgres)  │  127.0.0.1:8765 → 8765           │
 │   └─ spawn_session → sessão   │                         │  lê bancos, grafo, artefatos (ro)│
 │        └─ sandbox (Docker)    │──── session_events ────▶│  grava pedidos, inbox, gate      │
 │ REPL (igual a hoje)           │                         ├──────────────────────────────────┤
 └──────────────────────────────┘                         │ geminiclaw-web-frontend (Node)   │
                                                          │  build → volume web_dist (ro web)│
                                                          │ geminiclaw-postgres, -qdrant     │
                                                          └──────────────────────────────────┘
```

A sessão continua um processo no host, criado igual pelo REPL e pelo lançador. A web só **pede**; o lançador **decide e inicia**. Comandos, orientação e gate já passam pelo banco (`session_inbox`, `gate_requests`) e não mudam.

## 2. Fila `session_start_requests`

```sql
CREATE TABLE IF NOT EXISTS session_start_requests (
    id               UUID PRIMARY KEY,
    project_id       TEXT NOT NULL,
    tipo             TEXT NOT NULL CHECK (tipo IN ('nova','retomada')),
    retomar_session  TEXT,                                   -- obrigatório quando tipo = 'retomada'
    tarefa           TEXT NOT NULL DEFAULT '' CHECK (char_length(tarefa) <= 20000),
    modo             TEXT NOT NULL CHECK (modo IN ('semi','auto')),   -- assisted só no REPL (ADR 027 §6.6)
    confirmacoes     JSONB NOT NULL DEFAULT '{}',            -- {outra_em_execucao: bool, memoria_baixa: bool}
    canal            TEXT NOT NULL DEFAULT 'web' CHECK (canal IN ('web')),
    estado           TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN
                       ('pendente','assumido','lancado','recusado','falhou','cancelado','expirado')),
    motivo           TEXT CHECK (char_length(motivo) <= 64),  -- ex.: outra_em_execucao, memoria_baixa, problema_nao_confirmado
    detalhes         JSONB,                                  -- dados para a confirmação (sessões vivas, memória)
    session_id       TEXT,                                   -- preenchido em 'lancado'
    launcher_id      TEXT,
    criado_em        TIMESTAMPTZ NOT NULL DEFAULT now(),
    assumido_em      TIMESTAMPTZ,
    concluido_em     TIMESTAMPTZ,
    CHECK ((tipo = 'retomada') = (retomar_session IS NOT NULL)),
    CHECK ((estado = 'lancado') = (session_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_ssr_pendentes ON session_start_requests (criado_em) WHERE estado = 'pendente';
CREATE UNIQUE INDEX IF NOT EXISTS uq_ssr_projeto_pendente
    ON session_start_requests (project_id) WHERE estado IN ('pendente','assumido');
```

- Um pedido aberto por projeto (índice único); o segundo recebe 409 `pedido_em_andamento`.
- `id` gerado pela web (UUID) e devolvido no 202; a web acompanha por `GET /api/start-requests/{id}`.
- **Confirmações:** como no REPL, outra pesquisa viva ou memória baixa não impedem, mas exigem confirmação. O lançador verifica no host; sem a confirmação, grava `recusado` com `motivo` e `detalhes`; a web mostra o diálogo e cria **um novo pedido** com a confirmação (o recusado fica como registro).
- **Expiração:** pendente há mais de `LAUNCHER_REQUEST_TTL_SECONDS` (padrão 120) vira `expirado` (pelo lançador ao subir e a cada ciclo; pela web ao ler), para um pedido antigo nunca iniciar uma pesquisa de surpresa.
- **Cancelamento:** a web pode cancelar só enquanto `pendente`.
- Retenção: sem limpeza automática nesta versão (volume pequeno); `clean.md` ganha a tabela.

## 3. Lançador (`src/launcher/`)

- `uv run python -m src.launcher`: laço que assume pedidos com `UPDATE ... SET estado='assumido' WHERE id = (SELECT id ... WHERE estado='pendente' ORDER BY criado_em FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`, a cada `LAUNCHER_POLL_SECONDS` (padrão 1) e também por `LISTEN session_start` (a web faz `NOTIFY` depois do `INSERT`), para responder rápido sem consulta pesada.
- **Uma instância por máquina:** trava de arquivo em `logs/launcher/launcher.lock`; segunda instância sai com erro claro. Pedido `assumido` há mais de `LAUNCHER_CLAIM_TIMEOUT_SECONDS` (padrão 60) por um lançador que morreu volta a `falhou` com `motivo=lancador_interrompido` (nunca relançado sozinho).
- **Verificações (as mesmas do REPL, de `src/interaction/research.py`):** projeto existe e não está `arquivado`/`concluido`; Problema confirmado; modo `semi`/`auto`; outra pesquisa viva e memória abaixo de `MIN_AVAILABLE_MEMORY_MB` com a confirmação do pedido; orçamento da configuração vigente (`.env` + `RESEARCHER_ENV_FILE`, relidos a cada pedido); retomada só de sessão do mesmo projeto em estado retomável.
- **Início:** monta o `LaunchSpec` (com `terminal_id=None` e o canal `web` no resumo), grava o arquivo de lançamento `0600` e chama `spawn_session(foreground=False)`, exatamente o caminho do REPL em segundo plano. Espera a sessão se registrar (`LAUNCH_TIMEOUT` atual); grava `lancado` + `session_id`, ou `falhou` com `motivo=processo_nao_registrou` e o fim do log no log do lançador (nunca no banco).
- **Pedido como dado não confiável:** o lançador valida tudo de novo (tamanhos, enums, ids), como o processo da sessão faz com o arquivo de lançamento. O pedido não escolhe módulo, ambiente, diretório nem modo sem limite: modo sem limite continua só pelo REPL.
- **Batimento (decisão do pesquisador, 2026-10-24):** arquivo de estado `logs/launcher/state.json` (`{launcher_id, pid, atualizado_em, versao}`), gravado de forma atômica a cada ciclo, modo `0644` no diretório `logs/launcher/` (montado só leitura no `geminiclaw-web`; sem segredos). Sem schema novo. A web mostra "lançador ausente" e desabilita "Nova pesquisa" quando o arquivo falta, é inválido ou `atualizado_em` passa de `3 × LAUNCHER_POLL_SECONDS` + 10 s.
- Camadas: `"cli | web | launcher"` acima de `"interaction"`; `launcher` não importa `cli` nem `web`.

## 4. Containers

### 4.1 `geminiclaw-web` (`containers/web/Dockerfile`)

- Base `python:3.11-slim` fixada por digest, `uv` copiado da imagem oficial fixada; `uv sync --frozen --no-dev` em estágio de build; imagem final sem compiladores.
- Usuário `10001:10001`, `read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `pids_limit`, `mem_limit` (`WEB_CONTAINER_MEM_LIMIT`, padrão 512m).
- `ports: ["127.0.0.1:${WEB_PORT:-8765}:8765"]`; dentro do container o servidor escuta em `0.0.0.0:8765` **só** com `WEB_IN_CONTAINER=true`, que o `src/web/__main__.py` aceita apenas se também houver `/.dockerenv` (fora disso continua recusando endereço não loopback). `WEB_ALLOWED_HOSTS` continua exigido.
- Volumes: `./outputs:/app/outputs:ro` (artefatos), `web_dist:/app/frontend/dist:ro`, `./config:/app/config:rw` (só para `RESEARCHER_ENV_FILE` da `v18.10-web-settings`; o diretório só contém esse arquivo), `./logs/launcher:/app/logs/launcher:ro` (batimento). **Nunca** `/var/run/docker.sock`, `.env` inteiro ou o repositório.
- Ambiente: `DATABASE_URL` com host `postgres`; `QDRANT_URL` com host `qdrant`; `WEB_PASSWORD_HASH`, `WEB_*`, chaves só se a página de configurações precisar listar modelos (passadas por `env_file` restrito a nomes da lista, tarefa 2.3).
- `depends_on` com `condition: service_healthy` em `postgres`; `healthcheck` em `GET /api/health` (rota sem dados, sem autenticação, só `{"ok": true}`).

### 4.2 `geminiclaw-web-frontend` (`containers/web-frontend/Dockerfile`)

- Base `node:<LTS do .nvmrc>-slim` fixada por digest; `corepack` com a versão de `packageManager`; `pnpm install --frozen-lockfile` (scripts de instalação bloqueados por padrão no pnpm 10; exceções só em `onlyBuiltDependencies`) e `pnpm build`.
- Hoje: serviço de execução única que escreve o build no volume `web_dist` e sai (`restart: "no"`); o `geminiclaw-web` serve esse volume. Futuro (AGENTS.md §1 revisto): pode virar servidor de desenvolvimento ou de interface, sempre falando com o backend pela API, nunca com os bancos — a mudança que fizer isso revisa porta e CSP.
- Usuário não root, sem portas publicadas, sem acesso aos bancos (rede própria `web_build` sem a `geminiclaw-net`).

### 4.3 Comando único

- `scripts/up.sh`: confere Docker e `.env`, `docker compose --profile web up -d --build` (infra + build do frontend + web), espera a saúde, inicia o lançador em segundo plano (`nohup uv run python -m src.launcher`, log em `logs/launcher/launcher.log`, PID em `logs/launcher/launcher.pid`) e imprime a URL. Idempotente.
- `scripts/down.sh`: para o lançador pelo PID (sinal TERM; o lançador termina o pedido em curso e sai) e `docker compose --profile web stop`. Não remove volumes nem containers de sandbox; nada destrutivo.
- O modo local (`uv run python -m src.web` + `pnpm dev`) continua para desenvolvimento.

## 5. Mudança na web e no chat

- `POST /api/projects/{id}/research` (contrato do `v18.10-web-chat`) passa a **gravar o pedido** e devolver `202 {pedido_id}`; os 409 de confirmação passam a chegar como estado `recusado` do pedido, lido por `GET /api/start-requests/{id}` (ou pelo SSE do chat). `422 modo_nao_suportado_na_web` continua na web.
- O `v18.10-web-chat` remove de 0.2 a movimentação de `session_start.py` (feita aqui) e passa a depender desta mudança.
- Consulta ao Researcher: fica em `v18.10-web-chat` (no container da web é possível porque não usa sandbox; decidir lá).

## 6. Impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestração e agentes | Nenhum: a sessão nasce igual. |
| Sandboxes & containers | Dois containers novos sem socket do Docker; o sandbox continua criado pela sessão no host. |
| Persistência | Uma tabela aditiva; `NOTIFY` sem payload sensível (só o id). |
| Segurança | §7. |
| Testes | Unidade do lançador com relógio e `spawn` injetados; integração da fila com Postgres real (`SKIP LOCKED`, índice único, expiração); teste de imagem (usuário, `read_only`, ausência do socket) por `docker inspect` num teste marcado `container`. |
| Recursos no host | Lançador ocioso: um `LISTEN` e uma consulta por segundo; container da web ≤ 512 MB. |

## 7. Segurança (STRIDE)

| Ameaça | Mitigação |
|---|---|
| E — container da web ganha o host | Sem socket do Docker, `cap_drop ALL`, `no-new-privileges`, não root, `read_only`; o único efeito no host é um pedido que o lançador valida |
| T — pedido forjado no banco inicia pesquisa cara | Quem escreve no banco já é confiável hoje (mesmo papel); o lançador revalida, recusa modo sem limite e `assisted`, aplica o orçamento vigente; TTL impede pedido velho |
| T — injeção pelo texto da tarefa | `tarefa` vai no arquivo de lançamento (não na linha de comando), limite de tamanho, tratada como dado pelo processo da sessão como hoje |
| D — enxurrada de pedidos | Um pedido aberto por projeto; uma sessão nova por pedido; confirmação para outra pesquisa viva e memória baixa |
| R — quem iniciou | `canal='web'` no pedido e no resumo do lançamento; log do lançador com id do pedido |
| I — log da sessão vazando pelo banco | O fim do log fica só no log local do lançador |
| S — segundo lançador | Trava de arquivo; pedido assumido por lançador morto vai a `falhou`, nunca relançado sozinho |
| Porta exposta | Publicada só em `127.0.0.1`; `WEB_IN_CONTAINER` só com `/.dockerenv` |

## 8. Questões em aberto

Decidido em 2026-10-24: lançador no host junto dos containers; schema e `docker-compose.yml` aprovados.

Decidido também: batimento por arquivo de estado (Questão 1).
