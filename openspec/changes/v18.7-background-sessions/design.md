# Design: Sessão de Pesquisa em Processo Próprio

## 0. Estado atual (verificado na branch `docs/adr-021-022-exploracao-contrato`, 2026-10-15)

| Ponto | Onde | O que faz hoje |
|---|---|---|
| REPL | `src/cli.py:1249-1318` | laço com `input()`; texto livre chama `await execute_prompt(...)` e só volta ao prompt quando a sessão termina; `resume <id>` também roda no mesmo processo |
| Execução | `src/cli.py:1189-1246` | vincula projeto (confirmação do Problema no terminal), chama `orchestrator.handle_request` e imprime o resultado |
| Comando direto | `src/cli.py:1729-1750` | `asyncio.run(execute_prompt(...))`; sai com 0 mesmo após parada por limite ou Ctrl+C gracioso; 1 se recusado antes de começar |
| Ctrl+C | `src/cli.py:1556-1590` | 1º pede fechamento com checkpoint (`interrompida_pesquisador`); 2º limpa sandboxes e sai com 130 |
| Retomada | `src/cli.py:706-800` | `prepare_resume(confirm=_ask_yes_no)`, routing, `handle_request(resume=...)`, no processo do terminal |
| Detecção de parada | `src/orchestrator.py:814-838`, `src/session.py:261-287` | só na inicialização da CLI; marca `interrompida` a sessão `active` com `updated_at` antigo; não confere PID |
| Batimento | `src/heartbeat.py:18-56`, `src/orchestrator.py:714-723` | thread própria grava `updated_at`; se recusado, chama `reassert_active` |
| Reafirmação | `src/session.py:349-361` | volta a `active` qualquer sessão `interrompida`, sem conferir `continued_by` |
| Leituras de `stdin` na sessão | `src/autonomous_loop.py:526-547` (`_offer_suspension`, com `asyncio.to_thread(input, ...)`); `src/orchestrator.py:1506` (`ask_researcher` no `assisted`); `src/knowledge/hypothesis_cycle.py:577-620` (`terminal_approver`); `src/exploration.py:127-162` (`terminal_solution_confirmer`) | as duas últimas já devolvem "sem resposta" sem TTY; as duas primeiras bloqueiam ou levantam `EOFError` com `stdin` fechado |
| Suspensão por pedido | `src/autonomous_loop.py:762-777`, `:1080-1086` | sessão `assisted` com hipóteses pendentes sem TTY vira `suspended` com `motivo_parada="interrompida"` |
| Status | `src/session.py:61`, `:176`; `src/orchestrator.py:1146-1286` | `active`, `closed`, `suspended`, `interrompida`, `success`, `failed` (coluna `TEXT` livre, `scripts/init_db.sql:9-16`) |
| Estados retomáveis | `src/continuity.py:64-71`, `:1110` | `MOTIVOS_RETOMAVEIS`; status `suspended` e `interrompida` |
| Benchmark | `scripts/benchmark/run_benchmark.py:413-436`, `:302` | `Popen([python, "main.py", "--mode", "auto", ...])`, espera com `communicate(timeout)`; no tempo limite, `proc.kill()` só no processo filho direto; qualquer código diferente de 0 é anomalia |
| Comandos `sessions`/`stop` | `src/cli.py:1042-1177` | listam e param containers de sandbox, não sessões |

## 1. Decisões

### 1.1 Um caminho só: toda sessão roda no processo da sessão

O REPL e o comando direto criam o processo da sessão do mesmo jeito; a diferença é só se o terminal espera por ele. Rodar o comando direto em primeiro plano dentro do processo do terminal (como hoje) deixaria dois caminhos a manter e faria o processo que carrega a credencial do terminal (`v18.7-persistent-human-gate`) executar os agentes, o que o ADR 023 §4.3 proíbe. Assim, no comando direto em primeiro plano o "próprio comando é o terminal" (ADR 023 §1.2, item 4): ele cria o processo, registra presença, repassa as linhas e o código de saída do processo da sessão.

