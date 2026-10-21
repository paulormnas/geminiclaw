# Design: v18.9-memory-evaluation

## 1. Suficiência do histórico atual (verificado em 2026-10-21)

| Arquivo em `~/bench/` | Grafos | Conteúdo |
|---|---|---|
| `piloto_v18_8_sem_credito` | 5 vazios | Só Projeto, Problema e Sessão |
| `piloto_v18_8_parcial`, `piloto_v18_8_sem_credito/sonnet/P`, `verificacao_v18_8`, `verificacao_v18_8b` | 8 úteis | Um Problema cada (gerador controlado, regimes P e T); 5 a 43 experimentos; 11 eventos de melhoria da métrica principal no total; 2 arestas `DERIVADA_DE` |

Conclusão: **o histórico não permite o E0**. Não há pares entre Problemas, e 11 positivos não sustentam uma AUC com intervalo útil. O replay pode rodar sobre esses grafos como teste de fumaça, mas o resultado não é relatado como evidência.

## 2. Candidatos estruturais (`src/knowledge/candidates.py`)

A entrada é uma vista do grafo: Problemas, Abordagens, registros e arestas `DERIVADA_DE`, até um instante `t`. A saída é a lista de `Candidate(tipo, problema_id, abordagem_id, origem_ids, atributos)`.

| Tipo | Regra |
|---|---|
| `transferencia` | Abordagem A com registro `atingiu_alvo` ou `delta_base > 0` em um Problema P' semelhante a P (semelhança ≥ `CANDIDATE_MIN_SIMILARITY`), sem registro em P |
| `composicao` | Duas abordagens derivadas do mesmo pai com `delta_pai > 0`, ainda não combinadas |
| `pouco_explorado` | Abordagem com `delta_base > 0` e no máximo `CANDIDATE_MAX_DESCENDANTS` descendentes |

Atributos, sem pesos aprendidos:
- `semelhanca`, o cosseno entre os Problemas;
- `margem`, o melhor `delta_base` da origem;
- `replicas`, o `n_replicas_independentes` da origem;
- `grau_abordagem`, o número de Problemas com registro da abordagem (*preferential attachment*, Krenn et al.);
- `vizinhos_comuns`, o número de abordagens com registro nos dois Problemas.

A ordenação padrão é o produto normalizado `semelhanca × (1 + margem) × min(replicas, 3) / (1 + log(1 + descendentes))`. As alternativas por atributo isolado entram no replay como linhas de base.

| Variável | Padrão |
|---|---|
| `CANDIDATE_MIN_SIMILARITY` | 0.60 |
| `CANDIDATE_MAX_DESCENDANTS` | 2 |

## 3. Replay com corte temporal

- **Cortes:** para cada projeto e cada `t` em `cortes` (padrão: após cada sessão), o replay gera os candidatos com o grafo até `t`.
- **Rótulo positivo:** um par (Problema, Abordagem) é positivo se, depois de `t`, um experimento desse par terminar com `delta_pai > 0` ou `atingiu_alvo`.
- **Pares avaliados:** todos os (Problema, Abordagem) sem registro até `t`.
- **Métrica:** AUC (Krenn et al.; separação temporal do HyGRAIL).
- **Linhas de base:** ordem aleatória (média de 100 sementes), só `semelhanca` e só `grau_abordagem`.
- **Intervalo:** bootstrap por projeto (1000 reamostras).
- **Saída:** `replay.json`, com o commit, o sha256 dos grafos e as sementes.

O rótulo é de "mundo fechado": um par nunca tentado conta como negativo. Por isso, o relatório traz a AUC também restrita aos pares tentados depois de `t`.

## 4. Métricas do núcleo

| Métrica | Definição | Origem |
|---|---|---|
| `taxa_sucesso` | Fração das explorações com `objetivo_atingido` no Problema | MLE-bench, MLEvolve, Wasted Compute |
| `taxa_validas` | Fração com ao menos um `Resultado` de teste ou cv | MLE-bench, Wasted Compute |
| `ganho_base` | Melhor `delta_base` da exploração | AgentX |
| `falhas_repetidas` | Fração das falhas cuja assinatura e escopo já tinham ocorrido antes na exploração | Wasted Compute |

Cada métrica é relatada por braço, com intervalo de confiança de 95% por bootstrap e com n explorações. O orçamento é fixo por exploração (teto em US$ e tempo do orquestrador de exploração).

## 5. Famílias de Problemas relacionados

- **Geração:** `families.py` gera, a partir do gerador controlado, `k` Problemas por família que compartilham a abordagem que funciona (por exemplo, a mesma estrutura de não linearidade plantada) e variam em semente, tamanho e ruído. Também gera famílias de controle, em que a abordagem que funciona difere entre os membros, para medir o prejuízo da transferência.
- **Verdade:** `verdade.json` registra a família e a abordagem plantada, e fica fora do alcance dos agentes, como hoje.
- **Uso no E0:** rodar as sessões de uma família em sequência produz o histórico de que o E0 precisa. Isso tem custo de LLM e exige confirmação.

## 6. Pré-registro

Antes de cada experimento, um arquivo `docs/avaliacao-memoria/<data>-<experimento>-pre-registro.md` registra:
- pergunta, braços e métrica principal;
- regra de decisão, número de explorações e orçamento;
- commit.

O arquivo é commitado antes de qualquer resultado. O relatório posterior segue a lista de verificação de Ding et al. (2026): tentativas, regra de seleção, linha de base, independência do avaliador, sementes e rastros.

**Regra de decisão do E0:** os candidatos seguem para `v18.9-cross-project-context` se a AUC da ordenação padrão superar as ordenações aleatória e só por semelhança, com intervalos de 95% que não se sobrepõem.

## 7. Questões em aberto

1. **Corpus do E0:** (a) famílias do gerador (custo de LLM; histórico real do sistema), (b) histórico público de experimentos, como o OpenML (sem custo de LLM, mas não é história do agente; ainda não avaliado), ou ambos.
2. **Crédito disponível para E1 e E2,** que define o número de explorações por braço.
