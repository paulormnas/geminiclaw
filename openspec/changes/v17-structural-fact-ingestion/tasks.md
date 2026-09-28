# Tarefas: v17-structural-fact-ingestion

## 1. Contratos
- [ ] 1.1 `save_experiment_artifacts`: parâmetros `datasets` e `baselines` (retrocompatíveis).
- [ ] 1.2 Plano do Researcher: campo opcional `approach`; `AgentTask.approach`; parser aceita planos sem o campo.
- [ ] 1.3 Instrução do Developer: informar `datasets` e `baselines`.
- [ ] 1.4 `PythonSandbox`: retorno estruturado com `exit_code`, `oom_killed`, `exception_type`.

## 2. Ingestão
- [ ] 2.1 `src/knowledge/ingestion.py`: `ingest_session_start`, `ingest_inputs`, `ingest_subtask`, `ingest_session_end`.
- [ ] 2.2 Mapeamentos de `Insumo`, `Experimento`, `Resultado`, `Abordagem` conforme o design.
- [ ] 2.3 Classificação de causa e assinatura de falha.
- [ ] 2.4 `config_normalizada`.
- [ ] 2.5 Hipótese provisória a partir de `hypothesis` (§5).
- [ ] 2.6 Chamadas nos quatro pontos do orquestrador/loop.

## 3. Resiliência
- [ ] 3.1 Fila `knowledge_pending.jsonl` em erro de escrita.
- [ ] 3.2 `geminiclaw knowledge sync`.

## 4. Testes (com `InMemoryGraphStore`)
- [ ] 4.1 Sessão com 2 subtarefas gera os nós e arestas esperados.
- [ ] 4.2 Reingestão não duplica.
- [ ] 4.3 Classificação: traceback → `abordagem`; exit 137 → `abordagem/oom`; sem `metrics.json` → `ambigua`; provedor indisponível → `infraestrutura`.
- [ ] 4.4 `config_normalizada` remove `seed`, `random_state`, `data_path`, `output_dir`.
- [ ] 4.5 Grafo indisponível: sessão conclui; pendência gravada; `knowledge sync` aplica depois.
- [ ] 4.6 `metrics.json` antigo (sem `datasets`/`baselines`) é ingerido sem erro.

## 5. Fechamento
- [ ] 5.1 Ruff, testes, revisão nos 7 eixos, PR.