| | REPL | Comando direto (padrão) | Comando direto `--background` |
|---|---|---|---|
| Espera o processo | não | sim | não (imprime apelido e PID e sai com 0) |
| Grupo de processos | próprio (`start_new_session=True`) | o do terminal | próprio |
| `stdin` do processo | `DEVNULL` | `DEVNULL` | `DEVNULL` |
| `stdout`/`stderr` | `logs/sessions/<launch_id>.log` | herdados do terminal (o log do benchmark continua capturando tudo) | `logs/sessions/<launch_id>.log` |
| Ctrl+C | não chega ao processo | o terminal repassa `SIGINT` (1º: fechamento gracioso; 2º: imediato, como hoje) | não chega |
| Presença registrada | `tipo='repl'` | `tipo='direto'` | nenhuma (sessão segue sem terminal) |

`--background` com `--mode assisted` é recusado com mensagem ("o modo assisted precisa de um terminal presente; use o REPL"), porque a sessão se suspenderia na primeira verificação de presença.

### 1.2 Lançamento

O terminal faz, nesta ordem, tudo o que exige confirmação antes de a pesquisa começar (ADR 023 §1): carregar e confirmar `input_context/`, vincular o projeto e confirmar o Problema (`ProjectBinder`), confirmar o modo sem limite (`resolve_unlimited_budget`) e, na retomada, a confirmação de `prepare_resume` para sessão resolvida. Depois verifica a memória (§1.3) e grava o **arquivo de lançamento** `outputs/.launch/<launch_id>.json`, modo `0600`, que o processo da sessão lê e apaga ao iniciar:

```json
{
  "versao_lancamento": 1,
  "launch_id": "uuid4",
  "tipo": "nova | retomada",
  "prompt": "…",
  "modo": "assisted | semi | auto",
  "orcamento": {"…": "…"},
  "ilimitado": false,
  "projeto": {"project_id": "…", "project_context": "…"} ,
  "project_mode": null,
  "contexto": {"dir": "input_context", "digest": "sha256 do bundle confirmado"},
  "model_pin": null,
  "retomada": {"session_id": "…", "confirmado_resolvida": false},
  "terminal_id": "uuid4 | null",
  "primeiro_plano": true
}
```

- O prompt não vai na linha de comando (ficaria visível em `ps`); o processo recebe só `--launch <caminho>`.
- O processo recarrega `input_context/` e recusa o lançamento se o `digest` divergir do confirmado (o pesquisador confirmou outro conteúdo).
- O processo resolve o roteamento de modelos com os mesmos pins (o health check é do processo que vai chamar os provedores).
- O terminal espera até `SESSION_LAUNCH_TIMEOUT_SECONDS` pela linha da sessão com `payload.launch_id` e `pid` gravados; se o processo terminar antes, mostra o código de saída e o fim do log.
- Até `v18.7-persistent-human-gate`, `ilimitado` é aceito do arquivo; aquela mudança o substitui pelo id de um pedido `ativar_modo_sem_limite` resolvido pelo terminal, conferido no banco.

### 1.3 Verificação de memória ao iniciar ou retomar

`HealthMonitor().get_memory_usage()` (de `v18.7-resource-monitor-config`):

- **REPL, abaixo de `MIN_AVAILABLE_MEMORY_MB`:** mostra a memória disponível e as pesquisas em execução (apelido, modo, estado, PID vivo, tempo), pergunta "Iniciar mesmo assim? [s/N]"; "não" desiste sem criar nada.
- **REPL, memória desconhecida:** mesmo aviso ("memória disponível desconhecida") e mesma pergunta.
- **Comando direto, abaixo do mínimo ou desconhecida:** falha antes de criar o processo, com mensagem que cita os valores e `MIN_AVAILABLE_MEMORY_MB`, código de saída 5. Fail-fast: não há ninguém para decidir (ADR 023 §1).
- Não há fila nem número fixo de sessões simultâneas.

### 1.4 Códigos de saída do comando direto (`src/exit_codes.py`)

Contrato fixo (não configurável: scripts e o benchmark dependem dele). A classe vem do `motivo_parada` gravado na sessão.

