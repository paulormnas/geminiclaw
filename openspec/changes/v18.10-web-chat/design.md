# Design: v18.10-web-chat

## 1. Código comum ao REPL e à web (`src/interaction/`)

Movimentação antes do comportamento novo (ADR 024 §5), suíte verde antes de seguir:

| De | Para | O que |
|---|---|---|
| `src/cli/session_start.py` | `src/interaction/research.py` | preparar e lançar pesquisa nova e retomada (verificação de memória, orçamento, `launch` do processo da sessão); a impressão do banner e as perguntas ao terminal ficam em `src/cli/` |
| `src/cli/terminal_consult.py` (lado do terminal) | `src/interaction/consult.py` | criar o processo filho com `filtered_env` e `PGOPTIONS` somente leitura, passar a pergunta, validar o JSON da resposta; o ponto de entrada do filho continua um módulo executado por `python -m`, nunca importado pela web |
| `src/cli/progress_view.py` (envio de comandos) | `src/interaction/commands.py` | validar e gravar comandos e orientação pela `SessionInbox` |
| `src/cli/gate_commands.py` (resolver pedido) | `src/interaction/decisions.py` | listar pendentes por projeto ou sessão e responder por `TerminalGate.answer(source=...)` |

**Dependências que hoje prendem esses módulos a `src/cli/`** (revisão de consistência, 2026-10-24) e que se movem junto, para `src/interaction/` não importar `cli`:

| Dependência em `src/cli/` | Destino |
|---|---|
| `session_process.install_input_guard` (usada pelo filho da consulta) | `src/session/input_guard.py` (não depende do terminal) |
| `unlimited.resolve_unlimited_budget`, `_project_marked_unlimited` | `src/interaction/unlimited.py` (a pergunta ao terminal fica em `src/cli/`) |
| `context_commands.load_context_with_confirmation` | a carga vai para `src/interaction/context.py`; a confirmação fica em `src/cli/` |
| `sessions_view.label`, `resolve_target`, `_age` | `src/interaction/sessions.py` |

A lista exata sai de `uv run lint-imports` depois da movimentação; uma dependência nova que apareça volta ao Arquiteto antes de seguir.

**Importações tardias:** `src.agents.regimento` (usada por `session_start.py:22`) e qualquer módulo de `agents`, `agent_runtime` ou `orchestration` que não seja só de tipos passam a ser importados dentro da função que lança o processo da sessão, nunca no topo de `src/interaction/`. `orchestration.usage.UsageBudget` é dado puro e pode ficar no topo.

Camadas: `"cli | web"`, depois `"interaction"`, depois `"orchestration"`. Nenhuma função de `src/interaction/` lê a entrada padrão nem imprime: devolve dados e levanta erros tipados; o REPL e a web formatam.

**Garantia de execução (ADR 027 §1):** o processo da web nunca instancia agentes nem o orquestrador. Verificação em dois pontos: (a) na inicialização de `src.web` e (b) num teste de integração depois de exercitar todas as rotas, `sys.modules` do servidor não contém `src.agents.researcher`, `src.orchestration.orchestrator` nem `src.agent_runtime.runtime`; na inicialização, a presença de um deles faz o servidor recusar subir.

## 2. Contrato

| Rota | Corpo | Resposta |
|---|---|---|
| `POST /api/projects/{id}/chat/ask` | `{texto, session_id?}` (≤ 4 000 caracteres) | `{resposta, orientacao_sugerida?, tokens, sessao_consultada}`; 409 se a consulta estiver desligada (`TERMINAL_CONSULT_ENABLED=false`); 504 após `WEB_CONSULT_TIMEOUT_SECONDS` (padrão 180) |
| `POST /api/projects/{id}/research` | `{tarefa, modo: "assisted"\|"semi"\|"auto", confirmar_outra_em_execucao?: bool, confirmar_memoria_baixa?: bool}` | 202 `{session_id, alias}`; 409 `{erro:"outra_em_execucao", sessoes}` ou `{erro:"memoria_baixa", disponivel_mb, sessoes}` até o pesquisador confirmar; 409 `{erro:"problema_nao_confirmado"}` |
| `GET /api/projects/{id}/research` | — | pesquisas do projeto com estado, apelido, último evento, pedidos pendentes |
| `GET /api/sessions/{sid}/events/stream` | `Last-Event-ID` opcional | `text/event-stream`; `id: <seq>`, `event: <tipo>`, `data: <JSON do evento>`; histórico de `TERMINAL_FOLLOW_HISTORY` eventos ao conectar sem `Last-Event-ID`; comentário `: ping` a cada 15 s |
| `POST /api/sessions/{sid}/inbox` | `{texto}` | 201 `{id}`; 422 acima do limite da caixa (2 000) |
| `POST /api/sessions/{sid}/commands` | `{comando: "pausar"\|"retomar"\|"parar"\|"cancelar"\|"replanejar", subtarefa?}` | 202; 409 quando a sessão não tem processo vivo (exceto `retomar`) |
| `GET /api/gate/pending?projeto_id=` | — | `[{id, decisao, motivo, referencia, pergunta, opcoes, session_id, alias, criado_em}]` |
| `POST /api/gate/{request_id}/answer` | `{acao, texto?}` | 200 com o pedido resolvido; 409 `{erro:"ja_resolvido"}`; 422 resposta fora de `opcoes` |

