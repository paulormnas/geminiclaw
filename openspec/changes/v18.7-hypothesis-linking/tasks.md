# Tarefas: v18.7-hypothesis-linking

**Estado (2026-10-16):** implementada em `feat/v18.7-hypothesis-linking` (PR aberto); falta só a execução do teste de integração com AGE real no Pi (10.2) e a confirmação do Arquiteto (ADRs). As propostas das questões §16 do design foram adotadas e estão listadas abaixo, junto com as dúvidas de spec que surgiram.

## 0. Pré-requisitos
- [x] 0.1 `v18.7-graph-exploration-relations` mergeada (schema, leitura compatível, migração); os testes usam e estendem os construtores de `tests/support/exploration_graph.py` daquela mudança (design §5.1), sem criar outros para os mesmos nós.
- [x] 0.2 Questões do design §16 respondidas pelo pesquisador (ou propostas adotadas e listadas no PR); parecer do Analista de Segurança sobre o design §14, em especial a reversão de `Oportunidade`.
- [x] 0.3 Revisar esta mudança contra o código atual (`src/exploration.py`, `src/knowledge/hypotheses.py`, `src/knowledge/hypothesis_cycle.py`, `src/knowledge/ingestion.py`, `src/autonomous_loop.py`, `src/agents/validator_agent.py`) e contra o estado de `v18.7-exploration-limits` (mesmos `prepare_cycle` e `select`); registrar divergências no PR.
- [x] 0.4 Worktree `.worktrees/feat-v18.7-hypothesis-linking`.
- [x] 0.5 Conferir se `v18.7-persistent-human-gate` já foi mergeada: se sim, usar `ApprovalPort` e `PersistentGateApprover` de `src/human_approval.py`; se não, criar `src/human_approval.py` com o `Protocol` exatamente como no design §2.4 daquela mudança e a implementação provisória `NoGateApprovalPort` (design §4.5).
- [x] 0.9 Divisão do módulo grande antes do comportamento novo (ADR 024 §5), só movendo código, com a suíte verde antes de seguir: `src/orchestration/exploration.py` e `src/orchestration/autonomous_loop.py`: extrair para módulo próprio o papel do experimento e a ligação a hipóteses. Os caminhos citados nesta mudança valem pela tabela de `v18.7-source-layout`.

## 1. Configuração e campos
- [x] 1.1 `LINKAGE_FEEDBACK_MAX_ITEMS` e `HYPOTHESIS_TEXT_NEGATION_PREFIXES` em `src/config.py` e `.env.example` (design §11).
- [x] 1.2 `AgentTask.papel`, `papel_decidido`, `papel_fonte`, `prepara_ids`, `hypothesis_origin`; mapeamento do plano em `src/orchestrator.py`; `SubtaskInput.papel` e `prepara_ids` (serialização estrita da fila).
- [x] 1.3 `papel` como campo opcional no formato do Validator (`SCHEMA_INSTRUCTION`) e no formato do plano (`PLAN_FORMAT_INSTRUCTION`), corrigindo as linhas que contradizem o código (`src/exploration.py:108-109`); registro de `papeis_declarados` no evento `plan_validation`.
- [x] 1.4 Testes: os quatro cenários do delta `pipeline-robustness` e "Plano sem papel não é reprovado".

## 2. Ordem no laço
- [x] 2.1 Poda de dependências da retomada e `validate_dag` antes de `prepare_cycle`; `validate_dag` das mantidas depois (design §1).
- [x] 2.2 Teste: "DAG inválido não chega à governança".

## 3. Papel do experimento
- [x] 3.1 `src/exploration_roles.py` com `classify_role` e o sinal de teste (design §2.2–§2.3), reaproveitando o parser de critérios e os aliases do revisor sem duplicá-los.
- [x] 3.2 Remover `_is_bound` e a retirada por `sem_hipotese`.
- [x] 3.3 Ingestão grava `Experimento.papel`; experimento `referencia` sem `TESTA`.
- [x] 3.4 Testes: os seis cenários de "Papel do experimento decidido por ordem fixa".

## 4. Ligações derivadas
- [x] 4.1 `served(task)` e `prepara_ids` em `prepare_cycle`; `PREPARA` na ingestão (design §3.1).
- [x] 4.2 `link_preparation` incremental pela fila do `FactIngestor`; evento `preparacao_sem_experimento`.
- [x] 4.3 `REFERENCIA_DE` na ingestão e evento `referencia_sem_metrica` (design §3.2).
- [x] 4.4 Testes: cenários de "Preparação ligada às hipóteses que serve" e "Referência do Problema registrada".

