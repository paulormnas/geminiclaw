# Grade sintética do veredito

Gerado por `scripts.verdict_lab` em 2026-10-18T23:47:08Z, commit `5323325558f8`, comando `grade`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

## Acertos contra o esperado, por variante e limiar

| Variante | Acertos (limiar 0.2) | Acertos (limiar 0.25) | Acertos (limiar 0.3) | Acertos (limiar 0.35) | Acertos (limiar 0.4) |
|---|---|---|---|---|---|
| atual | 23/43 | 23/43 | 23/43 | 22/43 | 22/43 |
| sem_falhas_em_nconfig | 23/43 | 23/43 | 23/43 | 22/43 | 22/43 |
| por_tipo | 25/43 | 23/43 | 23/43 | 22/43 | 22/43 |
| folga | 24/43 | 23/43 | 23/43 | 22/43 | 22/43 |
| exige_alvo | 23/43 | 23/43 | 23/43 | 22/43 | 22/43 |
| b_variacao_sem_ganho | 23/43 | 23/43 | 23/43 | 22/43 | 22/43 |
| por_tipo+sem_falhas | 25/43 | 23/43 | 23/43 | 22/43 | 22/43 |
| por_tipo+melhora | 27/43 | 23/43 | 22/43 | 22/43 | 22/43 |
| completa | 33/43 | 34/43 | 33/43 | 31/43 | 24/43 |
| prior_0_5 | 24/43 | 21/43 | 23/43 | 24/43 | 23/43 |
| prior_0_25 | 27/43 | 24/43 | 25/43 | 24/43 | 24/43 |
| completa+prior_0_5 | 33/43 | 36/43 | 36/43 | 35/43 | 33/43 |
| completa+prior_0_25 | 28/43 | 29/43 | 30/43 | 31/43 | 36/43 |
| base_alvo | 28/43 | 24/43 | 23/43 | 23/43 | 22/43 |
| completa2 | 38/43 | 37/43 | 36/43 | 32/43 | 26/43 |
| completa2+prior_0_75 | 35/43 | 40/43 | 36/43 | 36/43 | 32/43 |
| completa2+prior_0_5 | 30/43 | 32/43 | 37/43 | 40/43 | 36/43 |
| completa2+prior_0_25 | 22/43 | 23/43 | 28/43 | 31/43 | 35/43 |

## Acertos por família (limiar 0.2)

| Variante | E | V | R | S | N | F | M | B | C | D | P | Q | G | A |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| atual | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 | 2/3 |
| sem_falhas_em_nconfig | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 | 2/3 |
| por_tipo | 4/6 | 1/4 | 1/3 | 3/3 | 3/5 | 1/4 | 3/3 | 0/2 | 1/2 | 1/3 | 2/2 | 1/1 | 2/2 | 2/3 |
| folga | 2/6 | 4/4 | 2/3 | 3/3 | 3/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 | 2/3 |
| exige_alvo | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 | 2/3 |
| b_variacao_sem_ganho | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 | 2/3 |
| por_tipo+sem_falhas | 4/6 | 1/4 | 1/3 | 3/3 | 3/5 | 1/4 | 3/3 | 0/2 | 1/2 | 1/3 | 2/2 | 1/1 | 2/2 | 2/3 |
| por_tipo+melhora | 4/6 | 4/4 | 1/3 | 3/3 | 3/5 | 1/4 | 3/3 | 0/2 | 1/2 | 1/3 | 0/2 | 1/1 | 2/2 | 3/3 |
| completa | 5/6 | 4/4 | 1/3 | 3/3 | 4/5 | 4/4 | 3/3 | 1/2 | 2/2 | 3/3 | 0/2 | 0/1 | 1/2 | 2/3 |
| prior_0_5 | 3/6 | 3/4 | 2/3 | 1/3 | 3/5 | 1/4 | 3/3 | 0/2 | 1/2 | 1/3 | 1/2 | 1/1 | 2/2 | 2/3 |
| prior_0_25 | 4/6 | 0/4 | 2/3 | 0/3 | 4/5 | 2/4 | 3/3 | 2/2 | 1/2 | 3/3 | 2/2 | 1/1 | 0/2 | 3/3 |
| completa+prior_0_5 | 6/6 | 3/4 | 3/3 | 1/3 | 4/5 | 4/4 | 2/3 | 1/2 | 2/2 | 2/3 | 2/2 | 0/1 | 0/2 | 3/3 |
| completa+prior_0_25 | 5/6 | 3/4 | 2/3 | 0/3 | 4/5 | 3/4 | 1/3 | 1/2 | 2/2 | 2/3 | 2/2 | 0/1 | 0/2 | 3/3 |
| base_alvo | 4/6 | 4/4 | 1/3 | 3/3 | 3/5 | 1/4 | 3/3 | 0/2 | 2/2 | 1/3 | 0/2 | 1/1 | 2/2 | 3/3 |
| completa2 | 6/6 | 4/4 | 1/3 | 3/3 | 4/5 | 4/4 | 3/3 | 1/2 | 2/2 | 3/3 | 2/2 | 1/1 | 1/2 | 3/3 |
| completa2+prior_0_75 | 6/6 | 4/4 | 2/3 | 2/3 | 4/5 | 4/4 | 1/3 | 2/2 | 2/2 | 2/3 | 2/2 | 0/1 | 1/2 | 3/3 |
| completa2+prior_0_5 | 5/6 | 3/4 | 3/3 | 1/3 | 4/5 | 4/4 | 1/3 | 2/2 | 2/2 | 2/3 | 2/2 | 0/1 | 0/2 | 1/3 |
| completa2+prior_0_25 | 4/6 | 0/4 | 2/3 | 0/3 | 3/5 | 3/4 | 1/3 | 2/2 | 2/2 | 2/3 | 2/2 | 0/1 | 0/2 | 1/3 |

