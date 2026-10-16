# Tarefas: v18.7-background-sessions

**Estado (2026-10-16):** em andamento, em PRs sequenciais. PR 1 (`feat/v18.7-background-sessions-base`): divisão do `cli/main.py` (0.9), schema e sessão (1.1 a 1.4), códigos de saída e apelido (2.1 e 2.2), retenção do registro de sessões. Faltam lançamento e processo da sessão (3), fim por modo e presença (4), REPL e comando direto (5), benchmark (6) e configuração/documentação (7).

**Decisões do pesquisador em 2026-10-16 (resposta à revisão desta mudança):**
- Entrega: pode haver quantos PRs forem necessários; `background-sessions` e `persistent-human-gate` são mergeadas em sequência no mesmo dia, sem uso intermediário (Questão 1).
- Coluna nova **`resumo`** em `agent_sessions` (tarefa da pesquisa em poucas linhas, montada sem LLM): a lista de pesquisas não finalizadas mostra o que cada sessão faz. As sessões **não precisam durar para sempre**: `SESSION_RETENTION_DAYS` (30; 0 desliga) remove do registro as sessões terminadas e antigas, nunca as com trabalho por terminar nem as antecessoras de uma cadeia viva (`SessionManager.purge_finished`). O que importa é retomar a pesquisa em curso quando o terminal ou a aplicação é encerrado (estados `interrompida`, `aguarda_pesquisador`, `suspensa_sem_pesquisador` retomáveis sem confirmação).
- **Memória desconhecida** (Questão 3): não falha, nem no REPL nem no comando direto; registra um evento no banco (telemetria) e a aplicação segue, mesmo que consuma muita memória. Memória conhecida abaixo de `MIN_AVAILABLE_MEMORY_MB` continua como no design (§1.3).
- **Papel do terminal** (Questão 2): ver `v18.7-persistent-human-gate` (sem endurecimento no desenvolvimento; a presença é gravada pelo papel principal e o endurecimento fica para a mudança anterior à produção).
- **Encerrar com Curator pendente** (Questão 5): aceito, com a condição de existir no laço a retomada da etapa do Curator (tarefa 5.6 abaixo).
- `sessions` e `stop` (Questão 4): decidido em 2026-10-16: os comandos de container passam a se chamar **`sandboxes`** e **`parar-sandboxes`** (REPL e comando direto; feito no PR de renomeação) e `sessions` fica livre para listar as pesquisas (tarefa 5.1).

## 0. Pré-requisitos
- [ ] 0.1 `v18.7-resource-monitor-config` mergeada; revisar esta mudança contra o código de `dev` (referências de linha de 2026-10-15). Merge junto com `v18.7-persistent-human-gate` (PRs em sequência no mesmo dia).
- [ ] 0.2 Aprovação do pesquisador para o schema (proposal, "Aprovações necessárias") e resposta às Questões em aberto 1 e 3 do design.
- [x] 0.9 Divisão do módulo grande antes do comportamento novo (ADR 024 §5), só movendo código, com a suíte verde antes de seguir: `src/cli/main.py`: extrair para módulos próprios em `src/cli/` o lançamento do processo da sessão e o laço do REPL. Os caminhos citados nesta mudança valem pela tabela de `v18.7-source-layout`.

## 1. Schema e sessão
- [x] 1.1 `scripts/init_db.sql` e `scripts/migrations/v18_7_001_session_process.sql` (idempotente) com o DDL do design §2.1.
- [x] 1.2 `src/session.py`: colunas novas em `Session`/`_row_to_session`; constantes de status; `heartbeat(session_id, loop_beat_at)`; `reassert_active` com `NOT (payload ? 'continued_by')`; `register_process`.
- [x] 1.3 `src/knowledge/schema.py`: `Sessao.motivo_parada` com `aguarda_pesquisador`, `suspensa_sem_pesquisador`, `encerrada_pesquisador`; `src/continuity.py`: estados retomáveis (os dois primeiros sem confirmação, `encerrada_pesquisador` com confirmação); `describe_stop_reason` com os três (design §1.4).
- [x] 1.4 Dev-deps `pexpect` e `pytest-timeout` (aprovadas em 2026-10-16: só testes) e `tests/support/pg.py` (banco temporário por execução). Testes de unidade: `reassert_active` recusa sessão continuada (caso 11); estados retomáveis; migração aplicada duas vezes sem erro (integração, PostgreSQL real).

