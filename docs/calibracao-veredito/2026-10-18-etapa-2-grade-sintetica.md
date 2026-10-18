# Etapa 2 da calibração do veredito: grade sintética, simulação e sensibilidade

**Data:** 2026-10-18 · **ADR:** [025](../decisions/adr_025_calibracao_do_veredito.md) §3, etapa 2 · **Mudança:** [`v18.8-verdict-lab`](../../openspec/changes/v18.8-verdict-lab/proposal.md) (#222) · **Commit do código usado:** `fa5573b` · **Custo:** nenhuma chamada de LLM · **Dados:** [`dados/2026-10-18-etapa-2/`](dados/2026-10-18-etapa-2/)

## 1. Pergunta

A [etapa 1](2026-10-18-etapa-1-repeticao-offline.md) mostrou que, com a equação do [ADR 015](../decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9, nenhuma hipótese das baterias passa de 0,111 e que variar os valores dos parâmetros quase não muda isso. O pesquisador definiu o que a equação deve fazer (seção 2). Esta etapa responde, com cenários cujo desfecho correto é conhecido:

1. Quais mudanças de estrutura da equação aproximam o veredito do desfecho correto, e quais valores de parâmetros importam?
2. Qual o preço de cada mudança em hipóteses registradas como conhecimento sem contribuir à pesquisa (falsa validação)?

## 2. O que o pesquisador definiu como correto

Regras do pesquisador (2026-10-18), usadas para escrever o desfecho esperado de cada cenário:

- Três variações de configuração com resultado positivo, cada uma melhor que a anterior, bastam para concluir que a abordagem **funciona**, mesmo em um único nó.
- Variações que não indicam evolução ficam **indecisas**: o volume de tentativas não pode produzir conclusão.
- Uma variação é útil quando supera o melhor valor anterior **por qualquer quantidade**, porque, conforme o problema, 1 % a 3 % já é melhora significativa.
- Variar a configuração conta como exploração; replicar em outro nó conta como validação e pesa menos que a variação.
- O objetivo é minimizar o registro e a validação de hipóteses que não contribuem para a pesquisa.

## 3. Método

O laboratório (`scripts/verdict_lab`) aplica **variantes da fórmula** a três instrumentos. Uma variante é um conjunto de valores dos parâmetros mais alternativas de estrutura. A variante `atual` é a equação do sistema, e um teste exige que a reimplementação com tudo no valor atual coincida com `compute_verdict` (diferença ≤ 10⁻¹²) em todos os cenários.

### 3.1 Alternativas de estrutura testadas

| Alternativa | O que muda |
|---|---|
| `por_tipo` | O fator de independência `d` passa a olhar o **tipo** da evidência: variação (configuração nunca executada) = 1,0; réplica em outro nó = 0,5; sessão nova = 0,5; semente nova = 0,2. Hoje, uma configuração nova no mesmo nó vale o mesmo que uma semente nova (0,2) |
| `sem_falhas_em_nconfig` | A penalidade de busca `b` conta só as configurações que viraram evidência, e não as que falharam |
| `melhora` (`variacao_util`) | Uma variação só vale como exploração se superar o melhor valor anterior da hipótese; senão vale como semente |
| `b_variacao_sem_ganho` | `b` conta só as variações que não melhoraram |
| `folga` | Sem baseline, a magnitude `m` vem da distância ao alvo (hoje, fixa em 0,5) |
| `exige_alvo` | Com baseline e alvo, a evidência positiva também precisa alcançar o alvo (hoje, o alvo é ignorado quando há baseline, enquanto o objetivo `limiar` do `Problema` exige os dois) |
| `prior` | Ponto de partida de `α` e `β` (hoje 1,0): valores menores tornam qualquer evidência mais decisiva |

Variantes compostas: `completa` = `por_tipo` + `melhora` + `b_variacao_sem_ganho` + `folga` + `exige_alvo`; `completa+prior_0_5` e `completa+prior_0_25` somam o `prior`.

### 3.2 Instrumentos

- **Grade:** 40 cenários determinísticos em 13 famílias (exploração em um nó, volume sem ganho, réplica entre nós, sementes e sessões, refutação, falhas, mistos, sem baseline, critério com alvo, métrica de erro, estagnação depois de melhoras, réplica que não confirma, métrica discreta). Cada cenário traz o desfecho esperado e a justificativa (catálogo no [relatório da grade](dados/2026-10-18-etapa-2/grade/relatorio.md)). "Concluir" significa `|veredito| ≥ limiar`.
- **Simulação:** hipóteses `verdadeira` (média real acima do alvo), `falsa` (abaixo) e `sem_efeito` (igual ao alvo), com ruído `sigma`, efeito por configuração `tau`, probabilidade de variar a configuração e de falhar, e 1 ou 2 nós. 96 pontos de grade × 40 repetições × 3 tipos × 20 tentativas, semente 20261018; cerca de 4,6 milhões de cálculos, 5 minutos no Raspberry Pi 5. A decisão é tomada na primeira vez em que `|veredito|` alcança o limiar.
- **Sensibilidade:** cada parâmetro varia ×0,5, ×0,75, ×1,25 e ×1,5, e os quatro de maior efeito variam em pares, sobre os 40 cenários.

## 4. Resultados

### 4.1 Grade: acertos contra o esperado (40 cenários)

| Variante | Limiar 0,3 | Limiar 0,2 |
|---|---|---|
| `atual` | 21/40 | 21/40 |
| `sem_falhas_em_nconfig`, `exige_alvo`, `b_variacao_sem_ganho` (isoladas) | 21/40 | 21/40 |
| `folga` | 21/40 | 22/40 |
| `por_tipo` | 21/40 | 23/40 |
| `por_tipo+melhora` | 20/40 | 24/40 |
| `completa` | **31/40** | **31/40** |
| `prior_0_5` / `prior_0_25` (sobre `atual`) | 21/40 / 23/40 | 22/40 / 24/40 |
| `completa+prior_0_5` | **34/40** | 30/40 |
| `completa+prior_0_25` | 27/40 | 25/40 |

Veredito de cenários-chave (limiar 0,3; esperado entre parênteses):

| Cenário | `atual` | `por_tipo` | `completa` | `completa+prior_0_5` |
|---|---|---|---|---|
| E3, três variações que melhoram (funciona) | 0,034 | 0,106 | 0,162 | **0,330** |
| E8, oito variações que melhoram (funciona) | 0,052 | 0,245 | 0,572 | 0,742 |
| E2, duas variações que melhoram (indeciso) | 0,033 | 0,073 | 0,074 | 0,184 |
| V8, oito variações sem evolução (indeciso) | 0,052 | **0,245** | 0,001 | 0,003 |
| V20, vinte variações sem evolução (indeciso) | 0,105 | **0,445** | 0,002 | 0,008 |
| P-E3-V15, E3 e quinze variações sem ganho (funciona) | 0,096 | 0,420 | 0,164 | 0,332 |
| N3, três variações abaixo do alvo (não funciona) | −0,067 | −0,184 | −0,360 | −0,562 |
| C3, três variações crescentes acima do baseline e abaixo do alvo (não funciona) | **+0,097** | **+0,242** | −0,360 | −0,562 |
| R3, a mesma configuração em três nós (funciona) | 0,184 | 0,111 | 0,111 | 0,250 |
| Q, E3 e réplica que não confirma (indeciso) | −0,005 | 0,084 | 0,240 | **0,375** |
| G-E2, duas melhoras de um acerto em 30 (indeciso) | 0,033 | 0,073 | 0,229 | **0,419** |

### 4.2 Grade: propriedades

Medidas por variante e relatadas sem reprovar (detalhe no [relatório da grade](dados/2026-10-18-etapa-2/grade/relatorio.md)):

- **Todas** respeitam os limites [−1, +1], são determinísticas e não dependem da ordem de entrada.
- **Simetria:** nenhuma é simétrica entre positivas e negativas (27 violações em 35 cenários para `atual` e `por_tipo`), porque a penalidade de busca `b` só age nas evidências positivas.
- **Monotonicidade:** `atual` e `por_tipo` nunca reduzem o veredito ao receberem uma evidência concordante de nó novo; `completa` viola em 13 de 80 verificações (por exemplo, E5 cai de 0,379 para 0,311 ao receber uma positiva de nó novo). A causa é `b_variacao_sem_ganho`: a nova configuração, sem ganho sobre o melhor valor, eleva `n_config` e reduz retroativamente o peso das evidências anteriores.
- **Volume sem ganho (V20/V3):** `atual` 3,1×; `por_tipo` 4,2×; `completa` 4,3× sobre valores quase nulos (0,002 e 0,0005).

### 4.3 Simulação (limiar 0,3, 20 tentativas, médias sobre os 96 pontos da grade)

| Variante | Poder (verdadeira validada) | Falsa validação (sem efeito) | Falsa validação (falsa) | Falsa refutação |
|---|---|---|---|---|
| `atual` | 1,0 % | 0,0 % | 0,0 % | 0,0 % |
| `por_tipo` | 33,3 % | 0,3 % | 0,0 % | 0,3 % |
| `por_tipo+melhora` | 4,3 % | 0,1 % | 0,0 % | 0,0 % |
| `completa` | 23,3 % | 0,5 % | 0,0 % | 0,1 % |
| `completa` com variação útil só acima de `δ` | 10,5 % | 0,2 % | 0,0 % | 0,0 % |
| `prior_0_5` (sobre `atual`) | 14,5 % | 1,3 % | 0,0 % | 0,2 % |
| `prior_0_25` (sobre `atual`) | 51,5 % | 6,8 % | 0,6 % | 3,4 % |
| `completa+prior_0_5` | 73,2 % | 9,5 % | 0,9 % | 1,3 % |
| `completa+prior_0_25` | 88,1 % | 30,2 % | 5,9 % | 8,5 % |

Compromisso entre **falsa validação (hipótese sem efeito)** e **poder**, por limiar (formato falsa validação / poder):

| Variante | 0,1 | 0,2 | 0,3 | 0,4 | 0,5 |
|---|---|---|---|---|---|
| `atual` | 0,05 / 0,32 | 0,00 / 0,09 | 0,00 / 0,01 | 0,00 / 0,00 | 0,00 / 0,00 |
| `por_tipo` | 0,17 / 0,83 | 0,02 / 0,59 | 0,00 / 0,33 | 0,00 / 0,13 | 0,00 / 0,01 |
| `completa` | 0,25 / 0,88 | 0,05 / 0,58 | 0,01 / 0,23 | 0,00 / 0,07 | 0,00 / 0,02 |
| `completa+prior_0_5` | 0,40 / 0,90 | 0,25 / 0,87 | 0,09 / 0,73 | 0,03 / 0,46 | 0,00 / 0,20 |

Outras medidas (detalhe no [relatório da simulação](dados/2026-10-18-etapa-2/sim/relatorio.md)):

- **Efeito da regra de variação útil:** exigir que a melhora supere `δ` (ou o ruído `sigma`) em vez de "qualquer quantidade" reduz a falsa validação pela metade (0,5 % para 0,2 % no limiar 0,3; 5,0 % para 2,2 % no limiar 0,2), ao custo de metade do poder (23 % para 10,5 %).
- **Peso da réplica em outro nó** (`d_replica_no` de 0,3 a 0,9, sobre `completa`): poder de 21,4 % a 26,0 % e falsa validação de 0,5 % a 1,0 %. O efeito é pequeno nesta simulação, que só tem 1 ou 2 nós e réplica em metade das repetições.
- **Tentativas até o veredito cruzar 0,3** (hipóteses verdadeiras que cruzam; mediana): `atual` 1 % (mediana 20); `por_tipo` 34 % (16); `completa` 23 % (9); `completa+prior_0_5` 74 % (4,5).

### 4.4 Sensibilidade (efeito médio de |Δ veredito| sobre os 40 cenários)

| Posição | `atual` | `completa` |
|---|---|---|
| 1 | `prior` (0,085) | `prior` (0,135) |
| 2 | `q_validated_complete` (0,042) | `q_validated_complete` (0,093) |
| 3 | `d_new_node_or_dataset` (0,030) | `d_variacao` (0,089) |
| 4 | `d_new_seed` e `gamma` (0,013) | `variacao_util_epsilon` (0,037) |
| Sem efeito mensurável | `lambda_ambiguous`, `q_validated_incomplete`, `q_divergent` | `q_validated_incomplete`, `q_divergent`, `d_dataset` |

## 5. Leitura

1. **A estrutura da equação importa mais que os valores.** Com os mesmos valores, `por_tipo` (independência por tipo de evidência) leva o poder de 1 % a 33 % no limiar 0,3 e mantém a falsa validação em 0,3 %. Mudar só `d_new_seed` ou `gamma` não muda o resultado (etapa 1 e sensibilidade).
2. **`por_tipo` sozinho premia o volume.** Vinte variações sem evolução produzem 0,445 e seriam validadas (V20), o oposto do que o pesquisador definiu. A regra de variação útil (`melhora`) corrige isso (0,002), e é o que separa `por_tipo` de `completa`. A simulação não mostra esse risco porque sua hipótese `sem_efeito` tem média exatamente no alvo, e metade dos resultados cai abaixo dele e vira evidência negativa; o volume sem ganho só aparece na grade.
3. **O alvo precisa entrar no critério.** Com baseline, a equação atual conta como positivas três variações em 0,80, 0,85 e 0,90 para um alvo de 0,95 (C3 = +0,097, e +0,242 em `por_tipo`). Só `exige_alvo` (em `completa`) inverte o sinal para o correto.
4. **A combinação `completa` acerta 31 dos 40 cenários**, contra 21 da equação atual. Com o `prior` em 0,5, chega a 34 no limiar 0,3: E3 passa a concluir (0,330), como pede o pesquisador.
5. **O `prior` baixo compra poder com falsa validação.** Em `completa`, passar de `prior` 1,0 para 0,5 leva o poder de 23 % para 73 % e a falsa validação (sem efeito) de 0,5 % para 9,5 %; com 0,25, 88 % e 30 %. Os cenários mostram o mesmo preço: com `prior` 0,5, duas melhoras de um acerto em 30 passam de 0,3 (G-E2 = 0,419), e uma réplica que não confirma ainda deixa a hipótese validada (Q = 0,375).
6. **Nenhuma variante testada atende ao mesmo tempo às regras do pesquisador e ao objetivo de minimizar falsa validação.** A que mais acerta o catálogo (`completa+prior_0_5`) valida 9,5 % das hipóteses sem efeito. Para a mesma falsa validação baixa (cerca de 2 %), `por_tipo` com limiar 0,2 dá poder de 59 %, mais que `completa` (58 %, mas com 5 % de falsa validação) e que `completa+prior_0_5` com limiar 0,4 (46 %, falsa validação de 3 %). Esse limiar mais baixo, porém, não corrige o volume sem ganho.
7. **Problemas de desenho encontrados na própria fórmula `completa`:** perda de monotonicidade (4.2); réplica negativa que pesa pouco quando o `prior` é baixo; e `folga` torna quase nulo o peso de uma melhora pequena sobre o alvo (B-folga-0,001: 0,017), contrariando a regra de que qualquer melhora conta. Esse é o único cenário em que nenhuma variante acerta.

## 6. Limitações

- Os desfechos esperados dos cenários são regras do pesquisador aplicadas por mim; uma regra diferente muda os acertos (a regra "três melhoras bastam" favorece variantes que concluem com pouca evidência).
- A simulação tem ruído gaussiano e independência entre tentativas. Ela não modela o reúso do mesmo conjunto de teste (a melhor de várias variações é otimista) nem a dependência entre hipóteses do mesmo `Problema`. Os efeitos e as variâncias são faixas genéricas, não os de um problema real.
- A hipótese `sem_efeito` tem média no alvo. Hipóteses com média logo abaixo do alvo e variações que o ultrapassam por acaso (recordes por acaso) são exploradas pela regra de variação útil (4.3), mas não por uma família própria.
- O catálogo é pequeno (40 cenários) e feito por quem propôs as variantes. As etapas 3 e 4 do ADR 025 (sessões controladas com agentes e bateria no Raspberry Pi) são o teste independente.
- A réplica em outro nó é pouco explorada: a simulação tem no máximo dois nós.

## 7. Decisões que o pesquisador precisa tomar

1. **Falsa validação aceitável.** O objetivo declarado é minimizar hipóteses que não contribuem. A simulação oferece pontos de compromisso (seção 4.3). Qual taxa de falsa validação em hipóteses sem efeito é aceitável (por exemplo, 1 %, 5 %)?
2. **Regra de variação útil.** "Qualquer quantidade" (decisão atual) dá poder de 23 % e falsa validação de 0,5 % no limiar 0,3; exigir `δ` dá 10,5 % e 0,2 %. A regra continua como decidida, salvo nova instrução.
3. **Direção do ajuste.** Os dados indicam `por_tipo` + `melhora` + `exige_alvo` como base. Ficam em aberto as correções do 5.7 (monotonicidade, `folga`) e o `prior` (que cobra falsa validação).

## 8. Próximos passos

1. Variantes corrigidas: `b_variacao_sem_ganho` sem perda de monotonicidade, magnitude pela folga com piso para melhora pequena, e peso próprio para réplica que não confirma. Nova rodada da grade e da simulação com a família de recordes por acaso.
2. Com a variante escolhida pelo pesquisador, especificar `v18.8-verdict-calibration` (revisão do ADR 015 §9) e, depois, as sessões controladas (etapa 3).

## 9. Como reproduzir

No Raspberry Pi, a partir da raiz do repositório no commit `fa5573b`, com os grafos em `~/bench/`:

```bash
L="uv run python -m scripts.verdict_lab"
$L replay ~/bench --saida ~/lab/replay --variante atual --variante completa
$L grade --propriedades --limiar 0.3 0.2 --saida ~/lab/grade
$L sensibilidade --variante atual --variante por_tipo --variante completa --saida ~/lab/sens
$L simulacao --saida ~/lab/sim --repeticoes 40 --limiar 0.3 0.2
```

Os `relatorio.md`, `manifesto.json` (com o commit, os parâmetros efetivos de cada variante, a semente e o sha256 das entradas) e os `resultados.csv` da repetição, da grade e da sensibilidade estão em `dados/2026-10-18-etapa-2/`. O `resultados.csv` da simulação (97.920 linhas, 8,7 MB, sha256 `3f3d01fe709a8f64e527feb2f55d706509c7d2b605a5edbdaa640245f5bf0c15`) não é versionado; a mesma semente o reproduz byte a byte.
