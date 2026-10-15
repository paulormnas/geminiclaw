# Design: Eventos de Progresso e Acompanhamento pelo Terminal

## 0. Estado atual (verificado na branch `docs/adr-021-022-exploracao-contrato`, 2026-10-15)

| Ponto | Onde | O que faz hoje |
|---|---|---|
| Telemetria | `src/telemetry.py:41`, `:517-545`, `:729-737` | eventos de agente e instantâneos de hardware em buffer, gravados a cada 50 registros ou no `flush` |
| Eventos de subtarefa | `src/autonomous_loop.py:1560-1570` | `record_agent_event(event_type="subtask_end")` na telemetria em lote |
| REPL | `src/cli.py:1249-1318` | `input()` bloqueante; comandos `sessions`, `stop`, `clear-context`, `resume`; nenhum acompanhamento |
| Saneamento de texto | `src/knowledge/graph_views.py:89` | `sanitize_text(value, limit)` |
| Filtros de egresso | `src/egress/filters.py` | máscaras de números, tracebacks e tabelas para texto que sai do nó |
| Consulta ao Researcher | `src/orchestrator.py:1679` (`_consult_researcher_core`); `openspec/specs/researcher-consult` | só dentro da sessão, para `ask_researcher` em `semi`/`auto`; ferramentas `quick_search` e `web_reader` |
| Grafo somente leitura | `src/knowledge/graph_store.py:554-601` | pool do papel `knowledge_reader` em transação `READ ONLY` |

## 1. Decisões

### 1.1 Consulta periódica, não `LISTEN/NOTIFY`

O terminal lê `SELECT ... FROM session_events WHERE id > %s ORDER BY id LIMIT 200` a cada `SESSION_EVENTS_POLL_SECONDS` (padrão 2). Motivos: a consulta usa o índice e custa pouco no volume de uma pesquisa (dezenas a centenas de eventos por hora); funciona igual depois de reconexão, sem perder nada (o `LISTEN` perde as notificações enquanto a conexão cai e exigiria a mesma consulta de recuperação); não prende uma conexão dedicada do pool; e é simples de testar com relógio simulado. Atraso de até 2 s é aceitável para "pequenas atualizações". Um painel futuro pode acrescentar `NOTIFY` sem mudar a tabela.

### 1.2 Escrita imediata e tolerante

O processo da sessão grava cada evento numa transação própria (`asyncio.to_thread`), com `seq` crescente por sessão mantido em memória e recuperado do banco na retomada (`max(seq)+1`). Falha de gravação: uma nova tentativa depois de 1 s; se falhar de novo, `WARNING` no log e a sessão segue (o evento é informativo; o pedido ao pesquisador é persistente no gate). O evento final (parada, suspensão) é gravado antes do status final da sessão, para que quem vê o estado final já tenha a linha.

### 1.3 Tipos de evento e resumo

| `tipo` | Emitido em | Resumo (modelo) |
|---|---|---|
| `sessao_iniciada` | registro do processo | `iniciada (modo auto, 2 papéis resolvidos)` |
| `plano_aprovado` | plano aprovado pelo Validator | `plano 2 aprovado: 5 subtarefas, 3 hipóteses` |
| `subtarefa_iniciada` / `subtarefa_concluida` / `subtarefa_reprovada` | despacho e revisão | `treinar_rf concluída (acuracia 0,967, validada)` |
| `hipotese_criada` / `hipotese_concluida` | grafo de hipóteses | `h3 refutada (veredito −0,41)` |
| `objetivo_atingido` | critério de solução | `objetivo atingido: acuracia 1,0 ≥ 0,95 (política: parar)` |
| `decisao_pendente` | pedido criado no gate | `aguarda você: aprovar a hipótese h4 (responda com 'decidir 12')` |
| `comando_recebido` | comando da caixa consumido | `pausa pedida: termina a subtarefa atual` |
| `parada` | fechamento com motivo | `encerrada: solucao_encontrada` |
| `suspensao` | `aguarda_pesquisador`, `suspensa_sem_pesquisador`, pausa | `suspensa: terminal fechado; retome ao abrir a aplicação` |
| `falha` | erro fatal na sessão; ou o terminal, ao marcar `interrompida` | `interrompida: processo parou; use 'retomar iris-01'` |

