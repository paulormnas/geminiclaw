# Tarefas: v18.7-hypothesis-linking

**Estado (2026-10-15):** não iniciada.

## 0. Pré-requisitos
- [ ] 0.1 `v18.7-graph-exploration-relations` mergeada (schema, leitura compatível, migração); os testes usam e estendem os construtores de `tests/support/exploration_graph.py` daquela mudança (design §5.1), sem criar outros para os mesmos nós.
- [ ] 0.2 Questões do design §16 respondidas pelo pesquisador (ou propostas adotadas e listadas no PR); parecer do Analista de Segurança sobre o design §14, em especial a reversão de `Oportunidade`.
- [ ] 0.3 Revisar esta mudança contra o código atual (`src/exploration.py`, `src/knowledge/hypotheses.py`, `src/knowledge/hypothesis_cycle.py`, `src/knowledge/ingestion.py`, `src/autonomous_loop.py`, `src/agents/validator_agent.py`) e contra o estado de `v18.7-exploration-limits` (mesmos `prepare_cycle` e `select`); registrar divergências no PR.
- [ ] 0.4 Worktree `.worktrees/feat-v18.7-hypothesis-linking`.
- [ ] 0.5 Conferir se `v18.7-persistent-human-gate` já foi mergeada: se sim, usar `ApprovalPort` e `PersistentGateApprover` de `src/human_approval.py`; se não, criar `src/human_approval.py` com o `Protocol` exatamente como no design §2.4 daquela mudança e a implementação provisória `NoGateApprovalPort` (design §4.5).

## 1. Configuração e campos
- [ ] 1.1 `LINKAGE_FEEDBACK_MAX_ITEMS` e `HYPOTHESIS_TEXT_NEGATION_PREFIXES` em `src/config.py` e `.env.example` (design §11).
- [ ] 1.2 `AgentTask.papel`, `papel_decidido`, `papel_fonte`, `prepara_ids`, `hypothesis_origin`; mapeamento do plano em `src/orchestrator.py`; `SubtaskInput.papel` e `prepara_ids` (serialização estrita da fila).
- [ ] 1.3 `papel` como campo opcional no formato do Validator (`SCHEMA_INSTRUCTION`) e no formato do plano (`PLAN_FORMAT_INSTRUCTION`), corrigindo as linhas que contradizem o código (`src/exploration.py:108-109`); registro de `papeis_declarados` no evento `plan_validation`.
- [ ] 1.4 Testes: os quatro cenários do delta `pipeline-robustness` e "Plano sem papel não é reprovado".

## 2. Ordem no laço
- [ ] 2.1 Poda de dependências da retomada e `validate_dag` antes de `prepare_cycle`; `validate_dag` das mantidas depois (design §1).
- [ ] 2.2 Teste: "DAG inválido não chega à governança".

## 3. Papel do experimento
- [ ] 3.1 `src/exploration_roles.py` com `classify_role` e o sinal de teste (design §2.2–§2.3), reaproveitando o parser de critérios e os aliases do revisor sem duplicá-los.
- [ ] 3.2 Remover `_is_bound` e a retirada por `sem_hipotese`.
- [ ] 3.3 Ingestão grava `Experimento.papel`; experimento `referencia` sem `TESTA`.
- [ ] 3.4 Testes: os seis cenários de "Papel do experimento decidido por ordem fixa".

## 4. Ligações derivadas
- [ ] 4.1 `served(task)` e `prepara_ids` em `prepare_cycle`; `PREPARA` na ingestão (design §3.1).
- [ ] 4.2 `link_preparation` incremental pela fila do `FactIngestor`; evento `preparacao_sem_experimento`.
- [ ] 4.3 `REFERENCIA_DE` na ingestão e evento `referencia_sem_metrica` (design §3.2).
- [ ] 4.4 Testes: cenários de "Preparação ligada às hipóteses que serve" e "Referência do Problema registrada".

## 5. Hipótese do sistema
- [ ] 5.1 `HypothesisBook.system_hypothesis`: abordagem canônica, M, chave, R fixada, enunciado, arestas, evento `hipotese_derivada` (design §4.1–§4.2).
- [ ] 5.2 Deduplicação pela chave com a tabela do design §4.3.
- [ ] 5.3 Campo livre `hypothesis` (design §9.3): sem hipótese provisória para `preparacao`/`referencia` e para `eda`/`synthesis` sem exploração.
- [ ] 5.4 Testes: os oito cenários de "Hipótese do sistema para teste sem hipótese aceita".
- [ ] 5.5 `enunciado_fonte` (`texto_livre` ou `modelo`) na nota de auditoria da criação, no evento `hipotese_derivada` e no item de aprovação; testes do requisito "Fonte do enunciado da hipótese do sistema registrada" (parecer de segurança, item 4).

