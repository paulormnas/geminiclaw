# Tarefas: v18.7-persistent-human-gate

**Estado (2026-10-15):** não iniciada.

## 0. Pré-requisitos
- [ ] 0.1 `v18.7-background-sessions` pronta para merge; as duas são mergeadas juntas (PRs em sequência no mesmo dia, sem uso intermediário). Revisar esta mudança contra o código de `dev` (referências de linha de 2026-10-15).
- [ ] 0.2 Aprovação do pesquisador para o schema, o papel `terminal_writer` e o arquivo de credencial; respostas às Questões em aberto 1 a 5 do design (a 1 decidida em 2026-10-15: endurecimento antes de produção, sem prazo de versão; a 5 decidida em 2026-10-15: agrupamento aceito); parecer do Analista de Segurança (registrado no design §6).
- [ ] 0.9 Divisão do módulo grande antes do comportamento novo (ADR 024 §5), só movendo código, com a suíte verde antes de seguir: `src/gate/human_gate.py`: separar o gate persistente e os pedidos ao pesquisador em módulos próprios em `src/gate/`. Os caminhos citados nesta mudança valem pela tabela de `v18.7-source-layout`.

## 1. Schema, papel e credencial
- [ ] 1.1 `scripts/init_db.sql` e `scripts/migrations/v18_7_002_gate_inbox.sql` (idempotente): tabelas, índices e os três gatilhos do design §1.3.
- [ ] 1.2 `scripts/migrate_v18_7_terminal_role.py`: cria ou atualiza `terminal_writer`, grants do design §2.2, gera a senha e grava o arquivo `0600` com `O_EXCL`; nada de senha em log.
- [ ] 1.3 `src/config.py`: `load_terminal_database_url()` (permissão, ausência, recusa no processo da sessão), recusa de credencial no ambiente, variáveis do design §3 com validações (`SESSION_INBOX_MAX_CHARS <= 2000`, `GATE_ASK_WAIT_SECONDS` contra `AGENT_TIMEOUT_SECONDS`).
- [ ] 1.4 `src/session_launcher.py`: lista fixa no `filtered_env`; `src/terminal_db.py` (pool pequeno do papel do terminal); `src/terminal_presence.py` passa a gravar com o papel do terminal.
- [ ] 1.5 Testes de integração (PostgreSQL real, dois papéis): caso 13 (terminal resolve; papel principal não resolve, não grava caixa nem presença; pedido já resolvido recusado); migração aplicada duas vezes; script do papel não imprime a senha.
- [ ] 1.6 Testes de unidade: permissão `0644` recusada; credencial no ambiente recusada; ambiente do processo da sessão sem os nomes da lista; "Nome da lista no .env" (nomes retirados de novo depois de `load_dotenv()`).
- [ ] 1.7 Gatilhos com `session_user` e `current_user`, sem `SECURITY DEFINER`, `search_path` fixo; conferência em `pg_trigger` pelo terminal ao abrir e antes de `decidir` e `mensagem`. Testes de integração: "SET ROLE não contorna o gatilho", "Gatilho desligado".
- [ ] 1.8 Teste estático "Teste estático dos contornos" (lista do requisito "Garantias do gate escritas"); frase de garantia no texto de ajuda de `decidir` e no `README.md`, com o teste "Garantia documentada".

## 2. Gate persistente
- [ ] 2.1 `src/human_gate.py`: `PersistentGate` e `TerminalGate` (design §2.3); remover `HumanGate` em memória e `ask_in_terminal`; manter `Source` e `HUMAN_SOURCES`.
- [ ] 2.2 `src/research_consult/__init__.py`: `DECISOES_RESERVADAS` com os cinco tipos novos.
- [ ] 2.3 Migrar os usuários: `src/knowledge/hypotheses.py:623-632`, `src/knowledge/opportunities.py:187`, `src/project_session.py:214`, `src/unlimited_mode.py:129`, `src/cli_graph.py:270`, comandos de CLI (`resolvido_por='cli'`).
- [ ] 2.4 Modo sem limite: o terminal cria e resolve `ativar_modo_sem_limite` antes do lançamento; o arquivo de lançamento leva o id; o processo da sessão confere no banco.
- [ ] 2.5 Testes de unidade: pedido não duplicado; fonte não humana ignorada; decisão nova reservada no consultor; tipos de resposta validados por decisão.
- [ ] 2.6 `consume_authorized` e `GateAuthorizationRefused` (design §1.2); referências fixas por tipo (`aprovar_hipotese` = id da hipótese, `ativar_modo_sem_limite` = `launch_id`, `ativar_adendo_regimento` = sha256 do adendo). Testes de integração (PostgreSQL real): "Reuso de autorização recusado", "Autorização de outra sessão", "Modo sem limite preso ao lançamento", "Modo sem limite consumido uma vez".
- [ ] 2.6a `authorized_reference` só para `ativar_adendo_regimento` (leitura sem consumo, fora da cadeia da sessão), também no `FakeGate`; testes dos três cenários do requisito "Leitura sem consumo para o adendo do regimento".
- [ ] 2.7 `src/human_approval.py`: `ApprovalPort` e `PersistentGateApprover` (design §2.4); se `v18.7-hypothesis-linking` já criou o arquivo com `NoGateApprovalPort`, trocar o uso pela implementação do gate sem mudar o `Protocol`.
- [ ] 2.8 Ajuda de teste compartilhada `tests/support/fake_gate.py` (`FakeGate`: implementa `ApprovalPort` e a API do `PersistentGate` em memória, com respostas roteirizadas por id de pedido); reaproveitada por `v18.7-exploration-limits`, `v18.7-session-events-terminal`, `v18.7-agent-system-prompts` e, depois desta, `v18.7-hypothesis-linking`. Testes: "Só decisões respondidas", "Aprovação anterior vem do gate", "FakeGate com a mesma interface".