| Código | Classe | Motivos |
|---|---|---|
| 0 | parada de pesquisa | `solucao_encontrada`, `sem_caminhos_promissores`, `hipoteses_nao_testadas`, `saturacao` (de `v18.7-exploration-limits`) |
| 1 | erro ou recusa | `erro`; sessão recusada antes de começar; motivo desconhecido (falha fechada) |
| 2 | modo sem limite não confirmado | (já existe, `src/cli.py:1665`) |
| 3 | limite | todo `limite_*` (`limite_tokens`, `limite_tempo`, `limite_retentativas`, `limite_conexao`, `limite_egresso`; `limite_cota_provedor` de `v18.7-benchmark-fixes`; `limite_custo` de `v18.7-exploration-limits`; `limite_ciclos` e `limite_execucoes` de sessões antigas), `versao_modelo`, `planos_rejeitados` |
| 4 | aguarda o pesquisador | `aguarda_pesquisador`, `suspensa_sem_pesquisador`, `pausada_pesquisador` (de `v18.7-session-events-terminal`) |
| 5 | memória insuficiente | verificação do §1.3 |
| 6 | sessão perdida | a sessão foi continuada por outra (§1.8) |
| 130 | interrupção pelo pesquisador | `interrompida_pesquisador` (Ctrl+C), `interrompida` (marcada pelo terminal; o processo já não existe), `encerrada_pesquisador` (gravado pelo terminal com a sessão parada; não há processo para sair, o código só existe para o teste de cobertura) |

`exit_code_for(motivo)` é testado contra todos os valores de `Sessao.motivo_parada` (`src/knowledge/schema.py`): um motivo novo sem classe faz o teste falhar. Esta tabela é a única fonte dos códigos de saída da V18.7; cada mudança que acrescenta um motivo acrescenta a linha aqui no próprio PR. `planos_rejeitados` e `versao_modelo` ficam em "limite" porque a sessão parou sem chegar a um critério de pesquisa e a retomada de `planos_rejeitados` pede confirmação (`src/continuity.py:1118`). O código de saída e a classe do benchmark (`stop_class`, requisito "Classificação dos motivos de parada") são eixos diferentes: o benchmark continua classificando `planos_rejeitados` e `versao_modelo` como `criterio_pesquisa` (`scripts/benchmark/run_benchmark.py:270-289`), e a anomalia por código divergente (§1.11) compara o código com `exit_code_for`, não com `stop_class`.

**Dono de cada motivo de parada novo da V18.7** (valor no enum de `Sessao.motivo_parada`, `describe_stop_reason`, retomada e `stop_class`):

| Motivo | Dono | Retomada | `stop_class` |
|---|---|---|---|
| `limite_cota_provedor` | `v18.7-benchmark-fixes` | sem confirmação | `limite` |
| `limite_custo` | `v18.7-exploration-limits` | sem confirmação | `limite` |
| `saturacao` | `v18.7-exploration-limits` | com confirmação | `criterio_pesquisa` |
| `aguarda_pesquisador` | esta mudança | sem confirmação | `interrupcao` |
| `suspensa_sem_pesquisador` | esta mudança | sem confirmação | `interrupcao` |
| `encerrada_pesquisador` | esta mudança | com confirmação | `interrupcao` |
| `pausada_pesquisador` | `v18.7-session-events-terminal` | sem confirmação | `interrupcao` |

Precedência quando há mais de um limite no mesmo ponto de verificação (`LimitStatus.stop_reason`): tokens, tempo, custo, egresso, `limite_cota_provedor`, conexão, parada pendente (texto de `v18.7-benchmark-fixes`, com `limite_custo` inserido por `v18.7-exploration-limits`). Os motivos desta mudança não competem com os limites: são gravados só quando o laço não tem mais trabalho (`aguarda_pesquisador`) ou pela ausência do terminal (`suspensa_sem_pesquisador`); um limite atingido no mesmo ponto prevalece.

### 1.5 Fim da sessão conforme o modo

- **`semi` e `auto`:** ao chegar a um motivo de parada, a sessão grava motivo, relatório e checkpoint (fechamento atual) e o processo sai com o código do §1.4. Quando o laço não tem mais nada executável e só restam pedidos ao pesquisador (hoje: hipóteses sem aprovação, `outcome.pending_approval` em `src/autonomous_loop.py:1082`; política `perguntar`, intervenções esgotadas e decisões reservadas quando `v18.7-exploration-limits` e `v18.7-persistent-human-gate` existirem), a sessão grava checkpoint, `status='aguarda_pesquisador'`, `motivo_parada='aguarda_pesquisador'` e o processo sai com 4. O processo nunca fica vivo esperando.
- **`assisted` com terminal presente:** espera como hoje; com o terminal ausente, §1.6.
- `aguarda_pesquisador`, `suspensa_sem_pesquisador` e `encerrada_pesquisador` entram nos estados conhecidos de `src/continuity.py`; os dois primeiros são retomáveis sem confirmação; `encerrada_pesquisador` pede confirmação, como `solucao_encontrada`.

