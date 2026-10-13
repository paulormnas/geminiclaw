# Design: Registro de Execuções Encadeado por Hash

## Estado atual (levantamento em `dev`, commit `2146166`)

| Ponto | Onde | Observação |
|---|---|---|
| Validação antes de executar | `src/skills/code/skill.py:116-124` | Código com padrão proibido é recusado antes do sandbox: nada executa, logo nada é registrado. |
| Snapshot do código | `skill.py:148-160` | `step_NN.py` no diretório da sessão; falha de gravação só gera `WARNING`. |
| Chamada ao sandbox | `skill.py:175-182` | Síncrona (vira `asyncio.to_thread` em `v18.5-sandbox-phases`). |
| `params.json`/`metrics.json` | `skill.py:198-227` | Lidos após sucesso só para o `manifest.json`; `seed` vem de `metrics.json` (`:209`). |
| Falhas e timeout | `skill.py:228-256`, `:269-291` | Registrados apenas no `manifest.json`. |
| Paralelismo | `src/autonomous_loop.py:944-946` | Subtarefas do DAG rodam por `asyncio.gather`; várias execuções podem terminar ao mesmo tempo. Mais de uma sessão pode usar o mesmo projeto. |
| Checkpoint | `autonomous_loop.py:1205-1232` | Gravado hoje só no fechamento (`checkpoint.json` e payload); `v18-research-continuity` o torna incremental. |
| Metadados da sessão | `src/orchestrator.py:450-466` | `session_metadata.json` com `report_path="relatorio_final.md"`. |
| Síntese final | `autonomous_loop.py:1502-1560` | O Summarizer (LLM) escreve o relatório a partir de `metrics.json`. |
| Banco | `src/db.py:71-114` | Pool síncrono `psycopg` v3 com `dict_row`; nenhum uso de *advisory lock* no projeto. |
| Schema | `scripts/init_db.sql:9-16` e seguintes; `scripts/migrations/v17_001_knowledge_graph.sql` | Nenhuma tabela de execuções; migrações aplicadas por script Python (`scripts/migrate_v17_knowledge.py`). |
| Contexto da tarefa | `src/agent_runtime/context.py:26-45` | `AgentContext` não tem `project_id` nem `subtask_id`. |
| Subcomandos da CLI | `src/cli.py:1084-1086`, `:1045-1071` | Padrão `geminiclaw embeddings <ação>` tratado antes do parser de prompt. |
| Módulo homônimo | `src/knowledge/provenance.py` | Trata autoria de escritas no grafo (ADR 015 §4), não de execuções. O novo pacote é `src/provenance/`; o código novo não importa um no outro, e as docstrings deixam a distinção explícita. |

## Decisões

### 1. Registros e formato

Toda chamada da skill de código que passa da validação gera exatamente um `exec_id`
(`exec_<uuid4>`) e dois registros: `inicio` e `termino`.

Registro (o que é hasheado):

```json
{
  "formato": 1,
  "project_id": "…", "seq": 42, "exec_id": "exec_…", "tipo": "inicio | termino",
  "session_id": "…", "subtask_id": "… | null", "task_name": "…",
  "registrado_em": "2026-09-29T12:00:00.123456+00:00",
  "prev_hash": "<64 hex>",
  "corpo": { … }
}
```

