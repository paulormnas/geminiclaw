# Proposta: Correções da bateria V18.6 (cota do provedor, cadeia de proveniência e egresso no relatório)

**ID:** `v18.7-benchmark-fixes` · **Versão:** V18.7 · **Capacidades:** `llm-providers`, `usage-limits`, `session-continuity`, `execution-provenance`, `operation-metrics`, `benchmark`
**ADRs de origem:** nenhum novo (correção). Requisitos relacionados: [ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) (provedores agnósticos), [ADR 017](../../../docs/decisions/adr_017_catalogo_modelos_roteador.md) (roteador e reserva do 429), [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §4 (registro de execuções encadeado), §8 (métricas de operação) e §11 (limites de uso), [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md) (exploração contínua com parada explícita).
**Origem:** achados 4, 5 e 6 de [`docs/benchmarks/2026-10-15-bateria-v18-6-resultados.md`](../../../docs/benchmarks/2026-10-15-bateria-v18-6-resultados.md).
**Depende de:** nenhuma mudança em aberto. Base: specs consolidadas de V18.5 e V18.6 (`usage-limits`, `execution-provenance`, `operation-metrics`, `benchmark`, `llm-providers`). Independente dos ADRs 021 e 022. Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.

## Por quê

A bateria V18.6 (2026-10-14/15) mostrou três defeitos que não são decisões de arquitetura, mas desvios do comportamento já especificado.

1. **Cota ou teto de gasto do provedor tratado como falha de tarefa.** Um HTTP 429 `RESOURCE_EXHAUSTED` causado pelo teto de gasto mensal do projeto Google foi retentado como limite de taxa transitório e, depois, tratado como falha de subtarefa; o laço autônomo replanejou por 3h20 até o `timeout_seconds` do benchmark. O código confirma três causas que se somam: (a) todo 429 é transitório para `src/llm/retry.py:24` e `:35`, e o Google trata `RESOURCE_EXHAUSTED` como limite de taxa (`src/llm/providers/google.py:40-42`), sem distinguir cota esgotada; (b) o resfriamento do `AdaptiveRateLimiter` dobra sem teto a cada 429 consecutivo (`src/rate_limiter.py:86`: 30 s, 60 s, ..., 3840 s no nono), o que sozinho explica horas de espera; (c) o evento `connection_retry` é gravado com o `EXECUTION_ID` de `os.environ` (`src/llm/retry.py:74-75`), que os agentes em processo não definem (o estado deles está no `AgentContext`, `src/llm/agent_loop.py:36-45`), de modo que o contador lido pelo `UsageTracker` com o id da sessão mestra (`src/usage.py:477`, `src/telemetry.py:1176-1203`) fica em zero e `SESSION_MAX_CONNECTION_RETRIES` nunca fecha a sessão. Nos testes, o leitor do contador é sempre injetado (`tests/unit/test_autonomous_loop.py:285`), por isso o defeito (c) passou.
2. **Cadeia de proveniência `divergente` com retentativas.** 6 das 8 execuções com Gemini saíram com a cadeia `divergente` (0 órfãs). O código confirma um mecanismo que produz exatamente esse quadro (detalhe em `design.md` §2): a execução que encontra `metrics.json` na pasta da tarefa o registra em `entradas` com o hash antigo (`src/provenance/records.py:94-107`) e, ao sobrescrevê-lo, o registra também em `saidas` com o hash novo (`src/provenance/records.py:110-130`); a verificação trata o caminho como "último escritor" desse mesmo registro e compara também a entrada antiga com o disco (`src/provenance/verify.py:166-202`), marcando `alterado`. A exceção de `.py` (`verify.py:184-189`) cobriu só o `script.py`. Falta confirmar, nos dados arquivados da bateria, que essa é a única causa (a verificação de checkpoint também pode dar `divergente`, §2.3).
3. **Tabela de egresso compara grandezas diferentes.** `EGRESS_SESSION_MAX_BYTES` limita apenas as saídas de execução novas enviadas fora do nó (`bytes_saida_execucao_novos`, `src/egress/gate.py:244`, `src/egress/log.py:64`, `src/usage.py:314-325`), mas a seção "Métricas de operação" escreve o total enviado fora do nó ao lado do limite (`src/operation_metrics.py:529-534`) e o relatório do benchmark só mostra o total (`scripts/benchmark/report.py:180` e `:200`). Execuções com 3,9 MB de total e 0,4 MB de saídas novas parecem violar um limite de 2 MB que não foi atingido.

## O que muda

### Novo

- **Classificação de erro de cota ou gasto** (`src/llm/quota.py`): cada provedor de nuvem distingue esgotamento de cota/gasto (não recuperável na sessão) de limite de taxa (transitório). O esgotamento levanta `ProviderQuotaExhausted`, sem retentativa e sem modelo de reserva, e registra a parada para a sessão corrente. Marcadores por provedor configuráveis.
- **Motivo de parada `limite_cota_provedor`** em `StopReason` e em `Sessao.motivo_parada`, com evento `cota_provedor_esgotada`, fechamento com checkpoint determinístico sem consolidação por LLM, mensagem acionável na CLI e no relatório, retomável com `geminiclaw resume --session <id>` depois que o pesquisador ajustar o teto ou trocar o provedor.
- **Política `ON_MODEL_VERSION_CHANGE`** (`retomar` padrão | `parar`): com `LLM_ROUTING=strict`, versão alterada ou desconhecida deixa de fechar a sessão; ela grava checkpoint, registra `versao_modelo_alterada` e continua, substituindo o modelo pelo próximo elegível da `preferencia` quando a versão é desconhecida ou o modelo está indisponível (`modelo_substituido`). A bateria define `parar`.
- **Teto do resfriamento do limitador de taxa** (`LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS`).
- **Causas da cadeia `divergente`** nas métricas de operação (`proveniencia.cadeia.motivos`) e no relatório do benchmark, para que a próxima bateria diga por que a cadeia divergiu.
- **Egresso limitado separado do total**: `egresso.bytes_limitados` (soma de `bytes_saida_execucao_novos`, a mesma que o `UsageTracker` compara com o limite) nas métricas de operação, na seção Markdown e em colunas próprias do relatório do benchmark.

### Modificado

- **Retentativa dos provedores:** 429 continua transitório, exceto quando classificado como cota/gasto. O provedor `openai_compatible` passa a ler o corpo do 429 antes de decidir (hoje o descarta, `src/llm/providers/openai_compatible.py:166-171`). Erros 400/402 de saldo esgotado da Anthropic deixam de virar falha de subtarefa.
- **Contagem de `connection_retry`:** o evento passa a usar a sessão do `AgentContext` (ou o id vinculado por `bound_execution_id`) antes de `os.environ`, de modo que `limite_conexao` volta a funcionar como rede de segurança para 429 não classificado.
- **Verificação da cadeia:** em um mesmo registro, um caminho que aparece em `entradas` e em `saidas` é conferido só pela saída; a entrada vira `substituido` ("consumida e reescrita pela mesma execução").
- **Classificação no benchmark:** `limite_cota_provedor` cai em `limite` (anomalia), com linha própria no relatório; `versao_modelo` passa de `criterio_pesquisa` a `limite` (anomalia); `build_env` define `ON_MODEL_VERSION_CHANGE=parar` no subprocesso.
- **Mudança de versão dentro da sessão** (`llm-providers`): requisito modificado conforme a política acima.

### Removido

- Nada.

### Fora do escopo

- Achados 1, 2 e 3 da bateria (ADRs 021 e 022 e calibração do veredito).
- Troca automática de provedor quando a cota acaba (distinta da substituição de modelo por versão desconhecida, que está no escopo) (quebraria a independência do julgamento, ADR 020, e a alocação da sessão, ADR 017); a decisão continua do pesquisador.
- Consultar saldo ou teto de gasto nas APIs dos provedores antes da sessão.
- Temperatura do Pi 5 (achado 7).

## Impacto

- **Código:** novo `src/llm/quota.py`; `src/llm/retry.py`, `src/llm/providers/{google,anthropic,openai_compatible}.py`, `src/agent_runtime/runtime.py`, `src/rate_limiter.py`, `src/orchestrator.py` (relato ao limitador), `src/usage.py`, `src/autonomous_loop.py` (`_pending_model_stop`, `_close_session`), `src/continuity.py` (`MOTIVOS_RETOMAVEIS`), `src/knowledge/schema.py` (enumeração), `src/provenance/verify.py`, `src/operation_metrics.py`, `src/cli.py` (mensagem de parada), `scripts/benchmark/{report,run_benchmark}.py`, `src/config.py`, `.env.example`.
- **Contratos:** exceção `ProviderQuotaExhausted`; `AgentResult.error_category = "cota_provedor"`; evento `cota_provedor_esgotada`; evento `modelo_substituido` e variável `ON_MODEL_VERSION_CHANGE`; chaves novas `egresso.bytes_limitados` e `proveniencia.cadeia.motivos` (aditivas, `versao` das métricas de operação continua 1).
- **Schema:** um valor novo na enumeração `Sessao.motivo_parada` do grafo (aditivo, sem migração). Nenhuma tabela nova; `egress_log` e `execution_records` não mudam.
- **Testes:** novo auxiliar compartilhado `tests/support/fake_recording_provider.py` (`FakeRecordingProvider`: registra `system` e `messages`, respostas roteirizadas, latência, erros 429, 503 e de cota), criado aqui e reutilizado pelas mudanças V18.7 seguintes. Sem dependência de desenvolvimento nova.
- **Custo:** reduz gasto e tempo perdido (a sessão para na primeira resposta de cota). Nenhuma chamada de LLM a mais.

## Aprovações necessárias

- **Alteração de schema do grafo (aditiva):** `Sessao.motivo_parada` ganha `limite_cota_provedor` (`src/knowledge/schema.py:134-151`). Precisa da aprovação explícita do pesquisador.
- **Diagnóstico com os dados arquivados da bateria no Pi** (tarefa 1.2): leitura de `~/bench/bateria_v18_6.json.d/`, sem chamada de LLM e sem rodar testes; pedir confirmação antes, conforme a orientação de não usar o Pi até a próxima bateria.
- Nenhuma alteração de Dockerfile, `docker-compose.yml`, `AGENTS.md` ou exclusão de arquivos.
