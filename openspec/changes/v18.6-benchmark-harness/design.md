# Design: v18.6-benchmark-harness

## 1. Visão geral do ciclo de uma execução

```
para cada combinação, para cada repetição r em 1..N:
    1. reset_stores (se --reset-stores): arquivo de segurança -> recria banco e coleções -> bootstrap -> conferência
    2. seed_project (falha se a Metrica do Problema não é canônica e aprovada)
    3. snapshot inicial; ResourceSampler + StoreSampler ligados
    4. main.py --mode auto --project <id> <tarefa>
    5. samplers desligados; snapshot final
    6. placar validado + checklist validado + anomalias
    7. arquivamento da sessão em <results>.d/<combinação>/r<r>/
    8. grava o resultado (uma entrada por repetição)
relatório: tabelas por repetição e agregados por combinação
```

## 2. Reset dos bancos

### 2.1 Alvo

- O runner lê `DATABASE_URL` do ambiente da combinação. O banco de benchmark é definido por
  `BENCHMARK_DATABASE_URL`; sem ela, o reset recusa com erro explícito.
- Durante a execução, o subprocesso recebe `DATABASE_URL=$BENCHMARK_DATABASE_URL`. O banco de
  desenvolvimento nunca é tocado.
- Guardas, todas obrigatórias:
  1. `--reset-stores` na linha de comando.
  2. `--confirm-target <banco>@<host>` igual ao alvo extraído de `BENCHMARK_DATABASE_URL`.
  3. O nome do banco contém `BENCHMARK_DB_MARKER` (padrão `bench`).
  4. O nome do banco é diferente do banco de `DATABASE_URL` do `.env`.
- Qdrant: o alvo é `BENCHMARK_QDRANT_URL` (padrão: `QDRANT_URL`). Como o Qdrant não tem banco
  separado, o reset apaga **só** as coleções do sistema: `KNOWLEDGE_COLLECTION`,
  `geminiclaw_documents` e `geminiclaw_knowledge` (lista em `REINDEXABLE_COLLECTIONS` mais
  `KNOWLEDGE_COLLECTION`). A questão §8.1 trata de usar uma instância Qdrant só para o benchmark.

### 2.2 Arquivo de segurança

Antes de apagar, se o banco existe: `pg_dump -Fc` do banco de benchmark e snapshot de cada
coleção do Qdrant (API `POST /collections/{nome}/snapshots`, download do arquivo), gravados em
`<results>.d/<combinação>/r<r>/pre_reset/`. `--no-pre-reset-dump` desliga; a falha do dump
interrompe o reset (fail-fast), salvo com essa flag.

### 2.3 Recriação e bootstrap

1. `DROP DATABASE <bench> WITH (FORCE)` e `CREATE DATABASE <bench>` (conexão no banco
   `postgres`). Apagar o banco inteiro evita os gatilhos de `execution_records` (somente
   acréscimo) e não exige `TRUNCATE` nem desligar gatilhos.
2. Aplicar `scripts/init_db.sql` e as migrações de `scripts/migrations/` pela ordem do nome,
   pelo mesmo caminho dos scripts `migrate_*.py` existentes (a tarefa 1.1 confere a ordem e
   documenta qualquer passo que hoje só roda pelo `docker-entrypoint-initdb.d`).
3. `seed_vocabulary` (com `data/vocabulary/`).
4. Conferência: tabelas esperadas existem e estão vazias, grafo `KNOWLEDGE_GRAPH_NAME` existe,
   `Metrica` `acuracia` existe com status aprovado e sinônimo `accuracy`, coleções do Qdrant não
   existem ou estão vazias. Falha na conferência interrompe o runner com código 4.

### 2.4 Contrato

```python
@dataclass
class ResetReport:
    database: str
    host: str
    dump_path: str | None
    qdrant_snapshots: list[str]
    dropped_collections: list[str]
    migrations_applied: list[str]
    vocabulary: dict[str, int]     # contadores do seed_vocabulary
    duration_s: float

def reset_stores(target: BenchmarkTarget, *, archive_dir: Path, dump: bool = True) -> ResetReport: ...
```

O `ResetReport` vai para o resultado da repetição em `reset`.

## 3. Crescimento das memórias

### 3.1 `StoreSampler`

Thread ao lado do `ResourceSampler`, intervalo `BENCHMARK_STORE_SAMPLE_SECONDS` (padrão 30).
Cada amostra:

```json
{"t": 120.4,
 "postgres": {"db_bytes": 18350080, "tabelas": {"agent_events": 412, "egress_log": 90, "...": 0}},
 "qdrant": {"knowledge_nodes": 17},
 "grafo": {"nos": {"Hipotese": 3, "Resultado": 41}, "arestas": {"TESTA": 7, "MEDE": 12}}}
```

- Tabelas: a lista `TABLES` de `footprint.py` mais `knowledge_audit`, `similarity_queue`,
  `long_term_memory`, `document_chunks`.
