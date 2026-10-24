# Delta: researcher-consult

## MODIFIED Requirements

### Requirement: Somente o papel do terminal resolve pedidos
_Nota (2026-10-24): o texto consolidado cita o papel `terminal_writer` e gatilhos que o código não tem (decisão de 2026-10-16); este delta descreve a regra como está no código, acrescida da origem `web`, e a reconciliação da spec consolidada é a tarefa 0.3._
Os pedidos do gate SHALL ser resolvidos só por `TerminalGate` com origem em `HUMAN_SOURCES = {terminal, cli, web}`; a web MUST gravar `resolvido_por='web'`; o processo da sessão continua sem `answer`; a resposta da web a pedido de `DECISOES_RESERVADAS` MUST exigir a senha do pesquisador (ADR 023 §4.3; ADR 027 §6.6).

#### Scenario: Resposta pela web
- **GIVEN** um pedido `aprovar_hipotese` pendente
- **WHEN** `POST /api/gate/{id}/answer {"acao":"autorizar"}` com sessão e CSRF válidos
- **THEN** o pedido fica `autorizada` com `resolvido_por='web'` e a sessão o consome como autorização humana

#### Scenario: Decisão reservada sem senha
- **GIVEN** um pedido `aprovar_oportunidade` pendente
- **WHEN** a web responde com sessão e CSRF válidos, sem `senha` ou com senha errada
- **THEN** 403 e o pedido segue `pendente`; com a senha correta, fica `autorizada` com `resolvido_por='web'`

#### Scenario: Pedido da CLI sem sessão
- **GIVEN** um pedido com `session_id` nulo
- **THEN** ele não aparece em `GET /api/gate/pending` e a resposta da web é 404

#### Scenario: Já resolvido
- **GIVEN** o pedido resolvido pelo REPL
- **WHEN** a web responde
- **THEN** 409 `ja_resolvido` e a resposta do REPL fica como está

#### Scenario: Sem CSRF
- **WHEN** a resposta ao gate chega sem `X-CSRF-Token`
- **THEN** 403 e o pedido segue `pendente`

#### Scenario: Ação fora das opções
- **WHEN** `{"acao":"aprovar_tudo"}`
- **THEN** 422 e o pedido segue `pendente`

#### Scenario: Migração
- **GIVEN** um banco com `v18_7_002`
- **WHEN** `v18_10_001_web_gate_source.sql` é aplicada duas vezes
- **THEN** a segunda não muda nada e `resolvido_por='web'` passa a ser aceito, mantendo `terminal` e `cli`

## ADDED Requirements

### Requirement: Presença da interface web
Enquanto houver conexão de eventos aberta e interação do pesquisador nos últimos `WEB_PRESENCE_IDLE_MINUTES`, a web SHALL manter presença `tipo='web'` com batimento, e a sessão `assisted` SHALL considerar presente qualquer presença viva de REPL ou web (aplicável se a Questão 2 for decidida pela opção a).

#### Scenario: Web mantém o assisted
- **GIVEN** uma sessão `assisted` e só a web conectada
- **WHEN** passa o prazo de `TERMINAL_PRESENCE_STALE_SECONDS`
- **THEN** a sessão não se suspende

#### Scenario: Última aba fecha
- **WHEN** a última conexão SSE fecha e nenhum REPL está aberto
- **THEN** a presença web ganha `ended_at` e a sessão `assisted` se suspende como no ADR 023 §1.2

#### Scenario: Aba esquecida
- **GIVEN** uma conexão SSE aberta sem interação há 31 minutos e `WEB_PRESENCE_IDLE_MINUTES=30`
- **THEN** a presença web ganha `ended_at` e a sessão `assisted` se suspende
