# Design: Robustez do Pipeline de Planejamento, Revisão e Relatório

## 1. Normalizador determinístico de plano (`src/plan_normalizer.py`)

### 1.1 Contrato

```python
@dataclass(frozen=True)
class PlanRepair:
    task_name: str | None     # None = reparo no plano inteiro
    kind: str                 # ver tabela 1.2
    detail: str               # texto curto, sem conteúdo de prompt

@dataclass(frozen=True)
class NormalizedPlan:
    tasks: list[dict[str, Any]]
    repairs: list[PlanRepair]
    unrecoverable: list[str]  # problemas que o normalizador NÃO corrige (viram feedback)

def normalize_plan(raw: Any) -> NormalizedPlan: ...
```

Função **pura** (sem I/O, sem LLM). Chamada em `Orchestrator._run_planning_loop`
(`src/orchestrator.py:740`) logo após `extract_json`, antes de `validate_plan`. Quando
`repairs` não é vazio, emite o evento `plan_normalized` (`payload`: `iteration`, `repairs`
com `kind` e `task_name`, no máximo 20). O plano normalizado é o que o Validator vê, e o que é
reenviado ao planejador em REPLAN.

### 1.2 Reparos permitidos (todos sem perda de informação)

| `kind` | Entrada | Saída |
|---|---|---|
| `unwrap_envelope` | `{"tasks": [...]}`, `{"plan": [...]}`, `{"subtasks": [...]}`, `{"steps": [...]}` com uma única chave de lista | a lista |
| `coerce_list` | `depends_on`, `validation_criteria` ou `expected_artifacts` como string (inclusive separada por vírgula ou quebra de linha, para `depends_on` e `expected_artifacts`) ou `null` | lista de strings; `null` em `depends_on`/`expected_artifacts` vira `[]` |
| `coerce_text` | `hypothesis`/`scientific_rationale` com tipo não texto | `str(...)` |
| `derive_task_name` | `task_name` ausente ou vazio | `<agent_id>_<n>` em snake_case |
| `snake_case_name` | `task_name` fora de snake_case ASCII (`"Carregar Dados"`) | `carregar_dados`, com o mapa antigo → novo aplicado também em `depends_on` |
| `dedupe_name` | nomes repetidos | sufixo `_2`, `_3`, na ordem do plano |
| `drop_unknown_dependency` | `depends_on` que cita nome inexistente | a dependência é removida **somente se** o nome citado casar, após normalização, com outra subtarefa (correção de grafia); caso contrário vai para `unrecoverable` |
| `break_self_dependency` | subtarefa que depende dela mesma | dependência removida |
| `normalize_task_type` | `EDA`, `Reproduction`, `model_implementation`, sinônimos listados na spec | valor canônico (`eda`, `reproduction`, `model_impl`, `validation`, `synthesis`); valor sem equivalente é removido e registrado |
| `normalize_agent_id` | `Developer`, `dev`, `desenvolvedor` | `developer`; id sem equivalente vai para `unrecoverable` |

O que **nunca** é reparado: conteúdo de `prompt`, `validation_criteria` vazio, ausência de
critério quantitativo, ciclos de dependência entre subtarefas distintas, plano sem subtarefas.
Esses casos ficam em `unrecoverable` e o Validator os reprova com a mensagem que já existe,
agora com o campo corrigível explicado (§1.3). Motivo: o princípio 6 do `AGENTS.md`
(nenhum dado inventado) e a regra de que um limiar de aceite é decisão do plano, não do
framework.

### 1.3 Reprovação determinística que se repete

Hoje o plano com `task_type` `validation`/`reproduction` sem limiar numérico é reprovado e o
planejador (por exemplo, GPT-6 Luna) devolve o mesmo plano. Regras novas, em
`ValidatorAgent.validate_plan` e `_run_planning_loop`:

1. Cada reprovação ganha uma **assinatura**: hash estável do conjunto
   `{(task_name, tipo_do_problema)}` (o texto livre não entra). A assinatura vai no evento
   `plan_validation`.
2. Se a assinatura de uma reprovação **determinística** repetir
   `PLAN_REJECTION_STALL_LIMIT` vezes seguidas (padrão 2), o planejamento termina com erro
   explícito e acionável (`PlanningStalled`), contendo os problemas e a correção pedida; o
   ciclo não consome as demais iterações. O erro chega ao pesquisador, como manda o
   princípio 6.
