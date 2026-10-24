# Proposta: Avaliação da memória (candidatos estruturais, replay e métricas comparáveis)

**ID:** `v18.9-memory-evaluation` · **Versão:** V18.9

**Capacidades:** `benchmark`

**ADRs de origem:** [ADR 026](../../../docs/decisions/adr_026_memoria_por_registros_de_resultado.md) §6 (candidatos) e §7 (avaliação).

**Depende de:** `v18.9-result-records`, porque o replay lê os registros.

## Por quê

A proposta só vale se a estrutura do grafo indicar bons próximos passos melhor do que alternativas simples, e se a memória melhorar a pesquisa em métricas comparáveis às de outros estudos. O E0 testa a primeira pergunta sem LLM. E1 e E2 testam a segunda e reutilizam o gerador e o orquestrador de exploração de `v18.8-verdict-controlled-sessions`.

## O que muda

### Novo
- `src/knowledge/structural_candidates.py`: gerador puro de candidatos estruturais (transferência, composição e ramo pouco explorado) com ordenação por atributos simples. É usado pelo replay e, depois, por `v18.9-cross-project-context` (design §2).
- `scripts/memory_eval/replay.py`: corta o grafo de um ou mais projetos em instantes `t`, gera candidatos com o grafo até `t` e mede a AUC contra os eventos depois de `t`. Compara com as ordenações aleatória e por semelhança textual (design §3).
- `scripts/memory_eval/metrics.py`: calcula, a partir de explorações arquivadas, as métricas do núcleo, com intervalo de confiança por bootstrap (design §4):
  - taxa de sucesso;
  - taxa de execuções válidas;
  - ganho sobre a linha de base;
  - falhas repetidas.
- `scripts/memory_eval/families.py`: famílias de Problemas relacionados no gerador controlado, com abordagem que funciona conhecida por Problema (design §5).
- Pré-registro em `docs/avaliacao-memoria/` antes de cada experimento (design §6).

### Fora do escopo
- Rodar E1, E2 ou o benchmark público, que exigem crédito e confirmação do pesquisador.
- Escolher o corpus do E0 (questão em aberto 1 do design).

## Impacto
- **Código:** `src/knowledge/structural_candidates.py` (novo, puro) e `scripts/memory_eval/` (novo).
- **Schema:** nenhuma mudança.
- **Custo:** E0 não chama LLM. A construção de famílias (design §5) chama, e só roda com confirmação.

## Aprovações necessárias
Nenhuma para implementar. Cada rodada com LLM (famílias, E1 e E2) exige confirmação do pesquisador e tabela de orçamento.