## 2. Códigos de saída e apelido
- [x] 2.1 `src/exit_codes.py` (`exit_code_for`) e `src/session_alias.py` (pela tabela de `v18.7-source-layout`: `src/session/exit_codes.py`, `src/session/alias.py`; estados em `src/session/states.py`).
- [x] 2.2 Testes: todo valor de `Sessao.motivo_parada` tem classe; motivo desconhecido dá 1; apelido `<slug>-NN` sem colisão no projeto; `sessao-NN` sem projeto.

## 3. Lançamento e processo da sessão
- [ ] 3.1 `src/session_launcher.py`: verificação de memória, arquivo de lançamento `0600` com `O_EXCL`, `filtered_env`, `spawn_session`, `wait_registered`.
- [ ] 3.2 `src/session_process.py`: leitura e validação do lançamento (dado não confiável), conferência do `digest`, roteamento, `input` proibido, registro de PID/host/apelido, tique do laço, batimento com `loop_beat_at`, chamada a `handle_request` ou à retomada, saída com `exit_code_for`.
- [ ] 3.3 Mover a lógica de `_run_resume` (`src/cli.py:706-800`) para uma função usada pelo processo da sessão; a confirmação de sessão resolvida fica no terminal.
- [ ] 3.4 Ajudas de teste compartilhadas (criadas aqui, reaproveitadas por `v18.7-persistent-human-gate`, `v18.7-session-events-terminal` e `v18.7-exploration-limits`):
  - `tests/support/session_process_recorded.py` e o harness `tests/support/session_harness.py`: lança o processo da sessão com arquivo de lançamento de teste, espera o PID registrado na sessão, envia `SIGKILL`/`SIGINT`, e no teardown encerra o grupo de processos inteiro (`os.killpg`) e confere que nada sobrou.
  - Provedor `gravado` em `tests/support/` (respostas de `tests/fixtures/recorded/<cenário>.jsonl`, na ordem, falha explícita se faltar resposta, latência configurável por resposta), reaproveitando o `FakeRecordingProvider` de `v18.7-benchmark-fixes` para registrar prompts e simular erros.
  - `tests/support/fake_clock.py` (`FakeClock`: `now()`, `monotonic()`, `sleep()` e `advance()`; injetado em `TerminalPresence`, `SessionWatch`, batimento, lembrete do gate e leitura de eventos). Sem `time-machine`: o relógio é injetado, não substituído globalmente.
  - Fixture de PostgreSQL real (`tests/support/pg.py`): banco temporário por sessão de testes, aplica `scripts/init_db.sql` e as migrações `v18_7_*`, cria o papel `terminal_writer` com senha de teste e devolve as duas conexões; pulada sem `DATABASE_URL` acessível.
  - REPL de teste: entrada simulada (lista de linhas) para os testes de unidade e REPL num pseudo-terminal com `pexpect` para os testes de redesenho e de Ctrl+C.
  - Marcador `pytest-timeout` de 15 s nos testes de integração desta mudança; o harness define os valores reduzidos por variável de ambiente listados no início da spec `session-continuity` (nenhum teste de integração espera um padrão de 30 s ou 60 s).
- [ ] 3.5 Testes de unidade: memória abaixo do mínimo no REPL (desiste e inicia mesmo assim; caso 14) e no comando direto (código 5; caso 15); retomada também verifica; `input` levanta `StdinForbiddenError`; `ask_researcher` no `assisted` vira `pendente_pesquisador`; lançamento com `digest` divergente sai com 1; prompt fora de `argv`.
- [ ] 3.6 `src/config.py`: no processo da sessão, retirar de `os.environ` os nomes negados logo depois de `load_dotenv()` e antes de outros imports do projeto. Teste de integração "Nome negado no .env".
- [ ] 3.7 Limpeza de sandboxes por `session_id` da cadeia (`src/skills/code/sandbox.py:361-381`), rótulo `session_id` também no container de preparação (`sandbox.py:717`), limpeza global só por comando explícito do REPL com confirmação. Testes de unidade com daemon simulado: "Containers de duas sessões", "Container de preparação rotulado".
- [ ] 3.8 Teste de integração "REPL livre durante a pesquisa" (provedor gravado com 3 s por chamada; prompt de volta antes do fim da sessão; teardown encerra o grupo).

