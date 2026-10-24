# Proposta: Conversa com o Sistema no Projeto (consulta, pesquisa, eventos e gate)

**ID:** `v18.10-web-chat` · **Versão:** V18.10 · **Capacidade:** `web-interface`, `researcher-consult`
**ADRs de origem:** [ADR 027](../../../docs/decisions/adr_027_interface_web.md) §6.6; [ADR 023](../../../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) §1–§5 (processo da sessão, eventos, terminal, gate persistente, caixa de entrada); ADR 012 §8 (decisões reservadas); ADR 022 (contexto delimitado como dado)
**Depende de:** `v18.10-web-skeleton`; ADR 023 implementado (`v18.7-background-sessions`, `-persistent-human-gate`, `-session-events-terminal` mergeadas). Implementada **por último** na V18.10.

## Por quê

A conversa é o que o REPL faz hoje: o pesquisador pergunta ao Researcher (só leitura), inicia pesquisa, acompanha os eventos, manda orientação e comandos e responde às decisões reservadas. Na web, isso precisa respeitar as mesmas barreiras: só um humano resolve o gate, a sessão roda em processo próprio, a consulta não escreve.

## O que muda

- **Novo:** pacote `src/interaction/` (camada logo abaixo de `cli | web`): o que o REPL e a web fazem igual, extraído de `src/cli/` sem mudar comportamento: lançar pesquisa nova (`SessionStarter` sem a parte de impressão), consulta em processo filho (lado do terminal de `src/cli/terminal_consult.py`), envio de comandos e orientação, leitura de pedidos pendentes. `src/cli/` passa a chamar `src/interaction/`.
- **Novo:** rotas `src/web/routes/chat.py`: `POST /api/projects/{id}/chat/ask` (consulta), `POST /api/projects/{id}/research` (nova pesquisa), `GET /api/projects/{id}/research` (pesquisas do projeto), `GET /api/sessions/{sid}/events/stream` (SSE), `POST /api/sessions/{sid}/inbox` (orientação), `POST /api/sessions/{sid}/commands` (pausar, retomar, parar, cancelar, replanejar), `GET /api/gate/pending`, `POST /api/gate/{request_id}/answer`.
- **Novo:** `Source.WEB` em `src/gate/types.py`, incluído em `HUMAN_SOURCES`; `TerminalGate` instanciado pelo processo da web.
- **Novo:** página Conversa: linha do tempo única com mensagens do pesquisador, respostas do Researcher, eventos da sessão e cartões de decisão do gate.
- **Modificado:** `scripts/init_db.sql` e migração `scripts/migrations/v18_10_001_web_gate_source.sql`: `gate_requests.resolvido_por` aceita `web`; conforme a Questão 2, `terminal_presence.tipo` aceita `web`.
- **Fora do escopo:** confirmar o Problema e editar o rascunho pela web (continua na CLI nesta versão, Questão 3); modo sem limite pela web; vários usuários.

## Impacto

- **Código:** `src/interaction/` (novo, código movido), `src/cli/{session_start,terminal_consult,progress_view,gate_commands}.py` (passam a delegar), `src/gate/types.py`, `src/gate/persistent_gate.py` (`_HUMAN`), `src/web/`, `frontend/`, contrato do `import-linter`.
- **Contratos:** rotas acima; formato do evento SSE igual ao `Event` de `src/session/events.py` serializado.
- **Custo:** a consulta chama o modelo do Researcher, como no REPL (`TERMINAL_CONSULT_MAX_TOKENS`, consumo em `token_usage` com `task_name='consulta_terminal'`; a web usa `consulta_web`). Testes com provedor simulado.

## Aprovações necessárias

- **Alteração de schema relacional (AGENTS.md §1.5):** `CHECK` de `gate_requests.resolvido_por` com `web`; e, se a Questão 2 for decidida por presença própria, `CHECK` de `terminal_presence.tipo` com `web`. Migração idempotente que descobre o nome das restrições `CHECK` implícitas em `pg_constraint` antes de trocá-las, aplicada no banco do Mac; no Pi só quando o pesquisador autorizar (a trilha 1 usa o Pi). **Nenhuma alteração do esquema do grafo.**
- **Mudança de camadas:** pacote novo `src/interaction/` no contrato do `import-linter`.