3. O texto de feedback da regra do limiar passa a incluir um exemplo concreto da correção
   (já existe, `validator_agent.py:287`) e a lista das subtarefas afetadas, uma por linha.
4. **Validator LLM consultivo:** se as checagens determinísticas passaram e o Validator LLM
   reprova com a mesma assinatura `PLAN_REJECTION_STALL_LIMIT` vezes seguidas, o plano é
   **aprovado com avisos** (`approved_with_warnings=true`), os problemas do LLM vão para o
   evento e para o relatório. A primeira reprovação do LLM continua valendo normalmente.

### 1.4 Ponto em aberto sobre o limiar numérico

Ver §10, questão 1: o framework pode apenas reprovar (comportamento descrito acima) ou
rebaixar `task_type` para `model_impl` quando a tarefa não tem limiar. A spec adota "apenas
reprovar, com parada explícita" por não inventar semântica; o pesquisador decide.

## 2. Comparador de artefatos (`src/artifact_match.py`)

### 2.1 Contrato

```python
@dataclass(frozen=True)
class ArtifactResolution:
    expected: str
    matched: list[Path]       # relativos à pasta da sessão; vazio = ausente
    tier: str                 # "exact" | "glob" | "normalized" | "extension" | "missing"

def resolve_artifacts(
    expected: list[str], session_dir: Path, task_dir: str | None, mode: str = "tolerant",
) -> list[ArtifactResolution]: ...
```

Função pura sobre o sistema de arquivos. `task_dir` é a pasta da subtarefa (`<task_name>/`) e
tem prioridade; `artifacts/` e a raiz da sessão vêm depois. Arquivos de infraestrutura
(`scientific_helpers.py`, `script.py`, `*.pyc`, `manifest.json`) são ignorados.

### 2.2 Camadas, da mais estrita à mais tolerante

| Camada | Regra | Exemplo |
|---|---|---|
| `exact` | caminho relativo ou nome base idêntico | `metrics.json` |
| `glob` | o esperado contém `*` ou `?` e casa com o nome base | `eda_*.png` ↔ `eda_hist.png` |
| `normalized` | mesmo nome após minúsculas, sem acento e sem `_`, `-`, espaços; mesma extensão | `ConfusionMatrix.PNG` ↔ `confusion_matrix.png` |
| `extension` | existem, na pasta da subtarefa, ao menos tantos arquivos com a **extensão** do esperado quanto o número de esperados com essa extensão que ficaram sem outra resolução | `eda_hist.png`, `eda_box.png` esperados; `iris_hist.png`, `iris_box.png` em disco |

`extension` é a camada que resolve o caso do benchmark (`iris_*.png` no lugar de `eda_*.png`).
Cada arquivo é usado em **uma** resolução. A camada só vale para extensões de artefato de
dados (`png`, `jpg`, `svg`, `csv`, `json`, `md`, `txt`, `html`, `pdf`, `parquet`); nunca para
`.py`. Resolução por `extension` ou `normalized` é **aprovação com aviso**: o veredito fica
`pass`, o resultado traz `name_mismatch` e o evento `subtask_review` lista os pares
esperado → real. Com `mode="strict"` só `exact` e `glob` valem (comportamento anterior).

### 2.3 Propagação para subtarefas dependentes

`SubtaskOutput` ganha `artifact_aliases: dict[str, str]` (esperado → caminho real relativo à
sessão). `_build_context_prefix` (`src/autonomous_loop.py:401`) inclui, para cada dependência, o
trecho `Arquivos produzidos: <esperado> → <real>`, de modo que a subtarefa seguinte use o nome
que existe em disco. O prompt do desenvolvedor já recebe os artefatos parciais por retentativa
(`autonomous_loop.py:802-810`); a lista passa a usar o mesmo mapa.

## 3. Revisão de subtarefa (`ValidatorAgent.review_result`)

Mudanças em ordem de execução:

1. **Resolução de artefatos** com `resolve_artifacts` no lugar da busca por nome
   (`validator_agent.py:441-463`). Ausente = nenhuma camada resolveu. A mensagem de falha lista
   os esperados ausentes **e** o que existe na pasta da subtarefa, para o desenvolvedor
   corrigir na retentativa.
