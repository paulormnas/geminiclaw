# Delta: session-continuity

Testes de integração: o processo da sessão real roda em processo separado (`python -m tests.support.session_process_recorded`), com PostgreSQL real e provedor LLM `gravado` (respostas de `tests/fixtures/recorded/`); nenhuma chamada paga. As ajudas de teste usadas aqui (harness do processo da sessão, provedor gravado, `FakeClock`, fixture de PostgreSQL com migrações e o papel `terminal_writer`, REPL com entrada simulada e em pseudo-terminal) são criadas por esta mudança (tasks §3.4) e reaproveitadas por `v18.7-persistent-human-gate`, `v18.7-session-events-terminal` e `v18.7-exploration-limits`.

Valores reduzidos nos testes de integração (cada teste em até 15 s, regra do tester; marcador `pytest-timeout` de 15 s): `SESSION_LAUNCH_TIMEOUT_SECONDS=10`, `SESSION_HEARTBEAT_SECONDS=1`, `SESSION_STALE_SECONDS=3`, `SESSION_LOOP_TICK_SECONDS=1`, `SESSION_LOOP_STALE_SECONDS=4`, `TERMINAL_PRESENCE_HEARTBEAT_SECONDS=1`, `TERMINAL_PRESENCE_STALE_SECONDS=3`, `SESSION_PRESENCE_CHECK_SECONDS=1`, `TERMINAL_STALE_CHECK_SECONDS=1`, `SESSION_LOST_EXIT_GRACE_SECONDS=2`, `LIMIT_GRACE_SECONDS=2`, provedor gravado com latência de até 1 s por chamada salvo quando o cenário diz outra coisa. Os padrões (60 s, 15 s, 900 s etc.) são conferidos em testes de unidade com `FakeClock`.

## ADDED Requirements

### Requirement: Sessão em processo próprio
Iniciar (no REPL, pelo comando `nova-pesquisa <tarefa>`; decisão do pesquisador de 2026-10-15) ou retomar uma pesquisa pelo REPL ou pelo comando direto SHALL criar um processo de sessão separado do terminal, que executa o orquestrador, os agentes e o laço autônomo; o processo SHALL gravar na sessão `pid`, `host`, `process_started_at`, `alias` e o batimento. No REPL, o processo SHALL estar em grupo de processos próprio, com `stdout` e `stderr` em `SESSION_LOG_DIR`, e o REPL SHALL voltar ao prompt sem esperar o fim da sessão (ADR 023 §1).

#### Scenario: REPL livre durante a pesquisa
- **GIVEN** um REPL com entrada simulada "nova tarefa de teste" seguida de "sair", modo `auto` e provedor gravado que demora 3 s por chamada
- **WHEN** o REPL processa a primeira linha
- **THEN** o prompt volta em menos de `SESSION_LAUNCH_TIMEOUT_SECONDS` e antes do fim da sessão
- **AND** a sessão tem `pid` de um processo vivo diferente do REPL, `host` igual ao do teste e `alias` no formato `<slug>-NN`

#### Scenario: Prompt fora da linha de comando
- **WHEN** o terminal cria o processo da sessão
- **THEN** os argumentos do processo são só `--launch <caminho>` e o arquivo de lançamento tem modo `0600`
- **AND** o arquivo não existe mais depois que o processo registra a sessão

#### Scenario: Contexto alterado depois da confirmação
- **GIVEN** um arquivo de lançamento cujo `contexto.digest` difere do `input_context/` atual
- **WHEN** o processo da sessão inicia
- **THEN** o processo sai com código 1 sem criar sessão, com mensagem que cita a divergência

### Requirement: Nenhuma leitura de stdin no processo da sessão
O processo da sessão MUST ser criado com `stdin` fechado e MUST NOT ler da entrada padrão em nenhum caminho; o que hoje pergunta no terminal dentro da sessão SHALL virar pendência registrada (ADR 023 §1 e §4.1).

