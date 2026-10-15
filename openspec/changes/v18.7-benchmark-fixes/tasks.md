# Tarefas: v18.7-benchmark-fixes

**Estado (2026-10-15):** não iniciada.

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada pelo pesquisador, inclusive o valor aditivo `limite_cota_provedor` em `Sessao.motivo_parada`.
- [ ] 0.2 Parecer do Analista de Segurança sobre `design.md` §7.
- [ ] 0.3 Worktree `.worktrees/fix-v18.7-benchmark-fixes` (ou uma por parte, §1 a §3 do design); spec confrontada com o código.

## 1. Diagnóstico (sem chamada de LLM, com confirmação do pesquisador antes de acessar o Pi)
- [ ] 1.1 Extrair do `run.log` arquivado da tentativa interrompida da rodada 3 (`~/bench/bateria_v18_6.json.d/`) o texto literal do 429 de teto de gasto do Google e se ele traz `retryDelay`; fixar `LLM_QUOTA_MARKERS_GOOGLE` e registrar o texto (sem identificadores de conta) no PR.
- [ ] 1.2 Com o `sessao.tar.gz` de uma execução `divergente`, aplicar offline a regra de `_check_files` aos registros exportados em `<sessão>/provenance/execution_records.jsonl` (gravados pelo relatório da sessão, `src/provenance/report.py:48`; script no scratchpad, fora do repositório) e confirmar se todos os `alterado` são entradas reescritas pela mesma execução (design §2.1) ou se há checkpoint de outra cadeia (§2.3). Registrar o resultado no PR; se aparecer outra causa, parar e voltar ao Arquiteto.

## 2. Configuração
- [ ] 2.1 `LLM_QUOTA_MARKERS_GOOGLE`, `LLM_QUOTA_MARKERS_ANTHROPIC`, `LLM_QUOTA_MARKERS_OPENAI`, `LLM_QUOTA_MARKERS_OPENAI_COMPATIBLE` e `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS` em `src/config.py` e `.env.example`.

## 3. Cota do provedor (design §1)
- [ ] 3.0 Criar o auxiliar de teste compartilhado `FakeRecordingProvider` em `tests/support/fake_recording_provider.py` (sem dependência nova): implementa a interface de provedor LLM; registra, por chamada, o `system` e as `messages` recebidos; devolve respostas roteirizadas em ordem; aceita latência simulada por chamada; injeta erros roteirizados 429 (com e sem marcador de cota), 503 e esgotamento de cota com status e mensagem configuráveis. Nenhuma chamada de rede. Esta mudança cria o auxiliar; as mudanças V18.7 seguintes o reutilizam em vez de criar outro. Testes do próprio auxiliar em `tests/unit/support/test_fake_recording_provider.py`.
- [ ] 3.1 `src/llm/quota.py`: `ProviderQuotaExhausted`, `is_quota_exhausted`, `record_quota_exhausted`, `quota_stop_for`, `clear_quota_stop`; `is_retryable_error` devolve `False` para a exceção.
- [ ] 3.2 Resolução única do contexto da sessão (extraída de `_task_env`) usada por `emit_connection_retry` e pelo registro de cota.
- [ ] 3.3 Classificação em `google.py` (sem reserva), `anthropic.py` e `openai_compatible.py` (corpo lido antes de `is_retryable_status`).
- [ ] 3.4 `AgentRuntime`: `error_category="cota_provedor"`; orquestrador não chama `report_429` nesse caso; teto em `AdaptiveRateLimiter.report_429`.
- [ ] 3.5 `StopReason.PROVIDER_QUOTA`, precedência sobre `limite_conexao`, `pending_stop` consultando `quota_stop_for`, limpeza no início da sessão.
- [ ] 3.6 `_close_session` sem Summarizer/Curator nesse motivo, checkpoint com `cota_provedor`, evento `cota_provedor_esgotada`, mensagem da CLI.
- [ ] 3.7 `MOTIVOS_RETOMAVEIS` e enumeração `Sessao.motivo_parada` com `limite_cota_provedor`; `describe_stop_reason`.
- [ ] 3.8 Testes: um por cenário de `specs/llm-providers`, `specs/usage-limits` e `specs/session-continuity`, com `FakeRecordingProvider` (tarefa 3.0) ou clientes HTTP simulados (nenhuma chamada paga); o teste do teto do resfriamento confere a sequência 30, 60, 120, 240, 300, 300.

## 4. Cadeia de proveniência (design §2)
- [ ] 4.1 `_check_files`: entrada reescrita pela mesma execução vira `substituido`.
- [ ] 4.2 `ProvenanceChainReader`: `cadeia.motivos` e `cadeia.arquivos_alterados_exemplos`.
- [ ] 4.3 Testes: cenários de `specs/execution-provenance` (regressão da retentativa com `metrics.json`) e de "Causas da cadeia divergente".

## 5. Egresso no relatório (design §3)
- [ ] 5.1 `EgressMetricsReader.bytes_limitados`; seção Markdown com as duas grandezas.
- [ ] 5.2 `scripts/benchmark/report.py`: três colunas de egresso, causa da cadeia; `run_benchmark.py`: `limite_cota_provedor` listado com provedor e modelo.
- [ ] 5.3 Testes: cenários de `specs/operation-metrics` e `specs/benchmark`.

## 6. Validação
- [ ] 6.1 `uv run ruff check .` sem erros novos; `uv run pytest -m "unit or integration" -v` verde.
- [ ] 6.2 Regenerar o relatório da bateria V18.6 a partir de `bateria_v18_6.json` (sem nova execução) e conferir que as colunas de egresso mostram as saídas novas como `-` (resultado antigo) sem erro.
- [ ] 6.3 Na próxima bateria (com confirmação do pesquisador): nenhuma cadeia `divergente` causada por `metrics.json` reescrito; se houver cota esgotada, a execução fecha com `limite_cota_provedor` em minutos.
- [ ] 6.4 Atualizar `tasks.md` (caixas e **Estado**), a tabela de `openspec/README.md` e o achado 4, 5 e 6 do relatório da bateria no PR.
