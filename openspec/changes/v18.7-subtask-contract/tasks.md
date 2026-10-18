# Tarefas: v18.7-subtask-contract

**Estado (2026-10-18):** em andamento. Seções 0 (#203) e 1 concluídas; achado das dependências decidido (design §14: mudança própria `v18.7-dependency-artifacts`, caminho `/deps_out/<projeto>/<task_name>`). Seções 2 a 7 não iniciadas.

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada pelo pesquisador, com as questões do design §11 decididas.
- [x] 0.2 Parecer do Analista de Segurança registrado no design §8.
- [x] 0.3 `v18.7-hypothesis-linking` mergeada (papel do experimento e hipótese do sistema); conferir no código os nomes reais dos campos usados nos itens 1 e 4. Se `v18.7-exploration-limits` já estiver mergeada (recomendado, mesma onda), rebase: o parecer tipado de revisão (design §6.3) preserva os campos `predicoes` e `viola_restricao` que aquela mudança acrescentou, e o item 6 usa o tipo do objetivo.
- [x] 0.4 Revisar a spec contra o código (`src/autonomous_loop.py`, `src/llm/agent_loop.py`, `src/agents/validator_agent.py`) e ajustar as referências de linha; criar o worktree `.worktrees/feat-v18.7-subtask-contract`.
- [x] 0.9 Substituída pela 2.0: o módulo do contrato mora em `src/agents/subtask_contract.py` (camadas, design §13), então a extração dos construtores existentes é feita ao criá-lo. Os caminhos citados nesta mudança valem pela tabela do design §13.

## 1. Configuração
- [x] 1.1 `SUBTASK_CONTRACT_ENABLED`, `CONTRACT_TASK_MAX_CHARS`, `CONTRACT_FIELD_MAX_CHARS`, `REVIEW_INTEGRITY_ALWAYS`, `REVIEW_SCRIPT_MAX_CHARS`, `REVIEW_OBSERVATIONS_MAX` e `PLAN_ARTIFACT_COLLISION_CHECK` em `src/config.py` e `.env.example` (design §9).

## 2. Contrato e construtores
- [ ] 2.0 Mover para `src/agents/subtask_contract.py`, sem mudar comportamento e com a suíte verde, os construtores de contexto do Researcher (`_run_planning_loop`) e do Validator do plano (ADR 024 §5).
- [ ] 2.1 `src/agents/subtask_contract.py`: `MetricKey`, `ProblemObjective`, `SubtaskContract` (com `sha256()` e `fragments()`), `INTEGRITY_RULES` e os quatro construtores (design §2).
- [ ] 2.2 Layout do bloco do design §3, com "não se aplica" para itens vazios e corte literal do item 5.
- [ ] 2.3 Derivação das chaves de métrica (split, vocabulário, termo novo) e dos consumidores pelo `depends_on` inverso.
- [ ] 2.4 Testes: cenários "Itens do contrato", "Preparação sem hipótese própria", "Métrica fora do vocabulário", "Tarefa original longa", "Ponto único de montagem"; teste de estabilidade do hash (mesmos campos, mesmo hash; ordem de chaves irrelevante).

## 3. Despacho, runtime e fixação
- [ ] 3.1 `AgentTask.contract`; `_dispatch_subtask` com `dataclasses.replace`.
- [ ] 3.2 Montagem do contrato no início de cada tentativa em `_execute_task_in_dag`, a partir do plano vigente.
- [ ] 3.3 `run_agent_loop(..., pinned_prefix=...)` e passagem pelo `AgentRuntime`; marca `_pinned` respeitada por `compress_messages`.
- [ ] 3.3a Conferência do teto `CONTRACT_FIELD_MAX_CHARS` antes de montar o contrato de cada tentativa; retirada com `campo_do_contrato_longo` em `retiradas_por_motivo` (design §8.1 item 9).
- [ ] 3.4 Testes, com o `FakeRecordingProvider` de `v18.7-benchmark-fixes` (grava `messages` e `system`): "Despacho", "Laço com várias voltas", "Compressão não remove o contrato", "Nova tentativa depois de replanejamento", "Contrato desligado", "Plano aceito com avisos e campo longo".

## 4. Egresso
- [ ] 4.1 Fonte `contrato:` delimitada no `EgressGate` com origem própria `planejador` (constantes em `src/egress/fragments.py`; nunca `instrucao` para texto do Researcher) e `PLANNER_TEXT_RULE` no `system` quando houver fragmento `planejador` (design §8.1 item 1); itens 3 e 8 com `ARTIFACT_NAMES_SOURCE`; limpeza de marcas e caracteres de controle nos campos do plano.
- [ ] 4.2 Registro de `limiar_mascarado` no evento `subtask_attempt` (regra provisória do design §11.1; reescrever o cenário antes de implementar se a decisão for a alternativa).
- [ ] 4.2a Script executado enviado ao revisor pelo `EgressGate` (origem e fonte `codigo`, `tainted = role_tainted("developer")`, política do destino do Validator) e registrado em `egress_log` (design §8.1 item 8).
- [ ] 4.3 Testes: "Critério com instrução embutida", "Rótulo de origem do texto do Researcher", "Researcher com dados brutos, Developer sem", "Researcher sem dados brutos", "Nome com dado", "Developer local, Validator de nuvem", "Developer e Validator sem restrição".

## 5. Revisão de subtarefa
- [ ] 5.1 `review_result` recebe o contrato; mensagem com contrato, regras de integridade, evidência, script executado e resposta (design §6.2).
- [ ] 5.2 Parecer tipado, guarda determinística e leitura do formato antigo (design §6.3); `ReviewResult.typed_issues`, `observations`, `contract_sha256`; evento `subtask_review` com `contrato_sha256` e `observacoes`.
- [ ] 5.3 Integridade sempre revisada (`REVIEW_INTEGRITY_ALWAYS`) e reprovação por métrica literal via `read_literal_findings`.
- [ ] 5.4 Tabela de chaves de métrica do design §5; desfecho `criterio_ambiguo`; `UsageTracker.refund_task_attempt`, no máximo uma devolução por `task_name` em cada sessão, com `devolucao_recusada` no evento (design §8.1 item 10); checkpoint `falhou` com `causa_falha = "ambigua"`.
- [ ] 5.5 Observações e casos `criterio_ambiguo` no `feedback` do replanejamento (design §6.4).
- [ ] 5.6 Testes: "Critério fraco vira observação", "Integridade reprova sempre", "Formato antigo do parecer", "Hash do contrato no parecer", "Só critérios de métrica, aprovados", "Integridade desligada", "Métrica literal", "Chave sem qualificador presente", "Ambiguidade", "Ambiguidade repetida", "Critério cita a chave qualificada", "Observação no replanejamento", "Artefato consumido no contrato"; atualizar os testes de `v18.6-review-evidence` do cenário "Grupo não nomeado" e rodar os demais cenários modificados sem mudança de resultado.

## 6. Validação do plano
- [ ] 6.1 `validate_plan` com `problem` (fragmento `contrato:objetivo`) e chamada atualizada na chamada de `validate_plan` em `src/orchestration/orchestrator.py`.
- [ ] 6.2 Colisão de artefatos (fecho de `depends_on`), aviso `artefato_atualizado`.
- [ ] 6.3 Teto dos campos do contrato na validação; padrão de nome de artefato no normalizador.
- [ ] 6.4 Regra `criterio_sem_chave` na instrução do Validator do plano.
- [ ] 6.5 Testes: "Validação do plano com o critério do Problema", "Colisão real", "Atualização intencional", "Critérios longos demais", "Nome de artefato com caminho relativo", "Instrução renderizada".

## 7. Validação
- [ ] 7.1 `uv run ruff check .` sem erros novos; `uv run pytest -m "unit or integration" -v` verde.
- [ ] 7.2 Reprocessar, sem LLM, os planos e os `metrics.json` da bateria V18.6 que ainda existirem e contar quantas reprovações por artefato ausente, chave de métrica e colisão as regras novas teriam evitado ou apontado antes da execução.
- [ ] 7.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR; confirmação com o Arquiteto para o status do ADR 022.