### 1.6 Presença do terminal e suspensão do `assisted`

- O terminal (REPL e comando direto em primeiro plano) cria uma linha em `terminal_presence` ao abrir e a atualiza em thread própria a cada `TERMINAL_PRESENCE_HEARTBEAT_SECONDS` (10). Na saída normal grava `ended_at` e `end_reason='saida'`.
- A sessão `assisted` guarda o `terminal_id` de quem a iniciou ou retomou. A cada `SESSION_PRESENCE_CHECK_SECONDS` (15), ela lê a presença: `ended_at` preenchido ou `heartbeat_at` mais antigo que `TERMINAL_PRESENCE_STALE_SECONDS` (60) significa ausência.
- Na ausência: a sessão para de despachar subtarefas novas, deixa as em curso terminarem (sem cancelar; o tempo limite do agente continua valendo), grava checkpoint com plano, hipóteses e seus estados, pedidos pendentes, último evento e custo até ali, grava `status='suspensa_sem_pesquisador'`, `motivo_parada='suspensa_sem_pesquisador'` e sai com 4. É um sinalizador do processo, como `request_interrupt` (`src/usage.py:45`), mas sem a carência que cancela subtarefas (`LIMIT_GRACE_SECONDS`).
- `semi` e `auto` não leem a presença.
- Escolha dos tempos: 10 s de batimento e 60 s de prazo toleram uma pausa curta do banco ou do laptop sem suspender por engano, e são pequenos frente à duração de uma subtarefa (minutos); a leitura a cada 15 s custa uma consulta indexada.

### 1.7 Ao abrir o REPL

1. **Um REPL por vez:** se há `terminal_presence` com `tipo='repl'`, `ended_at` nulo, batimento recente e, no mesmo host, PID vivo, o novo REPL é recusado com aviso (código 1). Linhas velhas recebem `ended_at` e `end_reason='obsoleta'`.
2. **Sessões paradas:** `SessionWatch.sweep()` marca `interrompida` (transição condicional, como `mark_stale`) a sessão `active` cujo processo, no mesmo host, não existe (ou existe com outro `create_time`, reuso de PID), cujo `updated_at` passou de `SESSION_STALE_SECONDS`, ou cujo `loop_beat_at` passou de `SESSION_LOOP_STALE_SECONDS`. Repete a cada `TERMINAL_STALE_CHECK_SECONDS` enquanto o REPL está aberto.
3. **Resumo desde a última vez:** sessões cujo `updated_at` é posterior ao fim da última presença de REPL: concluídas (motivo e apelido) e não finalizadas.
4. **Pergunta por pesquisa não finalizada** (`suspensa_sem_pesquisador`, `aguarda_pesquisador`, `interrompida`, inclusive `suspended` legado): mostra apelido, modo, motivo, último estado do checkpoint e, depois de `v18.7-persistent-human-gate`, os pedidos pendentes; pergunta "[r]etomar / [m]anter / [e]ncerrar". Retomar cria um processo novo pela retomada existente, com a verificação de memória do §1.3. Manter não muda nada. Encerrar grava `status='closed'`, `motivo_parada='encerrada_pesquisador'` e o relatório determinístico `relatorio_encerramento.md` (sem chamada a LLM), a partir do checkpoint e das métricas de operação já gravadas.
5. O REPL não carrega embeddings, cliente do Qdrant nem clientes de LLM ao abrir; só quando um comando os usa (ADR 023 §7).

### 1.8 Batimento com sinal do laço e sessão continuada

- O processo da sessão roda uma tarefa `asyncio` que atualiza um instante em memória a cada `SESSION_LOOP_TICK_SECONDS` (10). A thread do batimento grava `updated_at` e `loop_beat_at = último tique`. Assim o batimento continua independente do laço (um laço lento não apaga o batimento), mas quem confere vê há quanto tempo o laço não dá sinal.
- `SESSION_LOOP_STALE_SECONDS` (900) é três vezes `SESSION_STALE_SECONDS`: um laço sem sinal por 15 minutos é travamento, não lentidão (as chamadas bloqueantes já correm em `asyncio.to_thread`).
- `reassert_active` passa a exigir `NOT (payload ? 'continued_by')` e laço com sinal recente. Recusado porque a sessão foi continuada, a thread do batimento aciona o encerramento: o laço para de despachar e cancela o que roda, os containers de sandbox da sessão são removidos, nada é gravado na sessão e o processo sai com 6; se o laço não responder em `SESSION_LOST_EXIT_GRACE_SECONDS` (30), a thread encerra o processo com `os._exit(6)`.

