# Tarefas: v18.7-benchmark-fixes

**Estado (2026-10-16):** implementada em três PRs: #172 (diagnóstico, cadeia de proveniência e egresso no relatório), #173 (cota do provedor) e o PR 3 (esta etapa: política `ON_MODEL_VERSION_CHANGE`, §3.9 e §3.10, `build_env` e a classificação de `versao_modelo`). Pendente só o 6.3: confirmar na próxima bateria (com a confirmação do pesquisador) que nenhuma cadeia sai `divergente` por `metrics.json` reescrito e que a cota esgotada fecha a execução em minutos.

**Registros do PR 3 (política da versão do modelo):**
- `ON_MODEL_VERSION_CHANGE` (`retomar` padrão | `parar`; outro valor falha na inicialização) vale só com `LLM_ROUTING=strict`. O `VersionTracker` guarda a política: `parar` marca `parada_pendente` como antes; `retomar` empilha ações (`alterada` ou `desconhecida`) que o laço trata no ponto de verificação de limites (`AutonomousLoop._pending_stop` -> `_apply_model_version_policy`): grava o checkpoint e continua; para versão desconhecida troca o modelo do papel (`src/llm/model_substitution.py`) e grava `modelo_substituido`; sem elegível pede o fechamento por `versao_modelo`.
- Elegibilidade do substituto: depois do atual na `preferencia`, disponível, política e requisitos do ADR 017, independência do julgamento (ADR 020, pelo `JudgeIndependenceGuard`) e localidade (ADR 019: quem estava no nó não vai para fora dele e quem aceitava dados brutos continua aceitando). Papel com pin do pesquisador não é trocado: a sessão fecha.
- O mapa da sessão (`routing.papeis`) passa a mudar nesse ponto de verificação (antes era imutável); `llm_routing` e `allocation_profile` do payload são regravados.
- Lacuna conhecida: o gatilho "modelo indisponível" da spec não tem sinal próprio (a disponibilidade só é conferida no início da sessão); hoje a troca ocorre por versão desconhecida. Um modelo que nunca informa versão percorre a `preferencia` até não restar elegível e a sessão fecha por `versao_modelo`.
- A bateria define `ON_MODEL_VERSION_CHANGE=parar` (`build_env`) e `versao_modelo` é `limite`/anomalia no benchmark.

**Registros do PR 2 (cota do provedor):**
- A resolução do contexto da sessão ficou em `src/llm/session_context.py` (ordem: `AgentContext`, `bound_execution_id()`, `EXECUTION_ID`/`SESSION_ID`); `emit_connection_retry`, o registro de cota e `_task_env` a usam. Corrige o contador de retentativas de conexão, que ficava em zero para agentes em processo.
- `ProviderQuotaExhausted` e o registro por sessão estão em `src/llm/quota.py`; os provedores chamam `raise_if_quota_exhausted` (Google antes de `is_retryable_error` e sem modelo de reserva; Anthropic em `APIStatusError`; OpenAI e openai_compatible leem o corpo do 429, pela constante `PROVIDER_KEY` de cada classe).
- Parecer de segurança: `detalhe` truncado em 300 caracteres, sem controle e sem chaves de API (`clean_detail`, sem importar `knowledge`, que está acima de `llm`); a inicialização recusa marcador com menos de 6 caracteres ou só numérico, e lista vazia é aceita.
- O laço autônomo: `_pending_model_stop(master_session_id)` consulta `quota_stop_for`; o registro é limpo no início da sessão; a subtarefa que falha por `cota_provedor` **não é retentada** (acréscimo à spec: as retentativas da mesma tarefa só gastariam chamadas que falham igual); planejamento vazio com cota registrada fecha por `limite_cota_provedor` em vez de contar plano rejeitado.
- A mensagem da CLI sai de `_show_operation_metrics` (`quota_stop_message`); no benchmark, `summarize_events` ganhou `cota_provedor` (provedor, modelo e status do evento), `anomalies` cita `provedor/modelo` e o relatório lista as paradas por cota.
- Aprovação do pesquisador (2026-10-16) para o valor novo em `Sessao.motivo_parada`.