#### Scenario: input proibido
- **GIVEN** o módulo `src.session_process` inicializado
- **WHEN** qualquer código chama `input()`
- **THEN** levanta `StdinForbiddenError`

#### Scenario: ask_researcher no assisted sem terminal
- **GIVEN** uma sessão `assisted` no processo da sessão
- **WHEN** um agente chama `ask_researcher`
- **THEN** a interação é registrada com `respondido_por="pendente_pesquisador"` e o agente recebe a mensagem de pendência, sem bloquear

#### Scenario: Limite operacional no assisted
- **GIVEN** uma sessão `assisted` que atinge um limiar operacional
- **WHEN** o laço avalia os limiares
- **THEN** o aviso é registrado no log e a sessão continua, sem pergunta no terminal

### Requirement: Verificação de memória antes de iniciar ou retomar
Antes de criar o processo da sessão, o terminal SHALL ler a memória disponível. No REPL, abaixo de `MIN_AVAILABLE_MEMORY_MB` ou com leitura desconhecida, SHALL mostrar a memória disponível e as pesquisas em execução e perguntar se inicia mesmo assim. No comando direto, MUST falhar antes de criar o processo, com mensagem que cita a memória e `MIN_AVAILABLE_MEMORY_MB` e código de saída 5. Não há fila nem número fixo de sessões simultâneas (ADR 023 §1; casos 14 e 15).

#### Scenario: REPL abaixo do mínimo, desiste
- **GIVEN** `MIN_AVAILABLE_MEMORY_MB=512`, leitura simulada de 300 MB, uma sessão `iris-01` em execução e entrada simulada "n"
- **WHEN** o pesquisador inicia uma pesquisa no REPL com `nova-pesquisa <tarefa>`
- **THEN** o aviso mostra `300` MB e lista `iris-01`
- **AND** nenhum processo é criado e nenhuma sessão nova existe

#### Scenario: REPL abaixo do mínimo, inicia mesmo assim
- **GIVEN** a mesma leitura e entrada simulada "s"
- **WHEN** o pesquisador inicia uma pesquisa no REPL com `nova-pesquisa <tarefa>`
- **THEN** o processo da sessão é criado

#### Scenario: Comando direto abaixo do mínimo
- **GIVEN** leitura simulada de 300 MB e `MIN_AVAILABLE_MEMORY_MB=512`
- **WHEN** `geminiclaw "tarefa"` é executado
- **THEN** o processo termina com código 5, a mensagem cita `300` e `MIN_AVAILABLE_MEMORY_MB`, e nenhuma sessão é criada

#### Scenario: Retomada também verifica
- **GIVEN** leitura simulada abaixo do mínimo e entrada "n"
- **WHEN** o pesquisador escolhe retomar uma sessão no REPL
- **THEN** nenhum processo é criado e a sessão de origem continua sem `continued_by`

### Requirement: Fim da sessão autônoma com o processo
Nos modos `semi` e `auto`, a sessão SHALL rodar sem depender do terminal e, ao chegar a um motivo de parada, SHALL gravar motivo, relatório, checkpoint e encerrar o processo. Quando só restarem pedidos ao pesquisador, a sessão SHALL gravar checkpoint, `status="aguarda_pesquisador"` e `motivo_parada="aguarda_pesquisador"` e encerrar o processo; o processo MUST NOT ficar vivo sem trabalho (ADR 023 §1.2, item 1; casos 1, 2 e 3).

#### Scenario: Objetivo atingido com o terminal fechado
- **GIVEN** uma pesquisa `auto` iniciada pelo REPL, com respostas gravadas que levam ao critério de solução
- **WHEN** o REPL sai logo depois do lançamento
- **THEN** a sessão termina com `motivo_parada="solucao_encontrada"`, relatório e checkpoint `fechado` gravados
- **AND** o PID registrado deixa de existir em até 5 s depois do fechamento, sem intervenção