### 1.9 Apelido

`alias = <slug do nome do projeto, [a-z0-9], até 12 caracteres>-<NN>`, com `NN` o menor número de dois dígitos sem uso no projeto; sem projeto, `sessao-NN`. A retomada herda o apelido da cadeia; `retomar <apelido>` resolve para a folha da cadeia (sessão sem `continued_by`). Índice não único, porque a cadeia compartilha o apelido.

### 1.10 Nenhuma leitura de `stdin` no processo da sessão

O processo é criado com `stdin=DEVNULL` e, no início de `src/session_process.py`, substitui `builtins.input` por uma função que levanta `StdinForbiddenError`. Ajustes nesta mudança: remover `_offer_suspension` (no `assisted` o limite operacional passa a só registrar aviso, como nos outros modos; a pausa pelo pesquisador vem em `v18.7-session-events-terminal`); `_ask_researcher_core` no `assisted` registra a interação como `pendente_pesquisador` e devolve ao agente a mensagem de pendência (o gate persistente a substitui na mudança seguinte); `terminal_approver` e `terminal_solution_confirmer` já devolvem "sem resposta" quando não há TTY.

### 1.11 Benchmark

O runner continua chamando `main.py --mode auto ... <tarefa>` em primeiro plano e esperando o processo (ADR 023 §1), uma sessão por vez. Muda: `Popen(..., start_new_session=True)` e, no tempo limite, `os.killpg` com `SIGTERM` e, depois de 10 s, `SIGKILL`, para que o processo da sessão não continue rodando depois que o runner passa à próxima combinação (e ao reset dos bancos). `anomalies()` passa a conferir a coerência entre código de saída e `motivo_parada` (§1.4): `exit 4` é anomalia "aguarda o pesquisador"; código divergente da classe do motivo é anomalia "código de saída divergente". O `ResourceSampler` já mede a árvore de processos (`root_pid`), que inclui o processo da sessão.

## 2. Contratos

### 2.1 DDL (esboço; `scripts/init_db.sql` e `scripts/migrations/v18_7_001_session_process.sql`)

```sql
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS pid INTEGER;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS host TEXT;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS process_started_at TIMESTAMPTZ;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS loop_beat_at TIMESTAMPTZ;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS terminal_id TEXT;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS alias TEXT;
CREATE INDEX IF NOT EXISTS idx_agent_sessions_alias ON agent_sessions (alias);

CREATE TABLE IF NOT EXISTS terminal_presence (
    terminal_id  TEXT PRIMARY KEY,
    tipo         TEXT NOT NULL CHECK (tipo IN ('repl', 'direto')),
    pid          INTEGER NOT NULL,
    host         TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    ended_at     TIMESTAMPTZ,
    end_reason   TEXT CHECK (end_reason IN ('saida', 'obsoleta'))
);
CREATE INDEX IF NOT EXISTS idx_terminal_presence_ativos ON terminal_presence (tipo, heartbeat_at) WHERE ended_at IS NULL;
```

Os valores de `status` continuam em `TEXT` livre, como hoje; a lista conhecida fica em constantes (`src/session.py`).

### 2.2 Máquina de estados da sessão mestra

```
                      ┌────────────── retomar (nova sessão, continued_by) ───────────────┐
                      │                                                                  │
 lançamento ──> active ──(motivo de parada)──────────────> closed / success / failed     │
                  │  │                                                                   │
                  │  ├─(semi/auto: só pedidos pendentes)──> aguarda_pesquisador ─────────┤
                  │  ├─(assisted: terminal saiu ou caiu)──> suspensa_sem_pesquisador ────┤
                  │  ├─(PID morto, batimento ou laço sem sinal)──> interrompida ─────────┤
                  │  └─(Ctrl+C: fechamento gracioso)──> closed (interrompida_pesquisador)┘
                  │
 interrompida ──(reassert: processo vivo, laço com sinal, sem continued_by)──> active
 aguarda_pesquisador | suspensa_sem_pesquisador | interrompida ──(encerrar no REPL)──> closed (encerrada_pesquisador)
```

