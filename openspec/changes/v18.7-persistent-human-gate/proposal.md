# Proposta: Gate Persistente de Decisões Reservadas e Caixa de Entrada da Sessão

**ID:** `v18.7-persistent-human-gate` · **Versão:** V18.7 · **Capacidade:** `researcher-consult`, `hypothesis-loop`
**ADRs de origem:** [ADR 023](../../../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) §4 (gate persistente, papel de banco do terminal, a sessão não para por um pedido), §5 (caixa de entrada), §8 (aprovações); casos de aceite 3 (resposta que reabre a sessão), 7 (pedidos pendentes na lista) e 13; [ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §8; [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §5.3, §5.5, §5.6 (pedidos ao pesquisador); [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) (mensagem entregue como dado)
**Depende de:** `v18.7-background-sessions` (processo da sessão separado do terminal, `terminal_presence`, `aguarda_pesquisador`, `encerrada_pesquisador`). As duas são mergeadas juntas (PRs em sequência no mesmo dia, sem uso intermediário em `dev` nem no Pi), para que a presença do terminal nunca fique gravável pelo papel principal fora do PR: o gatilho `terminal_presence_guard` desta mudança fecha o risco 1 daquela.
**É pré-requisito de:** `v18.7-session-events-terminal` (evento "decisão pendente" e comandos que usam a caixa de entrada), `v18.7-exploration-limits` (que produz os pedidos de objetivo atingido, estagnação, saturação, intervenções esgotadas, planos rejeitados e restrição de direção com o catálogo `decisao`/`motivo` desta mudança) e `v18.7-agent-system-prompts` (pedido de ativação do adendo). Esta mudança é a dona do catálogo do gate (`CHECK` de `decisao` e `DECISOES_RESERVADAS`).

## Por quê

O gate de decisões reservadas guarda os pedidos em memória (`src/human_gate.py:73-134`): um pedido some se o processo cair, e só o mesmo processo o responde. Vários pontos dentro da sessão leem o terminal: aprovação de hipóteses no `assisted` (`src/knowledge/hypothesis_cycle.py:577-620`), confirmação de solução (`src/exploration.py:127-162`), `ask_researcher` no `assisted` (`src/orchestrator.py:1468-1509`). Com a sessão em processo próprio sem `stdin` (`v18.7-background-sessions`), essas decisões precisam de um caminho persistente, que só o pesquisador, pelo terminal, consiga resolver. O pesquisador também precisa orientar uma sessão em execução sem pará-la.

## O que muda

- **Novo:** tabela `gate_requests`: pedidos com estado `pendente`, `autorizada` ou `negada`, que sobrevivem à queda da sessão e do terminal; `PersistentGate` substitui `HumanGate` em memória.
- **Novo:** papel de banco `terminal_writer`, único que resolve pedidos, grava a caixa de entrada e a presença do terminal; credencial num arquivo separado do `.env`, lido só pelo processo do terminal; gatilhos no banco que recusam essas escritas por qualquer outro papel.
- **Novo:** `DECISOES_RESERVADAS` ganha `aprovar_hipotese`, `decidir_objetivo_atingido`, `responder_pergunta_agente`, `decidir_continuidade` e `restringir_direcao` (ADR 023 §4.1).
- **Novo:** comandos do terminal `pendentes` e `decidir <id>`; o REPL lembra pedidos pendentes a cada `GATE_REMINDER_SECONDS`; responder o último pedido de uma sessão `aguarda_pesquisador` a retoma.
- **Novo:** caixa de entrada (`session_inbox`) e comando `mensagem <apelido> <texto>`: orientação do pesquisador, de tamanho limitado, registrada no grafo e entregue ao Researcher no próximo replanejamento, delimitada como dado.
- **Modificado:** aprovação em lote do `assisted`, confirmação de solução, `ask_researcher` no `assisted` e a ativação do modo sem limite passam pelo gate persistente; nenhum caminho do processo da sessão lê a entrada padrão.
- **Modificado:** enquanto há pedido pendente, a sessão segue com o que não depende dele; a espera não conta como ciclo ocioso nem estagnação.
- **Modificado:** comandos de CLI que hoje autorizam em memória (`vocab approve`, `opportunities approve`, `graph edit`, `project confirm`) registram e resolvem o pedido no gate persistente com o papel do terminal.
- **Removido:** `HumanGate` em memória, `ask_in_terminal`, `terminal_approver`, `terminal_solution_confirmer` e a leitura de `stdin` em `_ask_researcher_core`.
- **Fora do escopo:** quem produz os pedidos de estagnação, saturação e restrição de direção (`v18.7-exploration-limits`); evento "decisão pendente" na tabela de eventos e comandos de acompanhamento (`v18.7-session-events-terminal`); usuário de sistema operacional separado para o processo da sessão (endurecimento opcional, ADR 023 §4.3).

## Impacto

- **Código:** `src/human_gate.py` (reescrito), `src/research_consult/__init__.py` (`DECISOES_RESERVADAS`), `src/session_inbox.py` (novo), `src/terminal_db.py` (novo: conexão do papel do terminal), `src/config.py` (`load_terminal_database_url`), `src/session_launcher.py` (ambiente filtrado e pedido do modo sem limite), `src/terminal_presence.py` (troca de papel), `src/knowledge/hypothesis_cycle.py`, `src/exploration.py`, `src/orchestrator.py`, `src/autonomous_loop.py`, `src/knowledge/hypotheses.py:623-632`, `src/knowledge/opportunities.py:187`, `src/project_session.py:214`, `src/unlimited_mode.py:129`, `src/cli_graph.py:270`, `src/cli.py`, `src/orchestrator.py:2115-2160` (bloco de mensagens no prompt de replanejamento `MODO: REPLAN`), `scripts/init_db.sql`, `scripts/migrations/v18_7_002_gate_inbox.sql` (novo), `scripts/migrate_v18_7_terminal_role.py` (novo).
- **Contratos:** tabela e estados do gate; transição condicional; formato da resposta por tipo de decisão; bloco `<mensagens_do_pesquisador>` no contexto do Researcher.
- **Custo:** nenhuma chamada nova a LLM; a mensagem acrescenta até `SESSION_INBOX_MAX_CHARS` por mensagem ao contexto do replanejamento.

## Aprovações necessárias

- **Alteração de schema (AGENTS.md §1.5):**
  - tabela nova `gate_requests`, com índices e gatilho `gate_requests_guard`.
  - tabela nova `session_inbox`, com índice e gatilho `session_inbox_guard`.
  - gatilho novo `terminal_presence_guard` na tabela `terminal_presence` (criada por `v18.7-background-sessions`).
  - aplicação no banco existente por `scripts/migrations/v18_7_002_gate_inbox.sql`, inclusive no banco do Pi, quando o pesquisador autorizar.
- **Papel de banco novo:** `terminal_writer` (`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`), com `GRANT SELECT, INSERT, UPDATE` em `gate_requests`, `session_inbox` e `terminal_presence`, `GRANT USAGE` nas sequências dessas tabelas e `GRANT SELECT` em `agent_sessions`; criado por `scripts/migrate_v18_7_terminal_role.py`, que gera a senha aleatória e grava o arquivo de credencial. O papel principal mantém `SELECT` e as colunas permitidas (design §2.2).
- **Arquivo de credencial fora do repositório:** padrão `~/.config/<nome do aplicativo>/terminal_database_url`, modo `0600`, nunca versionado; o caminho é configurável por `TERMINAL_DATABASE_URL_FILE`.
- **`.env` do Pi:** nenhuma variável obrigatória; a migração do papel roda no Pi e grava o arquivo de credencial lá (só o nome do arquivo e do papel aparecem em PR e logs).
- **Dependência nova:** nenhuma.
- **Exclusão de código:** `HumanGate` em memória, `ask_in_terminal`, `terminal_approver`, `terminal_solution_confirmer`. Nenhum arquivo apagado.
