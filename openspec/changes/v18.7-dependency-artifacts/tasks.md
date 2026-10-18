# Tarefas: v18.7-dependency-artifacts

**Estado (2026-10-18):** especificada; aguarda aprovação do pesquisador (questões do design §9).

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada pelo pesquisador, com as questões do design §9 decididas.
- [ ] 0.2 Parecer do Analista de Segurança registrado no design §7.2 (feito em 2026-10-18; conferir se a decisão do §9 o altera).
- [ ] 0.3 Revisar a spec contra o código (`sandbox.py`, `skill.py`, `inputs.py`, `agent_context.py`, `orchestrator.py`, `autonomous_loop.py`, `subtask_contract.py`, `provenance/records.py`) e ajustar as referências; criar o worktree.

## 1. Configuração
- [ ] 1.1 `DEPENDENCY_ARTIFACTS_ENABLED`, `DEPENDENCY_ARTIFACTS_SCOPE`, `DEPENDENCY_ARTIFACTS_MAX_MOUNTS` e `DEPENDENCY_ARTIFACTS_LIST_MAX` em `src/config.py` e `.env.example`, com falha na inicialização para valor inválido (design §8).

## 2. Contexto e resolução das dependências
- [ ] 2.1 `DependencyMount` e `AgentContext.dependency_dirs` (design §2).
- [ ] 2.2 No laço, cálculo das dependências concluídas (diretas ou transitivas) e da pasta de cada uma, inclusive a concluída na sessão anterior (design §3); `_execute_agent` preenche o contexto.
- [ ] 2.3 Testes: "Dependência direta", "Dependência transitiva", "Escopo direto", "Dependência da sessão anterior", "Dependência sem pasta", "Teto de montagens".

## 3. Sandbox
- [ ] 3.1 Montagens `ro` em `/deps_out/<projeto>/<task_name>` e validação da origem (design §4); `SandboxResult.dependencias_montadas`.
- [ ] 3.2 Decisão de rede: dependência montada desliga a rede da execução (parecer item 2).
- [ ] 3.3 Testes com o cliente Docker simulado: "Leitura da dependência", "Escrita recusada", "Pasta fora da sessão", "Sessão fora da cadeia", "Própria subtarefa", "Sem rede com dependência"; teste de integração no Pi: script lê `/deps_out/.../y_train.csv`.

## 4. Proveniência
- [ ] 4.1 `collect_inputs` com as pastas montadas; `inicio` com `dependencias` (design §2; parecer item 3).
- [ ] 4.2 Testes: "Entradas da dependência na proveniência", "Troca de arquivo entre execuções".

## 5. Contrato, prompt e contexto
- [ ] 5.1 Item 10 do contrato e `CONTRACT_VERSION = 2` (design §5); nomes como fragmento `artefatos`.
- [ ] 5.2 Regra 2 do prompt do Developer e `SubtaskOutput.to_context_string` com o caminho no container (design §6).
- [ ] 5.3 Testes: "Item 10 com alias", "Item 10 sem dependência", "Nome hostil omitido", "Montagem desligada", "Regra do prompt".

## 6. Validação
- [ ] 6.1 `uv run ruff check .` e `uv run lint-imports` sem erros novos; `uv run pytest -m "unit or integration" -v` verde no Pi.
- [ ] 6.2 Bateria curta no Pi com a `haiku-dev-sol-juiz` (só com confirmação do pesquisador): nenhuma falha por artefato de dependência ausente.
- [ ] 6.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR; confirmação com o Arquiteto para o status do ADR 022.
