# Delta: session-continuity

Testes de integração: processo da sessão real (`tests/support/session_process_recorded.py`) com PostgreSQL real e provedor `gravado`; nenhuma chamada paga. Ajudas reaproveitadas de `v18.7-background-sessions` (harness do processo, `FakeClock`, fixture de PostgreSQL com `terminal_writer`, REPL em pseudo-terminal com `pexpect`) e `FakeGate` de `v18.7-persistent-human-gate`; nenhuma ajuda nova. Valores reduzidos nos testes de integração (cada teste em até 15 s): `SESSION_EVENTS_POLL_SECONDS=1`, `SESSION_INBOX_POLL_SECONDS=1`, mais os valores reduzidos de `v18.7-background-sessions`.

## ADDED Requirements

### Requirement: Eventos de progresso com escrita imediata
O processo da sessão SHALL gravar cada evento de progresso na tabela `session_events` assim que ele ocorre, numa transação própria (não pela telemetria em lote), com `seq` crescente por sessão, `tipo` do conjunto fechado (`sessao_iniciada`, `plano_aprovado`, `subtarefa_iniciada`, `subtarefa_concluida`, `subtarefa_reprovada`, `hipotese_criada`, `hipotese_concluida`, `objetivo_atingido`, `decisao_pendente`, `comando_recebido`, `parada`, `suspensao`, `falha`) e resumo curto. O evento final SHALL ser gravado antes do status final da sessão. A falha de gravação MUST NOT derrubar a sessão (ADR 023 §2; casos 1, 4 e 10).

#### Scenario: Evento final antes do status
- **GIVEN** uma pesquisa `auto` que chega a `solucao_encontrada` com respostas gravadas
- **WHEN** a sessão fecha
- **THEN** existe o evento `parada` com resumo que contém `solucao_encontrada` e `criado_em` anterior ou igual ao `updated_at` final da sessão
- **AND** os eventos da sessão têm `seq` 1, 2, 3, ... sem lacuna

#### Scenario: Pendente aparece já
- **GIVEN** `_BUFFER_SIZE` da telemetria em 50 e uma sessão que cria um pedido no gate
- **WHEN** o pedido é criado
- **THEN** o evento `decisao_pendente` está no banco em menos de 1 s, sem `flush` da telemetria

#### Scenario: Suspensão
- **GIVEN** uma sessão `assisted` e o REPL que sai
- **WHEN** a sessão se suspende
- **THEN** existe o evento `suspensao` com resumo que cita o terminal fechado

#### Scenario: Falha gravada pelo terminal
- **GIVEN** uma sessão cujo processo recebeu `SIGKILL`
- **WHEN** o terminal a marca `interrompida`
- **THEN** existe o evento `falha` com resumo que contém `retomar <apelido>`

#### Scenario: Banco indisponível para um evento
- **GIVEN** a gravação de evento falha duas vezes seguidas
- **WHEN** a sessão emite o evento
- **THEN** a sessão continua e o log tem `WARNING` com o tipo do evento

### Requirement: Resumo de evento sem dado bruto
O resumo SHALL ser montado de campos estruturados, cada campo textual saneado, passar pelo filtro de exibição e ter no máximo `SESSION_EVENT_SUMMARY_MAX_CHARS` (padrão 300); MUST NOT conter saída de execução, trecho de dado, caminho absoluto ou mensagem de exceção; valor de métrica SHALL entrar só quando for resultado validado (ADR 023 §2 e §7; ADR 019).

#### Scenario: Dado sensível não aparece
- **GIVEN** uma subtarefa cujo resultado bruto contém `/home/usuario/dados/amostra.csv`, a linha `Traceback (most recent call last)` e o valor de coluna `12.537`
- **WHEN** o evento `subtarefa_concluida` é emitido
- **THEN** o resumo não contém o caminho, `Traceback` nem `12.537`