- **SSE:** o servidor consulta `session_events` a cada `SESSION_EVENTS_POLL_SECONDS` (mesma variável do REPL) a partir do último `seq` enviado, pegando e devolvendo uma conexão do pool a cada consulta (nenhuma conexão fica presa à stream); a cada consulta revalida a sessão de login, e logout ou expiração encerram a stream; o gerador termina quando o cliente desconecta; um gerador por conexão; no máximo `WEB_MAX_EVENT_STREAMS` (padrão 8) conexões simultâneas (503 acima). O `EventSource` reconecta com `Last-Event-ID` e não perde nem duplica eventos.
- **Gate:** `TerminalGate.answer(..., source=Source.WEB)`; `resolvido_por='web'`; `_HUMAN` passa a ter `terminal`, `cli` e `web` (e o comentário de `src/gate/persistent_gate.py:52` é atualizado). A resposta passa por `clean_answer` (opções do pedido, limite de texto). Toda resposta exige sessão, CSRF e `Origin` (skeleton).
- **Reautenticação nas decisões reservadas** (revisão cética, 2026-10-24): como `web` passa a valer como origem humana em todo consumo do gate, uma sessão de login sequestrada (XSS com a página aberta) não pode bastar para autorizar `DECISOES_RESERVADAS`. A resposta a esses pedidos exige a senha no próprio corpo (`{acao, texto?, senha}`), verificada por argon2id e contada no bloqueio de tentativas; os demais tipos do gate (aprovar hipótese, continuar em estagnação etc.) exigem só sessão e CSRF. O token CSRF é trocado a cada resposta ao gate.
- **Pedidos sem sessão de pesquisa** (`session_id` nulo, criados pela CLI): a web não os lista nem responde; continuam só na CLI.
- **Banco:** hoje o gate não usa papel de banco próprio (decisão de 2026-10-16: só a regra na aplicação; o papel `terminal_writer` e os gatilhos ficaram para o endurecimento antes da produção). **Divergência encontrada na revisão:** a spec consolidada `openspec/specs/researcher-consult/spec.md` ("Somente o papel do terminal resolve pedidos") descreve o papel e os gatilhos como se existissem; o código não os tem. Esta mudança segue o código; a correção da spec consolidada é registrada à parte (tarefa 0.3). Quando o endurecimento vier, a web usa a mesma credencial do terminal, lida por função própria de `src/config.py` só no processo da web, e a ameaça de credencial num processo HTTP de vida longa entra no parecer daquela mudança.
- **Consulta não bloqueia o servidor:** o filho é criado com `asyncio.create_subprocess_exec` (hoje `src/cli/terminal_consult.py:110` usa `subprocess.run` síncrono, que travaria o laço do servidor, o SSE e o gate); no máximo `WEB_MAX_CONCURRENT_CONSULTS` (padrão 1) filhos ao mesmo tempo no processo inteiro (429 acima), o que também limita memória e custo de LLM.
- **Nova pesquisa:** exige Problema confirmado do projeto (a confirmação continua na CLI, Questão 3); com outra pesquisa viva ou memória abaixo de `MIN_AVAILABLE_MEMORY_MB`, a API devolve 409 com os dados e só lança com a confirmação correspondente — o mesmo diálogo do REPL (ADR 023 §1).
- **Texto livre:** sempre consulta, nunca inicia pesquisa (decisão de 2026-10-15 para o REPL); iniciar pesquisa é o botão "Nova pesquisa".

## 3. Presença e modo `assisted` (ver Questão 2)

O `assisted` se suspende quando nenhum terminal está presente (ADR 023 §1.2). Proposta: enquanto houver ao menos uma conexão SSE aberta para uma sessão do projeto **e** interação recente do pesquisador (tecla, clique ou foco na aba nos últimos `WEB_PRESENCE_IDLE_MINUTES`, padrão 30, informado pelo frontend), o processo da web mantém uma linha de presença `tipo='web'` com batimento; sem interação recente, sem conexão ou com a sessão de login encerrada, grava `ended_at`. Uma aba esquecida aberta não segura o `assisted`. O REPL e a web podem coexistir (a regra "um REPL por vez" continua só entre REPLs). A sessão `assisted` considera presente qualquer presença viva, de REPL ou web.

