# Design: v18.7-benchmark-fixes

Três correções independentes, que podem ir em PRs separados (§1, §2 e §3). Referências de código conferidas no worktree em 2026-10-15.

## 1. Cota ou teto de gasto do provedor

### 1.1 Estado atual (confirmado no código)

| Ponto | Comportamento |
|---|---|
| `src/llm/retry.py:24`, `:35`, `:49-52` | Todo 429 (status ou texto "429" na mensagem) é transitório e retentado. |
| `src/llm/providers/google.py:40-42`, `:172-207` | `_is_rate_limit` aceita "429" ou "RESOURCE_EXHAUSTED"; retenta 3 vezes (0,5 s, 1 s, 2 s) e, com modelo de reserva diferente, retenta mais 3 vezes nele. Com `GOOGLE_FALLBACK_MODEL` igual ao principal (`gemini-4-argon`, `src/config.py:96`), a reserva fica desligada. |
| `src/llm/providers/anthropic.py:236-257` | 429 e 5xx retentados; 400 de saldo ("credit balance is too low", observado em `docs/benchmarks/2026-09-30-modelos-baixo-custo.md:18`) propaga sem retentativa e vira falha de subtarefa. |
| `src/llm/providers/openai_compatible.py:145-187` | 429 é retentado e, esgotadas as tentativas, levanta `HTTPStatusError("Status retentável 429")` sem o corpo; o código `insufficient_quota` da OpenAI se perde. `OpenAIProvider` herda esse método (`src/llm/providers/openai.py:30`, `:222`). |
| `src/agent_runtime/runtime.py:100-116` | Toda exceção do agente vira `AgentResult(status="error")`; `error_category="llm_connection"` se `is_retryable_error` (o 429 entra aqui). |
| `src/orchestrator.py:1980-1987`, `src/rate_limiter.py:80-105` | Erro com "429" na mensagem chama `report_429`, que dobra o resfriamento sem teto (`cooldown_seconds * 2 ** (n - 1)`). Nove 429 seguidos somam cerca de 4 h de espera. |
| `src/llm/retry.py:71-86` | `connection_retry` gravado com `EXECUTION_ID`/`SESSION_ID` de `os.environ`; ninguém define essas variáveis no processo (`grep os.environ[` em `src/` não acha atribuição), então o evento vai para `execution_id="unknown"` e o `UsageTracker` da sessão (`src/usage.py:477`) lê zero. `limite_conexao` (`SESSION_MAX_CONNECTION_RETRIES=20`, `src/config.py:221`) não dispara. |
| `src/autonomous_loop.py:1023-1054`, `src/orchestrator.py:2193-2196` | Falha do Researcher devolve plano vazio, conta como plano rejeitado e o laço tenta de novo; falha de subtarefa vira `execution_feedback` e replanejamento. |

Não foi possível reconstruir só pelo código a parcela exata de cada causa nas 3h20 (o log da tentativa está no Pi); as três causas são corrigidas, e a tarefa 1.1 extrai do log o texto literal do erro do Google para calibrar os marcadores.

### 1.2 Classificação

Novo módulo `src/llm/quota.py`:

```python
class ProviderQuotaExhausted(RuntimeError):
    provider: str        # "google" | "anthropic" | "openai" | "openai_compatible"
    model: str
    status_code: int | None
    detail: str          # mensagem do provedor, truncada em 300 caracteres e sem cabeçalhos

def is_quota_exhausted(provider: str, status_code: int | None, message: str) -> bool: ...
def record_quota_exhausted(exc: ProviderQuotaExhausted) -> None: ...
def quota_stop_for(execution_id: str) -> ProviderQuotaExhausted | None: ...
def clear_quota_stop(execution_id: str) -> None: ...
```

Regra: é esgotamento de cota/gasto quando o status é 429, 400, 402 ou 403 **e** a mensagem (sem diferenciar maiúsculas) contém um dos marcadores do provedor. Sem marcador, um 429 continua limite de taxa (comportamento atual). Marcadores por provedor, lista separada por vírgulas:

| Variável | Padrão | Fonte |
|---|---|---|
| `LLM_QUOTA_MARKERS_GOOGLE` | `spending cap` | provisório: confirmar com o texto literal do log da bateria (tarefa 1.1) |
| `LLM_QUOTA_MARKERS_ANTHROPIC` | `credit balance is too low` | observado em 2026-09-30 |
| `LLM_QUOTA_MARKERS_OPENAI` | `insufficient_quota` | código de erro documentado da OpenAI |
| `LLM_QUOTA_MARKERS_OPENAI_COMPATIBLE` | vazio | servidores próprios não têm cota de gasto |

Os marcadores genéricos "billing" e "exceeded your current quota" ficam de fora de propósito: o Google usa esse texto também no 429 por minuto, que é transitório. O Ollama não é classificado (local).

`is_retryable_error` passa a devolver `False` para `ProviderQuotaExhausted` antes da heurística de texto (a mensagem contém "429").

### 1.3 Onde cada provedor classifica

- **Google** (`_call_with_retry`): ao capturar a exceção, antes de `is_retryable_error`, classifica com o código (`exc.code` do `google.genai.errors.APIError`, quando houver) e a mensagem; se for cota, registra e levanta `ProviderQuotaExhausted` sem retentar. `_generate_content` não troca para o modelo de reserva nesse caso (a cota é do projeto, a reserva falharia igual).
- **Anthropic** (`_create_with_retry`): em `APIStatusError`, classifica com `exc.status_code` e `str(exc)` antes de `is_retryable_status`.
- **OpenAI e openai_compatible** (`_post_with_retry`): antes de `is_retryable_status`, lê `response.text[:800]` e classifica com o nome do provedor (`openai` ou `openai_compatible`).

Cada classificação positiva registra `logger.error` com provedor, modelo, status e o detalhe truncado (nunca a chave nem cabeçalhos).

### 1.4 Parada da sessão

- **Registro:** `record_quota_exhausted` guarda a exceção por `execution_id`, resolvido como na telemetria corrigida (§1.6). Grava o evento `cota_provedor_esgotada` (`agent_id="llm_provider:<provedor>"`, payload `provedor`, `modelo`, `status`, `detalhe`, `papel` quando conhecido). Só o primeiro registro por sessão gera evento.
- **Agente:** `AgentRuntime.run` captura `ProviderQuotaExhausted` antes do `except Exception` e devolve `AgentResult(status="error", error_category="cota_provedor")`. `classify_failure` já trata qualquer `agent_error_category` como causa `infraestrutura` (`src/knowledge/failure_cause.py:66-67`), então a subtarefa não vira resultado negativo de abordagem.
- **Laço:** `StopReason.PROVIDER_QUOTA = "limite_cota_provedor"` (`src/usage.py`). O `pending_stop` do `UsageTracker` (hoje `_pending_model_stop`, `src/autonomous_loop.py:139-152`) consulta `quota_stop_for(master_session_id)`. Os pontos de verificação existentes (`src/autonomous_loop.py:1007`, `:1195`, `:1309`) fecham a sessão no próximo ponto; nenhuma subtarefa nova é despachada e nenhum replanejamento acontece. Precedência em `LimitStatus.stop_reason`: `limite_cota_provedor` vem antes de `limite_conexao` (é a causa das retentativas), depois de tokens, tempo e egresso.
- **Fechamento:** `_close_session` com `limite_cota_provedor` não chama o Summarizer nem o Curator (`consolidation_pending=True`, mesmo caminho da reserva esgotada, `src/autonomous_loop.py:2112-2117`); o checkpoint determinístico é gravado com `motivo_parada`, `cota_provedor` (`provedor`, `modelo`, `status`) e as tarefas pendentes. A consolidação fica para a retomada.
- **Mensagem:** a CLI e a seção "Métricas de operação" descrevem `limite_cota_provedor (cota ou teto de gasto esgotado no provedor <p>, modelo <m>; aumente o teto ou troque o provedor e retome com geminiclaw resume --session <id>)`.
- **Retomada:** `limite_cota_provedor` entra em `MOTIVOS_RETOMAVEIS` (`src/continuity.py:65-70`), como os demais `limite_*`. A retomada não confere o saldo; se a cota continuar esgotada, a nova sessão para de novo na primeira chamada.
- **Início de sessão:** o registro da sessão anterior é limpo onde `clear_interrupt()` é chamado (`src/autonomous_loop.py:225`).

### 1.5 Limitador de taxa

