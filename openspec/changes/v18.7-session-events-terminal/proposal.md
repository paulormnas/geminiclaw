# Proposta: Eventos de Progresso e Acompanhamento pelo Terminal

**ID:** `v18.7-session-events-terminal` · **Versão:** V18.7 · **Capacidade:** `session-continuity`, `researcher-consult`
**ADRs de origem:** [ADR 023](../../../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) §2 (eventos de progresso), §3 (terminal: conversar e acompanhar), §7 (filtros de exibição e egresso); casos de aceite 1, 4 e 10 (evento final, de suspensão e de falha); [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) (nada de dado bruto nos eventos e na consulta); [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) (contexto da consulta delimitado como dado)
**Depende de:** `v18.7-background-sessions` (processo da sessão, apelido, presença, REPL livre); `v18.7-persistent-human-gate` (pedido pendente que vira evento, caixa de entrada usada pelos comandos e pela orientação vinda da conversa) Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.

## Por quê

Com a sessão em processo próprio, o pesquisador precisa ver o progresso e agir sobre a pesquisa sem esperar o fim. A telemetria existente grava em lote (`_BUFFER_SIZE = 50`, `src/telemetry.py:41`): um "aguarda você" atrasaria ou se perderia numa queda (ADR 023, alternativa F rejeitada). Hoje o REPL não tem comando para listar, acompanhar, pausar ou parar uma pesquisa: `sessions` e `stop` tratam containers de sandbox (`src/cli.py:1042-1177`). E o pesquisador não consegue perguntar sobre o projeto enquanto a sessão roda.

## O que muda

- **Novo:** tabela `session_events`, com escrita imediata pelo processo da sessão, indexada por sessão e ordem; resumo curto filtrado (sem dado bruto); retenção configurável.
- **Novo:** o REPL lê eventos novos por consulta periódica e imprime uma linha por evento (`[apelido] ...`) sem apagar o que o pesquisador digita; nível de detalhe configurável.
- **Novo:** comandos `pesquisas`, `acompanhar <apelido>`, `pausar <apelido>`, `retomar <apelido>`, `parar <apelido>`, `cancelar <apelido> <subtarefa>`, `replanejar <apelido>`; os de ação vão à sessão pela caixa de entrada (`tipo='comando'`).
- **Novo:** `perguntar <texto>` (ou `? <texto>`, ou texto livre sem comando): o Researcher responde em modo consulta só leitura (transação somente leitura, papel `knowledge_reader` no grafo, Qdrant sem escrita); quando a resposta sugere uma orientação, o terminal propõe transformá-la em mensagem à sessão e o pesquisador confirma.
- **Novo:** motivos `pausada_pesquisador` (pausa ao fim da subtarefa) e `cancelada_pesquisador` (subtarefa cancelada antes de começar).
- **Modificado (decisão do pesquisador, 2026-10-15):** o texto livre no REPL deixa de iniciar pesquisa e passa a ser conversa com o Researcher (`perguntar`); iniciar uma pesquisa exige o comando explícito `nova <tarefa>`; com outra pesquisa em execução, o terminal confirma antes.
- **Fora do escopo:** painel de monitoramento (roadmap de frontend, que consumirá a mesma tabela); notificação do PostgreSQL (`LISTEN/NOTIFY`); várias pesquisas acompanhadas por vários terminais (ADR 023, Evolução prevista).

## Impacto

- **Código:** `src/session_events.py` (novo: gravação, leitura, filtros, retenção), `src/terminal/` (novo: impressão assíncrona, comandos, acompanhamento), `src/terminal_consult.py` (novo), `src/cli.py` (`interactive_mode`), `src/autonomous_loop.py` e `src/orchestrator.py` (pontos de emissão), `src/session_process.py` (consumo dos comandos da caixa), `src/knowledge/schema.py` (`Sessao.motivo_parada`), `scripts/init_db.sql`, `scripts/migrations/v18_7_003_session_events.sql` (novo).
- **Contratos:** tipos de evento e formato do resumo; comandos do REPL; formato da resposta da consulta (`orientacao_sugerida`).
- **Custo:** a consulta do terminal chama o modelo do papel `researcher` (com provedor simulado nos testes); consumo registrado em `token_usage` com o `execution_id` da sessão consultada e origem `consulta_terminal`, limitado por `TERMINAL_CONSULT_MAX_TOKENS` por pergunta, e contado no orçamento dessa sessão (tokens e custo; decisão do pesquisador, 2026-10-15).

## Aprovações necessárias

- **Alteração de schema (AGENTS.md §1.5):** tabela nova `session_events` com índice `(session_id, id)` e restrição única `(session_id, seq)`; aplicada no banco existente por `scripts/migrations/v18_7_003_session_events.sql`, inclusive no banco do Pi quando o pesquisador autorizar.
- **Vocabulário do grafo:** `Sessao.motivo_parada` ganha `pausada_pesquisador`; `cancelada_pesquisador` é motivo de retirada de subtarefa (sem esquema de grafo novo).
- **Exclusão de dados:** a retenção (`SESSION_EVENTS_RETENTION_DAYS`) apaga eventos de sessões terminadas há mais de N dias; o padrão é `0` (nunca apaga). Ativar a retenção é decisão do pesquisador.
- **Papel de banco:** nenhum novo (a consulta usa `knowledge_reader`, existente, e transação somente leitura no papel principal; os comandos usam `terminal_writer`, de `v18.7-persistent-human-gate`).
- **Dependência nova:** nenhuma (impressão assíncrona com `readline` da biblioteca padrão). Os testes usam `pexpect` e `pytest-timeout`, dependências de desenvolvimento acrescentadas por `v18.7-background-sessions`.
