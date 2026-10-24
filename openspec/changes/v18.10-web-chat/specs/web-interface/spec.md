# Delta: web-interface

## ADDED Requirements

### Requirement: Consulta ao Researcher pela web
`POST /api/projects/{id}/chat/ask` SHALL responder pelo mesmo processo filho só leitura da consulta do REPL, com o texto delimitado como dado, e MUST NOT iniciar pesquisa (ADR 027 §6.6; ADR 023 §3).

#### Scenario: Pergunta respondida
- **GIVEN** provedor simulado que responde "h3 foi refutada"
- **WHEN** o pesquisador pergunta "como está a h3?"
- **THEN** a resposta é 200 com o texto, o consumo vai a `token_usage` com `task_name='consulta_web'` e nenhuma sessão nova existe

#### Scenario: Orientação sugerida
- **GIVEN** a resposta simulada traz `orientacao_sugerida`
- **WHEN** a página mostra a resposta e o pesquisador clica "Enviar como orientação"
- **THEN** uma linha `tipo='orientacao'` entra na `session_inbox` da sessão consultada

#### Scenario: Processo da web sem agentes
- **WHEN** a suíte de integração da web termina
- **THEN** `sys.modules` do servidor não tem `src.agents.researcher`, `src.orchestration.orchestrator` nem `src.agent_runtime.runtime`; e um servidor iniciado com um deles já importado recusa subir

#### Scenario: Consulta não bloqueia o servidor
- **GIVEN** um filho simulado que demora 2 s
- **WHEN** a consulta está em curso
- **THEN** `GET /api/session` responde em menos de 200 ms, e uma segunda consulta simultânea recebe 429 com `WEB_MAX_CONCURRENT_CONSULTS=1`

#### Scenario: Tempo limite
- **GIVEN** `WEB_CONSULT_TIMEOUT_SECONDS=1` e filho simulado que não responde
- **THEN** a resposta é 504 e o filho é encerrado

### Requirement: Nova pesquisa com as confirmações do REPL
`POST /api/projects/{id}/research` SHALL lançar a sessão em processo próprio (ADR 023 §1) e MUST devolver 409 com os dados quando houver outra pesquisa viva, memória abaixo de `MIN_AVAILABLE_MEMORY_MB` ou Problema não confirmado, lançando só com a confirmação correspondente.

#### Scenario: Outra em execução
- **GIVEN** uma pesquisa viva
- **WHEN** a nova pesquisa é pedida sem `confirmar_outra_em_execucao`
- **THEN** a resposta é 409 `outra_em_execucao` com o apelido; com a confirmação, 202 e o PID novo registrado na sessão

#### Scenario: Assisted recusado na web
- **WHEN** a nova pesquisa é pedida com `modo="assisted"`
- **THEN** 422 `modo_nao_suportado_na_web` e nenhum processo é criado

#### Scenario: Problema não confirmado
- **GIVEN** projeto sem Problema confirmado
- **THEN** a resposta é 409 `problema_nao_confirmado` e nenhum processo é criado

### Requirement: Eventos por SSE sem perda nem duplicação
`GET /api/sessions/{sid}/events/stream` SHALL enviar os eventos de `session_events` com `id` igual ao `seq` e MUST retomar a partir de `Last-Event-ID` sem lacuna nem repetição.

#### Scenario: Reconexão
- **GIVEN** eventos seq 1..5 e um cliente que recebeu até 3
- **WHEN** reconecta com `Last-Event-ID: 3` e os eventos 6 e 7 chegam
- **THEN** recebe exatamente 4, 5, 6 e 7, em ordem

#### Scenario: Limite de conexões
- **GIVEN** `WEB_MAX_EVENT_STREAMS=1` e uma conexão aberta
- **THEN** a segunda recebe 503

#### Scenario: Logout encerra a stream
- **GIVEN** uma stream aberta
- **WHEN** o pesquisador faz logout
- **THEN** a stream termina na próxima consulta periódica

#### Scenario: Evento com sequência de controle
- **GIVEN** um evento cujo resumo contém `\x1b[2J`
- **THEN** o `data` enviado não contém o caractere ESC

### Requirement: Comandos e orientação pela caixa de entrada
As rotas de comando e orientação SHALL gravar na `session_inbox` pelo mesmo código do REPL (`src/interaction/commands.py`), com validação e limites atuais.

#### Scenario: Pausar
- **GIVEN** uma sessão viva
- **WHEN** `POST /commands {"comando":"pausar"}`
- **THEN** a caixa tem um `tipo='comando'` codificado como no REPL e a sessão, no laço de teste, termina a subtarefa e fica `suspended` com `pausada_pesquisador`

#### Scenario: Parar a qualquer momento
- **GIVEN** uma pesquisa `auto` no meio de uma subtarefa
- **WHEN** `POST /commands {"comando":"parar"}`
- **THEN** a subtarefa em curso termina, a sessão grava relatório e o motivo de parada que o `parar` do REPL grava hoje, e a página mostra o comando como aplicado

#### Scenario: Sessão sem processo
- **GIVEN** uma sessão `completed`
- **WHEN** `pausar`
- **THEN** a resposta é 409

### Requirement: Página da conversa
A página SHALL juntar mensagens, respostas, eventos e cartões de decisão numa linha do tempo, anunciar decisão nova em região `aria-live="assertive"` e exibir todo texto vindo da sessão como texto.

#### Scenario: Cartão de decisão
- **GIVEN** MSW com um pedido pendente de opções `autorizar` e `negar`
- **WHEN** o pesquisador clica "Autorizar" e confirma
- **THEN** a requisição leva `X-CSRF-Token` e o cartão passa a "resolvido pela web"

#### Scenario: Reconexão visível
- **WHEN** o `EventSource` simulado cai
- **THEN** aparece "conexão de eventos perdida; reconectando" e some ao reconectar
