# Proposta: Benchmark com Bancos Isolados, Placar Independente e Crescimento das Memórias

**ID:** `v18.6-benchmark-harness` · **Versão:** V18.6 (correções do benchmark de 2026-10-13) ·
**Capacidade:** `benchmark` (nova)
**ADRs de origem:** [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md)
(avaliação do assistente), [ADR 005](../../../docs/decisions/adr_005_estrategia_persistencia.md)
(PostgreSQL, Qdrant) e [ADR 009](../../../docs/decisions/adr_009_camada_conhecimento_experimental.md)
(memória vetorial e de grafo). Não há ADR novo: o ferramental de benchmark é código de apoio
(`scripts/benchmark/`), sem contrato com o produto.
**Origem dos requisitos:** revisão do benchmark de 2026-10-13 com o pesquisador. Decisões de
2026-10-13: zerar os bancos antes de cada rodada, observar o crescimento das memórias nos bancos
relacional, vetorial e de grafo, manter o alvo 0,95 fixo e investigar a acurácia 1,000.
**Depende de:** — (pode ser implementada em paralelo com `v18.6-review-evidence`; o placar por
resultado validado só fica completo depois dela, ver design §4.3). O item "juiz declarado por
combinação" depende da aprovação do [ADR 020](../../../docs/decisions/adr_020_independencia_validator.md)
e de `v18.6-validator-independence`.
**Habilita:** a próxima rodada da matriz, com 3 repetições por combinação.

## Por quê

| Problema observado | Causa |
|---|---|
| Haiku e Luna aparecem com acurácia 1,000 | `scoring.py:91` usa o maior número de qualquer linha com "accuracy". A Haiku nem treinou modelo; no grafo, os valores 1,0 são contagens (`n_duplicatas`, `plain_csv_roundtrip_exact`) |
| Checklist 6/6 em todas as combinações | O checklist procura palavras ("random forest", "recomend") no texto do plano e dos relatórios, não em resultados aprovados |
| Execuções contaminam umas às outras | Cada combinação cria o seu projeto, mas o vocabulário, o grafo, o Qdrant e as tabelas são compartilhados; uma rodada encontra o que a anterior gravou |
| Vocabulário nunca semeado no Pi | Nenhum passo do runner roda `scripts/seed_vocabulary.py`; o `seed_project` criou a `Metrica` "acurácia" como `candidato`, sem sinônimos, e nenhum `Resultado` ganhou aresta `MEDE` (zero arestas no grafo do Pi) |
| Artefatos das sessões perdidos | As sessões ficam em `outputs/` da worktree; a limpeza da worktree apagou tudo, e a investigação teve de usar só eventos e grafo |
| Crescimento das memórias visto só como diferença final | `footprint.delta` compara antes e depois; não há série no tempo nem tamanho em disco |
| Custo do GPT ~25% acima do painel | Tokens em cache não são descontados para a OpenAI |
| Uma execução por combinação | O runner não repete nem agrega |

## O que muda

- **Novo:** `scripts/benchmark/reset_stores.py`: recria do zero o banco PostgreSQL de
  benchmark (tabelas, grafo AGE, `execution_records`) e as coleções do Qdrant, aplica o
  bootstrap de uma instalação nova (`init_db.sql`, migrações em `scripts/migrations/`,
  `seed_vocabulary.py`) e confere o resultado. É chamado pelo runner antes de cada execução
  quando `--reset-stores` é passado.
- **Novo:** guarda de segurança do reset: o alvo (nome do banco e host) tem de ser confirmado
  por `--confirm-target`, o nome do banco tem de conter `BENCHMARK_DB_MARKER` (padrão `bench`),
  e um arquivo de segurança (`pg_dump` e snapshot do Qdrant) é gravado antes de apagar.
- **Novo:** `seed_project` falha se a `Metrica` do `Problema` não for canônica e aprovada no
  vocabulário (sem isso o veredito das hipóteses nunca sai de 0).
- **Novo:** **amostrador de memória** (`StoreSampler`), em paralelo ao amostrador de recursos:
  a cada `BENCHMARK_STORE_SAMPLE_SECONDS` grava linhas por tabela, tamanho do banco, pontos por
  coleção do Qdrant e nós/arestas do grafo por rótulo. O resultado ganha a série
  `store_timeline` e o relatório, a tabela de crescimento.