#### Scenario: Parada por limite
- **GIVEN** uma pesquisa `auto` com `SESSION_MAX_TOKENS` baixo e respostas gravadas que o ultrapassam
- **WHEN** a sessão roda
- **THEN** a sessão fecha com `motivo_parada="limite_tokens"`, checkpoint gravado e processo encerrado

#### Scenario: Só pedidos pendentes
- **GIVEN** uma pesquisa `semi` cujo plano gravado só tem hipóteses aguardando decisão do pesquisador
- **WHEN** o laço não encontra mais nada executável
- **THEN** a sessão fica com `status="aguarda_pesquisador"`, checkpoint gravado e o processo sai com código 4

### Requirement: Presença do terminal
O REPL e o comando direto em primeiro plano SHALL registrar presença em `terminal_presence` com batimento a cada `TERMINAL_PRESENCE_HEARTBEAT_SECONDS` (padrão 10) e, na saída normal, SHALL gravar `ended_at`; a presença sem batimento há mais de `TERMINAL_PRESENCE_STALE_SECONDS` (padrão 60) SHALL valer como ausência (ADR 023 §1.2, item 2).

#### Scenario: Saída normal
- **WHEN** o pesquisador digita `sair` no REPL
- **THEN** a linha de presença tem `ended_at` preenchido e `end_reason="saida"`

#### Scenario: Batimento de presença com os padrões
- **GIVEN** `FakeClock`, os padrões `TERMINAL_PRESENCE_HEARTBEAT_SECONDS=10` e `TERMINAL_PRESENCE_STALE_SECONDS=60` e uma presença iniciada
- **WHEN** o relógio avança 35 s
- **THEN** `heartbeat_at` foi atualizado 3 vezes e `is_present` devolve `True`

#### Scenario: Presença envelhecida
- **GIVEN** uma presença com `heartbeat_at` 61 s atrás e `TERMINAL_PRESENCE_STALE_SECONDS=60`
- **WHEN** `is_present` é consultado
- **THEN** devolve `False`

### Requirement: Suspensão do assisted sem o pesquisador
Uma sessão `assisted` SHALL ler a presença do seu terminal a cada `SESSION_PRESENCE_CHECK_SECONDS` (padrão 15) e, na ausência, SHALL parar de despachar subtarefas, deixar as subtarefas em curso terminarem sem interrompê-las, gravar checkpoint com plano, hipóteses e seus estados, pedidos pendentes, último evento e custo, gravar `status="suspensa_sem_pesquisador"` e encerrar o processo com código 4. Sessões `semi` e `auto` MUST NOT ser afetadas pelo terminal (ADR 023 §1.2, item 2; §6; casos 4 e 5).

#### Scenario: Terminal sai normalmente
- **GIVEN** uma sessão `assisted` com uma subtarefa gravada que leva 3 s em curso
- **WHEN** o REPL sai normalmente
- **THEN** a subtarefa termina com sucesso e aparece como `concluida` no checkpoint
- **AND** nenhuma subtarefa nova começa, a sessão fica `suspensa_sem_pesquisador` e o PID deixa de existir

#### Scenario: Terminal cai
- **GIVEN** `TERMINAL_PRESENCE_STALE_SECONDS=3` e `SESSION_PRESENCE_CHECK_SECONDS=1` em teste, uma sessão `assisted` em execução e o processo do REPL morto com `SIGKILL`
- **WHEN** passam `TERMINAL_PRESENCE_STALE_SECONDS` mais `SESSION_PRESENCE_CHECK_SECONDS` (4 s)
- **THEN** a sessão se suspende como no cenário anterior, sem subtarefa com `causa_falha` de interrupção

#### Scenario: Modo auto ignora o terminal
- **GIVEN** uma sessão `auto` em execução
- **WHEN** o REPL sai
- **THEN** a sessão continua `active` até o seu motivo de parada

### Requirement: Um REPL por vez
Abrir o REPL com outro REPL presente (presença `tipo="repl"` sem `ended_at`, com batimento recente e, no mesmo host, PID vivo) MUST ser recusado com aviso e código 1; presenças envelhecidas SHALL ser marcadas `end_reason="obsoleta"` e não impedem a abertura (ADR 023 §1.2, item 5; caso 6).