- O resumo é montado de campos estruturados (nomes de subtarefa e hipótese, ids, contagens, valor de métrica validada, motivo), cada campo textual por `sanitize_text(..., 64)`; nada de `stdout`, trecho de dado, caminho absoluto ou mensagem de exceção. Valores de métrica só entram se forem resultado validado pelo Validator (já registrados como fato). O resumo final passa pelo filtro de exibição (máscara de números fora dos campos permitidos) e tem no máximo `SESSION_EVENT_SUMMARY_MAX_CHARS` (300).
- `dados` (JSONB) leva só os campos estruturados (ids, contagens, motivo), para o painel futuro.
- O evento `falha` de uma sessão parada é gravado pelo terminal (com o papel principal, que pode inserir eventos), já que o processo da sessão não existe mais.

### 1.4 Impressão no REPL sem apagar a entrada

Sem dependência nova: uma thread lê os eventos e, para imprimir, escreve `\r\x1b[2K`, a linha do evento e `\n`, e redesenha o prompt com `readline.get_line_buffer()`; a escrita fica sob uma trava compartilhada com o prompt. Sem TTY (testes, `stdout` redirecionado), imprime só as linhas. Níveis (`TERMINAL_EVENT_DETAIL`): `silencioso` (decisão pendente, parada, suspensão, falha), `resumo` (padrão: os anteriores mais plano aprovado, hipótese concluída, objetivo atingido, comando recebido) e `detalhado` (todos). `acompanhar <apelido>` mostra os últimos `TERMINAL_FOLLOW_HISTORY` (20) eventos da sessão e todos os novos dela, em nível detalhado, até `voltar` ou Ctrl+C, que só sai do acompanhamento.

### 1.5 Comandos

| Comando | Efeito | Transporte |
|---|---|---|
| `pesquisas` | lista sessões não terminadas e as terminadas nas últimas 24 h: apelido, modo, estado, tempo, custo, último evento, pedidos pendentes | leitura |
| `acompanhar <apelido>` | visualização detalhada (§1.4) | leitura |
| `pausar <apelido>` | ao fim das subtarefas em curso: checkpoint, `status='suspended'`, `motivo_parada='pausada_pesquisador'`, processo encerra (código 4) | caixa, `comando` |
| `retomar <apelido>` | retomada pela folha da cadeia, com verificação de memória | processo novo (`v18.7-background-sessions`) |
| `parar <apelido>` | fechamento gracioso com checkpoint, como o 1º Ctrl+C (`interrompida_pesquisador`) | caixa, `comando` |
| `cancelar <apelido> <subtarefa>` | retira a subtarefa que ainda não começou, motivo `cancelada_pesquisador`; recusada se já começou ou terminou | caixa, `comando` |
| `replanejar <apelido>` | ao fim das subtarefas em curso, o Researcher replaneja (`MODO: REPLAN`) | caixa, `comando` |
| `perguntar <texto>` / `? <texto>` | consulta só leitura (§1.6) | processo filho criado pelo terminal, sem a credencial do terminal (parecer, item 1) |

- Os comandos de ação só valem para sessão com processo vivo; para outra, o terminal recusa com o estado atual e sugere `retomar`.
- O conteúdo do comando na caixa é JSON validado: `{"comando": "pausar" | "parar" | "cancelar" | "replanejar", "subtarefa"?: str}`; a sessão o lê a cada `SESSION_INBOX_POLL_SECONDS` e emite `comando_recebido`. Comando que a sessão não conhece é consumido e registrado como ignorado.
- `cancelar` e `replanejar` não são decisões reservadas (ADR 023 §3): não passam pelo gate.
- Texto livre no REPL continua iniciando uma pesquisa; com outra em execução, o terminal pergunta "Já há pesquisa em execução (iris-01). Iniciar outra? [s/N]" antes da verificação de memória.

### 1.6 Consulta só leitura ao Researcher