## Veredito por cenário (o esperado na segunda coluna; limiar 0.2)

| Cenário | Esperado | atual | sem_falhas_em_nconfig | por_tipo | folga | exige_alvo | b_variacao_sem_ganho | por_tipo+sem_falhas | por_tipo+melhora | completa | prior_0_5 | prior_0_25 | completa+prior_0_5 | completa+prior_0_25 | base_alvo | completa2 | completa2+prior_0_75 | completa2+prior_0_5 | completa2+prior_0_25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | indeciso | 0.040 | 0.040 | 0.040 | 0.012 | 0.040 | 0.040 | 0.040 | 0.040 | 0.012 | 0.111 | 0.250 | 0.040 | 0.111 | 0.040 | 0.040 | 0.062 | 0.111 | 0.250 |
| E2 | indeciso | 0.033 | 0.033 | 0.073 | 0.013 | 0.033 | 0.053 | 0.073 | 0.073 | 0.074 | 0.095 | 0.222 | 0.184 | 0.360 | 0.073 | 0.111 | 0.160 | 0.250 | 0.444 |
| E3 | funciona | 0.034 | 0.034 | 0.106 | 0.017 | 0.034 | 0.067 | 0.106 | 0.106 | 0.162 | 0.097 | 0.225 | 0.330 | 0.533 | 0.106 | 0.204 | 0.274 | 0.388 | 0.589 |
| E5 | funciona | 0.040 | 0.040 | 0.167 | 0.036 | 0.040 | 0.096 | 0.167 | 0.167 | 0.379 | 0.111 | 0.249 | 0.580 | 0.748 | 0.167 | 0.405 | 0.490 | 0.605 | 0.766 |
| E8 | funciona | 0.052 | 0.052 | 0.245 | 0.068 | 0.052 | 0.141 | 0.245 | 0.245 | 0.572 | 0.137 | 0.292 | 0.742 | 0.856 | 0.245 | 0.585 | 0.660 | 0.751 | 0.862 |
| E3-b | funciona | 0.097 | 0.097 | 0.242 | 0.097 | 0.097 | 0.170 | 0.242 | 0.242 | 0.360 | 0.225 | 0.414 | 0.562 | 0.735 | 0.242 | 0.360 | 0.444 | 0.562 | 0.735 |
| V3 | indeciso | 0.034 | 0.034 | 0.106 | 0.000 | 0.034 | 0.034 | 0.106 | 0.034 | 0.000 | 0.097 | 0.225 | 0.002 | 0.007 | 0.034 | 0.040 | 0.062 | 0.111 | 0.250 |
| V8 | indeciso | 0.052 | 0.052 | 0.245 | 0.001 | 0.052 | 0.052 | 0.245 | 0.052 | 0.001 | 0.137 | 0.292 | 0.003 | 0.011 | 0.052 | 0.040 | 0.062 | 0.111 | 0.250 |
| V20 | indeciso | 0.105 | 0.105 | 0.445 | 0.002 | 0.105 | 0.105 | 0.445 | 0.105 | 0.002 | 0.240 | 0.433 | 0.008 | 0.026 | 0.105 | 0.040 | 0.062 | 0.111 | 0.250 |
| V8-decrescente | indeciso | 0.052 | 0.052 | 0.245 | 0.129 | 0.052 | 0.052 | 0.245 | 0.052 | 0.129 | 0.137 | 0.292 | 0.279 | 0.477 | 0.052 | 0.111 | 0.160 | 0.250 | 0.444 |
| R2 | indeciso | 0.111 | 0.111 | 0.074 | 0.111 | 0.111 | 0.111 | 0.074 | 0.074 | 0.074 | 0.250 | 0.444 | 0.184 | 0.360 | 0.074 | 0.074 | 0.111 | 0.184 | 0.360 |
| R3 | funciona | 0.184 | 0.184 | 0.111 | 0.184 | 0.184 | 0.184 | 0.111 | 0.111 | 0.111 | 0.360 | 0.562 | 0.250 | 0.444 | 0.111 | 0.111 | 0.160 | 0.250 | 0.444 |
| R5 | funciona | 0.309 | 0.309 | 0.184 | 0.309 | 0.309 | 0.309 | 0.184 | 0.184 | 0.184 | 0.510 | 0.694 | 0.360 | 0.563 | 0.184 | 0.184 | 0.250 | 0.360 | 0.563 |
| S3 | indeciso | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.170 | 0.340 | 0.170 | 0.340 | 0.067 | 0.067 | 0.101 | 0.170 | 0.340 |
| S10 | indeciso | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.340 | 0.543 | 0.340 | 0.543 | 0.170 | 0.170 | 0.233 | 0.340 | 0.543 |
| S3-sessoes | indeciso | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.250 | 0.444 | 0.250 | 0.444 | 0.111 | 0.111 | 0.160 | 0.250 | 0.444 |
| N1 | indeciso | -0.040 | -0.040 | -0.040 | -0.111 | -0.040 | -0.040 | -0.040 | -0.040 | -0.111 | -0.111 | -0.250 | -0.250 | -0.444 | -0.040 | -0.111 | -0.160 | -0.250 | -0.444 |
| N3 | nao_funciona | -0.067 | -0.067 | -0.184 | -0.170 | -0.067 | -0.067 | -0.184 | -0.184 | -0.360 | -0.170 | -0.340 | -0.562 | -0.735 | -0.184 | -0.360 | -0.444 | -0.562 | -0.735 |
| N5 | nao_funciona | -0.096 | -0.096 | -0.309 | -0.224 | -0.096 | -0.096 | -0.309 | -0.262 | -0.459 | -0.224 | -0.413 | -0.652 | -0.799 | -0.262 | -0.459 | -0.543 | -0.652 | -0.799 |
| N-abordagem-2 | indeciso | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.070 | -0.175 | -0.070 | -0.175 | -0.023 | -0.053 | -0.082 | -0.141 | -0.298 |
| N-abordagem-4 | nao_funciona | -0.037 | -0.037 | -0.141 | -0.037 | -0.037 | -0.037 | -0.141 | -0.141 | -0.141 | -0.105 | -0.240 | -0.298 | -0.498 | -0.141 | -0.141 | -0.198 | -0.298 | -0.498 |
| F1-E3 | funciona | 0.026 | 0.030 | 0.082 | 0.039 | 0.026 | 0.059 | 0.093 | 0.082 | 0.270 | 0.075 | 0.179 | 0.446 | 0.608 | 0.082 | 0.270 | 0.342 | 0.446 | 0.608 |
| F3-E3 | funciona | 0.022 | 0.025 | 0.071 | 0.033 | 0.022 | 0.050 | 0.080 | 0.071 | 0.231 | 0.064 | 0.154 | 0.383 | 0.521 | 0.071 | 0.231 | 0.293 | 0.383 | 0.521 |
| F7-1 | indeciso | 0.014 | 0.022 | 0.014 | 0.032 | 0.014 | 0.022 | 0.022 | 0.014 | 0.049 | 0.041 | 0.102 | 0.116 | 0.220 | 0.014 | 0.049 | 0.072 | 0.116 | 0.220 |
| F-infra-E3 | funciona | 0.029 | 0.034 | 0.094 | 0.044 | 0.029 | 0.067 | 0.106 | 0.094 | 0.309 | 0.086 | 0.205 | 0.510 | 0.694 | 0.094 | 0.309 | 0.391 | 0.510 | 0.694 |
| M11 | indeciso | 0.021 | 0.021 | -0.014 | 0.015 | 0.021 | 0.021 | -0.014 | 0.021 | 0.015 | 0.059 | 0.136 | 0.040 | 0.085 | 0.021 | 0.029 | 0.043 | 0.073 | 0.146 |
| M21 | indeciso | 0.023 | 0.023 | 0.017 | 0.023 | 0.023 | 0.029 | 0.017 | 0.054 | 0.109 | 0.063 | 0.144 | 0.224 | 0.365 | 0.054 | 0.161 | 0.216 | 0.303 | 0.457 |
| M33 | indeciso | 0.007 | 0.007 | -0.088 | -0.014 | 0.007 | 0.011 | -0.088 | 0.056 | 0.110 | 0.017 | 0.034 | 0.192 | 0.274 | 0.056 | 0.159 | 0.202 | 0.263 | 0.359 |
| B-folga-0,001 | funciona | 0.034 | 0.034 | 0.106 | 0.001 | 0.034 | 0.067 | 0.106 | 0.106 | 0.017 | 0.097 | 0.225 | 0.053 | 0.141 | 0.106 | 0.184 | 0.250 | 0.360 | 0.562 |
| B-folga-0,05 | funciona | 0.034 | 0.034 | 0.106 | 0.097 | 0.034 | 0.067 | 0.106 | 0.106 | 0.360 | 0.097 | 0.225 | 0.562 | 0.735 | 0.106 | 0.360 | 0.444 | 0.562 | 0.735 |
| C3-abaixo-do-alvo | nao_funciona | 0.097 | 0.097 | 0.242 | 0.097 | -0.170 | 0.170 | 0.242 | 0.242 | -0.360 | 0.225 | 0.414 | -0.562 | -0.735 | -0.360 | -0.360 | -0.444 | -0.562 | -0.735 |
| C3-acima-do-alvo | funciona | 0.097 | 0.097 | 0.242 | 0.097 | 0.097 | 0.170 | 0.242 | 0.242 | 0.360 | 0.225 | 0.414 | 0.562 | 0.735 | 0.242 | 0.360 | 0.444 | 0.562 | 0.735 |
| D-E3 | funciona | 0.034 | 0.034 | 0.106 | 0.051 | 0.034 | 0.067 | 0.106 | 0.106 | 0.309 | 0.097 | 0.225 | 0.510 | 0.694 | 0.106 | 0.309 | 0.391 | 0.510 | 0.694 |
| D-N3 | nao_funciona | -0.067 | -0.067 | -0.184 | -0.170 | -0.067 | -0.067 | -0.184 | -0.184 | -0.360 | -0.170 | -0.340 | -0.562 | -0.735 | -0.184 | -0.360 | -0.444 | -0.562 | -0.735 |
| D-M21 | indeciso | 0.023 | 0.023 | 0.017 | 0.023 | 0.023 | 0.029 | 0.017 | 0.054 | 0.109 | 0.063 | 0.144 | 0.224 | 0.365 | 0.054 | 0.161 | 0.216 | 0.303 | 0.457 |
| P-E3-V5 | funciona | 0.052 | 0.052 | 0.245 | 0.048 | 0.052 | 0.058 | 0.245 | 0.108 | 0.177 | 0.137 | 0.292 | 0.350 | 0.553 | 0.108 | 0.309 | 0.391 | 0.510 | 0.694 |
| P-E3-V15 | funciona | 0.096 | 0.096 | 0.420 | 0.064 | 0.096 | 0.100 | 0.420 | 0.145 | 0.164 | 0.224 | 0.413 | 0.332 | 0.535 | 0.145 | 0.309 | 0.391 | 0.510 | 0.694 |
| Q-E3-R1-neg | indeciso | -0.005 | -0.005 | 0.084 | -0.052 | -0.005 | 0.023 | 0.084 | 0.084 | 0.240 | -0.012 | -0.022 | 0.375 | 0.490 | 0.084 | 0.174 | 0.210 | 0.259 | 0.328 |
| G-E2-passo | indeciso | 0.033 | 0.033 | 0.073 | 0.077 | 0.033 | 0.053 | 0.073 | 0.073 | 0.229 | 0.095 | 0.222 | 0.419 | 0.618 | 0.073 | 0.229 | 0.303 | 0.419 | 0.618 |
| G-V5-repetidos | indeciso | 0.040 | 0.040 | 0.167 | 0.086 | 0.040 | 0.040 | 0.167 | 0.040 | 0.086 | 0.111 | 0.249 | 0.206 | 0.390 | 0.040 | 0.087 | 0.128 | 0.207 | 0.391 |
| A8-ruido | indeciso | -0.001 | -0.001 | -0.122 | -0.021 | -0.001 | 0.005 | -0.122 | 0.070 | -0.008 | -0.002 | -0.004 | -0.020 | -0.041 | 0.070 | 0.141 | 0.186 | 0.257 | 0.378 |
| A16-ruido | indeciso | -0.035 | -0.035 | -0.224 | -0.059 | -0.035 | -0.031 | -0.224 | 0.068 | -0.010 | -0.073 | -0.119 | -0.020 | -0.033 | 0.068 | 0.152 | 0.190 | 0.245 | 0.329 |
| A8-so-recordes | funciona | 0.052 | 0.052 | 0.245 | 0.004 | 0.052 | 0.141 | 0.245 | 0.245 | 0.126 | 0.137 | 0.292 | 0.274 | 0.473 | 0.245 | 0.444 | 0.529 | 0.640 | 0.790 |