## 6. Ciclo de vida, aprovação e derivação entre hipóteses
- [ ] 6.1 `system_origin` no `ExplorationSession` e no checkpoint; abandono pelo sistema nos três casos (design §4.4), com aviso do laço quando o DAG marca `abandonada` por retentativas.
- [ ] 6.2 Reabertura pela chave (design §4.5).
- [ ] 6.3 `_reject` grava `abandonada_por = "pesquisador"`; recusas e alternativas descartadas pelo Researcher gravam `abandonada_por = "agente"`; `resolve_ref`, `_record_hypothesis` e `ingestion.hipotese` passam a decidir pelo autor do abandono (leitura `abandoned_by`).
- [ ] 6.4 Origem `sistema` no lote do `assisted` e no caminho autônomo (design §5.1).
- [ ] 6.5 `derivada_de` aceita `Hipotese` do projeto e `ref` declarada antes no mesmo plano.
- [ ] 6.6 Testes: cenários de "Ciclo de vida da hipótese do sistema", "Aprovação da hipótese do sistema por modo" e "Hipótese derivada de outra hipótese".
- [ ] 6.7 Aprovação e reabertura no `assisted` pela `ApprovalPort` (pedido `aprovar_hipotese` no gate, `previously_approved` lido de `gate_requests`, nunca da trilha de auditoria); testes "Reabertura no assistido com aprovação no gate", "Reabertura no assistido sem aprovação no gate", "Interface provisória antes do gate" e "Aprovação pelo gate persistente" com `FakeGate` (parecer de segurança, itens 1 e 2).

## 7. Concluídas e transições
- [ ] 7.1 `select` aceita `validada`/`refutada` (design §5.2).
- [ ] 7.2 `sync_statuses` nos dois sentidos com auditoria e evento `hipotese_transicao` (design §5.3).
- [ ] 7.3 Revisão dos efeitos: `Oportunidade` `concluida -> em_investigacao` (alteração de `OPPORTUNITY_ORCHESTRATOR_TRANSITIONS` só para este caminho), decisões reavaliadas, atalhos contestados (design §5.4).
- [ ] 7.4 Testes: cenários de "Hipótese concluída recebe novos testes" e "Transições de status nos dois sentidos ao fim do ciclo"; teste de que o orquestrador continua sem poder aprovar ou rejeitar `Oportunidade`.
- [ ] 7.5 Testes do requisito "Reversão de Oportunidade fora do alcance dos agentes": Curator, orquestrador sem `revert_on_reopen` e plano com o campo (parecer de segurança, item 3).

## 8. Retiradas, fila e retorno ao Researcher
- [ ] 8.1 Motivos do design §6, renomeação de `hipotese_ja_concluida_ou_abandonada` e cascata por hipóteses servidas.
- [ ] 8.2 Fila substituída no replanejamento (design §7).
- [ ] 8.3 `linkage_feedback` e bloco `ligacoes_e_retiradas_do_ciclo_anterior` no `prompt_block` (design §8).
- [ ] 8.4 Testes: cenários de "Só decisão humana ou integridade impede a execução", "Replanejamento substitui a fila" e "Retiradas e ligações voltam ao Researcher".

## 9. Revisão e eventos
- [ ] 9.1 Remover `MOTIVO_SEM_HIPOTESE`; motivo `hipotese_do_sistema` (design §9.1); `hypothesis_origin` passado ao revisor.
- [ ] 9.2 Campos novos do evento `hypothesis_cycle` e eventos do design §10.
- [ ] 9.3 Atualizar os testes que esperam `sem_hipotese` e `hipotese_ja_concluida_ou_abandonada` (`tests/unit/hypothesis_loop/`, `tests/unit/test_hypothesis_closure.py`); `operation_metrics` e o benchmark continuam lendo os campos antigos até `v18.7-exploration-metrics`.
- [ ] 9.4 Testes: os nove cenários de "Resultado negativo na revisão", "Dados de ligação por ciclo" e "Hipóteses do sistema visíveis ao Curator e ao Researcher".

## 10. Validação
- [ ] 10.1 `uv run ruff check .` sem erros novos; `uv run pytest -m "unit or integration" -v` verde.
- [ ] 10.2 Teste de integração com AGE real: um ciclo com preparação, dois testes (um declarado, um do sistema) e uma referência, conferindo `PREPARA`, `TESTA`, `REFERENCIA_DE`, `origem = "sistema"` e o evento `hypothesis_cycle`.
- [ ] 10.3 Teste de regressão com o plano de passos finos da bateria V18.6 (reconstruído como JSON nos dados de teste, com nomes genéricos): nenhuma retirada, todas as subtarefas no DAG executado.
- [ ] 10.4 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
