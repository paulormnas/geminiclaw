# Etapa 2, segunda rodada: variantes corrigidas e critério de 2 % de falsa validação

**Data:** 2026-10-18 · **ADR:** [025](../decisions/adr_025_calibracao_do_veredito.md) §3 (etapa 2) e §4.1 a §4.3 · **Mudança:** [`v18.8-verdict-lab`](../../openspec/changes/v18.8-verdict-lab/proposal.md) (#222, #224, #225) · **Commit do código usado:** `5323325` · **Custo:** nenhuma chamada de LLM · **Dados:** [`dados/2026-10-18-etapa-2b/`](dados/2026-10-18-etapa-2b/) · **Rodada anterior:** [etapa 2](2026-10-18-etapa-2-grade-sintetica.md)

## 1. Pergunta

Depois da [primeira rodada](2026-10-18-etapa-2-grade-sintetica.md), o pesquisador decidiu o critério de aceite: **no máximo 2 % de falsa validação** (definição e método no [ADR 025 §4](../decisions/adr_025_calibracao_do_veredito.md)), com o objetivo de minimizar o registro e a validação de hipóteses que não contribuem para a pesquisa. A pergunta desta rodada: qual variante da equação e qual limiar de conclusão maximizam o poder (hipóteses verdadeiras validadas) sem passar de 2 % de falsa validação, respeitando as regras do pesquisador sobre o que o veredito deve concluir?

## 2. O que mudou desde a rodada anterior

- **Defeitos da variante `completa` corrigidos** na nova `completa2` (cada correção é uma alternativa do laboratório, com o comportamento anterior quando ausente):
  1. **Monotonicidade.** A penalidade por variação sem ganho passou a ser *acumulada*: conta só as variações até a própria evidência, em ordem cronológica. Uma evidência posterior não reduz mais o peso das anteriores (antes, 13 de 80 verificações violavam a monotonicidade; agora 0 de 86).
  2. **Piso na folga.** Sem baseline, uma melhora pequena sobre o alvo mantém `m` = 0,5 (o valor fixo atual) e `m` cresce com a folga. Antes, B-folga-0,001 pesava 0,017.
  3. **Réplica que não confirma pesa cheio** (`d` = 1,0 para evidência negativa em configuração já vista).
  4. **Positiva de variação sem ganho pesa zero.** A primeira correção ainda deixava as 19 variações iguais de V20 somarem peso 0,2 cada, e com `prior` 0,5 o cenário passava de 0,3. Com peso zero, V20 fica idêntico a V3 (razão 1,0).
- **Família A de cenários** (recordes por acaso), 43 cenários no total.
- **Critério de aceite** na simulação (`--fv-max`, padrão 2 %) e o comando **`selecao`**, que exige os dois instrumentos: falsa validação média ≤ 2 % na simulação **e** nenhuma conclusão `funciona` no catálogo onde o esperado não é `funciona`. A simulação sozinha não vê o volume sem evolução (a hipótese `sem_efeito` tem média no alvo), e a grade sozinha não mede taxas.
- Limiares avaliados: 0,2, 0,25, 0,3, 0,35 e 0,4 (antes 0,2 e 0,3).

## 3. Resultados

### 3.1 Seleção pelos dois instrumentos (limiar de conclusão, falsa validação ≤ 2 %)

Pares (variante, limiar) aceitos de maior poder ([relatório completo](dados/2026-10-18-etapa-2b/sel/relatorio.md)):

| Variante | Limiar | Falsa validação (média) | Falsa validação (pior ponto da grade) | Poder | Falsa refutação | Acertos do catálogo |
|---|---|---|---|---|---|---|
| `completa2` + `prior` 0,75 | 0,35 | 1,8 % | 12,5 % | **36,8 %** | 1,1 % | 36/43 |
| `completa2` | **0,30** (limiar atual do sistema) | 1,1 % | 7,5 % | 29,9 % | 1,0 % | 36/43 |
| `completa2` + `prior` 0,75 | 0,40 | 0,6 % | 5,0 % | 23,3 % | 0,6 % | 32/43 |
| `completa` (rodada anterior) | 0,30 | 0,5 % | 5,0 % | 23,3 % | 0,1 % | 33/43 |
| `atual` | 0,20 | 0,3 % | 7,5 % | 9,3 % | 0,0 % | 23/43 |

Rejeitadas pelo catálogo, apesar de dentro do teto na simulação: `por_tipo` (poder de 46,6 % no limiar 0,25 e 33,3 % no 0,3) e `por_tipo` sem falhas em `n_config`, porque concluem `funciona` em V20 (vinte variações sem evolução). O maior poder dentro do teto de 2 % exige, portanto, a regra de variação útil.

Sem aceite em nenhum limiar testado: `completa2` com `prior` 0,25 (o mesmo vale para `completa` com `prior` 0,25). Com `prior` 0,5, a variante só é aceita no limiar 0,5 (poder de 25,8 %).

### 3.2 O compromisso falsa validação / poder

Formato falsa validação (hipóteses sem efeito e falsas, o maior dos dois tipos, média sobre a grade) / poder:

| Variante | 0,2 | 0,25 | 0,3 | 0,35 | 0,4 |
|---|---|---|---|---|---|
| `atual` | 0,0 % / 9 % | 0,0 % / 4 % | 0,0 % / 1 % | 0,0 % / 0 % | 0,0 % / 0 % |
| `completa2` | 8,0 % / 62 % | 3,5 % / 46 % | **1,1 % / 30 %** | 0,3 % / 17 % | 0,1 % / 9 % |
| `completa2` + `prior` 0,75 | 16,4 % / 78 % | 9,8 % / 66 % | 4,8 % / 51 % | **1,8 % / 37 %** | 0,6 % / 23 % |
| `completa2` + `prior` 0,5 | 33,4 % / 89 % | 25,8 % / 85 % | 14,2 % / 75 % | 9,5 % / 65 % | 4,7 % / 52 % |

Os valores vêm da simulação (falsa validação = maior entre os tipos `falsa` e `sem_efeito`; [curva de compromisso](dados/2026-10-18-etapa-2b/sim/relatorio.md)). A falsa validação do **pior ponto** da grade (ruído `sigma` de 0,02, efeito de 0,01) chega a 7,5 % em `completa2` no limiar 0,3 e a 12,5 % em `completa2` + `prior` 0,75 no 0,35: no regime mais ruidoso, o teto de 2 % não se sustenta.

### 3.3 A regra do pesquisador contra o teto de 2 %

A regra "três variações positivas com evolução bastam para `funciona`" (E3) **não é cumprida por nenhuma variante aceita pelo teto**:

| Cenário (esperado) | `atual` | `por_tipo` | `completa2` | `completa2` + `prior` 0,75 | `completa2` + `prior` 0,5 |
|---|---|---|---|---|---|
| E2, duas variações que melhoram (indeciso) | 0,033 | 0,073 | 0,111 | 0,160 | 0,250 |
| **E3, três variações que melhoram (funciona)** | 0,034 | 0,106 | **0,204** | **0,274** | 0,388 |
| E5, cinco variações que melhoram (funciona) | 0,040 | 0,167 | 0,405 | 0,490 | 0,605 |
| V20, vinte variações sem evolução (indeciso) | 0,105 | 0,445 | 0,040 | 0,062 | 0,111 |
| A8, oito variações em torno do alvo (indeciso) | −0,001 | −0,122 | 0,141 | 0,186 | 0,257 |
| P-E3-V15, E3 e quinze variações sem ganho (funciona) | 0,096 | 0,420 | 0,309 | 0,391 | 0,510 |
| C3, três variações abaixo do alvo, acima do baseline (não funciona) | +0,097 | +0,242 | −0,360 | −0,444 | −0,562 |
| G-E2, duas melhoras de um acerto em 30 (indeciso) | 0,033 | 0,073 | 0,229 | 0,303 | 0,419 |
| Q, E3 e réplica que não confirma (indeciso) | −0,005 | 0,084 | 0,174 | 0,210 | 0,259 |

Em `completa2` (limiar 0,3), E3 chega a 0,204: pela fórmula, três melhoras bastam com `prior` perto de 0,7 e limiar 0,3, ou com limiar 0,2 e `prior` 1,0. Qualquer uma dessas combinações passa de 2 % de falsa validação na simulação (8,0 % em `completa2` no limiar 0,2; 14,2 % com `prior` 0,5 no 0,3). **Com cinco variações que melhoram (E5), `completa2` chega a 0,405 e conclui no limiar 0,3 com falsa validação de 1,1 %.**

Os sete cenários que `completa2` ainda erra no limiar 0,3 são E3, F1-E3, F3-E3 e B-folga-0,001 (todos "poucas melhoras: indeciso em vez de funciona"), R3 e R5 (a mesma configuração em três e cinco nós: indeciso em vez de funciona) e N-abordagem-4 (falha de abordagem em quatro configurações: indeciso em vez de não funciona).

### 3.4 Propriedades e sensibilidade

- `completa2`: limites, determinismo e ordem de entrada sem violações; **monotonicidade 0 de 86**; volume sem ganho V20/V3 = 1,0. A simetria continua violada (36 de 38 cenários) porque a penalidade de busca age só nas evidências positivas.
- Sensibilidade (`completa2`): [relatório](dados/2026-10-18-etapa-2b/sens/relatorio.md). Os parâmetros de maior efeito continuam sendo o `prior`, `q_validated_complete` e o peso da variação.
- Peso da réplica em outro nó (`d_replica_no`, 0,3 a 0,9, sobre `completa2` no limiar 0,3): poder de 27,3 % a 32,9 % e falsa validação de 1,0 % a 1,6 %, sempre dentro do teto. O efeito é pequeno, e a simulação tem no máximo dois nós.
- Regra de variação útil (limiar 0,3): "qualquer melhora" dá 29,9 % de poder e 1,1 % de falsa validação; exigir melhora acima de `δ` dá 11 % de poder no limiar 0,3 (18 % no 0,25, onde ainda respeita o teto); acima do ruído `sigma`, 31,5 % no limiar 0,2 com falsa validação de 1,9 % e pior ponto de 25 %.

## 4. Leitura

1. **A equação corrigida cumpre o teto de 2 % em um limiar viável.** `completa2` no limiar atual do sistema (0,3) tem 1,1 % de falsa validação e leva o poder de 1 % (equação atual) a 30 %. Com `prior` 0,75 e limiar 0,35, o poder sobe a 37 % com 1,8 %. Os dois acertam 36 dos 43 cenários.
2. **Estrutura e limiar contam mais que o `prior`.** O mesmo teto de 2 % custa muito mais poder quando só se mexe no `prior` (`prior` 0,5 sem as correções estruturais: 14,5 % de poder no limiar 0,3).
3. **Há uma tensão entre a regra "três melhoras bastam" e o teto de 2 %.** Com o ruído e os efeitos da grade (resultados que variam 0,5 a 2 pontos percentuais e efeitos de 1 a 2 pontos), três melhoras seguidas ocorrem por acaso com frequência. Para ficar abaixo de 2 %, o sistema precisa de mais evidência (cerca de cinco melhoras no catálogo). Manter as duas exigências ao mesmo tempo não é possível com as variantes testadas.
4. **Limitação da própria `completa2`.** Resultados em torno do alvo, alternando acima e abaixo (A8, A16), recebem veredito positivo de 0,14 a 0,15, porque as positivas pesam 1,0 e as negativas de variação sem ganho pesam 0,2. O efeito fica abaixo de 0,3, mas explica a falsa validação alta no pior ponto (ruído de 0,02) quando o limiar baixa a 0,2.
5. **Réplica entre nós.** Em `completa2`, a mesma configuração confirmada em três nós (R3) vale 0,111, menos que na equação atual (0,184), porque a réplica pesa 0,5 contra 1,0 do nó novo atual. Isso segue a decisão do pesquisador (a réplica pesa menos que a variação), mas contradiz o esperado do catálogo para R3 e R5 (que eu escrevi como `funciona`): é a regra de cenário que precisa de decisão.

## 5. Limitações

- Os desfechos esperados são regras do pesquisador aplicadas por mim; R3 e R5 mostram que uma delas ficou ambígua.
- A simulação usa ruído gaussiano, tentativas independentes e no máximo dois nós; não modela o reúso do conjunto de teste nem a dependência entre hipóteses.
- A grade da simulação (ruído de 0,5 a 2 pontos, efeito de 1 a 2 pontos) é uma faixa genérica; o poder absoluto depende dela. A comparação entre variantes é mais robusta que os valores absolutos.
- A média sobre a grade esconde regimes: o pior ponto passa do teto em todas as variantes com poder relevante.
- O limiar 0,35 não é o valor atual do sistema (`DECISION_EVAL_MIN_VERDICT` = 0,3).

## 6. Decisões que o pesquisador precisa tomar

1. **Regra de E3 contra o teto.** Manter 2 % de falsa validação e exigir cerca de cinco variações com evolução para concluir (E5), ou aceitar mais falsa validação para concluir com três? Os números da seção 3.3 mostram o preço.
2. **Variante e limiar.** `completa2` no limiar atual 0,3 (1,1 % de falsa validação, poder de 30 %, sem mudar o limiar do sistema) ou `completa2` com `prior` 0,75 e limiar 0,35 (1,8 %, 37 %)? O segundo muda `DECISION_EVAL_MIN_VERDICT` e fica perto do teto.
3. **R3 e R5.** A mesma configuração confirmada em três ou cinco nós deve concluir `funciona`? Hoje a réplica pesa 0,5, o que a faz valer menos que a equação atual.
4. **Falsa validação no pior regime.** O teto vale como média sobre a grade (decisão atual) ou também para o pior ponto? Para o pior ponto, nenhuma variante com poder relevante o respeita.

## 7. Próximos passos

Com as decisões acima: especificar `v18.8-verdict-calibration` (revisão do ADR 015 §9 e do código de `src/knowledge/verdict.py`) e, depois, as sessões controladas (etapa 3) e a bateria no Raspberry Pi (etapa 4), que reconferem o teto com dados que o ajuste não viu.

## 8. Como reproduzir

No Raspberry Pi, a partir da raiz do repositório no commit `5323325`, com os grafos em `~/bench/`:

```bash
L="uv run python -m scripts.verdict_lab"; LIM="0.2 0.25 0.3 0.35 0.4"
$L replay ~/bench --saida ~/lab4/replay --variante atual --variante completa2
$L grade --propriedades --limiar $LIM --saida ~/lab4/grade
$L sensibilidade --variante atual --variante por_tipo --variante completa2 --saida ~/lab4/sens
$L simulacao --saida ~/lab4/sim --repeticoes 40 --limiar $LIM
$L selecao --grade ~/lab4/grade/resultados.csv --simulacao ~/lab4/sim/resultados.csv --saida ~/lab4/sel
```

Os `relatorio.md`, `manifesto.json` e os `resultados.csv` pequenos estão em `dados/2026-10-18-etapa-2b/`. O `resultados.csv` da simulação (22 MB, sha256 `f58102d7dd389d35d4bfd24c1c6db7d5f14d636c93a80379d6b34acc3034152b`) e o da grade (472 KB) não são versionados; a semente do manifesto os reproduz byte a byte.