- **Processo:** a consulta roda num processo filho (`python -m src.terminal_consult --pergunta-fifo ...` ou equivalente), criado como o processo da sessão: `stdin` fechado, ambiente filtrado (`filtered_env` com a lista fixa de credenciais de `v18.7-persistent-human-gate`), retirada dos nomes negados depois de `load_dotenv()`. O terminal passa a pergunta e o apelido por arquivo `0600` ou pipe, recebe só o JSON da resposta e o valida como dado não confiável; a gravação da orientação confirmada fica no terminal. Assim o processo que tem a credencial de `terminal_writer` não executa agentes nem lê conteúdo web (regra de `v18.7-background-sessions` §1.1).
- **Contexto**, montado de forma determinística e delimitado como dado (ADR 022): projeto e Problema (resumo existente do vínculo de projeto), hipóteses com estado e veredito, plano do checkpoint, últimos 30 eventos, métricas de operação parciais, pedidos pendentes; no máximo `TERMINAL_CONSULT_CONTEXT_MAX_CHARS` (12000). Escolha da sessão: a indicada (`perguntar @iris-01 ...`) ou, se houver uma só em execução, ela; senão, o terminal pede o apelido.
- **Só leitura:** o grafo pelo pool do `knowledge_reader` (transação `READ ONLY`, existente); o banco relacional por conexão com `SET default_transaction_read_only = on`; o Qdrant por um invólucro que expõe só busca, `scroll`, `count` e `retrieve` e levanta erro em qualquer escrita. Ferramentas do modelo: as do consultor (`quick_search`, `web_reader`), com os limites `RESEARCHER_CONSULT_MAX_SEARCHES` e `RESEARCHER_CONSULT_MAX_READS`; nenhuma ferramenta de escrita, sandbox ou `ask_researcher`.
- **Egresso e localidade:** o contexto passa pelo mesmo `EgressGate` e pela mesma política de dados da sessão consultada (ADR 019); com o papel `researcher` resolvido para provedor não permitido pela localidade do projeto, a consulta é recusada com o motivo.
- **Resposta:** JSON `{"resposta": str, "orientacao_sugerida": str | null}`; a resposta é exibida após `sanitize_text`; com `orientacao_sugerida`, o terminal pergunta "Enviar como mensagem a iris-01? [s/N]"; "s" grava pela caixa de entrada (`v18.7-persistent-human-gate`), com os mesmos limites.
- **Custo:** consumo registrado em `token_usage` com o `execution_id` da sessão e origem `consulta_terminal`, visível nas métricas de operação; cada pergunta limitada por `TERMINAL_CONSULT_MAX_TOKENS` (20000). Não conta para os limites da sessão em execução (ver Questão 2).
- **Recursos:** embeddings, cliente do Qdrant e cliente LLM só são carregados na primeira `perguntar` (ADR 023 §7).

## 2. Contratos

### 2.1 DDL (esboço; `scripts/init_db.sql` e `scripts/migrations/v18_7_003_session_events.sql`)

```sql
CREATE TABLE IF NOT EXISTS session_events (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN (
                    'sessao_iniciada','plano_aprovado','subtarefa_iniciada','subtarefa_concluida',
                    'subtarefa_reprovada','hipotese_criada','hipotese_concluida','objetivo_atingido',
                    'decisao_pendente','comando_recebido','parada','suspensao','falha')),
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resumo      TEXT NOT NULL CHECK (char_length(resumo) <= 300),
    dados       JSONB NOT NULL DEFAULT '{}',
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_session_events_sessao ON session_events (session_id, id);
```

### 2.2 Interfaces

```python
# src/session_events.py
class EventWriter:   # no processo da sessão
    def emit(self, tipo: str, campos: dict[str, Any]) -> None: ...      # monta e filtra o resumo; grava já
class EventReader:   # no terminal
    def since(self, last_id: int, *, session_ids: Iterable[str] | None = None) -> list[Event]: ...
def purge(retention_days: int) -> int: ...                               # 0 = não apaga

# src/terminal_consult.py
async def ask(question: str, session: Session, *, provider_factory=...) -> ConsultAnswer: ...
```