- `db_bytes`: `pg_database_size(current_database())`.
- Grafo por rótulo: uma consulta por rótulo de vértice e de aresta do catálogo AGE
  (`ag_label`), contagem pela tabela do rótulo (`SELECT count(*) FROM "<grafo>"."<rótulo>"`), sem
  Cypher de caminho (custo baixo no Pi, ver #136).
- Falha de uma amostra é registrada em `erro` na própria amostra e o benchmark segue.

### 3.2 Saída

- `store_timeline`: lista de amostras, a primeira no início e a última no fim da execução.
- O relatório mostra, por combinação, o crescimento total (fim menos início) e a taxa por minuto
  de nós do grafo, pontos do Qdrant e linhas de `agent_events`, `egress_log` e
  `execution_records`.

## 4. Placar

### 4.1 Acurácia validada

```cypher
MATCH (r:Resultado)-[:MEDE]->(m:Metrica {id: $metrica_do_problema})
WHERE r.sessao_id = $sessao AND r.status_validacao = 'validado'
  AND coalesce(r.qualificador, '') IN ['', 'teste']
RETURN max(r.valor)
```

`accuracy_validated` é esse máximo, ou `null` sem resultado elegível. `accuracy_source` registra
`grafo_validado`.

### 4.2 Checklist validado

| Item | Exige |
|---|---|
| `eda` | subtarefa aprovada com `task_type` `eda` |
| `preprocessing` | subtarefa aprovada cujo plano cita divisão ou normalização (palavras atuais) |
| `two_algorithms` | duas subtarefas aprovadas de treino com abordagens diferentes (`approach.nome`) |
| `comparison` | `accuracy_validated` não nulo para ao menos dois `Resultado`s de experimentos diferentes |
| `recommendation` | relatório final gerado (`relatorio_final.md`) com a seção de recomendação |
| `artifacts` | ao menos um artefato resolvido em subtarefa aprovada |

Fontes: eventos `subtask_review` (aprovação e `resolved_artifacts`), plano gravado e grafo. O
checklist antigo continua no resultado como `checks_texto`, para comparação.

### 4.3 Dependência de `v18.6-review-evidence`

Sem o qualificador de métrica, `test_accuracy` não ganha `MEDE`, e a acurácia validada fica nula
quando o modelo usa esse nome. O runner registra `accuracy_validated = null` com
`accuracy_note = "sem MEDE"`, sem inventar valor (AGENTS.md §1.6).

### 4.4 Anomalias novas

- `acuracia_perfeita`: `accuracy_validated == 1.0`.
- `vocabulario_nao_semeado`: a `Metrica` do `Problema` não está aprovada (redundante com o
  fail-fast do `seed_project`, mas cobre execuções sem reset).
- `sem_mede`: a sessão gravou `Resultado`s, mas nenhum com `MEDE` para a métrica do `Problema`.

## 5. Arquivamento

Por repetição, em `<results>.d/<combinação>/r<r>/`:

- `sessao.tar.gz`: a pasta da sessão em `OUTPUT_BASE_DIR`.
- `run.log`: o log do subprocesso (hoje em `logs/` do benchmark).
- `eventos.json`: `agent_events` da sessão (`execution_id = sessão`).
- `grafo_projeto.json`: nós e arestas do projeto (`footprint.project_graph` ampliado com propriedades).
- `pre_reset/`: o arquivo de segurança do §2.2.

O caminho entra em `archive_dir` do resultado.

## 6. Repetições e agregados

- `--repeat N` (padrão 1). A chave de "já feito" passa a ser `(nome, repeticao)`, para retomar uma
  matriz interrompida.
- Agregados por combinação: média, desvio padrão amostral, mínimo e máximo de `wall_seconds`,
  `cost_usd`, `accuracy_validated` (ignorando nulos, com a contagem de nulos ao lado),
  subtarefas aprovadas; contagem por `stop_reason`.
- Sem reset (`--reset-stores` ausente), o runner avisa no início que as repetições não estão
  isoladas e grava `isolated: false` em cada resultado.

## 7. Custo com cache (OpenAI)

- O provedor OpenAI lê `usage.prompt_tokens_details.cached_tokens` (Chat Completions) e
  `usage.input_tokens_details.cached_tokens` (Responses) e repassa em `cached_tokens`.
- `src/llm/pricing.py` ganha `cached_input` para os modelos OpenAI da matriz, com a fonte
  oficial e a data no comentário, como os demais preços.
- Teste com resposta simulada dos dois formatos.

## 8. Questões em aberto

1. **Instância Qdrant do benchmark.** Proposta: mesmas coleções da instância do Pi (o Pi é
   ambiente de desenvolvimento e benchmark). Alternativa: um segundo serviço Qdrant só para o
   benchmark, que exige mudar `docker-compose.yml` (aprovação própria).
2. **Reexecução independente do modelo.** O placar validado ainda depende do número que o
   pipeline gravou. Uma checagem mais forte seria o runner carregar o modelo serializado e o
   conjunto de teste gravado pelo agente e recalcular a acurácia. Proposta: deixar para depois
   desta rodada, porque exige executar código do agente fora do sandbox ou um passo novo no
   sandbox.
3. **Número de repetições.** Proposta: 3 por combinação na próxima rodada (decisão de
   2026-10-13: 3 a 5).
4. **Retenção do arquivo de segurança.** Proposta: manter tudo em `~/bench/`; o pesquisador apaga
   quando quiser.

## 9. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador e loop | Nenhum; o runner chama `main.py` como hoje |
| Agentes e prompts | Nenhum |
| Sandbox | Nenhum |
| Persistência | Banco de benchmark separado, recriado por execução; coleções do Qdrant apagadas no reset |
| Segurança | Operação destrutiva com quatro guardas e arquivo de segurança; nenhuma credencial em log (a URL é exibida sem senha) |
| Testes e telemetria | Série de crescimento das memórias; placar a partir do grafo; testes de integração do reset com PostgreSQL e Qdrant reais |

## 10. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Reset aponta para o banco de desenvolvimento | Quatro guardas (§2.1); teste de recusa para cada uma |
| Bootstrap do reset diverge da instalação real | Conferência pós-reset (§2.3, item 4) e teste de integração que compara as tabelas com um banco criado pelo `docker-entrypoint-initdb.d` |
| `pg_dump` ausente no host | O reset usa o `pg_dump` do container `postgres` (`docker exec`), conferido no início; sem ele, falha antes de apagar |
| Amostrador pesa no Pi | Contagem por tabela de rótulo, intervalo de 30 s, conexão própria fora do pool do processo medido |