- **Novo:** **placar por resultado validado**: a acurácia oficial do benchmark é a maior
  acurácia de teste entre os `Resultado`s da sessão com `status_validacao = "validado"` e aresta
  `MEDE` para a métrica do `Problema`. A acurácia lida do texto continua no resultado, renomeada
  `acuracia_declarada_texto`, só para comparação.
- **Modificado:** checklist: cada item exige uma subtarefa aprovada pelo revisor com artefato
  resolvido (eventos `subtask_review`), não palavras no texto.
- **Novo:** anomalia `acuracia_perfeita`: acurácia validada igual a 1,0 é marcada para conferência
  manual de vazamento (o pesquisador decide; o runner não reprova).
- **Novo:** arquivamento da sessão: a pasta da sessão, o log e os eventos da sessão em JSON vão
  para `<results>.d/<combinação>/<repetição>/` antes do próximo reset.
- **Novo:** `--repeat N`: cada combinação roda N vezes, cada vez com reset; o relatório mostra
  média, desvio padrão, mínimo e máximo de tempo, custo, acurácia validada e subtarefas
  aprovadas, e a contagem de motivos de parada.
- **Modificado:** custo: o provedor OpenAI passa a informar `cached_tokens`, e a tabela de
  preços ganha `cached_input` para os modelos GPT usados (fonte oficial citada no código).
- **Novo:** juiz declarado por combinação (ADR 020, item 9): o `*` não cobre `validator` e
  `reviewer`; combinação com juiz da família do `developer` é recusada, salvo a combinação de
  controle (`"independencia_julgamento": "off"`); a matriz da próxima rodada tem ao menos uma.
- **Fora do escopo:**
  - Mudar o texto da tarefa (`task_iris.txt`), o alvo 0,95 ou o `delta_min` (decisão do
    pesquisador; o alvo segue fixo).
  - Reexecutar no runner o modelo treinado pelo agente (questão em aberto, design §8.2).
  - Limpar os bancos de desenvolvimento ou produção: o reset só age sobre o banco de benchmark.

## Impacto

- **Código:** `scripts/benchmark/reset_stores.py` (novo), `scripts/benchmark/run_benchmark.py`
  (opções, repetições, arquivamento), `scripts/benchmark/footprint.py` (`StoreSampler`, tamanho
  em disco), `scripts/benchmark/scoring.py` (placar validado, checklist), `scripts/benchmark/report.py`
  (crescimento, agregados), `scripts/benchmark/seed_project.py` (fail-fast), `src/llm/` (provedor
  OpenAI: `cached_tokens`), `src/llm/pricing.py` (`cached_input`), `.env.example`.
- **Contratos:** o JSON de resultados ganha `repeticao`, `store_timeline`, `accuracy_validated`,
  `acuracia_declarada_texto`, `checks_validated`, `archive_dir`, `reset`. O campo `score.accuracy`
  é removido (substituído pelos dois campos novos); `report.py` passa a ler os novos.
- **Schema de banco:** nenhuma alteração. O reset recria o banco **de benchmark** com o schema
  atual.
- **Operação destrutiva:** o reset apaga o banco e as coleções de benchmark. Exige a flag, a
  confirmação do alvo e a marca no nome (design §2); o arquivo de segurança é feito antes.
- **Custo:** nenhuma chamada LLM nova. As repetições multiplicam o gasto da matriz por N.
- **Hardware (Pi 5):** o amostrador faz contagens leves a cada 30 s (padrão); o `pg_dump` e o
  snapshot rodam entre execuções, fora da medição.

## Aprovações necessárias

- **Operação destrutiva (AGENTS.md §1.5):** a primeira execução com `--reset-stores` no Pi precisa
  de confirmação explícita do pesquisador, com o alvo exibido. O runner nunca reseta sem a flag.
- **Banco de benchmark separado:** criar o banco `geminiclaw_bench` (ou outro nome com a marca) no
  mesmo PostgreSQL do Pi. Não altera `docker-compose.yml` nem Dockerfile.
- Nenhuma exclusão de arquivo versionado nem alteração de `AGENTS.md`.
- **Decisão do pesquisador** sobre as questões em aberto do `design.md` §8.
