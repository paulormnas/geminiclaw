# Proposta: Sessão de Pesquisa em Processo Próprio

**ID:** `v18.7-background-sessions` · **Versão:** V18.7 · **Capacidade:** `session-continuity`, `benchmark`
**ADRs de origem:** [ADR 023](../../../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) §1 (processo da sessão, verificação de memória, comando direto), §1.2 (fim da sessão conforme o modo, presença do terminal, suspensão do `assisted`, pergunta de retomada, um terminal por vez), §6 (falhas), §7 (segurança e recursos); casos de aceite 1 a 12, 14 e 15
**Depende de:** `v18.7-resource-monitor-config` (leitura de memória multiplataforma, `MIN_AVAILABLE_MEMORY_MB`, `psutil` para conferir PID); `v18-research-continuity` (checkpoint, `resume`, `continued_by`), já arquivada Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.
**Mergeada junto com:** `v18.7-persistent-human-gate` (PRs em sequência no mesmo dia, sem uso intermediário em `dev` nem no Pi): a presença do terminal passa a ser gravada só pelo papel `terminal_writer` daquela mudança, e a janela em que o papel principal a grava (design §8, risco 1) não chega a ser usada.
**É pré-requisito de:** `v18.7-persistent-human-gate`, `v18.7-session-events-terminal` e `v18.7-exploration-limits` (estado `aguarda_pesquisador` e motivo `encerrada_pesquisador`). Esta mudança é a dona da tabela única de códigos de saída por motivo de parada (design §1.4).

## Por quê

Hoje `execute_prompt` é aguardado dentro do REPL (`src/cli.py:1189-1246`, chamado em `src/cli.py:1314-1317`): enquanto a sessão roda, o pesquisador não digita nada. Uma exploração sem teto (ADR 021 §5) pode durar horas e precisa sobreviver ao fechamento do terminal nos modos autônomos e se suspender, sem perda, no `assisted` quando o pesquisador sai. A detecção de sessão parada só acontece quando outro orquestrador inicia (`src/orchestrator.py:814-838`, chamada em `src/cli.py:1654-1657`), e `reassert_active` reativa uma sessão já continuada por outra (`src/session.py:349-361`).

## O que muda

- **Novo:** processo de sessão (`python -m src.session_process`), criado pelo terminal com `stdin` fechado, ambiente filtrado e, no REPL, desligado do grupo de processos do terminal; registra PID, host, início e batimento na sessão.
- **Novo:** no REPL, a pesquisa é iniciada pelo comando explícito `nova-pesquisa <tarefa>`; o texto livre sem comando deixa de iniciar pesquisa e vira conversa com o Researcher, em `v18.7-session-events-terminal` (decisão do pesquisador, 2026-10-15). Até essa mudança, o texto livre é recusado com a indicação de `nova-pesquisa` (as duas são mergeadas sem uso intermediário).
- **Novo:** verificação de memória disponível antes de iniciar ou retomar (`MIN_AVAILABLE_MEMORY_MB`): o REPL avisa e pergunta; o comando direto falha com código 5.
- **Novo:** fim da sessão conforme o modo: `semi` e `auto` rodam até um motivo de parada e encerram o processo; só com pedidos ao pesquisador, gravam checkpoint, passam a `aguarda_pesquisador` e encerram o processo.
- **Novo:** presença do terminal (tabela `terminal_presence`) com batimento próprio; a sessão `assisted` termina as subtarefas em curso, grava checkpoint e passa a `suspensa_sem_pesquisador` quando o terminal sai ou cai.
- **Novo:** ao abrir, o REPL recusa um segundo REPL presente, marca sessões paradas como `interrompida` (PID, batimento ou laço sem sinal), mostra o resumo desde a última vez e pergunta sobre cada pesquisa não finalizada (retomar, manter, encerrar com relatório).
- **Novo:** apelido curto da sessão (`<projeto>-NN`) usado nos comandos e nas linhas do terminal.
- **Novo:** códigos de saída do comando direto por classe de motivo de parada (`src/exit_codes.py`).
- **Modificado:** o batimento passa a carregar o sinal do laço de eventos; o terminal só aceita o batimento com sinal recente do laço.
- **Modificado:** `reassert_active` recusa reativar sessão com `continued_by`; o processo que perde a sessão se encerra (código 6).
- **Modificado:** o comando direto continua em primeiro plano por padrão (o terminal cria o processo da sessão e espera por ele); `--background` o manda para o segundo plano.
- **Modificado:** os caminhos que hoje leem `stdin` dentro da sessão deixam de ler: `_offer_suspension` (`src/autonomous_loop.py:526-547`) é removido; `_ask_researcher_core` no `assisted` (`src/orchestrator.py:1506`) registra a pergunta como `pendente_pesquisador` até `v18.7-persistent-human-gate`; `terminal_approver` e `terminal_solution_confirmer` já devolvem "sem resposta" sem TTY.
- **Modificado (benchmark):** o runner continua no comando direto em primeiro plano, inicia-o em grupo de processos próprio e encerra o grupo inteiro no tempo limite; o código de saída tem de ser coerente com o motivo de parada.
- **Fora do escopo:** tabela de eventos, atualizações assíncronas no REPL, comandos de acompanhamento, pausa, cancelamento e consulta (`v18.7-session-events-terminal`); gate persistente, papel de banco do terminal e caixa de entrada (`v18.7-persistent-human-gate`); agente de admissão, fila, reservas e vários terminais (ADR 023, Evolução prevista).