- `report_429` mantém o crescimento exponencial de hoje (`cooldown_seconds * 2^(n-1)`, `src/rate_limiter.py:86`) e limita o resultado a `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS` (padrão 300): com base 30, a sequência é 30, 60, 120, 240, 300, 300 e assim por diante.
- `src/orchestrator.py:1984` não chama `report_429` quando `error_category == "cota_provedor"` (esperar não devolve cota).

### 1.6 Contagem de retentativas de conexão

`emit_connection_retry` resolve o contexto na ordem: `AgentContext` corrente (`execution_id or session_id`), `bound_execution_id()` (`src/llm/metering.py:34-36`), depois `os.environ`, por fim `"unknown"`, a mesma ordem de `_task_env` em `src/llm/agent_loop.py:23-61`. A função de resolução é extraída para um ponto único e reutilizada pelos dois. Com isso, um 429 não classificado (marcador desconhecido) fecha a sessão com `limite_conexao` em no máximo `SESSION_MAX_CONNECTION_RETRIES` retentativas, em vez de rodar até o tempo da sessão.

## 2. Cadeia de proveniência `divergente`

### 2.1 Mecanismo confirmado no código

1. O Developer executa vários scripts por subtarefa (`step_02`, `step_04`, `step_07` nos registros da bateria) e cada `run_python` é uma execução registrada.
2. No `inicio` da execução N+1, `collect_inputs` registra tudo que já existe na pasta da tarefa como entrada, inclusive o `metrics.json` gravado pela execução N, com o hash antigo (`src/provenance/records.py:94-107`).
3. Se a execução N+1 reescreve `metrics.json`, `collect_outputs` o registra em `saidas` com o hash novo (tamanho ou `mtime_ns` mudou, `records.py:110-130`). O `termino` repete as `entradas` do `inicio` (`records.py:217-226`): o mesmo caminho aparece duas vezes no registro, com hashes diferentes.
4. `_check_files` calcula o último escritor por caminho considerando `saidas` e `entradas` (`src/provenance/verify.py:166-171`). Para N+1, `last_writer == rec.seq`, então nem a entrada nem a saída são `substituido` (`verify.py:181`); a entrada é comparada com o disco, que já tem o hash novo, e sai `alterado` (`verify.py:202`). `VerifyReport.integra` fica falso (`verify.py:66-71`) e `ProvenanceChainReader` escreve `divergente` (`src/operation_metrics.py:228-234`).
5. A exceção de `verify.py:184-189` só cobre entradas `.py` (o `script.py`), corrigida após o benchmark de 2026-10-12 pelo mesmo motivo.

Isso reproduz o quadro da bateria (cadeia `divergente` com 0 órfãs, só nas combinações em que o Developer é Gemini, que roda mais passos por subtarefa e reescreve `metrics.json`). A hipótese do relatório ("tentativas anteriores guardam o hash que a seguinte sobrescreveu") está quase certa: a verificação já trata a tentativa anterior como `substituido`; o falso `alterado` vem da **entrada** da tentativa seguinte.

### 2.2 Correção

Em `_check_files`, para cada registro: um caminho presente em `saidas` do mesmo registro faz a entrada correspondente ser `substituido` com `detalhe="consumida e reescrita pela mesma execução"`; a saída é conferida contra o disco normalmente. As demais regras não mudam (último escritor, código gerado `.py`). Um arquivo realmente editado no disco depois do último `termino` continua `alterado` (cenário existente "Arquivo de saída alterado").

### 2.3 Outra causa possível, a descartar com os dados

`_check_checkpoints` (`verify.py:224-250`) indexa os registros só por `seq` e não compara `tip["project_id"]` com a cadeia verificada; `verify_session` gera um relatório por cadeia que a sessão tocou (`verify.py:297-304`). Uma sessão que gravasse em duas cadeias (projeto e `sem_projeto:<sessão>`) teria o checkpoint `divergente` na cadeia que não é a da ponta. Não há indício disso na bateria (projeto semeado), mas a tarefa 1.2 confere. Se confirmado, a correção é ignorar a ponta de outra cadeia (estado `outra_cadeia`, não divergente); fica registrada como questão em aberto e não entra nesta mudança sem a evidência.

### 2.4 Diagnóstico nas próximas execuções