## 5. Hipótese do sistema
- [x] 5.1 `HypothesisBook.system_hypothesis`: abordagem canônica, M, chave, R fixada, enunciado, arestas, evento `hipotese_derivada` (design §4.1–§4.2).
- [x] 5.2 Deduplicação pela chave com a tabela do design §4.3.
- [x] 5.3 Campo livre `hypothesis` (design §9.3): sem hipótese provisória para `preparacao`/`referencia` e para `eda`/`synthesis` sem exploração.
- [x] 5.4 Testes: os oito cenários de "Hipótese do sistema para teste sem hipótese aceita".
- [x] 5.5 `enunciado_fonte` (`texto_livre` ou `modelo`) na nota de auditoria da criação, no evento `hipotese_derivada` e no item de aprovação; testes do requisito "Fonte do enunciado da hipótese do sistema registrada" (parecer de segurança, item 4).

## 6. Ciclo de vida, aprovação e derivação entre hipóteses
- [x] 6.1 `system_origin` no `ExplorationSession` e no checkpoint; abandono pelo sistema nos três casos (design §4.4), com aviso do laço quando o DAG marca `abandonada` por retentativas.
- [x] 6.2 Reabertura pela chave (design §4.5).
- [x] 6.3 `_reject` grava `abandonada_por = "pesquisador"`; recusas e alternativas descartadas pelo Researcher (decisão de não explorar o caminho) gravam `abandonada_por = "agente"` e não bloqueiam: a hipótese volta como `proposta` pela governança do modo (cenário "Hipótese abandonada pelo agente"); `resolve_ref`, `_record_hypothesis` e `ingestion.hipotese` passam a decidir pelo autor do abandono (leitura `abandoned_by`).
- [x] 6.4 Origem `sistema` no lote do `assisted` e no caminho autônomo (design §5.1).
- [x] 6.5 `derivada_de` aceita `Hipotese` do projeto e `ref` declarada antes no mesmo plano.
- [x] 6.6 Testes: cenários de "Ciclo de vida da hipótese do sistema", "Aprovação da hipótese do sistema por modo" e "Hipótese derivada de outra hipótese".
- [x] 6.7 Aprovação e reabertura no `assisted` pela `ApprovalPort` (pedido `aprovar_hipotese` no gate, `previously_approved` lido de `gate_requests`, nunca da trilha de auditoria); testes "Reabertura no assistido com aprovação no gate", "Reabertura no assistido sem aprovação no gate", "Interface provisória antes do gate" e "Aprovação pelo gate persistente" com `FakeGate` (parecer de segurança, itens 1 e 2).

## 7. Concluídas e transições
- [x] 7.1 `select` aceita `validada`/`refutada` (design §5.2).
- [x] 7.2 `sync_statuses` nos dois sentidos com auditoria e evento `hipotese_transicao` (design §5.3).
- [x] 7.3 Revisão dos efeitos: `Oportunidade` `concluida -> em_investigacao` (alteração de `OPPORTUNITY_ORCHESTRATOR_TRANSITIONS` só para este caminho), decisões reavaliadas, atalhos contestados (design §5.4).
- [x] 7.4 Testes: cenários de "Hipótese concluída recebe novos testes" e "Transições de status nos dois sentidos ao fim do ciclo"; teste de que o orquestrador continua sem poder aprovar ou rejeitar `Oportunidade`.
- [x] 7.5 Testes do requisito "Reversão de Oportunidade fora do alcance dos agentes": Curator, orquestrador sem `revert_on_reopen` e plano com o campo (parecer de segurança, item 3).

## 8. Retiradas, fila e retorno ao Researcher
- [x] 8.1 Motivos do design §6, renomeação de `hipotese_ja_concluida_ou_abandonada` e cascata por hipóteses servidas.
- [x] 8.2 Fila substituída no replanejamento (design §7).
- [x] 8.3 `linkage_feedback` e bloco `ligacoes_e_retiradas_do_ciclo_anterior` no `prompt_block` (design §8).
- [x] 8.4 Testes: cenários de "Só decisão humana ou integridade impede a execução", "Replanejamento substitui a fila" e "Retiradas e ligações voltam ao Researcher".

## 9. Revisão e eventos
- [x] 9.1 Remover `MOTIVO_SEM_HIPOTESE`; motivo `hipotese_do_sistema` (design §9.1); `hypothesis_origin` passado ao revisor.
- [x] 9.2 Campos novos do evento `hypothesis_cycle` e eventos do design §10.
- [x] 9.3 Atualizar os testes que esperam `sem_hipotese` e `hipotese_ja_concluida_ou_abandonada` (`tests/unit/hypothesis_loop/`, `tests/unit/test_hypothesis_closure.py`); `operation_metrics` e o benchmark continuam lendo os campos antigos até `v18.7-exploration-metrics`.
- [x] 9.4 Testes: os nove cenários de "Resultado negativo na revisão", "Dados de ligação por ciclo" e "Hipóteses do sistema visíveis ao Curator e ao Researcher".

