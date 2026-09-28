# Design: Ingestão Determinística de Fatos Estruturais

Todas as escritas usam `Actor(kind="orquestrador")`, exceto `Abordagem`, que é declarada pelo
Researcher no plano (`Actor(kind="agente", role="researcher")`).

## 1. Pontos de ingestão

| Momento | Onde | Escreve |
|---|---|---|
| Início da sessão | `Orchestrator.handle_request` | `Sessao` (`modo`, `inicio`, `no_execucao`) + `Sessao-PERTENCE_A->Projeto`; se o payload tiver `continues_session_id`, `Sessao-CONTINUA->Sessao` |
| Snapshot de insumos | `Orchestrator._snapshot_input_context` | um `Insumo` por arquivo + `Projeto-RECEBEU->Insumo` (deduplicado por `hash_conteudo` no projeto) |
| Subtarefa revisada | `AutonomousLoop`, após `_review_subtask` | `Experimento` + `EXECUTADO_EM`; `Resultado` por métrica + `PRODUZIU` + `MEDE`; `Abordagem` + `APLICOU`; `USOU` por dataset; `TESTA` para a hipótese da subtarefa (ver §5) |
| Fim da sessão | `Orchestrator.handle_request` (finally) | `Sessao.fim`, `motivo_parada`, `consumo` |

Subtarefas sem código experimental (ex.: `synthesis`) geram `Experimento` só se houver
`metrics.json`; caso contrário não geram nós.

## 2. Mapeamentos

**`Insumo.tipo`** pela extensão: `.csv .tsv .xlsx .xls .ods .json .jsonl .parquet` →
`dataset`; `.pdf .docx .md .txt .rst` → `artigo`; demais → `outro`. `titulo` = nome do
arquivo; `hash_conteudo` = sha256; `caminho` = caminho relativo em `input_snapshot/`.

**`Experimento`**:

| Campo | Origem |
|---|---|
| `subtarefa_id` | `AgentTask.subtask_id` (chave de idempotência) |
| `status` | Validator: `pass` → `sucesso`; `divergent_but_documented` → `divergente_documentado`; `fail`/erro → `falha` |
| `causa_falha`, `assinatura_falha` | §3 |
| `hash_params` | sha256 do JSON canônico (chaves ordenadas) de `params.json["parameters"]` |
| `seed` | `params.json["seed"]` |
| `hash_codigo` | sha256 dos scripts executados, pelo `WorkspaceManifest` |
| `ambiente` | `{"python": ..., "imagem_sandbox": ..., "pacotes": [...]}` da execução do sandbox |
| `caminho_artefatos` | diretório da subtarefa em `outputs/<sessão>/` |
| `no_execucao` | `config.NODE_ID` |
| `dataset_ids` | `Insumo`s cujos nomes aparecem em `params.json["datasets"]` |

**`Resultado`** — um por chave de `metrics.json["metrics"]` com valor numérico:
`nome_original`, `valor`, `baseline` = `metrics.json["baselines"][nome]` se existir,
`status_validacao` (`validado` se o Validator aprovou ou avaliou o critério quantitativo,
`divergente_documentado`, ou `nao_validado`), `caminho_metrics`. Métrica canônica por
`vocabulary.resolve_metric` → `MEDE`.

**`Abordagem` + `APLICOU`** — do campo `approach` da subtarefa no plano:

```json
"approach": {"nome": "gradient boosting", "tipo": "algoritmo"}
```

Resolução: nome normalizado exato ou sinônimo entre `Abordagem`s existentes; senão, cria
(`Actor` researcher, `justificativa_criacao = "declarada no plano da subtarefa <task_name>"`,
`nos_consultados` = candidatos verificados). A deduplicação semântica fina é do Curator.
`APLICOU.config` = `config_normalizada` (§4); `APLICOU.hash_params` = `hash_params`.

## 3. Causa da falha (determinística)

| Condição | `causa_falha` | `assinatura_falha` |
|---|---|---|
| Erro de conexão/timeout do provedor LLM após retentativas; erro do daemon Docker; sandbox não iniciou; sessão interrompida (sinal, queda de energia detectada na retomada) | `infraestrutura` | categoria do erro (ex.: `llm_connection`, `docker_unavailable`) |
| Código executou no sandbox e terminou com exceção (traceback no stderr) | `abordagem` | tipo da exceção (ex.: `MemoryError`, `ValueError`) |
| Sandbox encerrado por memória (exit 137) ou timeout de execução do código | `abordagem` | `oom` ou `timeout_execucao` |
| Execução terminou sem `metrics.json`, ou o Validator não conseguiu avaliar | `ambigua` | `sem_metricas` ou `validacao_indeterminada` |

A `PythonSandbox` passa a devolver `exit_code`, `oom_killed` e `exception_type` estruturados
(hoje só texto), para que a classificação não dependa de heurística sobre mensagens.

## 4. Configuração normalizada

`config_normalizada` = `params.json["parameters"]` sem chaves que **não** descrevem o método:
nomes que casam `(?i)(seed|random_state|path|file|dir|output|input|timestamp|session)`.
Valores numéricos preservados; ordem de chaves canônica.

## 5. Hipótese testada (V17, provisório)

Até o ciclo de hipóteses (V18), a ingestão cria um `Hipotese` a partir do campo `hypothesis`
da subtarefa quando ele não é vazio: busca por texto idêntico no projeto; se não existir, cria
com `origem="researcher"`, `status="em_teste"`, `justificativa` = `scientific_rationale`.
`Experimento-TESTA->Hipotese`. Na V18 esta regra é substituída pelas hipóteses formais.

## 6. Contrato de artefatos (Spec G2) — acréscimos

```python
save_experiment_artifacts(
    task_name, params, metrics, output_dir="/outputs", seed=None, divergence_note=None,
    datasets: list[str] | None = None,        # nomes de arquivos de input_snapshot/ usados
    baselines: dict[str, float] | None = None # baseline por métrica, quando houver
)
```

`params.json` ganha `datasets`; `metrics.json` ganha `datasets` e `baselines`. Arquivos antigos
sem esses campos continuam válidos. A instrução do Developer passa a pedir esses campos.

## 7. Idempotência e falhas

- Chaves: `Sessao` por `session_id`; `Insumo` por (`projeto_id`, `hash_conteudo`);
  `Experimento` por `subtarefa_id`; `Resultado` por (`subtarefa_id`, `nome_original`).
  Reingestão não duplica.
- Qualquer erro de escrita no grafo **não interrompe a sessão**: o evento é gravado em
  `outputs/<sessão>/knowledge_pending.jsonl` e um aviso é registrado.
- `geminiclaw knowledge sync [--session ID]` reprocessa os pendentes (idempotente).

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Chamadas de ingestão em quatro pontos; nenhuma mudança de fluxo. |
| Agentes & Prompts | Campo `approach` no plano; Developer informa `datasets`/`baselines`. |
| Sandboxes & Containers | Sandbox devolve saída estruturada (`exit_code`, `oom_killed`, `exception_type`). |
| Persistência | Nós e arestas de fatos; arquivo local de pendências. |
| Segurança | Escritas só por operações tipadas; valores vindos de artefatos são dados, nunca consulta. |
| Testes & Telemetria | Telemetria do tempo de ingestão; testes de idempotência e de classificação de falhas. |