#### Scenario: Segundo REPL
- **GIVEN** uma presença `repl` com batimento de 5 s atrás e PID vivo
- **WHEN** um novo REPL abre
- **THEN** o novo REPL termina com código 1 e mensagem de que já há um terminal aberto

#### Scenario: Presença velha
- **GIVEN** uma presença `repl` com batimento de 10 minutos atrás
- **WHEN** um novo REPL abre
- **THEN** o REPL abre e a presença velha fica com `end_reason="obsoleta"`

### Requirement: Pesquisas não finalizadas ao abrir o REPL
Ao abrir, o REPL SHALL mostrar o resumo das sessões alteradas desde o fim da última presença de REPL, listar as sessões `suspensa_sem_pesquisador`, `aguarda_pesquisador` e `interrompida` com apelido, modo, motivo e pedidos pendentes, e perguntar, para cada uma, se o pesquisador quer retomar, manter ou encerrar. Retomar SHALL criar um processo novo pela retomada existente (nova sessão com `continued_by` na origem), com a verificação de memória; manter MUST NOT alterar a sessão; encerrar SHALL gravar `status="closed"`, `motivo_parada="encerrada_pesquisador"` e o relatório determinístico `relatorio_encerramento.md`, sem chamada a LLM. Pesquisas autônomas concluídas SHALL aparecer só no resumo (ADR 023 §1.2, item 3; casos 7, 8 e 9).

#### Scenario: Lista e pergunta
- **GIVEN** sessões `a-01` (`suspensa_sem_pesquisador`), `b-01` (`aguarda_pesquisador`), `c-01` (`interrompida`) e `d-01` (`closed`, `solucao_encontrada`), todas alteradas depois da última presença, e entrada simulada "m", "m", "m"
- **WHEN** o REPL abre
- **THEN** a pergunta de retomada aparece para `a-01`, `b-01` e `c-01`, nessa ordem de atualização, e não para `d-01`
- **AND** `d-01` aparece no resumo com o motivo `solucao_encontrada`

#### Scenario: Retomar a exploração
- **GIVEN** uma sessão `suspensa_sem_pesquisador` com 2 subtarefas concluídas no checkpoint e respostas gravadas para o restante
- **WHEN** o pesquisador responde "r"
- **THEN** um processo novo cria a sessão que continua a origem, a origem fica com `continued_by` igual ao id novo, e as 2 subtarefas concluídas não são reexecutadas
- **AND** a sessão nova herda o apelido da origem

#### Scenario: Manter
- **WHEN** o pesquisador responde "m" para `a-01`
- **THEN** `status`, `payload` e `updated_at` de `a-01` ficam iguais

#### Scenario: Encerrar
- **WHEN** o pesquisador responde "e" para `b-01`
- **THEN** `b-01` fica `closed` com `motivo_parada="encerrada_pesquisador"` e `relatorio_encerramento.md` existe no diretório da sessão
- **AND** nenhum provedor LLM é chamado

### Requirement: Detecção de sessão parada pelo terminal
O terminal SHALL, ao abrir e a cada `TERMINAL_STALE_CHECK_SECONDS` (padrão 60), marcar `interrompida`, por transição condicional, a sessão `active` cujo processo não existe no mesmo host (ou existe com outra hora de início), cujo batimento passou de `SESSION_STALE_SECONDS` ou cujo `loop_beat_at` passou de `SESSION_LOOP_STALE_SECONDS` (padrão 900), e SHALL oferecer a retomada (ADR 023 §6; caso 10).

#### Scenario: Processo morto com SIGKILL
- **GIVEN** `TERMINAL_STALE_CHECK_SECONDS=1` em teste e uma sessão `auto` em execução lançada pelo REPL
- **WHEN** o processo da sessão recebe `SIGKILL` e passa `TERMINAL_STALE_CHECK_SECONDS` (1 s)
- **THEN** a sessão fica `interrompida`, as subtarefas em andamento viram falha de infraestrutura no checkpoint
- **AND** ao reabrir o REPL, a sessão aparece na pergunta de retomada

