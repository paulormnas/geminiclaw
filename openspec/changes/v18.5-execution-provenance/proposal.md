# Proposta: Registro de Execuções Encadeado por Hash

**ID:** `v18.5-execution-provenance` · **Versão:** V18.5 · **Capacidade:** `execution-provenance`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §4
(também §2 e §8), [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §2 e §9.3,
[ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md) item 4,
[ADR 013](../../../docs/decisions/adr_013_federacao_rede_publica.md) §2

## Por quê

O ADR 019 exige que cada número do relatório seja rastreável até uma execução registrada, e
que alterações posteriores nesses registros sejam detectáveis. Hoje:

- Cada execução deixa `step_NN.py`, `manifest.json`, `params.json` e `metrics.json` no diretório
  da sessão (`src/skills/code/skill.py:148-160`, `:198-227`), todos editáveis sem rastro.
- Execuções que falham ou estouram o tempo só aparecem no `manifest.json`
  (`skill.py:228-248`); uma queda do orquestrador no meio da execução não deixa registro algum.
- Não há hash de entradas nem de saídas, nem digest da imagem, nem pacotes com versões.
- O `checkpoint.json` (`src/autonomous_loop.py:1205-1232`) e o relatório final não carregam
  nenhuma referência verificável às execuções.
- Os campos `hash_codigo`, `hash_params`, `seed` e `ambiente` do `Experimento` (ADR 015) seriam
  preenchidos a partir desses arquivos (`v17-structural-fact-ingestion` design §2), sem
  evidência de que não foram alterados.

## O que muda

- **Novo:** módulo `src/provenance/` com o livro de execuções (`ExecutionLedger`): registros
  **somente-acréscimo** `inicio` e `termino` por execução do sandbox, ids `exec_<uuid4>`, em
  cadeia de hash **por projeto** (`prev_hash`).
- **Novo:** tabela `execution_records` no PostgreSQL, com acréscimo serializado por projeto
  (*advisory lock*) e gatilho que recusa `UPDATE`, `DELETE` e `TRUNCATE`.
- **Novo:** *fail-fast*: sem registro de `inicio`, a execução não começa; um `termino` que não
  puder ser gravado fica em `outputs/<sessão>/provenance_pending.jsonl` e é acrescentado na
  próxima gravação possível.
- **Novo:** execuções que falham, estouram o tempo ou falham na instalação também têm `termino`.
- **Novo:** CLI `geminiclaw provenance verify <projeto>` (recalcula a cadeia, confere arquivos,
  lista órfãs e pendências) e `geminiclaw provenance export --session <id>`.
- **Novo:** cache de hash de arquivos grandes por tamanho e data de modificação.
- **Novo:** ponta da cadeia (`provenance_chain_tip`) no `checkpoint.json`, no
  `session_metadata.json` e numa seção determinística do relatório final; exportação dos
  registros para o diretório da sessão no encerramento.
- **Modificado:** `Experimento` e `Resultado` apontam para o registro de execução, e os campos
  de hash, semente e ambiente do `Experimento` passam a ser **derivados** do `termino`.
- **Novo:** consulta `ExecutionLedger.get_metric(exec_id, nome)`, fonte das referências
  `{{res:<exec_id>/<nome_metrica>}}` de `v18.5-numeric-references`.

## Fora do escopo

- Assinatura dos registros com a chave do nó e ancoragem externa automática da ponta (ADR 013,
  federação). A cadeia é compatível com ambas.
- Renderização de referências numéricas e verificação de afirmações (`v18.5-numeric-references`,
  `v18.5-claim-verification`).
- Métricas de operação agregadas (`v18.5-operation-metrics`), que consomem o resultado do
  `verify` definido aqui.

## Impacto

- **Código:** `src/provenance/` (novo: `canonical.py`, `hashing.py`, `ledger.py`,
  `verify.py`, `export.py`), `src/skills/code/skill.py` (início e término em torno do sandbox),
  `src/skills/code/manifest.py` (`exec_id` por passo), `src/agent_runtime/context.py`
  (`project_id` e `subtask_id` no `AgentContext`), `src/autonomous_loop.py` (checkpoint e
  fechamento), `src/orchestrator.py` (`session_metadata.json`, seção do relatório, verificação
  da tabela na inicialização), `src/knowledge/ingestion.py` e `src/knowledge/schema.py`
  (derivação dos campos, quando `v17-structural-fact-ingestion` existir), `src/cli.py`,
  `src/config.py`, `.env.example`, `scripts/init_db.sql`,
  `scripts/migrations/v18_5_001_execution_records.sql` (novo),
  `scripts/migrate_v18_5_provenance.py` (novo), `.agents/skills/clean_dev.py` e
  `.agents/workflows/clean.md` (não apagar `execution_records`).
- **Dependências:** `v18.5-sandbox-phases` (digest da imagem, pacotes, ativos, fase da falha);
  `v17-research-project` (todo run pertence a um projeto: `project_id` no payload da sessão);
  `v17-structural-fact-ingestion` e `v17-graph-store` para a derivação no grafo;
  `v18-research-continuity` para a ponta no checkpoint incremental e a retomada de pendências
  (sem ela, a ponta entra no checkpoint de fechamento que já existe).

## Aprovações necessárias

1. **Nova tabela `execution_records` no PostgreSQL** (mudança de schema), com índices e
   gatilho de somente-acréscimo: exige **aprovação explícita do pesquisador** antes da
   implementação, e a migração é aplicada só após essa aprovação.
2. **Novas propriedades nos nós `Experimento` (`exec_id`, `exec_ids`) e `Resultado`
   (`exec_id`, `hash_metrics`)** em `src/knowledge/schema.py`: alteração do schema do grafo,
   mesma aprovação.
3. **Mudança no workflow de limpeza** (`clean_dev.py`/`clean.md`): a tabela deixa de ser
   limpa; apagar a cadeia de um projeto passa a ser operação destrutiva com confirmação
   própria, fora desta mudança.
4. **Revisão do Analista de Segurança** sobre o modelo de ameaça e os limites declarados
   (design §10).
