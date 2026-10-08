# Tarefas: v17-structural-fact-ingestion

**Estado (2026-10-08):** Implementada, com pendências — PR #105. Os itens abertos abaixo são validação em ambiente real (AGE/Qdrant/Pi 5, adiada para a bateria final) e débitos documentados.

## 1. Contratos
- [x] 1.1 `save_experiment_artifacts`: parâmetros `datasets` e `baselines` (retrocompatíveis).
- [x] 1.2 Plano do Researcher: campo opcional `approach`; `AgentTask.approach`; parser aceita planos sem o campo.
- [x] 1.3 Instrução do Developer: informar `datasets` e `baselines`.
- [x] 1.4 `PythonSandbox`: retorno estruturado com `exit_code`, `oom_killed`, `exception_type`.

## 2. Ingestão
- [x] 2.1 `src/knowledge/ingestion.py`: `ingest_session_start`, `ingest_inputs`, `ingest_subtask`, `ingest_session_end`.
- [x] 2.2 Mapeamentos de `Insumo`, `Experimento`, `Resultado`, `Abordagem` conforme o design.
- [x] 2.3 Classificação de causa e assinatura de falha.
- [x] 2.4 `config_normalizada`.
- [x] 2.5 Hipótese provisória a partir de `hypothesis` (§5).
- [x] 2.6 Chamadas nos quatro pontos do orquestrador/loop.

## 3. Resiliência
- [x] 3.1 Fila `knowledge_pending.jsonl` em erro de escrita.
- [x] 3.2 `geminiclaw knowledge sync`.

## 4. Testes (com `InMemoryGraphStore`)
- [x] 4.1 Sessão com 2 subtarefas gera os nós e arestas esperados.
- [x] 4.2 Reingestão não duplica.
- [x] 4.3 Classificação: traceback → `abordagem`; exit 137 → `abordagem/oom`; sem `metrics.json` → `ambigua`; provedor indisponível → `infraestrutura`.
- [x] 4.4 `config_normalizada` remove `seed`, `random_state`, `data_path`, `output_dir`.
- [x] 4.5 Grafo indisponível: sessão conclui; pendência gravada; `knowledge sync` aplica depois.
- [x] 4.6 `metrics.json` antigo (sem `datasets`/`baselines`) é ingerido sem erro.

## 5. Fechamento
- [x] 5.1 Ruff, testes, revisão nos 7 eixos, PR.
- [ ] 5.2 Validar a ingestão contra o Apache AGE real (Pi 5): idempotência de arestas via `neighbors`, `find_nodes` por `sessao_id`/`hash_conteudo`, propriedades `dict`/`list` (`ambiente`, `consumo`, `dataset_ids`, `APLICOU.config`) e `geminiclaw knowledge sync` ponta a ponta. Os testes desta mudança usam `InMemoryGraphStore`; o AGE não estava disponível no ambiente de desenvolvimento.
- [ ] 5.3 Medir o campo `python` de `Experimento.ambiente` (hoje só `imagem_sandbox` e `pacotes`; a versão do Python do sandbox não é medida no host).