### 2.3 Estados acrescentados à máquina de `v18.7-background-sessions`

```
active ──(pausar: fim das subtarefas em curso)──> suspended (pausada_pesquisador) ──(retomar)──> nova sessão
active ──(parar: fechamento gracioso)──> closed (interrompida_pesquisador)
```

## 3. Configuração (`src/config.py`)

| Variável | Padrão | Uso |
|---|---|---|
| `SESSION_EVENTS_POLL_SECONDS` | `2` | consulta de eventos novos pelo terminal |
| `SESSION_EVENT_SUMMARY_MAX_CHARS` | `300` | tamanho máximo do resumo (não pode passar de 300) |
| `SESSION_EVENTS_RETENTION_DAYS` | `0` | eventos de sessões terminadas há mais de N dias são apagados ao abrir o REPL; 0 = nunca |
| `TERMINAL_EVENT_DETAIL` | `resumo` | `silencioso`, `resumo` ou `detalhado`; valor inválido falha na inicialização |
| `TERMINAL_FOLLOW_HISTORY` | `20` | eventos anteriores mostrados ao acompanhar |
| `TERMINAL_CONSULT_ENABLED` | `true` | liga a consulta pelo terminal |
| `TERMINAL_CONSULT_CONTEXT_MAX_CHARS` | `12000` | contexto da consulta |
| `TERMINAL_CONSULT_MAX_TOKENS` | `20000` | teto de tokens por pergunta |

Escolha da retenção: 0 por padrão porque o volume é pequeno e o repositório segue "nada é apagado" para registros de pesquisa; quem quiser expurgo o liga explicitamente.

## 4. Mapa dos casos de aceite do ADR 023

| Caso | Requisito (spec `session-continuity` desta mudança) | Tipo |
|---|---|---|
| 1 (evento final) | "Eventos de progresso com escrita imediata" / evento final antes do status | integração |
| 4 (suspensão) | "Eventos de progresso com escrita imediata" / suspensão | integração |
| 10 (falha) | "Eventos de progresso com escrita imediata" / falha gravada pelo terminal | integração |

Os comandos e a consulta não têm caso numerado no ADR; cada cenário vira teste. Testes sem chamada paga: o processo da sessão roda com o provedor `gravado` de `v18.7-background-sessions`; a consulta usa provedor simulado chamado diretamente pela função `ask` nos testes de unidade (sem processo filho) e, no teste do processo filho, um módulo de teste que registra o provedor simulado antes de chamar a consulta, como `tests/support/session_process_recorded.py`.

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Médio | Pontos de emissão; consumo de comandos (pausa, parada, cancelamento, replanejamento). |
| Agentes & Prompts | Baixo | Prompt da consulta do terminal (só leitura) e campo `orientacao_sugerida`. |
| Sandboxes & Containers | Nenhum | |
| Persistência | Médio | Tabela `session_events`; motivos novos; consumo de `token_usage` da consulta. |
| Segurança | Médio | Filtros no resumo; consulta só leitura e pelo `EgressGate`; comandos só pelo papel do terminal. |
| Testes & Telemetria | Médio | Testes de atraso de evento, impressão sem apagar entrada, comandos com processo real. |

## 6. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.**