2. **Critério quantitativo exige métrica nomeada.** `_has_quantitative_criterion` continua
   existindo para a regra de plano (§1.3). Para a revisão, nova função
   `_metric_criteria(criteria) -> list[MetricCriterion]` devolve só os critérios cujo nome
   normalizado está em `_METRIC_ALIASES` (`validator_agent.py:62-81`). "Ao menos 3 gráficos"
   não é critério de métrica e segue para o revisor LLM, que recebe a contagem de arquivos na
   evidência.
3. **`metrics.json` da própria subtarefa.** `_resolve_artifact_path` passa a procurar primeiro
   em `<output_dir>/<task_name>/`, depois em `artifacts/`; o de outra subtarefa só vale se
   `depends_on` da tarefa a inclui. Sem arquivo: reprova, como hoje, com a lista do que existe.
4. **Todos os critérios mapeáveis são avaliados**; a subtarefa passa se todos passam. O
   `feedback` lista cada critério com valor real, operador e limiar. Critério com métrica
   nomeada mas ausente de `metrics.json` reprova com mensagem específica (a métrica faltou).
5. **Evidência do revisor LLM** (`build_artifact_evidence`, `validator_agent.py:172-199`)
   recebe as resoluções, não o conjunto de nomes (`wanted`), e inclui `tier` para cada
   arquivo. Hoje o filtro por nome esconde `iris_*.png` do revisor.
6. `divergent_but_documented` mantém o comportamento atual.

O revisor **LLM** continua julgando os critérios qualitativos. Esta mudança não altera o seu
prompt, salvo para informar a regra 2 do §2.2 (nome diferente do esperado não é motivo de
reprovação).

## 4. Disjuntor de progresso

`_run_complex_path` (`autonomous_loop.py:1002-1045`) deixa de comparar `hash(frozenset(
succeeded))`. Novo cálculo, por ciclo de planejamento:

```python
@dataclass(frozen=True)
class CycleProgress:
    succeeded: frozenset[str]
    failure_signatures: frozenset[str]   # hash de (task_name, tipo de erro normalizado)
```

- **Houve progresso** se `succeeded` aumentou **ou** `failure_signatures` mudou (erro
  diferente, subtarefa diferente falhando, revisão que passou a apontar outro critério).
- **Tipo de erro normalizado:** `review:<critério ou artefato>` para reprovação do revisor,
  `agent:<classe da exceção>` para falha do agente, `timeout`, `limit`. Números, caminhos e
  identificadores são removidos do texto antes do hash.
- O disjuntor conta ciclos **consecutivos sem progresso**; dispara ao atingir
  `CIRCUIT_BREAKER_STALL_CYCLES` (padrão 2, hoje implícito em 1 repetição). O primeiro ciclo
  nunca dispara.
- O evento `circuit_breaker` passa a incluir `stalled_cycles`, `succeeded` e
  `failure_signatures` (sem texto de erro).
- A mensagem final aponta as subtarefas e o erro **persistente**, como hoje.

## 5. Limites de execução de agente

### 5.1 Contadores

`Orchestrator._session_agent_run_counts` (`src/orchestrator.py:540-548`) vira dois contadores
por sessão, classificados pelo papel da tarefa e pela origem da chamada:

| Contador | O que conta | Limite |
|---|---|---|
| `planning` | `_execute_agent` chamado de `_run_planning_loop` (Researcher em modo PLAN/REPLAN) | `MAX_PLANNING_RUNS_PER_SESSION` (padrão 20) |
| `execution` | subtarefas do DAG (inclusive retentativas) e síntese final | `max(MAX_AGENT_RUNS_PER_SESSION, n * (1 + SESSION_MAX_TASK_RETRIES) + 2)`, com `n` = subtarefas do plano aprovado mais recente |

`MAX_AGENT_RUNS_PER_SESSION` mantém o padrão 30 como piso; o limite efetivo cresce com o plano.
A chamada de planejamento recebe o rótulo por parâmetro explícito (`run_kind`), não por
adivinhação de `agent_id`.

### 5.2 Ao atingir

