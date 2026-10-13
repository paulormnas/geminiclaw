# Design: Métricas de Operação por Sessão e Modo Sem Limite

## 0. Estado atual do código (2026-09-29)

| Ponto | Onde | Situação |
|---|---|---|
| Orçamento | `src/usage.py:34-73` | `UsageBudget` congelado; `__post_init__` rejeita qualquer limite ≤ 0 — não há como expressar "sem limite". |
| Teto de exploração | `src/usage.py:75-82` | `exploration_token_ceiling` sempre numérico. |
| Verificação de limites | `src/usage.py:341-391` | `check()` avalia tokens, tempo e conexão; `stop_reason` com prioridade tokens > tempo > conexão (`src/usage.py:168-181`). Não há limite de egresso. |
| Reserva esgotada | `src/usage.py:393-400` | `tokens_hard_exhausted()` compara com `max_tokens`. |
| Motivos de parada | `src/usage.py:25-31` | `limite_tokens`, `limite_tempo`, `limite_retentativas`, `limite_conexao`. |
| Motivos no grafo | `src/knowledge/schema.py:127-136` | Enum de `Sessao.motivo_parada` sem `sem_caminhos_promissores`, `limite_egresso`, `interrompida_pesquisador`. |
| CLI do orçamento | `src/cli.py:189-218`, `src/cli.py:221-238`, `src/cli.py:1090-1097` | `--max-*` e `build_usage_budget`; orçamento inválido encerra com erro. |
| Banner | `src/cli.py:729-782` | Linha "Orçamento" com tokens, minutos e retentativas. |
| Ctrl+C | `src/cli.py:1102-1130` | Para containers, faz flush da telemetria e `sys.exit(130)` — sem checkpoint. |
| Orçamento no loop | `src/autonomous_loop.py:90-98` | `UsageTracker` criado por sessão com `execution_id=master_session_id`. |
| Avisos G5 | `src/autonomous_loop.py:256-336` | Lê `SESSION_MAX_TOKENS`/`SESSION_MAX_MINUTES` de `config` (não do orçamento efetivo); custo é só aviso (`cost_usd`). |
| Timeout do ciclo | `src/autonomous_loop.py:936-945` | `gather_timeout` depende de `budget.max_minutes`. |
| Fechamento | `src/autonomous_loop.py:1125-1240` | Grava `motivo_parada` e `checkpoint` no payload e em `checkpoint.json`. |
| Estatísticas ao Summarizer | `src/autonomous_loop.py:1476-1478`, `src/telemetry.py:1075-1108` | Texto com tokens, custo, temperatura enviado ao LLM para reescrever. |
| `session_metadata.json` | `src/orchestrator.py:440-468` | Tokens, custo, interações, divergências; sem métricas do §8. |
| Tokens por tarefa | `src/telemetry.py:127-146`, `src/telemetry.py:1015-1040` | `token_usage.task_name`, `subtask_metrics.total_tokens/total_cost_usd`. |
| Hardware | `src/telemetry.py:149-163`, `src/telemetry.py:888-915` | Picos de temperatura, CPU e memória por `execution_id`. |
| Interações humanas | `src/orchestrator.py:458-459`, `src/orchestrator.py:506-545` | `researcher_interactions` e `divergence_reports` no payload. |
| IPC | `src/ipc.py:15-19` | Tipos de mensagem permitidos; nenhum altera orçamento. |
| Configuração | `src/config.py:161-186`, `src/config.py:277-291`, `.env.example:99-126` | Limites e avisos G5. |

## 1. Métricas de operação (§8)

### 1.1 Estrutura

Gravada em `agent_sessions.payload["operation_metrics"]` (JSONB, sem mudança de schema) e
copiada para `session_metadata.json` (`src/orchestrator.py:447-468`):

