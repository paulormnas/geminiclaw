# Delta: web-interface

## ADDED Requirements

### Requirement: Web em container sem iniciar sessões
O container `geminiclaw-web` SHALL rodar sem root, com sistema de arquivos só leitura, sem capacidades e com a porta publicada só em `127.0.0.1`, e MUST NOT montar o socket do Docker nem iniciar processos de sessão (ADR 027 §9).

#### Scenario: Inspeção do container
- **WHEN** `docker inspect geminiclaw-web`
- **THEN** o usuário não é 0, `ReadonlyRootfs=true`, `CapDrop` contém `ALL`, nenhum `Mount` aponta para `docker.sock` e a porta tem `HostIp=127.0.0.1`

#### Scenario: Endereço externo fora do container
- **GIVEN** `WEB_IN_CONTAINER=true` sem `/.dockerenv`
- **WHEN** `src.web` inicia com `WEB_HOST=0.0.0.0`
- **THEN** recusa subir, como hoje

### Requirement: Nova pesquisa pela fila
`POST /api/projects/{id}/research` SHALL gravar um pedido em `session_start_requests` e devolver `202 {pedido_id}`; o estado SHALL ser lido em `GET /api/start-requests/{id}`.

#### Scenario: Pedido gravado
- **WHEN** o pesquisador pede pesquisa `auto` num projeto com Problema confirmado
- **THEN** 202 com `pedido_id`, o pedido está `pendente` com `canal='web'` e a web não cria processo

#### Scenario: Recusa vira diálogo
- **GIVEN** o pedido terminou `recusado` com `motivo='memoria_baixa'`
- **WHEN** a página lê o pedido
- **THEN** mostra o diálogo com a memória disponível e, ao confirmar, cria novo pedido com `confirmacoes.memoria_baixa=true`

#### Scenario: Lançador ausente
- **GIVEN** batimento do lançador mais velho que o limite
- **THEN** `GET /api/launcher` devolve `presente=false` e o botão Nova pesquisa fica desabilitado com o aviso

### Requirement: Comando único
`scripts/up.sh` SHALL subir infra, build do frontend, web e lançador, de forma idempotente; `scripts/down.sh` SHALL parar web e lançador sem remover volumes nem containers de sandbox.

#### Scenario: Subir duas vezes
- **WHEN** `scripts/up.sh` roda duas vezes
- **THEN** existe um só lançador (PID em `logs/launcher/launcher.pid`) e um só `geminiclaw-web`