## 10. Validação
- [x] 10.1 `uv run ruff check .` sem erros novos; `uv run pytest -m "unit or integration" -v` verde.
- [ ] 10.2 Teste de integração com AGE real: um ciclo com preparação, dois testes (um declarado, um do sistema) e uma referência, conferindo `PREPARA`, `TESTA`, `REFERENCIA_DE`, `origem = "sistema"` e o evento `hypothesis_cycle`.
- [x] 10.3 Teste de regressão com o plano de passos finos da bateria V18.6 (reconstruído como JSON nos dados de teste, com nomes genéricos): nenhuma retirada, todas as subtarefas no DAG executado.
- [x] 10.4 `tasks.md` com caixas e linha **Estado** atualizadas no PR.

## Decisões e dúvidas registradas na implementação (2026-10-16)

**Propostas do design §16 adotadas (tarefa 0.2; aguardam a confirmação do pesquisador):** (1) referência R `indisponivel` até o critério do `Problema` ganhar um baseline numérico (o código já lê `criterio_sucesso.baseline` quando existir); (2) teste sem `approach`: `Abordagem` `tipo = "outro"` com o nome da subtarefa e aviso `abordagem_nao_declarada`; (3) sem métrica M resolvida a subtarefa segue como `preparacao` do `Problema`, com aviso `sem_metrica`; (4) o `papel` declarado vence o `task_type`; (5) hipótese declarada semelhante a uma do sistema: a deduplicação por similaridade continua só entre declaradas (a chave estruturada cobre as do sistema), sem `DERIVADA_DE` automático; (6) teste que depende de teste retirado sai com `depende_de_subtarefa_retirada`; (7) só a visibilidade da hipótese do sistema para o Researcher e o Curator, sem tipo novo de sugestão.

**Dúvidas de spec (decidido o mínimo, a confirmar):**
- **Caminho de `ApprovalPort`:** o design cita `src/human_approval.py`, mas a raiz de `src/` só pode ter `config.py`, `db.py` e `logger.py` (ADR 024 §1; `tests/unit/structure`), e o pacote `gate` fica abaixo de `knowledge` na regra de camadas, então não pode importar `ApprovalItem`. O `Protocol`, o `NoGateApprovalPort` e `as_approval_port` ficaram em `src/knowledge/approval_port.py`. A `v18.7-persistent-human-gate` decide onde mora o `PersistentGateApprover` (precisa de uma camada que enxergue `knowledge`).
- **`revert_on_reopen`:** em vez de um argumento novo em todas as implementações de `update_node`, a validação aceita `concluida -> em_investigacao` só para o `Actor` orquestrador com `role = "revert_on_reopen"` (`validation.REVERT_ON_REOPEN_ROLE`), construído apenas por `hypothesis_cycle.ORQUESTRADOR_REABERTURA` na revisão dos efeitos. Mesma garantia (nenhuma ferramenta de agente nem campo do plano o constrói), com menos superfície.
- **Proveniência da `Hipotese` do sistema:** `justificativa_criacao` e `nos_consultados` só existem para `Actor` de agente (o schema recusa no orquestrador); a justificativa "derivada pelo sistema da subtarefa X (motivo)" foi para o campo `justificativa`, e o motivo e a fonte do enunciado ficam na nota de auditoria da criação.
- **Retorno ao Researcher "referência sem métrica":** o evento `referencia_sem_metrica` sai na ingestão, mas a frase do §8 não chega ao replanejamento seguinte (a ingestão não devolve resultado ao laço); fica só no evento.
- **Ligação incremental na retomada:** a preparação concluída em sessão anterior é achada pelo `subtask_id` guardado no ciclo atual ou, sem ele, por `<sessão>:<subtarefa>`; sem `Experimento` o evento `preparacao_sem_experimento` registra.
- **`HYPOTHESES_PER_CYCLE`:** continua adiando hipóteses (inclusive as do sistema) até `v18.7-exploration-limits`; os testes que não tratam disso usam um teto alto.
- **Caminhos do tasks.md:** os caminhos antigos (`src/exploration.py` etc.) valem pela tabela de `v18.7-source-layout`; o papel do experimento ficou em `src/orchestration/exploration_roles.py`, a ligação em `exploration_linking.py`, o retorno ao Researcher em `exploration_feedback.py` e a hipótese do sistema em `src/knowledge/system_hypotheses.py`.