## 3. Leitores do terminal dentro da sessão
- [ ] 3.1 `src/knowledge/hypothesis_cycle.py` e `src/exploration.py`: aprovação em lote e confirmação de solução pelo gate; remover `terminal_approver` e `terminal_solution_confirmer`.
- [ ] 3.2 `src/orchestrator.py` `_ask_researcher_core`: pedido `responder_pergunta_agente`, espera limitada, pendência e entrega posterior no replanejamento.
- [ ] 3.3 `src/autonomous_loop.py`: hipóteses pendentes fora da fila; espera do `assisted` sem contar ocioso nem estagnação; consumo dos pedidos da cadeia na retomada.
- [ ] 3.4 Testes de integração (processo real, provedor gravado): aprovação, rejeição e edição de hipótese; encerrar e continuar ao atingir o objetivo; `ask_researcher` respondido a tempo e sem resposta; pedido sobrevive ao `SIGKILL`; caso 3 (resposta ao último pedido retoma; com dois pedidos, não retoma).
- [ ] 3.5 Teste: espera do `assisted` não altera `idle_cycles` nem o contador de estagnação.

## 4. Terminal e caixa de entrada
- [ ] 4.1 `src/cli.py`: comandos `pendentes`, `decidir <id>`, `mensagem <apelido> <texto>`; lembrete periódico; pedidos na lista de pesquisas não finalizadas.
- [ ] 4.2 `src/session_inbox.py`: gravação pelo terminal, limites, registro `Decisao` no grafo com vetorização pendente; leitura e consumo pela sessão; bloco `<mensagens_do_pesquisador>` no prompt `MODO: REPLAN` (`src/orchestrator.py:2115-2160`).
- [ ] 4.3 Testes de unidade: caso 7 com pedidos na lista; lembrete com relógio simulado; mensagem de 2001 caracteres recusada; limite de pendentes; mensagem não resolve pedido.
- [ ] 4.4 Teste de integração: mensagem entregue no replanejamento (prompt gravado pelo provedor de teste) e consumida; nó `Decisao` criado (com AGE disponível; pulado sem ele).

## 5. Compatibilidade
- [ ] 5.1 `.env.example`: variáveis do design §3 e instrução do script do papel; `README.md`: passo de migração do papel.
- [ ] 5.2 Teste estático da tarefa 1.8 rodando no conjunto `unit` (lista completa do requisito "Garantias do gate escritas", não só `SET ROLE` e `DISABLE TRIGGER`).
- [ ] 5.3 Métricas de operação: `intervencoes_humanas` contadas a partir do gate persistente; teste.
- [ ] 5.4 `PersistentGate.request` com `motivo` e `opcoes` validadas contra o catálogo do design §1.1 (os produtores de `decidir_continuidade` e `restringir_direcao` chegam com `v18.7-exploration-limits`, mergeada depois desta); testes com pedidos sintéticos de cada `motivo`.
- [ ] 5.5 Testes de integração (processo real, provedor gravado, pedidos sintéticos `decidir_continuidade` com `motivo="saturacao"`): "Parar por decisão do pesquisador" (sessão encerrada pelo terminal com `encerrada_pesquisador`, relatório, nenhum processo novo) e "Orientar" (texto em `<mensagens_do_pesquisador>` no prompt gravado da sessão retomada); "Resposta fora das opções do pedido" (unidade).

## 6. Validação final
- [ ] 6.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v` verde com PostgreSQL real.
- [ ] 6.2 Teste com `StdinForbiddenError` no laço completo de uma sessão `assisted` gravada: nenhuma leitura de `stdin`.
- [ ] 6.3 Revisão nos 7 eixos; PR para `dev` citando esta mudança; atualizar a linha **Estado** deste arquivo.