**Diagnóstico com os dados arquivados da bateria no Pi (1.1 e 1.2, só leitura, sem chamada de LLM):**
- **1.1, texto literal do 429 do Google:** `429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'Your project has exceeded its monthly spending cap. Please go to AI Studio at https://ai.studio/spend to manage your project spend cap. Learn more at https://ai.google.dev/gemini-api/docs/billing#project-spend-caps. ', 'status': 'RESOURCE_EXHAUSTED'}}`. Sem `retryDelay`/`RetryInfo`, sem identificador de conta; o marcador `spending cap` (padrão do design) casa. Vale para `LLM_QUOTA_MARKERS_GOOGLE`.
- **1.2, cadeia `divergente`:** aplicada offline a regra de `_check_files` às 7 sessões arquivadas com registros no Pi. Dos 23 arquivos `alterado` em 4 sessões divergentes (as demais sessões arquivadas estavam íntegras), 21 eram **entrada reescrita pela mesma execução** (a causa do design §2.1; a regra nova os resolve) e 2 eram `metricas_literais.json`, outra causa que a spec não previa: a **plataforma** grava esse arquivo na pasta da subtarefa (`write_findings`) depois do término de cada execução, a execução seguinte o registra como entrada com o hash antigo e a plataforma o reescreve depois do último término. Não é adulteração nem saída de código gerado. Todas as pontas dos checkpoints conferiram (`ok`), todas as sessões tinham uma só cadeia: a hipótese do design §2.3 (checkpoint de outra cadeia) não se confirmou. **Decisão tomada na implementação (a confirmar):** `PLATFORM_WRITTEN_FILES` em `src/provenance/verify.py` trata `metricas_literais.json` como `substituido` (detalhe "arquivo gravado pela plataforma depois do término"), com teste de que a constante cobre `LITERALS_FILE`. Alternativas se o Arquiteto preferir: registrar esse arquivo como saída da própria execução ou gravá-lo fora da pasta da subtarefa.

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada pelo pesquisador, inclusive o valor aditivo `limite_cota_provedor` em `Sessao.motivo_parada`.
- [x] 0.2 Parecer do Analista de Segurança sobre `design.md` §7.
- [x] 0.3 Worktree `.worktrees/fix-v18.7-benchmark-fixes` (ou uma por parte, §1 a §3 do design); spec confrontada com o código.

## 1. Diagnóstico (sem chamada de LLM, com confirmação do pesquisador antes de acessar o Pi)
- [x] 1.1 Extrair do `run.log` arquivado da tentativa interrompida da rodada 3 (`~/bench/bateria_v18_6.json.d/`) o texto literal do 429 de teto de gasto do Google e se ele traz `retryDelay`; fixar `LLM_QUOTA_MARKERS_GOOGLE` e registrar o texto (sem identificadores de conta) no PR.
- [x] 1.2 Com o `sessao.tar.gz` de uma execução `divergente`, aplicar offline a regra de `_check_files` aos registros exportados em `<sessão>/provenance/execution_records.jsonl` (gravados pelo relatório da sessão, `src/provenance/report.py:48`; script no scratchpad, fora do repositório) e confirmar se todos os `alterado` são entradas reescritas pela mesma execução (design §2.1) ou se há checkpoint de outra cadeia (§2.3). Registrar o resultado no PR; se aparecer outra causa, parar e voltar ao Arquiteto.

## 2. Configuração
- [x] 2.1 `LLM_QUOTA_MARKERS_GOOGLE`, `LLM_QUOTA_MARKERS_ANTHROPIC`, `LLM_QUOTA_MARKERS_OPENAI`, `LLM_QUOTA_MARKERS_OPENAI_COMPATIBLE` e `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS` em `src/config.py` e `.env.example`.

