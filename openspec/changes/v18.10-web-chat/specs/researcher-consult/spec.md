# Delta: researcher-consult

## MODIFIED Requirements

### Requirement: Somente o papel do terminal resolve pedidos
_Nota (2026-10-24): o texto consolidado cita o papel `terminal_writer` e gatilhos que o código não tem (decisão de 2026-10-16); este delta descreve a regra como está no código, acrescida da origem `web`, e a reconciliação da spec consolidada é a tarefa 0.3._
Os pedidos do gate SHALL ser resolvidos só por `TerminalGate` com origem em `HUMAN_SOURCES` (inalterado); a web MUST resolver com `resolvido_por='terminal'` e `resposta.canal='web'`; o processo da sessão continua sem `answer`; a resposta da web a pedido de `DECISOES_RESERVADAS` MUST exigir a senha do pesquisador (ADR 023 §4.3; ADR 027 §6.6).

#### Scenario: Resposta pela web
- **GIVEN** um pedido `aprovar_hipotese` pendente
- **WHEN** `POST /api/gate/{id}/answer {"acao":"autorizar"}` com sessão e CSRF válidos
- **THEN** o pedido fica `autorizada` com `resolvido_por='terminal'` e `resposta.canal='web'` e a sessão o consome como autorização humana

#### Scenario: Decisão reservada sem senha
- **GIVEN** um pedido `aprovar_oportunidade` pendente
- **WHEN** a web responde com sessão e CSRF válidos, sem `senha` ou com senha errada
- **THEN** 403 e o pedido segue `pendente`; com a senha correta, fica `autorizada` com `resolvido_por='terminal'` e `resposta.canal='web'`

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

## ADDED Requirements

### Requirement: Problema definido e confirmado pela web
A web SHALL pedir o rascunho do Problema ao Researcher pelo processo filho só leitura, validar o rascunho editado com `parse_problem_draft` sem gravar, e confirmar por `confirm_problem` com ator `pesquisador` só com a senha do pesquisador (ADR 027 §6.6; decisão de 2026-10-24).

#### Scenario: Rascunho não grava
- **GIVEN** provedor simulado que devolve um rascunho válido
- **WHEN** `POST /problem/draft` e depois `POST /problem/draft/validate`
- **THEN** ambos respondem 200 e o grafo não tem nenhum `Problema` novo

#### Scenario: Erro por campo
- **WHEN** o rascunho validado tem métrica sem sentido quando o catálogo exige
- **THEN** 422 com `campo="sentido_metrica"` e nada é gravado

#### Scenario: Confirmar com senha
- **WHEN** `POST /problem/confirm` com rascunho válido e a senha correta
- **THEN** existe `Projeto-INVESTIGA->Problema` com `status="confirmado"` e autor `pesquisador`, e o pedido `confirmar_problema` do gate está `autorizada` com `resposta.canal="web"`

#### Scenario: Confirmar sem senha
- **WHEN** o mesmo pedido sem senha
- **THEN** 403 e nenhum `Problema` é criado