1. **Médio: a consulta executa um agente no processo que tem a credencial do terminal.** `perguntar` roda o Researcher com `quick_search` e `web_reader` (conteúdo web não confiável) no processo do terminal, que carrega a credencial de `terminal_writer`. Isso contraria a regra adotada em `v18.7-background-sessions` §1.1, segundo a qual esse processo não executa agentes. Requisito: a consulta roda num processo filho criado como o da sessão, com ambiente filtrado sem as credenciais do terminal e `stdin` fechado, e devolve o JSON da resposta. A gravação da orientação confirmada continua no terminal. Manter a consulta no processo do terminal só com aceite de risco explícito do pesquisador, registrado nesta seção.
2. **Médio: saneamento no ponto de exibição.** `session_events.resumo` é gravado pelo papel principal, a que o processo da sessão tem acesso. Antes de imprimir, o terminal aplica de novo `sanitize_text`, que remove ESC, C1 e marcas bidi (`src/knowledge/graph_views.py:89-108`), e o limite de 300 caracteres. O mesmo vale para a resposta da consulta e para a listagem `pesquisas`. Um teste grava diretamente na tabela uma sequência ANSI/OSC e confere que ela não chega ao terminal.
3. **Baixo: `dados` com chaves fechadas.** Cada `tipo` tem uma lista fechada de chaves permitidas (ids, contagens, códigos), validada na escrita; nada de texto livre.
4. **Baixo: custo da consulta.** Além do teto por pergunta, o consumo conta para o limite de custo da sessão consultada. Recomendo essa resposta para a Questão 2.
5. **Baixo: transação somente leitura no papel principal.** Para superusuário ela é só indicativa, já que o código pode reabrir a transação para escrita. É aceitável porque o modelo não tem ferramenta de SQL. A garantia efetiva é a ausência de ferramentas de escrita, coberta por teste.
6. **Informativo (pré-existente, fora do escopo):** o Qdrant está publicado em `0.0.0.0:6333/6334` sem autenticação (`docker-compose.yml`, com TODO de segurança). O invólucro somente leitura protege contra o código, não contra a rede local. Restringir a `127.0.0.1`, ou exigir chave, antes de uma bateria em rede compartilhada, numa mudança própria.

Pontos para o parecer:
- **Dados nos eventos:** resumo de campos estruturados, saneado e filtrado; teste com dado sensível simulado (valor de coluna, caminho absoluto, traceback) que não pode aparecer.
- **Consulta só leitura:** três barreiras (papel `knowledge_reader`, transação somente leitura, invólucro do Qdrant) e nenhuma ferramenta de escrita; o contexto enviado ao provedor passa pelo `EgressGate` da sessão consultada.
- **Injeção de prompt:** o contexto da consulta inclui texto vindo de agentes e do grafo; é delimitado como dado; a orientação sugerida só vira mensagem com confirmação do pesquisador e nunca resolve pedido reservado.
- **Comandos:** gravados só pelo papel do terminal (gatilho de `v18.7-persistent-human-gate`); a sessão valida o JSON e recusa comando desconhecido.
- **`stdin` e credencial:** inalterados (de `v18.7-background-sessions` e `v18.7-persistent-human-gate`).

## 7. Riscos e mitigações

1. **Linha impressa no meio da digitação em terminais sem `readline` completo** (libedit no macOS). Mitigação: teste com pseudo-terminal; se o redesenho falhar, a linha é impressa e o prompt é reescrito inteiro (a entrada não se perde, só é redesenhada).
2. **Eventos atrasados até 2 s.** Aceito; o pedido pendente é lembrado pelo gate independentemente.
3. **Custo da consulta fora do orçamento da sessão.** Limitado por pergunta; registrado nas métricas.
4. **Pausa ou parada com o laço travado:** o comando não é lido. A varredura de `v18.7-background-sessions` detecta o laço sem sinal e marca `interrompida`.

## 8. Questões em aberto

1. **Texto livre no REPL:** esta spec mantém o texto livre iniciando pesquisa e usa `perguntar`/`?` para conversar. A alternativa (texto livre conversa enquanto há pesquisa em execução, `nova <tarefa>` inicia outra) é mais fluida, mas muda o significado do texto conforme o estado. Qual o pesquisador prefere?
2. **Consumo da consulta** fica fora dos limites da sessão consultada (registrado com origem `consulta_terminal`). Deve contar para o limite de custo e tokens da sessão (ADR 021 §5.4)?
3. **`pausar` grava `suspended`**, estado legado retomável. Prefere um estado próprio (`pausada`)? Exigiria mais um valor de status no schema.
4. **Nomes dos comandos** em português (`pesquisas`, `acompanhar`, `pausar`, `retomar`, `parar`, `cancelar`, `replanejar`, `perguntar`, `decidir`, `pendentes`, `mensagem`) convivem com `sessions`, `stop` e `resume` em inglês. Manter `resume` como sinônimo de `retomar`?