`_execute_agent` deixa de lançar `RuntimeError` solto. Lança `AgentRunLimitReached` (subclasse
própria); `AutonomousLoop` a captura e chama `_close_session` com
`StopReason.RUNS = "limite_execucoes"` (novo membro de `src/usage.py:25`), que faz checkpoint
e consolidação com a reserva de tokens, como os demais limites (`v18-usage-limits` §3). A
mensagem inclui o contador, o limite e qual contador estourou. O evento `limit_reached` já
usado para outros limites ganha `limit="agent_runs"` e `kind="planning"|"execution"`.

### 5.3 Observabilidade

O banner da sessão e `_check_operational_thresholds` (`autonomous_loop.py:260-340`) mostram os
dois contadores. O benchmark passa a reportar ambos.

## 6. Modelo estruturado de relatório (`src/report/report_model.py`)

### 6.1 Dados

```python
@dataclass(frozen=True)
class ReportMetadata:
    duration_s: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    agent_runs: dict[str, int]        # por papel
    sandbox_runs: int
    models_by_role: dict[str, str]    # "provedor/modelo"
    stop_reason: str | None
    replans: int

@dataclass(frozen=True)
class ResultRow:
    task_name: str
    metric: str
    value: float | str
    expected: float | None
    divergence_pct: float | None
    source: str                       # caminho relativo do metrics.json

@dataclass(frozen=True)
class ReportData:
    title: str
    request: str
    metadata: ReportMetadata
    results: list[ResultRow]
    divergences: list[dict]           # de divergence_reports e metrics.json
    interactions: list[dict]          # researcher_interactions
    artifacts: list[str]
    references: list[dict]            # fontes com URL, quando houver

@dataclass(frozen=True)
class Narrative:                      # texto livre; `parse_narrative` valida (pydantic não é dependência)
    resumo_executivo: str
    contexto_e_objetivo: str
    metodologia: str
    analise_divergencias: str
    limitacoes: str
    proximos_passos: str
    confianca_nivel: Literal["alto", "medio", "baixo"]
    confianca_justificativa: str
```

### 6.2 Fluxo

1. `build_report_data(session_id)` lê `metrics.json` de cada subtarefa (via `ArtifactReader`),
   a telemetria (`token_usage`, `agent_events`, contagem de `spawn` por papel e de `sandbox_run`)
   e `agent_sessions.payload`. **Nenhum número passa por LLM.**
2. O Summarizer recebe `ReportData` serializado em JSON e **sem ferramentas**; devolve só o
   JSON de `Narrative`. Uma tentativa de reparo (reenvio com o erro de validação); se a
   segunda falhar, `Narrative` é preenchida com `"[narrativa indisponível: <erro>]"` em todos
   os campos e o relatório marca `narrativa_indisponivel=true` em `report_data.json`. Nada é
   inventado e a falha é visível.
3. `render_report_markdown(data, narrative)` produz `relatorio_final.md` com as seções na
   ordem atual (Resumo Executivo, Contexto e Objetivo, Metodologia, Resultados, Análise das
   Divergências, Decisões do Pesquisador, Limitações Identificadas, Próximos Passos Sugeridos,
   Metadados de Execução). Resultados, Decisões do Pesquisador e Metadados vêm só de
   `ReportData`; a seção de metadados lista duração, tokens, custo, execuções de agente por
   papel, execuções no sandbox, modelos por papel e o nível de confiança do `Narrative`.
4. `report_data.json` é gravado ao lado, para auditoria e para a avaliação de comunicação.

O conversor existente (`src/report/*_converter.py`) segue lendo `relatorio_final.md`, sem mudança
de contrato.

### 6.3 Evento `sandbox_run`

O sandbox (`src/skills/code/`) hoje não emite evento por execução. Cada execução emite
`sandbox_run` (`payload`: `task_name`, `exit_code`, `duration_ms`, `timed_out`), sem conteúdo
do script. Alimenta a contagem do relatório e a verdade determinística da avaliação.

## 7. Configuração (`src/config.py`, `.env.example`)