## Cenários em que nenhuma variante acerta (limiar 0.2)

Nenhum.

## Catálogo

| Cenário | Família | Descrição | Esperado | Justificativa |
|---|---|---|---|---|
| E1 | E | 1 variação(ões) acima do alvo, crescentes | indeciso | menos de três variações positivas com evolução |
| E2 | E | 2 variação(ões) acima do alvo, crescentes | indeciso | menos de três variações positivas com evolução |
| E3 | E | 3 variações acima do alvo, crescentes | funciona | pelo menos três variações positivas com evolução |
| E5 | E | 5 variações acima do alvo, crescentes | funciona | pelo menos três variações positivas com evolução |
| E8 | E | 8 variações acima do alvo, crescentes | funciona | pelo menos três variações positivas com evolução |
| E3-b | E | E3 com baseline 0,333 | funciona | três variações positivas com evolução |
| V3 | V | 3 variações com o mesmo valor (0,951) | indeciso | variações sem evolução |
| V8 | V | 8 variações com o mesmo valor (0,951) | indeciso | variações sem evolução |
| V20 | V | 20 variações com o mesmo valor (0,951) | indeciso | variações sem evolução |
| V8-decrescente | V | 8 variações acima do alvo, cada uma pior que a anterior | indeciso | sem evolução depois da primeira |
| R2 | R | a mesma configuração (0,96) em 2 nós | indeciso | uma réplica só |
| R3 | R | a mesma configuração (0,96) em 3 nós | funciona | replicação independente em três ou mais nós confirma |
| R5 | R | a mesma configuração (0,96) em 5 nós | funciona | replicação independente em três ou mais nós confirma |
| S3 | S | a mesma configuração com 3 sementes na mesma sessão | indeciso | repetir sementes não explora nem replica em outro nó |
| S10 | S | a mesma configuração com 10 sementes na mesma sessão | indeciso | repetir sementes não explora nem replica em outro nó |
| S3-sessoes | S | a mesma configuração em 3 sessões do mesmo nó | indeciso | mesmo nó e mesmos dados |
| N1 | N | 1 variação abaixo do alvo (0,90) | indeciso | uma evidência negativa só |
| N3 | N | 3 variações abaixo do alvo | nao_funciona | três variações sem alcançar o alvo |
| N5 | N | 5 variações abaixo do alvo | nao_funciona | cinco variações sem alcançar o alvo |
| N-abordagem-2 | N | falha de abordagem reproduzida 2 vezes | indeciso | reprodução mínima de uma falha |
| N-abordagem-4 | N | a mesma falha de abordagem em 4 configurações | nao_funciona | a abordagem não funciona nestas condições |
| F1-E3 | F | 1 falha ambígua e E3 | funciona | três variações positivas com evolução |
| F3-E3 | F | 3 falhas ambíguas e E3 | funciona | três variações positivas com evolução |
| F7-1 | F | 7 falhas ambíguas e 1 positiva sem baseline (etapa 1, hipótese …459203) | indeciso | uma evidência positiva só |
| F-infra-E3 | F | 5 falhas de infraestrutura e E3 | funciona | infraestrutura não informa sobre a hipótese |
| M11 | M | 1 positiva (0,96) e 1 negativa (0,94) | indeciso | evidências em conflito |
| M21 | M | 2 positivas crescentes e 1 negativa | indeciso | evidências em conflito |
| M33 | M | 3 positivas e 3 negativas alternadas | indeciso | evidências em conflito |
| B-folga-0,001 | B | E3 com folga de 0,001 a 0,003 sobre o alvo | funciona | três variações positivas com evolução (qualquer melhora conta) |
| B-folga-0,05 | B | E3 com folga de 0,03 a 0,05 sobre o alvo | funciona | três variações positivas com evolução |
| C3-abaixo-do-alvo | C | 3 variações crescentes acima do baseline e abaixo do alvo | nao_funciona | objetivo limiar exige alcançar o alvo |
| C3-acima-do-alvo | C | 3 variações crescentes acima do baseline e do alvo | funciona | três variações positivas com evolução |
| D-E3 | D | 3 variações abaixo do alvo de erro, decrescentes | funciona | três variações positivas com evolução |
| D-N3 | D | 3 variações acima do alvo de erro | nao_funciona | três variações sem alcançar o alvo |
| D-M21 | D | 2 positivas e 1 negativa, métrica de erro | indeciso | evidências em conflito |
| P-E3-V5 | P | E3 seguido de 5 variações sem ganho (0,955) | funciona | as três melhoras continuam valendo; o volume não deve desfazê-las |
| P-E3-V15 | P | E3 seguido de 15 variações sem ganho (0,955) | funciona | as três melhoras continuam valendo; o volume não deve desfazê-las |
| Q-E3-R1-neg | Q | E3 e a melhor configuração replicada em outro nó abaixo do alvo (0,93) | indeciso | a réplica não confirma a melhor variação |
| G-E2-passo | G | 2 variações com um acerto de diferença (0,967 e 1,0) | indeciso | menos de três melhoras possíveis |
| G-V5-repetidos | G | 5 variações com o mesmo valor discreto (0,967) | indeciso | variações sem evolução |
| A8-ruido | A | 8 variações em torno do alvo, positivas com recordes crescentes alternadas com negativas | indeciso | metade dos resultados não alcança o alvo; os recordes são pequenos e podem ser acaso |
| A16-ruido | A | 16 variações em torno do alvo, com recordes crescentes lentos | indeciso | metade dos resultados não alcança o alvo |
| A8-so-recordes | A | 8 variações acima do alvo, cada uma melhor que a anterior por 0,0005 | funciona | toda melhora conta (decisão do pesquisador, 2026-10-18) e nenhuma variação fica abaixo do alvo |