## Impacto

- **Código:** `src/session_process.py` (novo), `src/session_launcher.py` (novo: criação do processo, ambiente filtrado, verificação de memória, arquivo de lançamento), `src/terminal_presence.py` (novo), `src/session_watch.py` (novo: PID, batimento e laço), `src/exit_codes.py` (novo), `src/session_alias.py` (novo), `src/cli.py` (`main`, `interactive_mode`, `execute_prompt`, `_run_resume`), `src/session.py` (`heartbeat`, `reassert_active`, colunas novas, `mark_stale_process`), `src/heartbeat.py`, `src/orchestrator.py` (`_start_heartbeat`, fechamento por modo), `src/autonomous_loop.py` (suspensão por ausência, `aguarda_pesquisador`), `src/continuity.py` (estados retomáveis), `src/knowledge/schema.py` (`Sessao.motivo_parada`), `scripts/init_db.sql`, `scripts/migrations/v18_7_001_session_process.sql` (novo), `scripts/benchmark/run_benchmark.py`.
- **Contratos:** códigos de saída do comando direto; arquivo de lançamento `launch.json`; estados `aguarda_pesquisador` e `suspensa_sem_pesquisador`; motivos `aguarda_pesquisador`, `suspensa_sem_pesquisador`, `encerrada_pesquisador`.
- **Custo:** nenhuma chamada nova a LLM; um processo Python a mais por pesquisa em execução.

## Aprovações necessárias

- **Alteração de schema (AGENTS.md §1.5):**
  - `agent_sessions`: colunas novas `pid INTEGER`, `host TEXT`, `process_started_at TIMESTAMPTZ`, `loop_beat_at TIMESTAMPTZ`, `terminal_id TEXT`, `alias TEXT`; índice `idx_agent_sessions_alias`; valores novos da coluna `status`: `aguarda_pesquisador` e `suspensa_sem_pesquisador` (a coluna é `TEXT` sem restrição; o contrato muda).
  - tabela nova `terminal_presence` (presença do terminal), com índice por tipo e batimento.
  - vocabulário do grafo: `Sessao.motivo_parada` (`src/knowledge/schema.py:134-152`) ganha `aguarda_pesquisador`, `suspensa_sem_pesquisador` e `encerrada_pesquisador`.
  - aplicação no banco existente por `scripts/migrations/v18_7_001_session_process.sql` (idempotente, só `ADD COLUMN IF NOT EXISTS` e `CREATE ... IF NOT EXISTS`), inclusive no banco do Pi, quando o pesquisador autorizar.
- **Papel de banco:** nenhum nesta mudança. Dentro do PR, a presença é gravada pelo papel principal; `v18.7-persistent-human-gate`, mergeada junto, passa a gravá-la pelo papel do terminal e bloqueia a escrita pelo papel principal (ver design §8, risco 1).
- **Dependência nova de produção:** nenhuma (usa `psutil`, declarada por `v18.7-resource-monitor-config`).
- **Dependências novas de desenvolvimento** (`uv add --dev`): `pexpect` (REPL em pseudo-terminal nos testes de Ctrl+C e de redesenho da linha, reaproveitado por `v18.7-session-events-terminal`) e `pytest-timeout` (teto de 15 s por teste de integração). O relógio de teste é próprio (`FakeClock` injetado), sem `time-machine`.
- **`.env` do Pi:** nenhuma variável removida; variáveis novas opcionais com padrão (design §5), sem migração obrigatória.
- **Exclusão de código:** `_offer_suspension` (`src/autonomous_loop.py:526-547`) e a leitura de `stdin` em `src/orchestrator.py:1506`. Nenhum arquivo apagado.