`record_hash = sha256(canonical(registro))`. Canonicalização (`src/provenance/canonical.py`):
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`
codificado em UTF-8. **Números de ponto flutuante são proibidos no registro**: valores de
métricas entram como texto (`repr(float)`, `"nan"`, `"inf"`), para que o hash não dependa da
formatação de floats. O primeiro registro do projeto tem `prev_hash` = 64 zeros.

Corpo do `inicio` (gravado antes de qualquer container):

| Campo | Origem |
|---|---|
| `hash_codigo` | sha256 dos bytes UTF-8 de `script.py` |
| `arquivos_injetados` | `[{nome, sha256}]` (ex.: `scientific_helpers.py`) |
| `entradas` | `[{caminho, sha256, tamanho}]` de tudo que o script verá somente leitura: `input_snapshot/`, diretórios `/prior/*`, e arquivos pré-existentes em `outputs/<sessão>/<tarefa>/` |
| `pacotes_solicitados`, `ativos_declarados` | parâmetros da skill |
| `imagem_solicitada` | nome da imagem do sandbox |

Corpo do `termino` (o mínimo do ADR 019 §4, autossuficiente):

| Campo | Origem |
|---|---|
| `inicio_hash` | `record_hash` do `inicio` correspondente |
| `status` | `sucesso` · `falha_execucao` · `timeout` · `falha_install` · `falha_fetch_assets` · `erro_sandbox` · `erro_orquestrador` |
| `fase_falha`, `download_nao_declarado`, `rede_na_execucao` | `SandboxResult` (`v18.5-sandbox-phases` §7) |
| `exit_code`, `inicio_execucao`, `fim_execucao`, `fases` | `SandboxResult` |
| `hash_codigo`, `arquivos_injetados`, `entradas` | repetidos do `inicio` |
| `hash_params` | sha256 canônico de `params.json["parameters"]` (mesma definição de `v17-structural-fact-ingestion` design §2); `null` se ausente |
| `seed` | `params.json["seed"]`, senão `metrics.json["seed"]`; inteiro ou `null` |
| `saidas` | `[{caminho, sha256, tamanho}]` dos arquivos novos ou alterados em `outputs/<sessão>/<tarefa>/`, exceto `step_*.py` |
| `metricas`, `hash_metrics` | `metrics.json["metrics"]` numéricos (texto, ver acima) e sha256 do arquivo; `metrics_invalido=true` se não for JSON válido |
| `imagem` | `{nome, id, repo_digests}` |
| `python_version`, `pacotes` | introspecção da fase `execute` |
| `ativos` | `[{url, sha256, destino, tamanho, hash_declarado, origem}]` |

Caminhos são relativos a `OUTPUT_BASE_DIR` (ex.: `<sessão>/<tarefa>/metrics.json`).

### 2. Tabela `execution_records`

```sql
CREATE TABLE IF NOT EXISTS execution_records (
    project_id   TEXT        NOT NULL,
    seq          BIGINT      NOT NULL,
    exec_id      TEXT        NOT NULL,
    tipo         TEXT        NOT NULL CHECK (tipo IN ('inicio', 'termino')),
    session_id   TEXT        NOT NULL,
    subtask_id   TEXT,
    task_name    TEXT        NOT NULL,
    registrado_em TEXT       NOT NULL,          -- o mesmo texto que entra no hash
    prev_hash    CHAR(64)    NOT NULL,
    record_hash  CHAR(64)    NOT NULL,
    corpo        JSONB       NOT NULL,
    PRIMARY KEY (project_id, seq),
    UNIQUE (exec_id, tipo)
);
CREATE INDEX IF NOT EXISTS idx_exec_records_session ON execution_records (session_id);
CREATE INDEX IF NOT EXISTS idx_exec_records_subtask ON execution_records (subtask_id);
-- gatilhos BEFORE UPDATE OR DELETE (por linha) e BEFORE TRUNCATE (por comando)
-- que levantam exceção "execution_records é somente-acréscimo"
```

`corpo` em JSONB serve à consulta; o hash é sempre recalculado a partir do registro
reconstruído com o `corpo` lido do banco. Como o JSONB normaliza a representação (ordem de
chaves, espaços) mas preserva textos e inteiros, e o registro não tem floats, a
reconstrução é determinística. Teste de ida e volta cobre isso.

Aplicação: `scripts/migrations/v18_5_001_execution_records.sql` (idempotente) por
`scripts/migrate_v18_5_provenance.py`, no padrão de `scripts/migrate_v17_knowledge.py`; o
mesmo DDL é acrescentado a `scripts/init_db.sql` para instalações novas. Na inicialização, o
orquestrador verifica a existência da tabela; se faltar, a primeira execução de código falha
com a instrução de migração (não há execução sem registro).

### 3. Acréscimo serializado por projeto

```python
# src/provenance/ledger.py (síncrono; chamado via asyncio.to_thread)
with get_connection() as conn, conn.transaction():
    conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (LOCK_CLASSID, project_id))
    tip = conn.execute("SELECT seq, record_hash FROM execution_records "
                       "WHERE project_id = %s ORDER BY seq DESC LIMIT 1", (project_id,)).fetchone()
    registro = montar(seq=(tip.seq + 1 if tip else 1), prev_hash=(tip.record_hash if tip else ZERO))
    conn.execute("INSERT INTO execution_records (...) VALUES (...)", ...)
```

- `LOCK_CLASSID = 19019` (constante do módulo, identifica o uso). O lock é de transação: é
  liberado no `commit`/`rollback`, inclusive se o processo morrer.
- Serializa subtarefas paralelas da mesma sessão (`asyncio.gather`) e sessões concorrentes do
  mesmo projeto, em processos diferentes. Colisão de `hashtext` entre projetos só causa espera
  extra; a chave primária `(project_id, seq)` garante a integridade mesmo assim.
- A ordem da cadeia é a ordem de acréscimo, não a de execução: `inicio` e `termino` de
  execuções paralelas se intercalam, e o `termino` sempre tem `seq` maior que o seu `inicio`.

### 4. Integração com a skill de código

```
validação (skill.py:116) ── recusado → nada executa, nada é registrado
snapshot step_NN.py
ledger.flush_pending(sessão)                     # §5
hash das entradas (cache §6)
ledger.begin(...) ── falhou → SkillResult(success=False, "registro de início indisponível;
                                 execução não iniciada"), causa infraestrutura; sem sandbox
sandbox.run(...)  (qualquer desfecho, inclusive exceção → status erro_orquestrador)
hash das saídas, params, metrics
ledger.finish(...) ── falhou → provenance_pending.jsonl (§5)
manifest.record_step(..., exec_id=...)
SkillResult.metadata += {exec_id, record_hash, provenance_pending: bool}
```

- `begin` e `finish` recebem `project_id` e `subtask_id` do `AgentContext`, que ganha os dois
  campos (o orquestrador já conhece `AgentTask.subtask_id`, `src/orchestrator.py:74`, e o
  `project_id` do payload da sessão, `v17-research-project`). Sem `project_id` no contexto,
  `begin` falha (fail-fast) em vez de inventar um projeto.
- O `termino` é gravado em `finally`: falha do sandbox, timeout, falha de instalação e exceção
  inesperada na skill geram `termino` com o `status` correspondente.
- Se o processo morrer entre `begin` e `finish`, o `inicio` fica **órfão**; o `verify` o lista
  (§7). Não há fechamento automático de órfãos: um `termino` inventado depois não descreve a
  execução.

### 5. Término pendente

Se `finish` falhar (banco indisponível), o registro **sem** `seq`/`prev_hash` é anexado a
`outputs/<sessão>/provenance_pending.jsonl` como
`{"exec_id", "project_id", "tipo": "termino", "registrado_em", "corpo", "corpo_sha256"}`, com
`fsync`. A skill devolve o resultado normalmente, com `provenance_pending=True`.

- **Acréscimo posterior:** antes de cada `begin` na mesma sessão, no fechamento da sessão e na
  retomada (`v18-research-continuity`, pelos `exec_id` listados no checkpoint), o ledger
  acrescenta os pendentes na cadeia e reescreve o arquivo sem eles (arquivo temporário +
  `os.replace`). O `registrado_em` original fica no corpo como `registrado_localmente_em`, e o
  registro ganha o `registrado_em` do acréscimo.
- **Idempotência:** violação de `UNIQUE (exec_id, tipo)` significa que o pendente já entrou
  (queda entre o `INSERT` e a reescrita do arquivo); o corpo gravado é comparado ao pendente e,
  se diferir, o `verify` reporta conflito.
- Se nem o arquivo de pendências puder ser gravado, a skill devolve `success=False` com erro
  explícito ("término não registrado nem guardado localmente"): um resultado sem registro não
  pode virar `Resultado` no grafo.
- A ingestão no grafo de uma execução com `termino` pendente é adiada pela fila de
  `v17-structural-fact-ingestion` (`knowledge_pending.jsonl`) até o registro entrar na cadeia.

### 6. Cache de hash de arquivos grandes

`src/provenance/hashing.py`: sha256 em blocos de 1 MiB. Arquivos com tamanho ≥
`PROVENANCE_HASH_CACHE_MIN_BYTES` (padrão 8 MiB) consultam um cache SQLite local
(`PROVENANCE_HASH_CACHE_PATH`, padrão `store/hash_cache.db`; stdlib, sem dependência nova) pela
chave `(caminho resolvido, dispositivo, inode, tamanho, mtime_ns)`. Acerto reutiliza o hash;
erro recalcula e grava. Saídas da própria execução são sempre hasheadas (são novas) e entram no
cache, o que barateia o `verify` seguinte. `verify --full` ignora o cache.

### 7. Verificação: `geminiclaw provenance verify <projeto>`

Subcomando tratado como `embeddings` (`src/cli.py:1084-1086`), com opções `--full`, `--json`
e `--from-export <dir>`. Passos:

1. **Cadeia:** percorre `seq` de 1 à ponta; exige sequência sem lacunas, `prev_hash` igual ao
   `record_hash` anterior e `record_hash` recalculado igual ao gravado.
2. **Pares:** cada `termino` aponta para um `inicio` existente pelo `inicio_hash`.
3. **Arquivos:** confere `entradas` e `saidas` em disco: `ok`, `alterado` (hash difere) ou
   `ausente` (arquivo não existe, ex.: sessão limpa).
4. **Órfãs:** `inicio` sem `termino`, separadas em `pendente_local` (há término em algum
   `provenance_pending.jsonl` das sessões do projeto) e `sem_termino`.
5. **Checkpoints:** para cada sessão do projeto com `checkpoint.json`, a
   `provenance_chain_tip` precisa existir na cadeia com o mesmo `seq` e hash.

Saída: resumo legível ou JSON; código de saída 0 (íntegra, possivelmente com órfãs e ausentes
listados), 1 (cadeia quebrada, arquivo alterado, checkpoint divergente ou conflito de
pendência), 2 (não foi possível verificar, ex.: banco indisponível). `--from-export` verifica,
sem banco, um segmento exportado (§8) a partir do seu primeiro `prev_hash`, que é exibido como
âncora.

A função `verify_project`/`verify_session` devolve um `VerifyReport` usado também no relatório
e por `v18.5-operation-metrics`.

### 8. Ponta da cadeia, relatório e exportação

- **Checkpoint:** toda gravação de `checkpoint.json` (hoje `autonomous_loop.py:1205-1232`;
  incremental com `v18-research-continuity`) inclui
  `"provenance_chain_tip": {"project_id", "seq", "record_hash"}` e
  `"provenance_pending": ["exec_…"]`. Na retomada, a ponta do checkpoint é conferida contra a
  cadeia; divergência gera aviso no banner, evento `proveniencia_divergente` e linha no
  relatório (não bloqueia; o pesquisador roda `verify`).
- **Relatório final:** depois da síntese, o **orquestrador** (não o LLM) acrescenta a
  `relatorio_final.md` a seção "Proveniência das execuções": projeto, ponta (`seq` e hash),
  execuções da sessão por `status`, órfãs e pendências, resultado do `verify_session`, ativos
  sem hash declarado, execuções com rede na fase `execute`, e o limite do §9 em uma frase.
  `session_metadata.json` (`orchestrator.py:450-466`) ganha `provenance_chain_tip`.
- **Exportação:** no fechamento, `outputs/<sessão>/provenance/execution_records.jsonl` recebe
  o segmento contíguo da cadeia do projeto do primeiro registro da sessão até a ponta
  (inclui registros intercalados de outras sessões do mesmo projeto, necessários para
  verificar os elos), e `chain_tip.json` a ponta. `geminiclaw provenance export --session <id>`
  faz o mesmo para sessões interrompidas.

### 9. Derivação no grafo (`Experimento` e `Resultado`)

Função `derive_experiment_fields(subtask_id) -> ExperimentProvenance` em
`src/provenance/ledger.py`, usada pela ingestão de `v17-structural-fact-ingestion`:

- `Experimento.exec_ids`: todas as execuções da subtarefa, na ordem da cadeia.
- `Experimento.exec_id` (principal): o último `termino` com `status="sucesso"` cujas `saidas`
  contêm `metrics.json`; na falta, o último `termino` da subtarefa.
- `hash_codigo`, `hash_params`, `seed` e `ambiente` (`{python, imagem, pacotes, ativos}`) são
  copiados do `termino` principal, não dos arquivos.
- `Resultado.exec_id` = principal; `Resultado.valor` vem de `corpo.metricas[nome]`;
  `Resultado.hash_metrics` = `corpo.hash_metrics`. Se o `metrics.json` em disco tiver hash
  diferente, o `Resultado` **não** é criado e o evento `proveniencia_inconsistente` vai para a
  fila de pendências e para o relatório.
- `ExecutionLedger.get_metric(exec_id, nome) -> RecordedMetric(valor_texto, exec_id, seq,
  record_hash)` é a fonte de `{{res:<exec_id>/<nome_metrica>}}` (`v18.5-numeric-references`).

Para §9.3 do ADR 015, o `status`/`fase_falha` do `termino` alimentam a classificação de causa:
`erro_sandbox` com `fase_falha="infra"` → `infraestrutura`; `falha_install` e
`falha_fetch_assets` → `infraestrutura` quando o log indica rede/índice indisponível, senão
`abordagem`; `timeout` e `falha_execucao` seguem `v17-structural-fact-ingestion` §3.

### 10. Limites declarados

- **Evidência de adulteração, não prevenção.** No próprio nó, a cadeia detecta edição
  acidental ou parcial (de um registro, de um arquivo de saída). Quem controla o banco **e** o
  disco pode reescrever a cadeia inteira e recalcular todos os hashes; só uma ponta guardada
  fora do nó (relatório enviado, exportação copiada) revela isso. Assinatura com a chave do nó
  vem com a federação (ADR 013 §2), sobre esta mesma cadeia.
- O gatilho de somente-acréscimo impede `UPDATE`/`DELETE` acidentais, não o dono do banco.
- Términos pendentes ficam fora da cadeia até serem acrescentados.
- `verify` sem `--full` confia no cache: uma alteração que preserve tamanho, inode e
  `mtime_ns` só é vista com `--full`.
- O registro prova que código, entradas e saídas registrados correspondem ao que está em disco;
  **não** que a métrica foi calculada corretamente (ADR 019 §2).
- Arquivos `ausente` não distinguem limpeza legítima de remoção maliciosa.

### 11. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `PROVENANCE_HASH_CACHE_PATH` | `store/hash_cache.db` | Cache de hash (§6) |
| `PROVENANCE_HASH_CACHE_MIN_BYTES` | 8388608 | Tamanho mínimo para usar o cache |

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Início/término em torno de cada execução; ponta no checkpoint; seção do relatório; exportação no fechamento; flush de pendências. |
| Agentes & Prompts | Nenhuma mudança de prompt; `exec_id` disponível no resultado da skill para as referências numéricas. |
| Sandboxes & Containers | Nenhuma; consome o resultado estruturado de `v18.5-sandbox-phases`. |
| Persistência | Tabela nova `execution_records` com gatilhos; cache SQLite local; arquivos `provenance_pending.jsonl` e `provenance/` na sessão; propriedades novas em `Experimento`/`Resultado`. |
| Segurança | Adulteração detectável; fail-fast sem execução não registrada; limites do §10 explícitos. |
| Testes & Telemetria | Dois `INSERT` por execução; tempo de hash e de lock na telemetria; testes de concorrência, adulteração, órfãs e pendências. |

## Riscos

- **Latência do lock** com muitas subtarefas paralelas: a seção crítica é um `SELECT` e um
  `INSERT`; medir no Pi 5 (tarefa 7.1).
- **Hash de entradas grandes a cada execução**: mitigado pelo cache (§6).
- **Crescimento da tabela**: dois registros por execução, corpo pequeno (hashes e listas); sem
  expurgo por decisão (somente-acréscimo).
- **Dependência de `v17-research-project`**: sem `project_id`, nenhuma execução roda. A
  implementação deve entrar depois dela.

## Questões em aberto para o pesquisador

1. Apagar a cadeia de um projeto (ex.: projeto de teste) deve existir como comando com
   confirmação dupla, ou a tabela fica estritamente somente-acréscimo e só o `DROP` manual
   remove?
2. O relatório deve só exibir a ponta, ou também sugerir um meio de ancoragem externa
   (ex.: enviar `chain_tip.json` por e-mail ao pesquisador) já nesta versão?
3. Divergência entre a ponta do checkpoint e a cadeia na retomada: aviso (proposto) ou
   bloqueio da retomada até um `verify` limpo?

## Decisões (2026-10-08) e desvios da implementação

Questões em aberto, decididas conforme a proposta (aprovação do pesquisador):

1. **Apagar a cadeia:** a tabela fica estritamente somente-acréscimo; nenhum comando de apagamento nesta mudança (só o
   `DROP` manual de quem controla o banco). A limpeza de desenvolvimento não toca `execution_records`.
2. **Ancoragem externa:** o relatório só exibe a ponta (e a exportação grava `chain_tip.json`); nenhum envio automático.
3. **Ponta divergente na retomada:** aviso (banner da CLI, evento `proveniencia_divergente`, linha no relatório), sem
   bloquear a retomada.

Desvios e escolhas de implementação:

- **Cadeia sem projeto.** Sessões sem `project_id` (contorno `RESEARCH_PROJECT_GRAPH_OPTIONAL`/`sem_grafo` e chamadas
  programáticas) usam a cadeia `sem_projeto:<sessão>` em vez de recusar a execução; o relatório e o `verify` mostram o
  escopo. Evita que a queda do grafo impeça qualquer execução, sem inventar um projeto no grafo.
- **Ponta do checkpoint.** `provenance_chain_tip` vem da última ponta acrescentada **por este processo**
  (`ExecutionLedger.known_tip`, sem consulta ao banco a cada gravação); `verify` e a retomada a conferem contra a
  cadeia (`ExecutionLedger.check_tip`).
- **Arquivos reescritos.** `verify` considera o último escritor de cada caminho: um `metrics.json` reescrito por uma
  retentativa na mesma pasta não acusa `alterado` o `termino` anterior (estado `substituido`).
- **Armazenamento injetável.** `LedgerStore` (PostgreSQL em produção, memória nos testes) mantém o fluxo de acréscimo
  idêntico; o lock `pg_advisory_xact_lock(19019, hashtext(project_id))` e o `INSERT` ficam na mesma transação.
- **Resultado do `verify` na seção do relatório.** Exportação e acréscimo de pendências ocorrem na síntese final
  (`_synthesize_results`), que é o ponto comum do fechamento normal e do por limite.