#### Scenario: Reuso de PID
- **GIVEN** uma sessão `active` cujo `pid` pertence a um processo vivo com `create_time` 1 hora depois de `process_started_at`
- **WHEN** a varredura roda
- **THEN** a sessão é marcada `interrompida`

#### Scenario: Outro host
- **GIVEN** uma sessão `active` com `host` diferente do terminal e batimento recente
- **WHEN** a varredura roda
- **THEN** a sessão não é marcada, mesmo sem processo local com aquele PID

### Requirement: Recusa de reativar sessão continuada
`reassert_active` MUST NOT reativar uma sessão com `continued_by`; o processo cujo batimento é recusado por isso SHALL parar de despachar, cancelar o que roda, remover seus containers de sandbox, não gravar nada na sessão e sair com código 6 (ADR 023 §6; caso 11).

#### Scenario: Sessão já continuada
- **GIVEN** uma sessão `interrompida` com `payload.continued_by="s2"`
- **WHEN** `reassert_active` é chamado para ela
- **THEN** devolve `False` e o status continua `interrompida`

#### Scenario: Processo antigo se encerra
- **GIVEN** um batimento simulado recusado e `reassert_active` recusado por `continued_by`
- **WHEN** a thread do batimento trata a recusa
- **THEN** o sinalizador de sessão perdida é acionado e o código de saída registrado é 6

### Requirement: Comando direto em primeiro plano
O comando direto (`geminiclaw "tarefa"`) SHALL, por padrão, criar o processo da sessão, registrar presença, mostrar a saída dele e esperar o fim, saindo com o código de `exit_code_for(motivo_parada)`: 0 parada de pesquisa, 1 erro ou recusa, 2 modo sem limite não confirmado, 3 limite, 4 aguarda o pesquisador, 5 memória insuficiente, 6 sessão perdida, 130 interrupção pelo pesquisador. Ctrl+C SHALL ser repassado ao processo da sessão (o primeiro pede o fechamento gracioso com checkpoint). `--background` SHALL criar o processo, imprimir apelido e PID e sair com 0; `--background` com `--mode assisted` MUST ser recusado (ADR 023 §1 e §1.2, item 4; caso 12).

#### Scenario: Primeiro plano termina com a exploração
- **GIVEN** `geminiclaw --mode auto "tarefa"` com respostas gravadas que levam a `solucao_encontrada`
- **WHEN** o comando roda
- **THEN** o comando só termina depois do processo da sessão e sai com 0

#### Scenario: Código do limite
- **GIVEN** respostas gravadas que levam a `limite_tokens`
- **WHEN** o comando roda
- **THEN** sai com 3

#### Scenario: Ctrl+C
- **GIVEN** o comando em primeiro plano com uma subtarefa em curso
- **WHEN** o terminal recebe `SIGINT` uma vez
- **THEN** a sessão fecha com `motivo_parada="interrompida_pesquisador"` e checkpoint gravado, e o comando sai com 130

#### Scenario: Todo motivo tem classe
- **WHEN** `exit_code_for` é chamado com cada valor de `Sessao.motivo_parada` em `src/knowledge/schema.py`
- **THEN** nenhum valor conhecido cai no código de motivo desconhecido

#### Scenario: Interrupção da sessão lançada pelo REPL
- **GIVEN** uma sessão `auto` lançada pelo REPL, com uma subtarefa gravada de 3 s em curso, e o REPL ainda aberto
- **WHEN** o processo da sessão recebe `SIGINT` uma vez, enviado pelo teste ao PID registrado (o comando `parar` de `v18.7-session-events-terminal` chega pela caixa de entrada e é testado lá)
- **THEN** a sessão fecha com `motivo_parada="interrompida_pesquisador"` e checkpoint gravado, o processo da sessão sai com 130 e o REPL continua aberto, com a presença sem `ended_at`