```json
{
  "versao": 1,
  "gerado_em": "ISO-8601",
  "parcial": false,
  "egresso": {
    "estado": "disponivel",
    "bytes_total": 0,
    "por_destino": [
      {"provedor": "…", "modelo": "…", "trust": "third_party", "localidade": "fora_do_no",
       "bytes": 0, "chamadas": 0}
    ],
    "por_origem": {"instrucao": 0, "documento": 0, "esquema_agregado": 0, "codigo": 0,
                    "saida_execucao": 0, "grafo": 0, "dado_de_pesquisa": 0},
    "intervencoes_filtro": {"<tipo definido por v18.5-egress-gate>": 0},
    "consultas_busca": 0,
    "chamadas_visao": 0,
    "limite_bytes": 0
  },
  "proveniencia": {
    "estado": "disponivel",
    "numeros_por_origem": {"res": 0, "calc": 0, "src": 0},
    "numeros_nao_verificados": 0,
    "metricas_literais": 0,
    "cadeia": {"resultado": "integra | divergente | nao_verificada", "orfas": 0,
               "pendentes": 0, "ponta": "<hash>"}
  },
  "verificacao": {
    "estado": "disponivel",
    "afirmacoes_por_status": {"suportada": 0, "parcial": 0, "refutada_deterministica": 0,
                              "contestada": 0, "nao_verificavel": 0, "pendente": 0},
    "ciclos_correcao_conclusoes": [{"conclusao_id": "…", "ciclos": 0, "aprovada": true}],
    "ciclos_rejeicao_plano": 0
  },
  "custo_recursos": {
    "estado": "disponivel",
    "tokens_total": 0, "custo_usd_total": null,
    "por_tarefa": [{"task_name": "…", "agent_id": "…", "tokens": 0, "custo_usd": null}],
    "por_papel": [{"agent_id": "…", "tokens": 0, "custo_usd": null}],
    "no": {"cpu_pct_medio": null, "cpu_pct_pico": null, "ram_pct_pico": null,
           "ram_disponivel_min_mb": null, "temperatura_pico_c": null,
           "incidentes_throttling": 0}
  },
  "intervencoes_humanas": {
    "estado": "disponivel",
    "aprovacoes": 0, "rejeicoes": 0, "edicoes": 0,
    "respostas_ask_researcher": 0, "decisoes_divergencia": 0,
    "suspensoes": 0, "interrupcoes": 0,
    "eventos": [{"tipo": "…", "em": "ISO-8601", "referencia": "…"}]
  },
  "modo_sem_limite": {"ativo": false, "origem": null, "confirmado_em": null,
                      "avisos_emitidos": 0}
}
```

- **Custo** `null` quando o provedor não informa (`estimated_cost_usd` só existe para nuvem —
  `src/telemetry.py:141`); nunca somado como zero. O total é `null` se nenhuma chamada tiver
  custo, e a seção indica quantas chamadas ficaram sem custo informado.
- **Hardware** `null` quando o sensor não existe (ex.: temperatura fora do Pi).
- **Chamadas de verificação** (Validator sobre conclusões) entram em `por_papel` e
  `por_tarefa` como qualquer chamada, pela telemetria existente.

### 1.2 Grupo indisponível

Cada grupo tem `estado`: `disponivel`, `indisponivel` (produtor não implementado ou desligado)
ou `erro` (falha de leitura, com mensagem). Um grupo `indisponivel` ou `erro` não tem valores
numéricos: o relatório mostra "indisponível (<mudança>)" ou "erro de leitura: <mensagem>".
Isso segue o princípio *fail-fast* do AGENTS.md: nenhum zero inventado.

Falha de leitura de um grupo não impede os demais nem o fechamento; é registrada em log
`ERROR` e evento de telemetria `operation_metrics_error`.

### 1.3 Momentos de agregação

- **Fechamento** (`_close_session`, `src/autonomous_loop.py:1125`) e fim normal da sessão
  (`src/orchestrator.py:365-468`): agregação completa, `parcial=false`.
- **Avisos do modo sem limite** (§2.5): agregação dos grupos baratos (custo, egresso),
  `parcial=true`.
- **Sessão interrompida por queda** (detectada por `v18-research-continuity`):
  `geminiclaw --metrics <id>` (`src/cli.py:343`) recalcula a partir dos produtores e grava com
  `parcial=true`, porque o fechamento não ocorreu.

A agregação é idempotente: recalcular sobrescreve o conteúdo da chave.