## 4. Frontend (Designer)

- `/p/:projetoId/conversa`: linha do tempo única, rolagem ancorada no fim, entrada de texto embaixo (Enter envia, Shift+Enter quebra linha).
- **Itens:** mensagem do pesquisador; resposta do Researcher (Markdown sem HTML, `react-markdown` de `v18.10-web-artifacts`) com o botão "Enviar como orientação à sessão" quando há `orientacao_sugerida`; eventos da sessão em linha compacta com o apelido (nível de detalhe como `TERMINAL_EVENT_DETAIL`, escolhido na página); cartões de decisão com a pergunta, as opções como botões e, quando o tipo pede, campo de texto.
- **Barra superior:** pesquisas do projeto com estado (`StatusBadge`), seletor de qual sessão acompanhar, botões Pausar, Parar (com confirmação), Replanejar; "Nova pesquisa" abre diálogo com tarefa e modo e trata as confirmações do 409.
- **Anúncios:** região `aria-live="polite"` para eventos e `assertive` para nova decisão pendente; contador de pendentes na barra lateral em todas as páginas.
- **Estados:** consulta em andamento (indicador, entrada desabilitada), erro de consulta, conexão de eventos perdida (aviso e reconexão automática), sem pesquisa no projeto.

## 5. Impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador & laço | Nenhum comportamento novo; só a origem `web` nos pedidos resolvidos e a presença `web` lida pelo `assisted`. |
| Agentes & prompts | Nenhum; a consulta é a mesma do REPL. |
| Sandboxes | Nenhum. |
| Persistência | `CHECK` ampliados em `gate_requests` e (Questão 2) `terminal_presence`; leitura de `session_events`; gravação na `session_inbox`. |
| Segurança | Gate respondido por HTTP: ponto principal (§6). |
| Testes & telemetria | Movimentação com suíte verde; testes de integração com processo de sessão real e provedor gravado (ajudas de `v18.7-background-sessions`). |

## 6. Segurança (parecer do Analista)

| Ameaça | Mitigação |
|---|---|
| S — página maliciosa responde o gate (CSRF) | Sessão, `X-CSRF-Token`, `Origin` e `SameSite=Strict` (skeleton); teste específico na rota do gate |
| S — agente ou documento "responde" o gate | A sessão não tem rota HTTP nem credencial da web; `Source.WEB` só é usada em `src/web/routes/chat.py` e `src/interaction/decisions.py`; teste estático junto dos existentes em `tests/unit/persistent_gate/` |
| T — resposta fora das opções | `clean_answer`; transição condicional `pendente → …` |
| R — de onde veio a decisão | `resolvido_por='web'` |
| I — eventos com dado bruto | Os eventos já passam pelos filtros (ADR 023 §2); a web exibe como texto |
| I — consulta escreve | Processo filho com `PGOPTIONS` somente leitura e invólucros (inalterado) |
| D — muitas conexões SSE ou consultas | `WEB_MAX_EVENT_STREAMS`; `WEB_MAX_CONCURRENT_CONSULTS` global; subprocesso assíncrono; tempo limite; conexão do pool por consulta |
| E — sessão de login sequestrada autoriza decisão reservada | Senha no corpo da resposta a `DECISOES_RESERVADAS`; CSRF trocado a cada resposta |
| E — injeção de prompt pela conversa | Texto do pesquisador delimitado como dado (ADR 022), como no REPL; a consulta só lê |

## 7. Questões em aberto

1. **Origem própria `web` no gate** (recomendado, exige o `CHECK` novo) ou reutilizar `terminal` (sem schema, perde o repúdio)?
2. **Presença:** (a) presença `tipo='web'` enquanto houver conexão de eventos, coexistindo com o REPL (recomendado; exige o `CHECK` novo); (b) a web conta como "o terminal" e é exclusiva com o REPL; (c) a web não mantém presença e o `assisted` só funciona pelo REPL.
3. **Confirmar o Problema pela web** (o Advogado do Valor recomenda incluir nesta mudança, porque sem isso uma pesquisa nova pela web volta à CLI justamente no primeiro passo) (decisão reservada `confirmar_problema`, com edição do rascunho): fica para uma mudança seguinte, ou entra nesta?
4. **Ativar modo sem limite pela web:** recomendação é não oferecer (continua só na CLI, com a confirmação atual).