`suspended` (legado de `src/autonomous_loop.py:762-777`) continua aceito na leitura e retomável; esta mudança não o grava mais na ausência do pesquisador.

### 2.3 Classes e funções novas

```python
# src/session_launcher.py
def check_memory(monitor: HealthMonitor, running: list[Session]) -> MemoryCheck: ...
def write_launch_file(spec: LaunchSpec, base_dir: Path) -> Path: ...          # 0600
def filtered_env(environ: Mapping[str, str]) -> dict[str, str]: ...          # remove SESSION_ENV_DENYLIST
def spawn_session(launch_path: Path, *, foreground: bool, log_dir: Path) -> subprocess.Popen: ...
async def wait_registered(launch_id: str, proc: Popen, timeout: float) -> Session: ...

# src/terminal_presence.py
class TerminalPresence:  # start(tipo) / stop() / is_present(terminal_id) -> bool

# src/session_watch.py
class SessionWatch:      # sweep() -> list[str]  (PID, create_time, updated_at, loop_beat_at)

# src/exit_codes.py
def exit_code_for(motivo_parada: str | None) -> int: ...
```

## 3. Configuração (`src/config.py`)

| Variável | Padrão | Uso |
|---|---|---|
| `SESSION_LAUNCH_TIMEOUT_SECONDS` | `60` | espera do terminal pelo registro do processo (cobre o health check dos provedores) |
| `SESSION_LOG_DIR` | `logs/sessions` | `stdout`/`stderr` do processo em segundo plano |
| `SESSION_LOOP_TICK_SECONDS` | `10` | tique do laço |
| `SESSION_LOOP_STALE_SECONDS` | `900` | laço sem sinal além disso: sessão parada |
| `TERMINAL_PRESENCE_HEARTBEAT_SECONDS` | `10` | batimento de presença |
| `TERMINAL_PRESENCE_STALE_SECONDS` | `60` | presença sem batimento além disso: terminal ausente |
| `SESSION_PRESENCE_CHECK_SECONDS` | `15` | intervalo com que a sessão `assisted` lê a presença |
| `TERMINAL_STALE_CHECK_SECONDS` | `60` | intervalo da varredura de sessões paradas no REPL |
| `SESSION_LOST_EXIT_GRACE_SECONDS` | `30` | espera do laço depois da recusa por sessão continuada, antes de `os._exit(6)` |
| `SESSION_ENV_DENYLIST` | vazio | nomes extras retirados do ambiente do processo da sessão (`v18.7-persistent-human-gate` acrescenta os do terminal à lista fixa) |
| `SESSION_STALE_SECONDS`, `SESSION_HEARTBEAT_SECONDS` | `300`, `30` | existentes (`src/config.py:232-233`) |
| `MIN_AVAILABLE_MEMORY_MB` | `512` | de `v18.7-resource-monitor-config` |

Validação na inicialização: `TERMINAL_PRESENCE_STALE_SECONDS > 2 * TERMINAL_PRESENCE_HEARTBEAT_SECONDS` e `SESSION_LOOP_STALE_SECONDS > SESSION_LOOP_TICK_SECONDS`; senão, falha com mensagem.

## 4. Mapa dos casos de aceite do ADR 023

| Caso | Requisito (spec `session-continuity` desta mudança, salvo indicação) | Tipo |
|---|---|---|
| 1 | "Fim da sessão autônoma com o processo" / cenário objetivo atingido | integração |
| 2 | "Fim da sessão autônoma com o processo" / cenário limite | integração |
| 3 | "Fim da sessão autônoma com o processo" / cenário só pedidos pendentes (a resposta que reabre está em `v18.7-persistent-human-gate`) | integração |
| 4 | "Suspensão do assisted sem o pesquisador" / saída normal | integração |
| 5 | "Suspensão do assisted sem o pesquisador" / queda do terminal | integração |
| 6 | "Um REPL por vez" | unidade |
| 7 | "Pesquisas não finalizadas ao abrir o REPL" | unidade (entrada simulada) |
| 8 | "Pesquisas não finalizadas ao abrir o REPL" / retomar | integração |
| 9 | "Pesquisas não finalizadas ao abrir o REPL" / manter e encerrar | unidade |
| 10 | "Detecção de sessão parada pelo terminal" / SIGKILL | integração |
| 11 | "Recusa de reativar sessão continuada" | unidade |
| 12 | "Comando direto em primeiro plano" e `benchmark` / "Comando direto em primeiro plano no runner" | integração |
| 14 | "Verificação de memória antes de iniciar ou retomar" / REPL | unidade (leituras simuladas) |
| 15 | "Verificação de memória antes de iniciar ou retomar" / comando direto | unidade |

