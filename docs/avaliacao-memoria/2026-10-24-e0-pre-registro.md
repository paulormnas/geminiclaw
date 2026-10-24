# Pré-registro do E0 (replay dos candidatos estruturais)

**Data:** 2026-10-24 · **Mudança:** `v18.9-memory-evaluation` · **ADR:** 026 §6 e §7 · **Custo de LLM:** nenhum.

## Pergunta
A ordenação padrão dos candidatos estruturais (`src/knowledge/structural_candidates.py`, design §2) prevê, melhor do que
a ordem aleatória e do que a semelhança textual sozinha, quais pares (Problema, abordagem) terão um resultado positivo
nas sessões seguintes?

## Corpus
Banco de benchmark do Mac (`geminiclaw_bench`), 21 projetos de 4 problemas de classificação tabular (Iris, Wine, Glass,
Breast Cancer) e configurações de modelos diferentes. Exclusões: projetos sem nenhuma tentativa válida ligada a uma
hipótese (4 de 21, entre eles a sessão vazia por cota do Google). O instantâneo (`scripts/memory_eval/snapshot.py`) tem
o sha256 registrado em `replay.json`.

## Definições
- **Abordagem:** nome normalizado (minúsculas, sem acento nem pontuação). Os nós `Abordagem` são por projeto; o mesmo
  nome em projetos diferentes é a mesma abordagem. Nomes diferentes para a mesma técnica contam como abordagens
  distintas (limitação conhecida).
- **Corte:** o fim de cada projeto. **Par avaliado:** (Problema com tentativas depois do corte, abordagem vista em
  algum Problema até o corte) sem registro do par até o corte.
- **Positivo:** depois do corte, uma tentativa do par atinge o alvo ou melhora o melhor valor do Problema até então.
- **Semelhança:** cosseno dos embeddings locais do texto canônico do Problema.
- **Ordenações:** `padrao`, `semelhanca`, `grau_abordagem`, `aleatoria` (média de 100 sementes).
- **Intervalo:** bootstrap por projeto, 1000 reamostras, semente 20261024, percentis 2,5 e 97,5.
- Limiares: `CANDIDATE_MIN_SIMILARITY=0.60`, `CANDIDATE_MAX_DESCENDANTS=2`.

## Análises
1. **Principal:** todos os pares avaliados.
2. **Entre problemas distintos:** semelhança zerada entre Problemas com a mesma assinatura de dados (o mesmo conjunto
   de dados repetido em outro projeto), isolando a transferência entre problemas.
3. **Somente tentados:** AUC restrita aos pares tentados depois do corte (controle do mundo fechado).

## Regra de decisão (design §6)
Os candidatos seguem para `v18.9-cross-project-context` se, na análise principal, a AUC da ordenação padrão superar a
da aleatória **e** a da semelhança sozinha, com intervalos de 95% que não se sobrepõem. Caso contrário, o relatório
diz que a regra não foi cumprida e `CROSS_PROJECT_CANDIDATES` permanece `false`.

## Declaração prévia (transparência)
Antes deste registro, uma execução exploratória do mesmo código sobre o mesmo corpus mostrou (análise principal, 26
positivos em 1186 pares): padrão 0,53; semelhança 0,85; grau 0,55; aleatória 0,51. As análises e a regra de decisão
acima não foram alteradas depois de ver esses números. O relatório final declara que este pré-registro é posterior à
execução exploratória.

## Limitações já conhecidas
- Poucos positivos e poucos pares independentes: os intervalos serão largos.
- A semelhança textual entre repetições do mesmo conjunto de dados domina a ordenação por semelhança.
- Sem arestas `VARIANTE_DE` no corpus, só candidatos de transferência existem; composição e ramo pouco explorado não
  são avaliados.