## 2. Modo sem limite (§11)

### 2.1 Orçamento

```python
# src/usage.py
@dataclass(frozen=True)
class UsageBudget:
    max_tokens: int | None            # None somente com unlimited=True
    max_minutes: float | None         # None somente com unlimited=True
    max_task_retries: int             # sempre positivo
    max_connection_retries: int       # sempre positivo
    closing_reserve_pct: float
    max_egress_bytes: int | None = None   # de EGRESS_SESSION_MAX_BYTES; None somente com unlimited
    unlimited: bool = False
```

Validação (`__post_init__`):

- `unlimited=False`: `max_tokens`, `max_minutes` e `max_egress_bytes` positivos (como hoje,
  `src/usage.py:64-73`). `max_egress_bytes` é obrigatório a partir desta mudança.
- `unlimited=True`: `max_tokens`, `max_minutes` e `max_egress_bytes` **devem** ser `None`;
  `max_task_retries` e `max_connection_retries` continuam positivos.
- `from_config(unlimited=True, max_tokens=...)` com qualquer override de tokens, tempo ou
  egresso levanta `ValueError` ("opções --max-tokens/--max-minutes são incompatíveis com
  --unlimited"). A CLI mostra o erro e encerra, como já faz em `src/cli.py:1092-1097`.

Efeitos no `UsageTracker` e em `LimitStatus`:

| Item | `unlimited=False` | `unlimited=True` |
|---|---|---|
| `exploration_token_ceiling` | como hoje | `None` |
| `tokens_exhausted`, `time_exhausted`, `egress_exhausted` | avaliados | sempre `False`; `*_pct` = `None` |
| `connection_retries_exhausted` | avaliado | avaliado |
| `task_retries_exhausted` | avaliado | avaliado |
| `tokens_hard_exhausted()` | como hoje | `False` (fechamento sempre com tokens) |
| `gather_timeout` (`src/autonomous_loop.py:941-945`) | tempo restante + carência | sem timeout |
| `MAX_PLAN_RETRIES` (rejeições consecutivas do Validator) e circuit breaker de progresso zero (`src/autonomous_loop.py:1005-1030`) | mantidos | mantidos |

`to_payload()` grava `unlimited`, os limites como `null` e a origem da ativação (§2.2).

**Custo:** hoje não há limite de parada por custo, só o aviso `cost_usd` da G5
(`src/config.py:279`). No modo sem limite esse aviso por limiar não é emitido (é substituído
pelos avisos periódicos, que incluem o custo). Esta mudança **não** cria limite de custo (ver
questão em aberto 1).

### 2.2 Ativação

Duas origens, ambas explícitas e sempre com confirmação **no início de cada execução**:

1. **Por sessão:** `geminiclaw --unlimited "<prompt>"`, `geminiclaw resume --session <id>
   --unlimited`, `geminiclaw continue --project <id> --unlimited`.
2. **Por projeto:** `geminiclaw project unlimited <projeto_id> --on|--off`, comando
   determinístico (ator pesquisador, auditado, como os comandos de oportunidade da
   `v18-hypothesis-loop` §7). Grava no nó `Projeto` `modo_sem_limite` (bool),
   `modo_sem_limite_decidido_em`, `modo_sem_limite_decidido_por`. Depende de
   `v17-research-project`; se o nó `Projeto` ainda não existir, o comando falha com erro
   acionável e só a opção por sessão fica disponível.

Confirmação (em `src/cli.py`, antes de criar o orquestrador):

```
⚠ MODO SEM LIMITE: tokens, tempo, custo e volume de egresso não interrompem a sessão.
  Retentativas por tarefa (3) e de conexão (20) continuam limitadas.
  As regras de localidade dos dados continuam valendo.
  Avisos de consumo a cada 15 min ou 500 000 tokens.
  Digite "sem limite" para confirmar:
```

- Resposta diferente, EOF ou ausência de TTY (`sys.stdin.isatty()` falso): a sessão **não
  inicia** (sai com código 2 e mensagem acionável). O modo nunca cai silenciosamente para o
  modo limitado, porque o pesquisador pediu outra coisa (ver questão em aberto 2).
- Retomada **não herda** o modo da sessão anterior: `resume`/`continue` usam orçamento novo
  (`v18-usage-limits` design §1); o modo só vale se `--unlimited` for passado ou o projeto
  estiver marcado, e sempre com nova confirmação.

Gravado em `payload["budget"]`: `{"unlimited": true, "unlimited_origem": "cli" | "projeto",
"unlimited_confirmado_em": "ISO-8601"}` e evento de telemetria `unlimited_mode_confirmed`.

### 2.3 Nunca ativado por agente

- **Não existe** variável de ambiente nem chave de `config` que ative o modo (ativar "por
  padrão" seria possível por `.env`). `SESSION_*` continuam só com limites numéricos.
- `UsageBudget` é congelado e criado só na CLI (`src/cli.py:221-238`) antes do orquestrador; o
  `AutonomousLoop` o recebe pronto (`src/autonomous_loop.py:96-97`).
- Nenhum tipo de mensagem IPC (`src/ipc.py:15-19`), ferramenta de agente ou campo de plano
  altera o orçamento. Um plano ou resposta de agente que mencione "sem limite" não tem efeito;
  teste garante que o orçamento no fim da sessão é igual ao do início.
- O comando de projeto é determinístico e só é chamado pela CLI, nunca exposto como
  ferramenta.

### 2.4 Critérios de parada mantidos

No modo sem limite a sessão para por:

- `solucao_encontrada` e `sem_caminhos_promissores` (`v18-hypothesis-loop` design §8);
- `limite_retentativas` (todas as pendentes abandonadas) e `limite_conexao`;
- interrupção pelo pesquisador (§2.6);
- circuit breaker de progresso zero e rejeições consecutivas do Validator (existentes).

A V18 completa é pré-requisito (roadmap V18.5). Sem os critérios da `v18-hypothesis-loop`
implementados, `--unlimited` é recusado com erro acionável, para não deixar a sessão sem
nenhum critério de término por resultado.

### 2.5 Avisos periódicos de consumo

| Variável (`src/config.py`) | Default proposto | Significado |
|---|---|---|
| `UNLIMITED_NOTICE_INTERVAL_MINUTES` | 15 | Aviso a cada N minutos de relógio |
| `UNLIMITED_NOTICE_TOKEN_STEP` | 500000 | Aviso a cada vez que o total cruza um múltiplo de N tokens |

O que ocorrer primeiro dispara o aviso; ambos reiniciam após cada aviso. Valores ≤ 0 são
rejeitados na inicialização (`ValueError`): não há como desligar os avisos no modo sem limite.
A verificação é feita no mesmo ponto das verificações de limite (antes de cada despacho e de
cada ciclo, `src/autonomous_loop.py:526`, `:607`, `:684`).

Conteúdo do aviso: tempo decorrido, tokens, custo (ou "não informado"), bytes de egresso,
ciclos concluídos, hipóteses em teste. Os números vêm da agregação parcial (§1.3).

- Exibido no terminal **em todos os modos** (diferente dos avisos G5, que em `semi`/`auto`
  só vão ao log — `src/autonomous_loop.py:314-316`), porque no modo sem limite o consumo é a
  informação de risco.
- No `assisted`, reaproveita o mecanismo da G5: "Digite 's' para suspender", com espera de
  `OPERATIONAL_THRESHOLD_WAIT_SECONDS` (`src/autonomous_loop.py:322-336`); suspensão faz o
  fechamento com checkpoint.
- Em `semi`/`auto`, não bloqueia.
- Evento `unlimited_notice` na telemetria; contador em `operation_metrics.modo_sem_limite`.

### 2.6 Interrupção sem perda de avanço

Em qualquer modo (não só no sem limite):

- **Primeiro Ctrl+C:** o handler (`src/cli.py:1102`) sinaliza o loop, que para de despachar,
  aguarda as subtarefas em andamento até `LIMIT_GRACE_SECONDS` e executa `_close_session` com
  `motivo_parada="interrompida_pesquisador"` (checkpoint + agregação de métricas).
- **Segundo Ctrl+C:** comportamento atual (encerramento imediato, `exit 130`). A sessão fica
  `active` com batimento parado e é marcada `interrompida` por `v18-research-continuity`.

A interrupção conta em `intervencoes_humanas.interrupcoes`.

### 2.7 Exibição

- **Banner** (`src/cli.py:771-778`): linha "Orçamento: **SEM LIMITE** de tokens, tempo, custo
  e egresso │ 3 retentativas/tarefa │ 20 retentativas de conexão │ avisos a cada 15 min /
  500 000 tokens", em destaque (amarelo), com a origem (sessão ou projeto).
- **Sessão:** `payload["budget"]` (§2.2) e `operation_metrics.modo_sem_limite`.
- **Relatório:** primeira linha da seção "Métricas de operação" indica o modo e a origem.

### 2.8 Localidade não é afetada

O modo sem limite só altera `UsageBudget`/`UsageTracker`. O `EgressGate`
(`v18.5-egress-gate`) continua aplicando filtros, regras de `aceita_dados_brutos`, reaplicação
por destino e registro em `egress_log`; ele não recebe o orçamento como parâmetro. Apenas
`max_egress_bytes=None` deixa de parar a sessão; o volume continua registrado e exibido.

## 3. Limite de egresso como condição de parada

Divisão com `v18.5-egress-gate` (decidida na consolidação das specs V18.5):

- **`v18.5-egress-gate` é dona do limite:** `EGRESS_SESSION_MAX_BYTES`, o que conta como
  "saída de execução", `egress_bytes_for_session(session_id) -> int`,
  `UsageBudget.max_egress_bytes`, o leitor injetável no `UsageTracker` (como
  `connection_retry_reader`, `src/usage.py:226-256`) e `StopReason.EGRESS = "limite_egresso"`.
- **Esta mudança** só acrescenta o modo sem limite sobre esses campos
  (`max_egress_bytes=None` quando `unlimited=True`), a prioridade em `stop_reason`
  (tokens > tempo > egresso > conexão), a opção `--max-egress-bytes` na CLI (incompatível com
  `--unlimited`) e a apresentação do volume nas métricas.
- Comportamento igual ao de tokens: não despacha nova chamada externa, aguarda as em
  andamento, fechamento com checkpoint; retomável (`v18-research-continuity`).

## 4. Produtores e interface de leitura

`src/operation_metrics.py`:

```python
class MetricsGroupReader(Protocol):
    grupo: str        # "egresso" | "proveniencia" | "verificacao" | "custo_recursos" | "intervencoes_humanas"
    produtor: str     # id da mudança, para a mensagem "indisponível"
    def read(self, session_id: str) -> dict: ...   # levanta MetricsUnavailable se o produtor não existe

def aggregate_operation_metrics(session_id: str, *, parcial: bool,
                                readers: Sequence[MetricsGroupReader] | None = None) -> dict
def render_operation_metrics_section(metrics: dict) -> str   # Markdown determinístico
```

| Grupo | Produtor | Fonte |
|---|---|---|
| egresso | `v18.5-egress-gate` | `egress_log` por `session_id` |
| proveniencia.numeros_*, metricas_literais | `v18.5-numeric-references` | resultado do verificador de números |
| proveniencia.cadeia | `v18.5-execution-provenance` | `provenance verify` do projeto no fechamento |
| verificacao | `v18.5-claim-verification` | afirmações da sessão e ciclos por conclusão |
| verificacao.ciclos_rejeicao_plano | existente | eventos `replan_triggered` / iterações do Validator (`src/telemetry.py:938-951`, `src/orchestrator.py:1245-1246`) |
| custo_recursos | existente | `token_usage`, `subtask_metrics`, `hardware_snapshots` (`src/telemetry.py:823-915`, `:1015-1040`) + consulta nova de média de CPU |
| intervencoes_humanas | existente + `v18-hypothesis-loop` | `researcher_interactions`, `divergence_reports`, aprovações/rejeições/edições de hipótese e oportunidade, suspensões, interrupções |

Os leitores registrados por padrão ficam numa lista em `src/operation_metrics.py`; cada
mudança produtora acrescenta o seu ao ser implementada. Até lá, o grupo aparece como
`indisponivel`.

## 5. Seção do relatório

- `render_operation_metrics_section` gera a seção **"Métricas de operação"** e o orquestrador
  a **acrescenta** ao `relatorio_final.md` depois da saída do Summarizer. O LLM não escreve
  esses números.
- `get_summarized_stats` (`src/telemetry.py:1075`) deixa de ser injetado no prompt do
  Summarizer (`src/autonomous_loop.py:1478`); a função continua para `--metrics`.
- A seção é delimitada (`<!-- operation-metrics:begin -->` … `<!-- operation-metrics:end -->`)
  para que o verificador de números de `v18.5-numeric-references` a trate como contagens do
  orquestrador (números estruturais excluídos pelo ADR 019 §2). **Dependência de acordo** com
  aquela mudança.
- Conteúdo: modo e origem; motivo de parada; tabelas por grupo; grupos indisponíveis com o
  motivo; aviso se `parcial=true`.
- Sessão continuada (`continues_session_id`): a seção mostra a sessão e, em linha separada,
  a soma de tokens, custo e egresso da cadeia de sessões do projeto (informativo).
- Conversores (`src/report/*_converter.py`) recebem a seção como Markdown comum.

## 6. Correção dos avisos G5

`_check_operational_thresholds` (`src/autonomous_loop.py:256-336`) passa a usar
`self._usage_tracker.check()` para percentuais (orçamento efetivo, incluindo overrides da
CLI). No modo sem limite, os avisos percentuais de tokens e tempo e o aviso de custo não são
emitidos; `container_count_pct` continua.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Orçamento com `unlimited`; limite de egresso no tracker; avisos periódicos; Ctrl+C gracioso; agregação no fechamento. |
| Agentes & Prompts | Summarizer deixa de receber estatísticas de telemetria. Nenhuma ferramenta nova. |
| Sandboxes & Containers | Nenhum. |
| Persistência | `payload["operation_metrics"]`, campos do modo em `payload["budget"]`, `session_metadata.json`; propriedades do nó `Projeto`; valores novos em `Sessao.motivo_parada`. |
| Segurança | Modo só por ação explícita do pesquisador com confirmação; sem ativação por env ou agente; localidade intacta; retentativas limitadas contra laços. |
| Testes & Telemetria | Eventos `unlimited_mode_confirmed`, `unlimited_notice`, `operation_metrics_error`; leitores injetáveis para teste. |

## Riscos

- **Consumo alto no modo sem limite** sem ninguém olhando (modo `auto`): mitigado pelos
  avisos obrigatórios, pelos critérios de parada da V18, pelas retentativas limitadas e pela
  confirmação por execução. Não elimina o risco; é a escolha do pesquisador.
- **Produtores ainda não implementados:** grupos `indisponivel`, visíveis no relatório.
- **Divergência de contrato com `v18.5-egress-gate`** sobre onde fica a parada de egresso
  (§3): resolver antes de implementar a que vier por último.
- **Ctrl+C gracioso pode demorar** até `LIMIT_GRACE_SECONDS`: o segundo Ctrl+C mantém a saída
  imediata.

## Questões em aberto (para o pesquisador)

1. **Limite de custo:** hoje custo é só aviso (`src/config.py:279`). O ADR 019 §11 fala em
   remover o limite de custo no modo sem limite, mas não existe limite de parada por custo.
   Criar `SESSION_MAX_COST_USD` como condição de parada fica fora desta mudança, salvo decisão
   contrária.
2. **Execução sem terminal:** a confirmação interativa impede o modo sem limite em execuções
   em segundo plano. Uma alternativa seria um arquivo de confirmação assinado por sessão; não
   foi incluída para não criar um caminho de ativação sem presença do pesquisador.
3. **Cadência dos avisos:** os defaults de 15 min e 500 000 tokens são propostas.
4. **Ctrl+C gracioso para todos os modos:** a mudança vale fora do modo sem limite também,
   porque o §11 exige interrupção sem perda de avanço e o comportamento atual perde o avanço
   desde o último checkpoint.