**Como os testes de integração rodam sem chamada paga:** o processo da sessão real é iniciado por `python -m tests.support.session_process_recorded --launch <arquivo>`, módulo de teste que registra no `src/llm/registry` um provedor `gravado` (respostas lidas de `tests/fixtures/recorded/<cenário>.jsonl`, na ordem das chamadas, e falha explícita se faltar resposta) e depois chama `src.session_process.main`. Nenhum gancho de teste entra no código de produção. PostgreSQL real (pulado sem `DATABASE_URL` acessível, como `tests/integration/test_egress_log_integration.py:22-38`); sem AGE, os cenários usam `project_mode="sem_grafo"`; o sandbox só entra no caso 4 (subtarefa em curso) e pode ser trocado por um agente gravado que demora 3 s.

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Alto | Novo ponto de entrada do processo; sinalizador de suspensão; `aguarda_pesquisador`; tique do laço; encerramento por sessão perdida. |
| Agentes & Prompts | Baixo | `ask_researcher` no `assisted` deixa de bloquear no terminal (pendência até o gate). |
| Sandboxes & Containers | Baixo | Containers de sandbox da sessão perdida são removidos pelo processo; o benchmark encerra o grupo de processos. |
| Persistência | Alto | Seis colunas em `agent_sessions`, tabela `terminal_presence`, dois estados e três motivos novos. |
| Segurança | Médio | `stdin` fechado; arquivo de lançamento `0600`; ambiente filtrado; o processo segue com as barreiras de hoje (ADR 023 §7). |
| Testes & Telemetria | Alto | Testes de integração com processos separados; provedor gravado de teste; códigos de saída verificados. |

## 6. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.**

1. **Médio: limpeza de sandboxes sem escopo de sessão.** `cleanup_sandbox_containers` (`src/skills/code/sandbox.py:361-381`) remove todo container com `project=geminiclaw`. Com várias pesquisas simultâneas, o segundo Ctrl+C de um comando direto, ou o encerramento por sessão perdida (§1.8), derrubaria sandboxes de outras sessões. Requisito: a limpeza feita pelo processo da sessão e pelo Ctrl+C filtra pelo rótulo `session_id` da sessão e da sua cadeia. O container de preparação também recebe esse rótulo (hoje só o de execução o tem, `sandbox.py:717`). A limpeza global fica restrita a um comando explícito do REPL, com confirmação. Um teste usa containers com rótulos de duas sessões.
2. **Médio: o `.env` recarregado anula o ambiente filtrado.** `src/config.py:8` chama `load_dotenv()` na importação. O processo da sessão relê o `.env` e reintroduz qualquer nome de `SESSION_ENV_DENYLIST`, e depois também os da lista fixa de `v18.7-persistent-human-gate`, que esteja no arquivo. Requisito: no processo da sessão, os nomes negados saem de `os.environ` logo depois da carga do `.env` e antes de qualquer outro import do projeto, ou a carga os ignora. Um teste usa um `.env` temporário com um nome negado e confirma que o processo não o enxerga.
3. **Baixo: arquivo de lançamento.** O diretório `outputs/.launch` tem modo `0700` e o arquivo é criado com `O_EXCL|O_NOFOLLOW`. A leitura recusa link simbólico e dono diferente do usuário do processo. `launch_id` é validado como UUID antes de montar o caminho. Um teste de regressão confirma que o diretório nunca é montado no sandbox, que só monta `outputs/<session_id>`.
4. **Baixo: log do processo em segundo plano.** `logs/sessions/<launch_id>.log` pode conter dado de pesquisa impresso por agentes. Ele é criado com modo `0600`; `logs/` já está no `.gitignore`. Nunca é anexado a evento, prompt nem registro federado.
5. **Baixo: presença gravável pelo papel principal** (risco 1 do §7). É aceitável só se esta mudança e `v18.7-persistent-human-gate` forem mergeadas sem uso real nem bateria entre elas. Registrar a condição em `tasks.md`; resposta à Questão 1.
6. **Informativo: recursos no Pi.** A verificação de memória acontece só ao iniciar ou retomar. Durante a execução, a contenção continua com `wait_for_health` antes de cada agente (`MIN_AVAILABLE_MEMORY_MB`) e com `SANDBOX_MIN_FREE_BYTES` em cada execução. Com várias sessões, a concorrência efetiva é `MAX_CONCURRENT_AGENTS` multiplicado pelo número de processos; documentar isso no `.env.example`.