#### Scenario: Métrica validada aparece
- **GIVEN** a subtarefa `treinar_rf` com `acuracia=0.967` aprovada pelo Validator
- **WHEN** o evento `subtarefa_concluida` é emitido
- **THEN** o resumo é `treinar_rf concluída (acuracia 0,967, validada)`

### Requirement: Texto saneado de novo na exibição
Antes de imprimir qualquer texto lido do banco ou vindo do processo da consulta (`session_events.resumo`, linhas de `pesquisas` e `acompanhar`, resposta e `orientacao_sugerida` da consulta), o terminal SHALL aplicar de novo `sanitize_text` (que remove ESC, caracteres C1 e marcas bidi, `src/knowledge/graph_views.py:89-108`) e o limite de `SESSION_EVENT_SUMMARY_MAX_CHARS`, porque a tabela é gravável pelo papel principal; o terminal MUST NOT confiar no saneamento feito na gravação. `dados` SHALL aceitar, por `tipo`, só uma lista fechada de chaves (ids, contagens, códigos), validada na escrita.

#### Scenario: Sequência de controle gravada direto na tabela
- **GIVEN** um evento inserido pelo teste direto em `session_events`, com o papel principal, cujo `resumo` é `"ok \x1b]0;titulo\x07 \x1b[2J fim ‮"`
- **WHEN** o REPL lê e imprime o evento, e o pesquisador digita `acompanhar <apelido>` e `pesquisas`
- **THEN** nenhuma das três saídas contém `\x1b`, `\x07` nem `‮`, e as três contêm `ok` e `fim`

#### Scenario: Chave fora da lista em dados
- **WHEN** `EventWriter.emit("subtarefa_concluida", campos)` recebe em `dados` a chave `stdout`
- **THEN** a chave é descartada e o evento é gravado só com as chaves permitidas

### Requirement: Retenção configurável dos eventos
Com `SESSION_EVENTS_RETENTION_DAYS` maior que 0, o terminal SHALL apagar, ao abrir, os eventos de sessões terminadas há mais de N dias e MUST NOT apagar eventos de sessões não finalizadas; com 0 (padrão), nada SHALL ser apagado (ADR 023 §2).

#### Scenario: Padrão não apaga
- **GIVEN** `SESSION_EVENTS_RETENTION_DAYS=0` e eventos de uma sessão fechada há 400 dias
- **WHEN** o REPL abre
- **THEN** os eventos continuam

#### Scenario: Retenção ligada
- **GIVEN** `SESSION_EVENTS_RETENTION_DAYS=30`, uma sessão fechada há 40 dias e outra `aguarda_pesquisador` há 40 dias
- **WHEN** o REPL abre
- **THEN** só os eventos da sessão fechada são apagados

### Requirement: Atualizações no REPL sem apagar a entrada
O REPL SHALL ler eventos novos a cada `SESSION_EVENTS_POLL_SECONDS` (padrão 2) e imprimir uma linha por evento, prefixada pelo apelido (`[iris-01] ...`), conforme `TERMINAL_EVENT_DETAIL` (`silencioso`, `resumo` padrão, `detalhado`), sem apagar o que o pesquisador está digitando (ADR 023 §3).

#### Scenario: Linha intercalada
- **GIVEN** um pseudo-terminal com o REPL e o texto parcial `pesq` digitado
- **WHEN** chega o evento `plano_aprovado` da sessão `iris-01`
- **THEN** a linha `[iris-01] plano 2 aprovado: 5 subtarefas, 3 hipóteses` é impressa
- **AND** o prompt é redesenhado com `pesq` e a entrada final do pesquisador é `pesquisas` quando ele completa a digitação

#### Scenario: Nível silencioso
- **GIVEN** `TERMINAL_EVENT_DETAIL=silencioso`
- **WHEN** chegam os eventos `subtarefa_concluida` e `decisao_pendente`
- **THEN** só a linha de `decisao_pendente` é impressa

#### Scenario: Atraso máximo
- **GIVEN** relógio simulado e `SESSION_EVENTS_POLL_SECONDS=2`
- **WHEN** um evento é gravado
- **THEN** a linha é impressa em no máximo 2 s simulados