`ProvenanceChainReader` passa a gravar `cadeia.motivos`: contagens de `cadeia` (problemas de encadeamento), `pares`, `arquivos_alterados`, `checkpoints_divergentes` e `conflitos_pendencia`, e a lista dos até 5 primeiros caminhos alterados. O relatório do benchmark mostra a causa ao lado de `divergente`.

## 3. Egresso no relatório

- `EgressMetricsReader` (`src/operation_metrics.py:144-209`) acrescenta `bytes_limitados = egress_bytes_for_session(session_id)` (`src/egress/log.py:150-160`), a mesma soma que o `UsageTracker` compara com `max_egress_bytes` (`src/usage.py:314-325`, `:486-487`). `bytes_total` não muda.
- A seção Markdown passa a escrever: `Egresso: <total> bytes enviados fora do nó; saídas de execução novas (sujeitas ao limite): <limitados> de <limite> bytes`. O limite nunca aparece ao lado do total.
- `render_operation` (`scripts/benchmark/report.py:175-205`) troca a coluna "Egresso (bytes)" por três: "Egresso total (bytes)", "Saídas novas (bytes)" e "Limite de saídas (bytes)" (`sem limite` no modo sem limite). Execuções antigas, sem `bytes_limitados`, mostram `-`.
- A coluna "Cadeia de execuções" mostra `divergente (<motivo principal>)` quando houver `motivos`.

## 4. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `LLM_QUOTA_MARKERS_GOOGLE` | `spending cap` | §1.2 (provisório até a tarefa 1.1) |
| `LLM_QUOTA_MARKERS_ANTHROPIC` | `credit balance is too low` | §1.2 |
| `LLM_QUOTA_MARKERS_OPENAI` | `insufficient_quota` | §1.2 |
| `LLM_QUOTA_MARKERS_OPENAI_COMPATIBLE` | vazio | §1.2 |
| `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS` | `300` | §1.5 |

Todas em `src/config.py` e `.env.example`.

## 5. Testes (sem chamada paga)

- Provedores: clientes simulados (`AsyncMock` do `genai.Client.aio.models.generate_content`, do `anthropic.AsyncAnthropic.messages.create` e `httpx.MockTransport`) que respondem 429 com e sem marcador, 400 de saldo e 200.
- Laço: `UsageTracker` com leitores injetados e `quota_stop_for` preenchido por um provedor falso que levanta `ProviderQuotaExhausted`; confere `motivo_parada`, ausência de replanejamento e de chamada ao Summarizer.
- Telemetria: `emit_connection_retry` dentro de um `AgentContext` vinculado, com `get_telemetry` simulado.
- Proveniência: `LedgerStore` em memória com dois registros reais de `termino` montados por `termino_body` sobre uma pasta temporária.
- Relatório: dicionários de resultado sintéticos para `render_operation` e para a seção Markdown.

## 6. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador e loop autônomo | Novo motivo de parada pelo `pending_stop` existente; fechamento sem LLM nesse motivo; limitador com teto; relato ao limitador ignora cota. Nenhuma mudança no planejamento ou no DAG. |
| Agentes e prompts | Nenhum prompt muda. `AgentRuntime` ganha a categoria `cota_provedor`. |
| Sandbox e containers | Nenhum. A verificação de proveniência lê os mesmos registros; o sandbox e o `collect_inputs`/`collect_outputs` não mudam. |
| Persistência | Um valor aditivo na enumeração `Sessao.motivo_parada` (grafo); chaves aditivas no payload `operation_metrics`; evento novo em `agent_events`. Sem migração; `execution_records` e `egress_log` intactos. |
| Segurança | A mensagem do provedor entra em log, evento e checkpoint: truncada e sem cabeçalhos (ver §7). A correção da verificação não afrouxa a detecção de adulteração de saídas (só a entrada reescrita pela mesma execução deixa de ser comparada). |
| Testes e telemetria | `connection_retry` passa a ser atribuído à sessão certa (corrige um contador que hoje fica em zero); novos contadores e colunas no relatório; testes unitários para cada cenário. |

## 7. Segurança

**Parecer do Analista de Segurança (2026-10-15):** Aprovado com ressalvas, nenhuma delas bloqueante.

