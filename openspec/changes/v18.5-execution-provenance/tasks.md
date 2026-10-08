# Tarefas: v18.5-execution-provenance

**Estado (2026-10-08):** Implementada na branch `feat/v185-execution-provenance` (PR aberto para `dev`). A migração NÃO foi aplicada em nenhum banco; testes de integração (PostgreSQL) escritos e não executados; medição no Pi 5 na bateria final.

## 0. Pré-requisitos
- [x] 0.1 **Aprovação explícita do pesquisador** para a tabela `execution_records`, as propriedades novas no grafo e a mudança no workflow de limpeza (proposal, "Aprovações necessárias"). *(Aprovação do pesquisador registrada em sessões anteriores; as três questões em aberto do design foram decididas conforme a proposta — ver "Decisões" no design.)*
- [x] 0.2 **Revisão do Analista de Segurança** do modelo de ameaça (design §10). *(Revisão registrada no PR; limites do design §10 expostos no `verify` e no relatório.)*
- [x] 0.3 Confirmar `v18.5-sandbox-phases` e `v17-research-project` em `dev`.
- [x] 0.4 Worktree `.worktrees/feat-v18.5-execution-provenance`.

## 1. Schema
- [x] 1.1 `scripts/migrations/v18_5_001_execution_records.sql` (idempotente, com gatilhos de somente-acréscimo).
- [x] 1.2 `scripts/migrate_v18_5_provenance.py` no padrão de `migrate_v17_knowledge.py`; DDL também em `scripts/init_db.sql`.
- [x] 1.3 Verificação da tabela na inicialização, com erro acionável. *(`ProvenanceUnavailable` com a instrução `scripts/migrate_v18_5_provenance.py`; `PostgresStore.check_ready()`.)*

## 2. Núcleo `src/provenance/`
- [x] 2.1 `canonical.py`: serialização canônica, recusa de floats, `record_hash`.
- [x] 2.2 `hashing.py`: sha256 em blocos, cache SQLite por `(caminho, dispositivo, inode, tamanho, mtime_ns)`.
- [x] 2.3 `ledger.py`: `begin`, `finish`, `flush_pending`, `chain_tip`, `get_metric`, `derive_experiment_fields`; lock `pg_advisory_xact_lock(19019, hashtext(project_id))`.
- [x] 2.4 `verify.py`: cadeia, pares, arquivos, órfãs, pendências, checkpoints; `VerifyReport`; modo `--from-export`.
- [x] 2.5 `export.py`: segmento da sessão e `chain_tip.json`.
- [x] 2.6 Configurações do design §11 em `src/config.py` e `.env.example`.

## 3. Integração
- [x] 3.1 `AgentContext` com `project_id` e `subtask_id`, preenchidos pelo orquestrador.
- [x] 3.2 `CodeSkill.run`: fluxo do design §4 (`flush_pending`, hash de entradas, `begin` fail-fast, `termino` em `finally`, `exec_id` no `manifest.json` e em `SkillResult.metadata`).
- [x] 3.3 Checkpoint com `provenance_chain_tip` e `provenance_pending` (fechamento atual e, se existir, checkpoint incremental de `v18-research-continuity`); conferência da ponta na retomada.
- [x] 3.4 Seção determinística no `relatorio_final.md` e `provenance_chain_tip` em `session_metadata.json`.
- [x] 3.5 Exportação no fechamento; subcomandos `geminiclaw provenance verify` e `export` em `src/cli.py`.
- [x] 3.6 Ingestão: `Experimento`/`Resultado` derivados do registro, propriedades novas em `src/knowledge/schema.py`, evento `proveniencia_inconsistente` (se `v17-structural-fact-ingestion` ainda não existir, deixar `derive_experiment_fields` pronto e anotar no PR). *(`v17-structural-fact-ingestion` já existe em `dev`: `Experimento`/`Resultado` derivados em `src/knowledge/ingestion.py`; término pendente adia a ingestão pela fila `knowledge_pending.jsonl`.)*
- [x] 3.7 `clean_dev.py`/`clean.md`: não limpar `execution_records`.

## 4. Testes unitários
- [x] 4.1 Canonicalização estável; float recusado; métrica como texto.
- [x] 4.2 Montagem de `inicio`/`termino` para cada `status` a partir de `SandboxResult` simulado.
- [x] 4.3 Cache de hash: acerto, erro por mudança de `mtime_ns`, `--full` ignora.
- [x] 4.4 Pendências: gravação, acréscimo posterior, idempotência, conflito, falha dupla → `success=False`.
- [x] 4.5 `verify` com cadeia em memória: adulteração, lacuna, órfã, pendente local, checkpoint divergente, códigos de saída.
- [x] 4.6 Derivação do `Experimento` com retentativas; `get_metric` inexistente levanta erro.

## 5. Testes de integração (PostgreSQL)
- [x] 5.1 Gatilhos recusam `UPDATE`, `DELETE` e `TRUNCATE`. *(Escrito em `tests/integration/provenance/`; não executado: sem PostgreSQL neste ambiente.)*
- [x] 5.2 Ida e volta pelo JSONB preserva o hash. *(Idem 5.1.)*
- [x] 5.3 Concorrência: 8 execuções em duas sessões/processos → `seq` 1..16 sem bifurcação. *(Idem 5.1.)*
- [x] 5.4 Banco indisponível no início → nenhum container criado. *(Idem 5.1.)*
- [ ] 5.5 Sessão completa com sandbox: registros, ponta no checkpoint, seção no relatório, exportação e `verify --from-export`.

## 6. Documentação
- [x] 6.1 Limites do design §10 no texto de ajuda de `provenance verify` e na seção do relatório.

## 7. Fechamento
- [ ] 7.1 Medição no Pi 5: tempo de `begin`/`finish` com 4 subtarefas paralelas e hash de um dataset de 500 MB com e sem cache (registrar no PR).
- [ ] 7.2 Ruff, `uv run pytest -m "unit or integration"`. *(Parcial: unitários verdes e `ruff` limpo nos arquivos novos; integração na bateria final.)*
- [ ] 7.3 Revisão nos 7 eixos, PR para `dev`.
