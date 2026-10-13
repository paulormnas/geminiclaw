# Tarefas: v18.6-benchmark-harness

**Estado (2026-10-13):** Proposta, aguardando aprovação do pesquisador (inclui a autorização da operação destrutiva de reset no banco de benchmark).

## 0. Pré-requisitos
- [ ] 0.1 Questões do design §8 respondidas pelo pesquisador.
- [ ] 0.2 Worktree `.worktrees/feat-v18.6-benchmark-harness`.

## 1. Reset dos bancos
- [ ] 1.1 Levantar a sequência real de bootstrap (`init_db.sql`, migrações de `scripts/migrations/`, migrações aplicadas pelo pool em `src/db.py`, `seed_vocabulary`) e documentá-la no módulo.
- [ ] 1.2 `scripts/benchmark/reset_stores.py`: `BenchmarkTarget`, guardas (design §2.1), `ResetReport`.
- [ ] 1.3 Arquivo de segurança: `pg_dump -Fc` (via container `postgres` quando não houver no host) e snapshots do Qdrant (§2.2).
- [ ] 1.4 Recriação, bootstrap e conferência (§2.3); código de saída 4 em falha.
- [ ] 1.5 `BENCHMARK_DATABASE_URL`, `BENCHMARK_QDRANT_URL`, `BENCHMARK_DB_MARKER` em `.env.example` (seção de benchmark).
- [ ] 1.6 Testes unitários: as quatro recusas das guardas; URL exibida sem senha.
- [ ] 1.7 Teste de integração (PostgreSQL com AGE e Qdrant reais): "Reset completo", "Dump gravado", "Dump falha"; tabelas iguais às de um banco criado pelo `docker-entrypoint-initdb.d`.

## 2. Projeto semeado
- [ ] 2.1 `seed_project`: fail-fast sem `Metrica` canônica aprovada.
- [ ] 2.2 Teste: "Vocabulário vazio".

## 3. Crescimento das memórias
- [ ] 3.1 `StoreSampler` em `scripts/benchmark/footprint.py` (§3.1), conexão própria.
- [ ] 3.2 Integração no `run_combination` (amostras de início e fim; série em `store_timeline`).
- [ ] 3.3 `report.py`: tabela de crescimento e taxa por minuto (§3.2).
- [ ] 3.4 `BENCHMARK_STORE_SAMPLE_SECONDS` (padrão 30) em `.env.example`.
- [ ] 3.5 Testes: "Série com início e fim" e "Amostra com falha" com fontes simuladas; "Relatório de crescimento".

## 4. Placar
- [ ] 4.1 `accuracy_validated` pela consulta do §4.1; `accuracy_note` quando nulo.
- [ ] 4.2 Checklist validado (§4.2) e `checks_texto`.
- [ ] 4.3 Anomalias `acuracia_perfeita`, `sem_mede`, `vocabulario_nao_semeado`, fora do `--fail-fast`.
- [ ] 4.4 Remover `score.accuracy`; `report.py` usa os campos novos.
- [ ] 4.5 Testes: os três cenários de "Acurácia oficial", "Plano cita algoritmos que não rodaram" e "Acurácia perfeita", com grafo em memória ou fixture.

## 5. Arquivamento e repetições
- [ ] 5.1 Arquivamento por repetição (§5) e `archive_dir`.
- [ ] 5.2 `--repeat N`, chave `(nome, repeticao)`, aviso e `isolated: false` sem reset (§6).
- [ ] 5.3 Agregados no relatório (§6).
- [ ] 5.4 Testes: "Arquivos presentes", "Retomada", "Agregado ignora nulos".

## 6. Custo com cache
- [ ] 6.1 Provedor OpenAI: `cached_tokens` dos dois formatos de resposta (§7).
- [ ] 6.2 `cached_input` dos modelos OpenAI da matriz, com fonte e data.
- [ ] 6.3 Teste: "Responses com cache" e o equivalente de Chat Completions.

## 6b. Juiz independente na matriz (ADR 020 item 9)
- [ ] 6b.1 `build_env` não expande `*` para `VALIDATOR` e `REVIEWER`; a combinação declara o juiz.
- [ ] 6b.2 Recusa da combinação com juiz da mesma família do `developer`, salvo `"independencia_julgamento": "off"` (controle); a família vem do catálogo.
- [ ] 6b.3 `check_pins` aceita o registro `independencia_julgamento` como esperado.
- [ ] 6b.4 Nova matriz `scripts/benchmark/matrix_modelos_v18_6.json` com o juiz declarado e ao menos uma combinação de controle (composição a confirmar com o pesquisador).
- [ ] 6b.5 Testes: os cenários de "Juiz declarado por combinação".

## 7. Validação
- [ ] 7.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 7.2 Execução curta no Pi **somente após confirmação do pesquisador** (bateria final): uma combinação, `--repeat 1`, `--reset-stores`, conferindo o arquivo de segurança, a série e o placar.
- [ ] 7.3 Atualizar `.agents/workflows/clean.md` e o cabeçalho de `run_benchmark.py` com o novo uso.
- [ ] 7.4 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