1. **Baixo: `detalhe` do provedor.** É truncado, vai sem cabeçalhos e passa pelo filtro de segredos e por `sanitize_text` antes de chegar a log, evento, checkpoint e CLI. Nunca é enviado a LLM nem a registro federado, porque alguns servidores compatíveis ecoam trechos da requisição.
2. **Baixo: marcadores.** A inicialização recusa marcador vazio, com menos de 6 caracteres ou só numérico (por exemplo, `429`), porque ele classificaria todo limite de taxa como cota.
3. **Baixo: regra de proveniência.** O estado `substituido` só vale para caminho dentro da pasta da própria tarefa que aparece em `entradas` e em `saidas` do mesmo registro. Entradas em `/inputs` ou de outras tarefas continuam conferidas contra o disco.

Pontos para o parecer:

- **Vazamento pela mensagem do provedor:** o detalhe do erro pode trazer identificador do projeto ou da conta. Proposta: truncar em 300 caracteres, nunca incluir cabeçalhos nem a requisição, e passar pelo mesmo filtro de segredos do logger. O detalhe não é enviado a nenhum LLM (o fechamento não chama LLM).
- **Negação de serviço por classificação falsa:** um texto de erro que contenha o marcador encerra a sessão. A mensagem vem do provedor por TLS, não do conteúdo pesquisado; o efeito é uma parada retomável. Aceitável.
- **Integridade da proveniência:** a regra nova só marca `substituido` a entrada cujo caminho é também saída do mesmo registro, cujo hash novo continua conferido contra o disco. Uma edição posterior ao `termino` continua `alterado`.
- **Fail-fast:** o esgotamento de cota passa a ser erro explícito e acionável, em vez de falhas silenciosas de subtarefa.

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| O texto real do erro de gasto do Google não contém `spending cap` | Tarefa 1.1 extrai o texto do log antes de fixar o padrão; a variável permite corrigir sem código; `limite_conexao` (§1.6) limita o estrago a cerca de 20 retentativas. |
| Um 429 por minuto é classificado como cota e para a sessão | Marcadores específicos por provedor; teste com o texto do 429 por minuto do Google ("exceeded your current quota, please check your plan and billing details") exige classificação transitória. |
| Corrigir a atribuição de `connection_retry` faz sessões antes estáveis fecharem por `limite_conexao` | É o comportamento especificado desde V18; o relatório da próxima bateria mostra a contagem. Se o limite de 20 se mostrar baixo, ajustar `SESSION_MAX_CONNECTION_RETRIES`. |
| A correção de `_check_files` esconde uma adulteração | Só a entrada de caminho reescrito pela mesma execução deixa de ser comparada; a saída do mesmo registro é comparada. Cenário de regressão cobre a edição posterior. |
| Conflito com `v18.7-exploration-limits`, que também acrescenta valores (`limite_custo`, `saturacao`) a `StopReason`, `Sessao.motivo_parada` e `MOTIVOS_RETOMAVEIS` | Mudanças aditivas nas mesmas listas; quem fizer merge depois rebaseia e mantém todos os valores. Uma aprovação de schema pode cobrir os três valores. |
| A cadeia continua `divergente` por outra causa | `cadeia.motivos` (§2.4) mostra a causa na próxima bateria; tarefa 1.2 olha os dados atuais. |

## 9. Questões em aberto

1. **Texto literal do 429 de teto de gasto do Google** e se ele traz `RetryInfo`/`retryDelay`. Proposta: tarefa 1.1 extrai do `run.log` arquivado; o padrão de `LLM_QUOTA_MARKERS_GOOGLE` é fixado no PR.
2. **Cota diária** (ex.: limite por dia do nível gratuito do Google, `PerDay` na mensagem): não é gasto, mas também não volta na sessão. Proposta: tratar como cota (marcador `PerDay`) só se o pesquisador concordar; por padrão fica como limite de taxa e cai em `limite_conexao`.
3. **Cota de um papel só** (ex.: acabou o saldo da Anthropic, que é só o Validator). Proposta: parar a sessão inteira, porque trocar o juiz quebraria a regra de família do ADR 020; a retomada continua possível depois do ajuste.
4. **Checkpoint de outra cadeia** (§2.3): corrigir só se a tarefa 1.2 mostrar o caso.
5. **Padrão de `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS`**: 300 s proposto; com `SESSION_MAX_CONNECTION_RETRIES=20` o pior caso de espera fica em torno de 20 minutos antes de `limite_conexao`.