## 4. Fim por modo e presença
- [ ] 4.1 `src/autonomous_loop.py`: remover `_offer_suspension` (`:526-547`); `aguarda_pesquisador` em `semi`/`auto` quando só restam pedidos; sinalizador de suspensão sem carência que cancela.
- [ ] 4.2 `src/orchestrator.py`: remover a leitura de `stdin` em `:1506`; fechamento grava o código de saída no payload.
- [ ] 4.3 `src/terminal_presence.py` (batimento em thread, saída normal, linhas obsoletas, criação sob trava); leitura de presença pela sessão `assisted`.
- [ ] 4.4 Testes de integração (processo real, PostgreSQL real, provedor gravado): caso 1 (objetivo com REPL fechado), caso 2 (limite), caso 3 (só pedidos pendentes: `aguarda_pesquisador`, código 4), caso 4 (saída normal do terminal com subtarefa em curso), caso 5 (`SIGKILL` no terminal), modo `auto` ignora o terminal.
- [ ] 4.5 Teste de unidade: segundo REPL recusado; presença velha marcada `obsoleta` (caso 6); "Batimento de presença com os padrões" e "Presença envelhecida" com `FakeClock`.
- [ ] 4.6 Teste de integração "Saída normal": `sair` no REPL grava `ended_at` e `end_reason="saida"` na presença.

## 5. REPL e comando direto
- [ ] 5.1 `src/cli.py` `interactive_mode`: iniciar pesquisa pelo comando `nova-pesquisa <tarefa>` (texto livre sem comando recusado com a dica de `nova-pesquisa` até `v18.7-session-events-terminal`) e lançar em segundo plano; varredura de sessões paradas ao abrir e periódica (`src/session_watch.py`); resumo desde a última vez; pergunta retomar/manter/encerrar; relatório determinístico de encerramento; carga sob demanda de embeddings e clientes.
- [ ] 5.2 `src/cli.py` `main`: comando direto em primeiro plano com presença, repasse de `SIGINT` e código de saída; `--background`; recusa de `--background` com `assisted`.
- [ ] 5.3 Testes de unidade (entrada simulada): lista e pergunta do caso 7; manter e encerrar do caso 9 (sem chamada a LLM); `fastembed` não importado depois de abrir e sair do REPL.
- [ ] 5.4 Testes de integração: retomar do caso 8 (`continued_by`, sem reexecutar concluídas, apelido herdado); `SIGKILL` no processo da sessão do caso 10; reuso de PID e outro host (unidade); laço travado com `SESSION_LOOP_STALE_SECONDS=2`; comando direto do caso 12 (código 0, código 3, Ctrl+C com 130) e, também do caso 12, "Interrupção da sessão lançada pelo REPL" (`SIGINT` ao processo da sessão: `interrompida_pesquisador`, checkpoint, saída 130, REPL aberto).
- [ ] 5.5 Teste de unidade "Laço lento não derruba a sessão" com `FakeClock` e os padrões (300, 30, 900).

- [ ] 5.6 Retomada da etapa do Curator: ao retomar uma cadeia cujo checkpoint tem `curator_pendente` (gravado pelo encerramento no REPL), o laço da sessão nova executa a consolidação do Curator antes de planejar. Teste de unidade com Curator simulado.

## 6. Benchmark
- [ ] 6.1 `scripts/benchmark/run_benchmark.py`: `start_new_session=True`, `killpg` no tempo limite; `anomalies()` com código 4 e código divergente; `stop_class` devolve `interrupcao` para todo motivo terminado em `_pesquisador`.
- [ ] 6.2 Testes de unidade do benchmark: tempo limite encerra o grupo (`kill_grace_seconds=1`); código 4; código divergente; `exit 0` com `solucao_encontrada` sem anomalia; `stop_class` dos motivos `*_pesquisador`; código 3 para `versao_modelo` e `planos_rejeitados` sem anomalia de código.
- [ ] 6.3 Teste "Uma sessão por vez": dois comandos simulados que gravam PID, início e fim; o início da segunda é posterior ao fim da primeira e o grupo da primeira não existe mais.

## 7. Configuração e documentação
- [ ] 7.1 `src/config.py` com as variáveis do design §3 e validações; `.env.example` documentado.
- [ ] 7.2 `README.md`: REPL em segundo plano, `--background`, códigos de saída.

## 8. Validação final
- [ ] 8.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v` verde, com PostgreSQL real para os testes de integração.
- [ ] 8.2 Conferir que nenhum `input(` é alcançável no processo da sessão (teste do `StdinForbiddenError` com o laço completo de um cenário gravado).
- [ ] 8.3 Revisão nos 7 eixos; PR para `dev` citando esta mudança; atualizar a linha **Estado** deste arquivo.