### Requirement: Limpeza de sandboxes restrita à sessão
A limpeza de containers de sandbox feita pelo processo da sessão (encerramento por sessão perdida, fechamento) e pelo segundo Ctrl+C do comando direto SHALL remover só os containers com o rótulo `session_id` da sessão ou da sua cadeia, e MUST NOT remover containers de outras sessões; o container de preparação SHALL receber o mesmo rótulo `session_id` que o de execução. A limpeza de todos os containers do projeto SHALL existir só como comando explícito do REPL, com confirmação (hoje `cleanup_sandbox_containers`, `src/skills/code/sandbox.py:361-381`, remove todos os containers com `project=geminiclaw`).

#### Scenario: Containers de duas sessões
- **GIVEN** um daemon Docker simulado com dois containers de rótulo `project=geminiclaw`, um com `session_id=s1` e outro com `session_id=s2`
- **WHEN** a sessão `s1` é encerrada por sessão perdida e faz a limpeza
- **THEN** só o container de `s1` é removido e o de `s2` continua

#### Scenario: Container de preparação rotulado
- **WHEN** o sandbox cria o container de preparação de uma subtarefa da sessão `s1`
- **THEN** o container tem o rótulo `session_id=s1`

### Requirement: Ambiente filtrado mantido depois do .env
No processo da sessão, os nomes de `SESSION_ENV_DENYLIST` (e, a partir de `v18.7-persistent-human-gate`, os da lista fixa de credenciais do terminal) SHALL ser retirados de `os.environ` logo depois de `load_dotenv()` em `src/config.py` e antes de qualquer outro import do projeto, para que o `.env` relido não os reintroduza (hoje `src/config.py:8` chama `load_dotenv()` na importação).

#### Scenario: Nome negado no .env
- **GIVEN** `SESSION_ENV_DENYLIST=SEGREDO_TESTE` no terminal e um `.env` temporário com `SEGREDO_TESTE=abc` no diretório de trabalho do processo da sessão
- **WHEN** o processo da sessão inicia e importa `src.config`
- **THEN** `os.environ` do processo não contém `SEGREDO_TESTE`

## MODIFIED Requirements

### Requirement: Batimento independente do laço de eventos
_Origem: [`v18-research-continuity`](../../../archive/v18-research-continuity/proposal.md); modificado por `v18.7-background-sessions` (ADR 023 §6)_
O sistema SHALL manter o batimento da sessão em thread própria e gravar com ele `loop_beat_at`, o último sinal do laço de eventos (tique a cada `SESSION_LOOP_TICK_SECONDS`, padrão 10). O batimento SHALL ser aceito como sinal de vida só enquanto `loop_beat_at` for mais recente que `SESSION_LOOP_STALE_SECONDS` (padrão 900). A reafirmação de uma sessão marcada obsoleta por engano SHALL acontecer só com o laço dando sinal e sem `continued_by`.

#### Scenario: Laço lento não derruba a sessão
- **GIVEN** `FakeClock`, os padrões `SESSION_STALE_SECONDS=300`, `SESSION_HEARTBEAT_SECONDS=30` e `SESSION_LOOP_STALE_SECONDS=900`, a thread do batimento ativa e o último tique do laço em t = 0
- **WHEN** o relógio avança até t = 400 s sem novo tique e a varredura do terminal roda
- **THEN** `updated_at` foi atualizado pelo batimento, `loop_beat_at` continua em t = 0 e a sessão não é marcada `interrompida`

#### Scenario: Laço travado
- **GIVEN** `SESSION_LOOP_TICK_SECONDS=1` e `SESSION_LOOP_STALE_SECONDS=2` em teste e o laço bloqueado por 5 s, com a thread do batimento viva
- **WHEN** a varredura do terminal roda
- **THEN** a sessão é marcada `interrompida` mesmo com `updated_at` recente