### Requirement: Comandos de acompanhamento
O REPL SHALL oferecer `pesquisas` (estado, tempo, custo, último evento e pedidos pendentes de cada pesquisa), `acompanhar <apelido>` (últimos `TERMINAL_FOLLOW_HISTORY` eventos e os novos, em nível detalhado, até `voltar`), `pausar <apelido>` (fim das subtarefas em curso, checkpoint, `status="suspended"`, `motivo_parada="pausada_pesquisador"`, processo encerrado), `retomar <apelido>` (retomada pela folha da cadeia, com verificação de memória) e `parar <apelido>` (fechamento gracioso com checkpoint, `interrompida_pesquisador`). Os comandos de ação SHALL chegar à sessão pela caixa de entrada com `tipo="comando"`, gravados pelo papel do terminal, e SHALL ser recusados para sessão sem processo vivo (ADR 023 §3).

#### Scenario: Lista de pesquisas
- **GIVEN** a sessão `iris-01` em execução com 1 pedido pendente e a sessão `b-01` fechada há 2 h
- **WHEN** o pesquisador digita `pesquisas`
- **THEN** a saída tem uma linha para cada uma, com estado, tempo, custo e último evento, e `iris-01` mostra 1 pedido pendente

#### Scenario: Pausar
- **GIVEN** a sessão `iris-01` com uma subtarefa gravada de 3 s em curso
- **WHEN** o pesquisador digita `pausar iris-01`
- **THEN** a subtarefa termina, nenhuma outra começa, a sessão fica `suspended` com `motivo_parada="pausada_pesquisador"` e o processo encerra
- **AND** `retomar iris-01` cria a sessão que a continua

#### Scenario: Parar
- **WHEN** o pesquisador digita `parar iris-01`
- **THEN** a sessão fecha com `motivo_parada="interrompida_pesquisador"` e checkpoint gravado

#### Scenario: Sessão sem processo
- **GIVEN** a sessão `b-01` em `aguarda_pesquisador`
- **WHEN** o pesquisador digita `pausar b-01`
- **THEN** o terminal recusa, mostra o estado `aguarda_pesquisador` e sugere `retomar b-01`

#### Scenario: Acompanhar
- **GIVEN** 25 eventos anteriores da sessão `iris-01` e `TERMINAL_FOLLOW_HISTORY=20`
- **WHEN** o pesquisador digita `acompanhar iris-01` e depois `voltar`
- **THEN** são mostrados os 20 últimos eventos e o REPL volta ao prompt sem encerrar nada

### Requirement: Ações imediatas que não são decisões reservadas
O REPL SHALL permitir `cancelar <apelido> <subtarefa>`, que retira uma subtarefa que ainda não começou com o motivo `cancelada_pesquisador`, e `replanejar <apelido>`, que pede ao Researcher um replanejamento ao fim das subtarefas em curso; nenhuma das duas MUST passar pelo gate de decisões reservadas, e o cancelamento de subtarefa iniciada ou concluída MUST ser recusado (ADR 023 §3).

#### Scenario: Cancelar subtarefa pendente
- **GIVEN** a sessão `iris-01` com a subtarefa `testar_svm` pendente
- **WHEN** o pesquisador digita `cancelar iris-01 testar_svm`
- **THEN** `testar_svm` não executa e aparece no checkpoint com motivo `cancelada_pesquisador`
- **AND** existe o evento `comando_recebido`

#### Scenario: Cancelar subtarefa em curso
- **GIVEN** `treinar_rf` em curso
- **WHEN** o pesquisador digita `cancelar iris-01 treinar_rf`
- **THEN** o comando é recusado, a subtarefa continua e a recusa aparece no terminal

#### Scenario: Replanejar
- **WHEN** o pesquisador digita `replanejar iris-01`
- **THEN** depois das subtarefas em curso, o Researcher recebe um prompt `MODO: REPLAN` e um evento `plano_aprovado` com versão nova é gravado