Pontos para o parecer:
- **`stdin` removido:** `stdin=DEVNULL` e `input` substituído no processo da sessão; nenhuma decisão pode ser lida de um terminal herdado.
- **Ambiente filtrado:** o processo é criado com `filtered_env`, que nesta mudança retira só `SESSION_ENV_DENYLIST`; a lista fixa de credenciais do terminal entra em `v18.7-persistent-human-gate`.
- **Arquivo de lançamento:** contém o prompt e o contexto do projeto (dado de pesquisa local, como `outputs/`); modo `0600`, criado com `O_EXCL`, apagado pelo processo ao ler; validado como dado não confiável (versão, tamanhos, `session_id` com `SESSION_ID_RE`, `src/continuity.py:73`).
- **Presença gravável pelo papel principal nesta mudança:** o processo da sessão poderia, por defeito de código, manter uma presença falsa e seguir no `assisted` sem o pesquisador. Fechado em `v18.7-persistent-human-gate` (só o papel do terminal grava a presença).
- **PID de outro host:** a conferência por PID só vale com `host` igual; em outro host, só batimento e laço.
- **Recursos:** um processo Python a mais por pesquisa; o REPL carrega embeddings e clientes LLM só sob demanda (ADR 023 §7).

## 7. Riscos e mitigações

1. **Janela entre esta mudança e o gate persistente:** no `assisted`, aprovações de hipótese, confirmação de solução e `ask_researcher` ficam pendentes sem forma de resposta, e a sessão se suspende. Mitigação: entregar esta mudança, `v18.7-persistent-human-gate` e `v18.7-session-events-terminal` antes de qualquer uso real e da bateria no Pi; ver Questão 1.
2. **Processo órfão do benchmark** no tempo limite. Mitigação: grupo de processos próprio e `killpg` (§1.11).
3. **Falso "parado" por laço lento.** Mitigação: prazo de 900 s, reafirmação quando o laço volta e a sessão não foi continuada (o débito 6.3 de `v18-research-continuity` sobre fatos de infraestrutura ingeridos por falso positivo continua).
4. **Reuso de PID.** Mitigação: conferir `process_started_at` contra `psutil.Process(pid).create_time()` com tolerância de 2 s.
5. **Suspensão demorada** se uma subtarefa em curso for longa. Aceito pelo ADR (não interromper no meio); o tempo limite do agente continua valendo.
6. **Dois REPL simultâneos por corrida na abertura.** Mitigação: a criação da presença usa `INSERT ... WHERE NOT EXISTS (presença repl viva)` numa transação com `LOCK TABLE terminal_presence IN SHARE ROW EXCLUSIVE MODE`.

## 8. Questões em aberto

1. **Entrega conjunta.** A janela do risco 1 some se esta mudança e `v18.7-persistent-human-gate` forem mergeadas juntas (PRs em sequência sem uso intermediário). O pesquisador prefere um PR por mudança, mergeados no mesmo dia, ou um PR único para as duas?
2. **Papel do terminal antes do gate.** O ADR 023 põe o papel de banco do terminal em `v18.7-persistent-human-gate`, mas a presença (§1.2, item 2: "gravado pelo papel de banco do terminal") nasce aqui. Alternativa: criar o papel nesta mudança. Mantido como no ADR; a mudança de ordem exigiria editar a tabela "Mudanças OpenSpec exigidas".
3. **Memória desconhecida no comando direto:** esta spec falha (fail-fast, código 5). Se o pesquisador preferir seguir com aviso quando a plataforma não informar memória, a regra muda aqui.
4. **Comandos `sessions` e `stop`** do REPL continuam tratando containers de sandbox (`src/cli.py:1042-1177`) e convivem com os comandos em português de `v18.7-session-events-terminal`. Renomeá-los (por exemplo, `sandboxes`) fica para decisão do pesquisador.
5. **Encerrar com Curator pendente:** o encerramento pelo REPL grava `curator_pendente` no checkpoint, mas não roda a consolidação (exigiria LLM). A consolidação acontece se a sessão for continuada depois; o pesquisador aceita?