## 3. Cota do provedor (design §1)
- [x] 3.0 Criar o auxiliar de teste compartilhado `FakeRecordingProvider` em `tests/support/fake_recording_provider.py` (sem dependência nova): implementa a interface de provedor LLM; registra, por chamada, o `system` e as `messages` recebidos; devolve respostas roteirizadas em ordem; aceita latência simulada por chamada; injeta erros roteirizados 429 (com e sem marcador de cota), 503 e esgotamento de cota com status e mensagem configuráveis. Nenhuma chamada de rede. Esta mudança cria o auxiliar; as mudanças V18.7 seguintes o reutilizam em vez de criar outro. Testes do próprio auxiliar em `tests/unit/support/test_fake_recording_provider.py`.
- [x] 3.1 `src/llm/quota.py`: `ProviderQuotaExhausted`, `is_quota_exhausted`, `record_quota_exhausted`, `quota_stop_for`, `clear_quota_stop`; `is_retryable_error` devolve `False` para a exceção.
- [x] 3.2 Resolução única do contexto da sessão (extraída de `_task_env`) usada por `emit_connection_retry` e pelo registro de cota.
- [x] 3.3 Classificação em `google.py` (sem reserva), `anthropic.py` e `openai_compatible.py` (corpo lido antes de `is_retryable_status`).
- [x] 3.4 `AgentRuntime`: `error_category="cota_provedor"`; orquestrador não chama `report_429` nesse caso; teto em `AdaptiveRateLimiter.report_429`.
- [x] 3.5 `StopReason.PROVIDER_QUOTA`, precedência sobre `limite_conexao`, `pending_stop` consultando `quota_stop_for`, limpeza no início da sessão.
- [x] 3.6 `_close_session` sem Summarizer/Curator nesse motivo, checkpoint com `cota_provedor`, evento `cota_provedor_esgotada`, mensagem da CLI.
- [x] 3.7 `MOTIVOS_RETOMAVEIS` e enumeração `Sessao.motivo_parada` com `limite_cota_provedor`; `describe_stop_reason`.
- [x] 3.8 Testes: um por cenário de `specs/llm-providers`, `specs/usage-limits` e `specs/session-continuity`, com `FakeRecordingProvider` (tarefa 3.0) ou clientes HTTP simulados (nenhuma chamada paga); o teste do teto do resfriamento confere a sequência 30, 60, 120, 240, 300, 300.

- [x] 3.9 `ON_MODEL_VERSION_CHANGE` (`retomar` padrão | `parar`) em `src/config.py` e `.env.example`, com validação (design §1.7).
- [x] 3.10 Política `retomar` com `LLM_ROUTING=strict`: checkpoint e continuação no ponto de verificação de limites (`src/orchestrator.py`, `src/llm/versions.py`, `src/usage.py`, `src/continuity.py`); nova versão registrada na proveniência; substituição pelo próximo modelo elegível da `preferencia` do papel (ADR 017, ADR 020, ADR 019) com o evento `modelo_substituido`; sem elegível, fecha com `versao_modelo`. Testes: um por cenário do requisito "Mudança de versão dentro da sessão" de `specs/llm-providers`, com `FakeRecordingProvider` e catálogo de teste (nenhuma chamada paga).

## 4. Cadeia de proveniência (design §2)
- [x] 4.1 `_check_files`: entrada reescrita pela mesma execução vira `substituido`.
- [x] 4.2 `ProvenanceChainReader`: `cadeia.motivos` e `cadeia.arquivos_alterados_exemplos`.
- [x] 4.3 Testes: cenários de `specs/execution-provenance` (regressão da retentativa com `metrics.json`) e de "Causas da cadeia divergente".

## 5. Egresso no relatório (design §3)
- [x] 5.1 `EgressMetricsReader.bytes_limitados`; seção Markdown com as duas grandezas.
- [x] 5.2 (colunas de egresso e causa da cadeia no PR 1; `limite_cota_provedor` no PR 2; `stop_class` de `versao_modelo` e `build_env` no PR 3) ~~`scripts/benchmark/report.py`: três colunas de egresso, causa da cadeia;~~ `run_benchmark.py`: `limite_cota_provedor` listado com provedor e modelo; `stop_class` devolve `limite` para `versao_modelo`; `build_env` define `ON_MODEL_VERSION_CHANGE=parar` no ambiente do subprocesso (junto de `LLM_ROUTING` e `LLM_DATA_POLICY`).
- [x] 5.3 Testes: cenários de `specs/operation-metrics` e `specs/benchmark`.

## 6. Validação
- [x] 6.1 `uv run ruff check .` sem erros novos; `uv run pytest -m "unit or integration" -v` verde.
- [x] 6.2 Regenerar o relatório da bateria V18.6 a partir de `bateria_v18_6.json` (sem nova execução) e conferir que as colunas de egresso mostram as saídas novas como `-` (resultado antigo) sem erro.
- [ ] 6.3 Na próxima bateria (com confirmação do pesquisador): nenhuma cadeia `divergente` causada por `metrics.json` reescrito; se houver cota esgotada, a execução fecha com `limite_cota_provedor` em minutos.
- [x] 6.4 Atualizar `tasks.md` (caixas e **Estado**), a tabela de `openspec/README.md` e o achado 4, 5 e 6 do relatório da bateria no PR.
