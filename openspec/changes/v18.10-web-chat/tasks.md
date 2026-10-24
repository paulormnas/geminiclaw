# Tarefas: v18.10-web-chat

**Estado (2026-10-24):** especificada; aguarda aprovação do pesquisador.

## 0. Pré-requisitos
- [ ] 0.1 `v18.10-web-skeleton` mergeada (e, de preferência, as três de leitura); respostas às Questões em aberto 1 a 4; aprovação do schema relacional.
- [ ] 0.2 Movimentação para `src/interaction/` (design §1), só movendo código, com `lint-imports` e a suíte verdes antes de seguir.
- [ ] 0.3 Reconciliar a spec consolidada `openspec/specs/researcher-consult/spec.md` com o código (papel `terminal_writer` e gatilhos não implementados por decisão de 2026-10-16): o Arquiteto propõe o texto, o pesquisador aprova.

## 1. Gate e presença
- [ ] 1.1 Resposta pela web com `Source.TERMINAL` e `canal: web` (preservado por `clean_answer`); reautenticação por senha nas `DECISOES_RESERVADAS` e troca do CSRF. Testes: resposta pela web, já resolvido, ação fora das opções, decisão reservada sem senha, teste estático do `canal`.
- [ ] 1.2 Presença `web` (se Questão 2 = a; migração `v18_10_001_web_presence.sql` idempotente, descobrindo o nome da restrição em `pg_constraint`, aprovada para o Mac; no Pi só com autorização) e leitura pelo `assisted`. Testes: web mantém, última aba fecha.

## 2. Rotas
- [ ] 2.1 Consulta (processo filho, tempo limite, `consulta_web`), nova pesquisa com os 409, pesquisas do projeto. Testes de unidade e de integração com provedor gravado e processo real.
- [ ] 2.2 SSE (`Last-Event-ID`, limite, ping), comandos e orientação, pedidos pendentes. Testes dos cenários; verificação de `sys.modules`.
- [ ] 2.3 Variáveis `WEB_CONSULT_TIMEOUT_SECONDS`, `WEB_MAX_EVENT_STREAMS`, `WEB_MAX_CONCURRENT_CONSULTS` e `WEB_PRESENCE_IDLE_MINUTES` em `src/config.py` e `.env.example`; regenerar o OpenAPI.

## 3. Frontend
- [ ] 3.1 Página da conversa, cartões de decisão, barra de pesquisas, diálogo de nova pesquisa, contador de pendentes. Testes com MSW e `EventSource` simulado.

## 4. Validação final
- [ ] 4.1 `ruff`, `lint-imports`, `pytest -m "unit or integration"`; `pnpm --dir frontend lint typecheck test build`.
- [ ] 4.2 Manual no Mac (banco `geminiclaw`, com confirmação do pesquisador antes de gastar tokens): pergunta, pesquisa `semi` curta, decisão respondida pela web, pausa e retomada.
- [ ] 4.3 Parecer do Analista de Segurança no PR; revisão nos 7 eixos; PR pelo GitHub App; linha **Estado**; o Arquiteto atualiza o ADR 027 e o 023.