## Propriedades

| Variante | Propriedade | Verificados | Violações | Exemplo |
|---|---|---|---|---|
| atual | limites | 43 | 0 |  |
| atual | determinismo | 43 | 0 |  |
| atual | ordem_de_entrada | 43 | 0 |  |
| atual | monotonicidade | 86 | 0 |  |
| atual | simetria | 38 | 30 | E2: +0.0332 e espelhado -0.0533 |
| atual | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| sem_falhas_em_nconfig | limites | 43 | 0 |  |
| sem_falhas_em_nconfig | determinismo | 43 | 0 |  |
| sem_falhas_em_nconfig | ordem_de_entrada | 43 | 0 |  |
| sem_falhas_em_nconfig | monotonicidade | 86 | 0 |  |
| sem_falhas_em_nconfig | simetria | 38 | 29 | E2: +0.0332 e espelhado -0.0533 |
| sem_falhas_em_nconfig | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| por_tipo | limites | 43 | 0 |  |
| por_tipo | determinismo | 43 | 0 |  |
| por_tipo | ordem_de_entrada | 43 | 0 |  |
| por_tipo | monotonicidade | 86 | 0 |  |
| por_tipo | simetria | 38 | 30 | E2: +0.0733 e espelhado -0.1111 |
| por_tipo | volume_sem_ganho | 1 |  | V3 +0.1064, V20 +0.4447, razão 4.18 |
| folga | limites | 43 | 0 |  |
| folga | determinismo | 43 | 0 |  |
| folga | ordem_de_entrada | 43 | 0 |  |
| folga | monotonicidade | 86 | 0 |  |
| folga | simetria | 38 | 37 | E1: +0.0123 e espelhado -0.0400 |
| folga | volume_sem_ganho | 1 |  | V3 +0.0005, V20 +0.0021, razão 4.31 |
| exige_alvo | limites | 43 | 0 |  |
| exige_alvo | determinismo | 43 | 0 |  |
| exige_alvo | ordem_de_entrada | 43 | 0 |  |
| exige_alvo | monotonicidade | 86 | 0 |  |
| exige_alvo | simetria | 38 | 30 | E2: +0.0332 e espelhado -0.0533 |
| exige_alvo | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| b_variacao_sem_ganho | limites | 43 | 0 |  |
| b_variacao_sem_ganho | determinismo | 43 | 0 |  |
| b_variacao_sem_ganho | ordem_de_entrada | 43 | 0 |  |
| b_variacao_sem_ganho | monotonicidade | 86 | 0 |  |
| b_variacao_sem_ganho | simetria | 38 | 17 | V3: +0.0340 e espelhado -0.0672 |
| b_variacao_sem_ganho | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| por_tipo+sem_falhas | limites | 43 | 0 |  |
| por_tipo+sem_falhas | determinismo | 43 | 0 |  |
| por_tipo+sem_falhas | ordem_de_entrada | 43 | 0 |  |
| por_tipo+sem_falhas | monotonicidade | 86 | 0 |  |
| por_tipo+sem_falhas | simetria | 38 | 29 | E2: +0.0733 e espelhado -0.1111 |
| por_tipo+sem_falhas | volume_sem_ganho | 1 |  | V3 +0.1064, V20 +0.4447, razão 4.18 |
| por_tipo+melhora | limites | 43 | 0 |  |
| por_tipo+melhora | determinismo | 43 | 0 |  |
| por_tipo+melhora | ordem_de_entrada | 43 | 0 |  |
| por_tipo+melhora | monotonicidade | 86 | 8 | E5 + positiva de nó novo: 0.1674 -> 0.1655 |
| por_tipo+melhora | simetria | 38 | 30 | E2: +0.0733 e espelhado -0.0533 |
| por_tipo+melhora | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| completa | limites | 43 | 0 |  |
| completa | determinismo | 43 | 0 |  |
| completa | ordem_de_entrada | 43 | 0 |  |
| completa | monotonicidade | 86 | 13 | E5 + positiva de nó novo: 0.3787 -> 0.3114 |
| completa | simetria | 38 | 37 | E1: +0.0123 e espelhado -0.0400 |
| completa | volume_sem_ganho | 1 |  | V3 +0.0005, V20 +0.0021, razão 4.31 |
| prior_0_5 | limites | 43 | 0 |  |
| prior_0_5 | determinismo | 43 | 0 |  |
| prior_0_5 | ordem_de_entrada | 43 | 0 |  |
| prior_0_5 | monotonicidade | 86 | 0 |  |
| prior_0_5 | simetria | 38 | 30 | E2: +0.0950 e espelhado -0.1406 |
| prior_0_5 | volume_sem_ganho | 1 |  | V3 +0.0968, V20 +0.2401, razão 2.48 |
| prior_0_25 | limites | 43 | 0 |  |
| prior_0_25 | determinismo | 43 | 0 |  |
| prior_0_25 | ordem_de_entrada | 43 | 0 |  |
| prior_0_25 | monotonicidade | 86 | 0 |  |
| prior_0_25 | simetria | 38 | 30 | E2: +0.2220 e espelhado -0.2975 |
| prior_0_25 | volume_sem_ganho | 1 |  | V3 +0.2253, V20 +0.4326, razão 1.92 |
| completa+prior_0_5 | limites | 43 | 0 |  |
| completa+prior_0_5 | determinismo | 43 | 0 |  |
| completa+prior_0_5 | ordem_de_entrada | 43 | 0 |  |
| completa+prior_0_5 | monotonicidade | 86 | 13 | E5 + positiva de nó novo: 0.5805 -> 0.5131 |
| completa+prior_0_5 | simetria | 38 | 37 | E1: +0.0400 e espelhado -0.1111 |
| completa+prior_0_5 | volume_sem_ganho | 1 |  | V3 +0.0019, V20 +0.0077, razão 4.11 |
| completa+prior_0_25 | limites | 43 | 0 |  |
| completa+prior_0_25 | determinismo | 43 | 0 |  |
| completa+prior_0_25 | ordem_de_entrada | 43 | 0 |  |
| completa+prior_0_25 | monotonicidade | 86 | 13 | E5 + positiva de nó novo: 0.7480 -> 0.6967 |
| completa+prior_0_25 | simetria | 38 | 37 | E1: +0.1111 e espelhado -0.2500 |
| completa+prior_0_25 | volume_sem_ganho | 1 |  | V3 +0.0069, V20 +0.0260, razão 3.78 |
| base_alvo | limites | 43 | 0 |  |
| base_alvo | determinismo | 43 | 0 |  |
| base_alvo | ordem_de_entrada | 43 | 0 |  |
| base_alvo | monotonicidade | 86 | 8 | E5 + positiva de nó novo: 0.1674 -> 0.1655 |
| base_alvo | simetria | 38 | 30 | E2: +0.0733 e espelhado -0.0533 |
| base_alvo | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| completa2 | limites | 43 | 0 |  |
| completa2 | determinismo | 43 | 0 |  |
| completa2 | ordem_de_entrada | 43 | 0 |  |
| completa2 | monotonicidade | 86 | 0 |  |
| completa2 | simetria | 38 | 36 | E2: +0.1111 e espelhado -0.0672 |
| completa2 | volume_sem_ganho | 1 |  | V3 +0.0400, V20 +0.0400, razão 1.00 |
| completa2+prior_0_75 | limites | 43 | 0 |  |
| completa2+prior_0_75 | determinismo | 43 | 0 |  |
| completa2+prior_0_75 | ordem_de_entrada | 43 | 0 |  |
| completa2+prior_0_75 | monotonicidade | 86 | 0 |  |
| completa2+prior_0_75 | simetria | 38 | 36 | E2: +0.1600 e espelhado -0.1012 |
| completa2+prior_0_75 | volume_sem_ganho | 1 |  | V3 +0.0625, V20 +0.0625, razão 1.00 |
| completa2+prior_0_5 | limites | 43 | 0 |  |
| completa2+prior_0_5 | determinismo | 43 | 0 |  |
| completa2+prior_0_5 | ordem_de_entrada | 43 | 0 |  |
| completa2+prior_0_5 | monotonicidade | 86 | 0 |  |
| completa2+prior_0_5 | simetria | 38 | 36 | E2: +0.2500 e espelhado -0.1696 |
| completa2+prior_0_5 | volume_sem_ganho | 1 |  | V3 +0.1111, V20 +0.1111, razão 1.00 |
| completa2+prior_0_25 | limites | 43 | 0 |  |
| completa2+prior_0_25 | determinismo | 43 | 0 |  |
| completa2+prior_0_25 | ordem_de_entrada | 43 | 0 |  |
| completa2+prior_0_25 | monotonicidade | 86 | 0 |  |
| completa2+prior_0_25 | simetria | 38 | 36 | E2: +0.4444 e espelhado -0.3403 |
| completa2+prior_0_25 | volume_sem_ganho | 1 |  | V3 +0.2500, V20 +0.2500, razão 1.00 |