| Variável | Padrão | Uso |
|---|---|---|
| `PLAN_NORMALIZER_ENABLED` | `true` | liga o normalizador; `false` reproduz o comportamento anterior |
| `PLAN_REJECTION_STALL_LIMIT` | `2` | reprovações idênticas seguidas até parar (determinística) ou aprovar com avisos (LLM) |
| `ARTIFACT_MATCH_MODE` | `tolerant` | `tolerant` ou `strict` |
| `CIRCUIT_BREAKER_STALL_CYCLES` | `2` | ciclos consecutivos sem progresso até encerrar |
| `MAX_AGENT_RUNS_PER_SESSION` | `30` (existente) | piso do limite de execuções de subtarefa |
| `MAX_PLANNING_RUNS_PER_SESSION` | `20` | limite de execuções de planejamento |

## 8. Análise de impacto nos 6 eixos

| Eixo | Avaliação |
|---|---|
| Segurança | Nenhuma superfície nova: funções puras e leitura de nomes de arquivo dentro da pasta da sessão; o comparador resolve caminhos com `Path.resolve` e rejeita saída da pasta (`..`, links simbólicos para fora). O relatório deixa de aceitar números de LLM. |
| Desempenho | Comparador lê só nomes; relatório faz uma chamada LLM a menos de formatação. Normalizador é O(n) sobre o plano. |
| Persistência | Sem schema novo. `report_data.json` e eventos novos são aditivos. |
| Compatibilidade | Chaves `strict`/`PLAN_NORMALIZER_ENABLED=false` preservam o comportamento antigo; `StopReason` ganha um membro (consumidores do `motivo_parada` devem tolerar valor novo). |
| Observabilidade | Quatro eventos novos ou ampliados; o benchmark e a avaliação de comunicação os consomem. |
| Testabilidade | Todas as regras são funções puras ou usam `tmp_path`; provedor LLM simulado pelas fixtures existentes. Nenhum teste chama rede paga. |

## 9. Segurança e riscos

- **Parecer do Analista de Segurança:** a mudança não toca sandbox, rede, permissões, segredos
  nem banco; revisão formal só do comparador (travessia de caminho) e do evento `sandbox_run`
  (sem conteúdo de script), no PR de implementação.
- **Risco:** a camada `extension` aprovar artefato errado (um PNG qualquer no lugar do esperado).
  Mitigação: o revisor LLM ainda avalia o conteúdo quando há critério qualitativo; o veredito
  carrega `name_mismatch`; a avaliação de comunicação mede falsos aceites.
- **Risco:** o normalizador mascarar uma regressão do planejador. Mitigação: cada reparo é
  registrado e contado (`plan_normalized`), e o relatório de avaliação mostra a taxa de reparo
  por modelo.
- **Risco:** aprovar plano com avisos deixar passar plano ruim. Mitigação: só vale para o
  Validator LLM depois de repetição idêntica, e os avisos vão ao relatório.
- **Risco:** o piso derivado do limite de execuções permitir sessões longas. Mitigação: tokens
  e minutos continuam limitados por `v18-usage-limits`.

## 10. Decisões do pesquisador e questões em aberto

**Decididas em 2026-10-05:** (1) `validation`/`reproduction` sem limiar numérico: apenas
reprovar e parar com erro explícito, sem rebaixar `task_type`; (2) camada `extension` do
comparador mantida; (3) `OLLAMA_NUM_CTX` para modelos de nuvem fica fora desta mudança.
O texto abaixo é o original, mantido para rastreabilidade.

1. **Tarefa `validation`/`reproduction` sem limiar numérico:** apenas reprovar e parar com erro
   explícito (adotado), ou rebaixar o `task_type` para `model_impl` com registro? A segunda
   opção deixa a sessão andar, mas altera a semântica do plano.
2. **Camada `extension` do comparador:** aceitar por extensão equivalente (adotado) ou parar na
   camada `normalized` e deixar o revisor LLM decidir? A primeira resolve o caso Iris; a
   segunda é mais conservadora.
3. **`OLLAMA_NUM_CTX=4096` aplicado a modelos de nuvem** (`src/llm/agent_loop.py:269`):
   separar a janela de contexto por tipo de provedor nesta mudança ou em outra? Fora do escopo
   até a decisão.
4. **`CIRCUIT_BREAKER_STALL_CYCLES=2` e `PLAN_REJECTION_STALL_LIMIT=2`:** valores iniciais; a
   próxima avaliação mostra se bastam.
