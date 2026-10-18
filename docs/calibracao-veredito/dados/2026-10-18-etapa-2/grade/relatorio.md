# Grade sintética do veredito

Gerado por `scripts.verdict_lab` em 2026-10-18T22:18:10Z, commit `fa5573b7f8d6`, comando `grade`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

## Acertos contra o esperado, por variante e limiar

| Variante | Acertos (limiar 0.3) | Acertos (limiar 0.2) |
|---|---|---|
| atual | 21/40 | 21/40 |
| sem_falhas_em_nconfig | 21/40 | 21/40 |
| por_tipo | 21/40 | 23/40 |
| folga | 21/40 | 22/40 |
| exige_alvo | 21/40 | 21/40 |
| b_variacao_sem_ganho | 21/40 | 21/40 |
| por_tipo+sem_falhas | 21/40 | 23/40 |
| por_tipo+melhora | 20/40 | 24/40 |
| completa | 31/40 | 31/40 |
| prior_0_5 | 21/40 | 22/40 |
| prior_0_25 | 23/40 | 24/40 |
| completa+prior_0_5 | 34/40 | 30/40 |
| completa+prior_0_25 | 27/40 | 25/40 |

## Acertos por família (limiar 0.3)

| Variante | E | V | R | S | N | F | M | B | C | D | P | Q | G |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| atual | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 |
| sem_falhas_em_nconfig | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 |
| por_tipo | 2/6 | 3/4 | 1/3 | 3/3 | 3/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 1/2 | 1/1 | 2/2 |
| folga | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 |
| exige_alvo | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 |
| b_variacao_sem_ganho | 2/6 | 4/4 | 2/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 |
| por_tipo+sem_falhas | 2/6 | 3/4 | 1/3 | 3/3 | 3/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 1/2 | 1/1 | 2/2 |
| por_tipo+melhora | 2/6 | 4/4 | 1/3 | 3/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 |
| completa | 5/6 | 4/4 | 1/3 | 3/3 | 4/5 | 2/4 | 3/3 | 1/2 | 2/2 | 3/3 | 0/2 | 1/1 | 2/2 |
| prior_0_5 | 2/6 | 4/4 | 3/3 | 2/3 | 2/5 | 1/4 | 3/3 | 0/2 | 0/2 | 1/3 | 0/2 | 1/1 | 2/2 |
| prior_0_25 | 3/6 | 3/4 | 2/3 | 0/3 | 4/5 | 1/4 | 3/3 | 0/2 | 1/2 | 2/3 | 1/2 | 1/1 | 2/2 |
| completa+prior_0_5 | 6/6 | 4/4 | 2/3 | 2/3 | 4/5 | 4/4 | 3/3 | 1/2 | 2/2 | 3/3 | 2/2 | 0/1 | 1/2 |
| completa+prior_0_25 | 5/6 | 3/4 | 2/3 | 0/3 | 4/5 | 4/4 | 2/3 | 1/2 | 2/2 | 2/3 | 2/2 | 0/1 | 0/2 |

## Veredito por cenário (o esperado na segunda coluna; limiar 0.3)

| Cenário | Esperado | atual | sem_falhas_em_nconfig | por_tipo | folga | exige_alvo | b_variacao_sem_ganho | por_tipo+sem_falhas | por_tipo+melhora | completa | prior_0_5 | prior_0_25 | completa+prior_0_5 | completa+prior_0_25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | indeciso | 0.040 | 0.040 | 0.040 | 0.012 | 0.040 | 0.040 | 0.040 | 0.040 | 0.012 | 0.111 | 0.250 | 0.040 | 0.111 |
| E2 | indeciso | 0.033 | 0.033 | 0.073 | 0.013 | 0.033 | 0.053 | 0.073 | 0.073 | 0.074 | 0.095 | 0.222 | 0.184 | 0.360 |
| E3 | funciona | 0.034 | 0.034 | 0.106 | 0.017 | 0.034 | 0.067 | 0.106 | 0.106 | 0.162 | 0.097 | 0.225 | 0.330 | 0.533 |
| E5 | funciona | 0.040 | 0.040 | 0.167 | 0.036 | 0.040 | 0.096 | 0.167 | 0.167 | 0.379 | 0.111 | 0.249 | 0.580 | 0.748 |
| E8 | funciona | 0.052 | 0.052 | 0.245 | 0.068 | 0.052 | 0.141 | 0.245 | 0.245 | 0.572 | 0.137 | 0.292 | 0.742 | 0.856 |
| E3-b | funciona | 0.097 | 0.097 | 0.242 | 0.097 | 0.097 | 0.170 | 0.242 | 0.242 | 0.360 | 0.225 | 0.414 | 0.562 | 0.735 |
| V3 | indeciso | 0.034 | 0.034 | 0.106 | 0.000 | 0.034 | 0.034 | 0.106 | 0.034 | 0.000 | 0.097 | 0.225 | 0.002 | 0.007 |
| V8 | indeciso | 0.052 | 0.052 | 0.245 | 0.001 | 0.052 | 0.052 | 0.245 | 0.052 | 0.001 | 0.137 | 0.292 | 0.003 | 0.011 |
| V20 | indeciso | 0.105 | 0.105 | 0.445 | 0.002 | 0.105 | 0.105 | 0.445 | 0.105 | 0.002 | 0.240 | 0.433 | 0.008 | 0.026 |
| V8-decrescente | indeciso | 0.052 | 0.052 | 0.245 | 0.129 | 0.052 | 0.052 | 0.245 | 0.052 | 0.129 | 0.137 | 0.292 | 0.279 | 0.477 |
| R2 | indeciso | 0.111 | 0.111 | 0.074 | 0.111 | 0.111 | 0.111 | 0.074 | 0.074 | 0.074 | 0.250 | 0.444 | 0.184 | 0.360 |
| R3 | funciona | 0.184 | 0.184 | 0.111 | 0.184 | 0.184 | 0.184 | 0.111 | 0.111 | 0.111 | 0.360 | 0.562 | 0.250 | 0.444 |
| R5 | funciona | 0.309 | 0.309 | 0.184 | 0.309 | 0.309 | 0.309 | 0.184 | 0.184 | 0.184 | 0.510 | 0.694 | 0.360 | 0.563 |
| S3 | indeciso | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.067 | 0.170 | 0.340 | 0.170 | 0.340 |
| S10 | indeciso | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.170 | 0.340 | 0.543 | 0.340 | 0.543 |
| S3-sessoes | indeciso | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.111 | 0.250 | 0.444 | 0.250 | 0.444 |
| N1 | indeciso | -0.040 | -0.040 | -0.040 | -0.111 | -0.040 | -0.040 | -0.040 | -0.040 | -0.111 | -0.111 | -0.250 | -0.250 | -0.444 |
| N3 | nao_funciona | -0.067 | -0.067 | -0.184 | -0.170 | -0.067 | -0.067 | -0.184 | -0.184 | -0.360 | -0.170 | -0.340 | -0.562 | -0.735 |
| N5 | nao_funciona | -0.096 | -0.096 | -0.309 | -0.224 | -0.096 | -0.096 | -0.309 | -0.262 | -0.459 | -0.224 | -0.413 | -0.652 | -0.799 |
| N-abordagem-2 | indeciso | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.023 | -0.070 | -0.175 | -0.070 | -0.175 |
| N-abordagem-4 | nao_funciona | -0.037 | -0.037 | -0.141 | -0.037 | -0.037 | -0.037 | -0.141 | -0.141 | -0.141 | -0.105 | -0.240 | -0.298 | -0.498 |
| F1-E3 | funciona | 0.026 | 0.030 | 0.082 | 0.039 | 0.026 | 0.059 | 0.093 | 0.082 | 0.270 | 0.075 | 0.179 | 0.446 | 0.608 |
| F3-E3 | funciona | 0.022 | 0.025 | 0.071 | 0.033 | 0.022 | 0.050 | 0.080 | 0.071 | 0.231 | 0.064 | 0.154 | 0.383 | 0.521 |
| F7-1 | indeciso | 0.014 | 0.022 | 0.014 | 0.032 | 0.014 | 0.022 | 0.022 | 0.014 | 0.049 | 0.041 | 0.102 | 0.116 | 0.220 |
| F-infra-E3 | funciona | 0.029 | 0.034 | 0.094 | 0.044 | 0.029 | 0.067 | 0.106 | 0.094 | 0.309 | 0.086 | 0.205 | 0.510 | 0.694 |
| M11 | indeciso | 0.021 | 0.021 | -0.014 | 0.015 | 0.021 | 0.021 | -0.014 | 0.021 | 0.015 | 0.059 | 0.136 | 0.040 | 0.085 |
| M21 | indeciso | 0.023 | 0.023 | 0.017 | 0.023 | 0.023 | 0.029 | 0.017 | 0.054 | 0.109 | 0.063 | 0.144 | 0.224 | 0.365 |
| M33 | indeciso | 0.007 | 0.007 | -0.088 | -0.014 | 0.007 | 0.011 | -0.088 | 0.056 | 0.110 | 0.017 | 0.034 | 0.192 | 0.274 |
| B-folga-0,001 | funciona | 0.034 | 0.034 | 0.106 | 0.001 | 0.034 | 0.067 | 0.106 | 0.106 | 0.017 | 0.097 | 0.225 | 0.053 | 0.141 |
| B-folga-0,05 | funciona | 0.034 | 0.034 | 0.106 | 0.097 | 0.034 | 0.067 | 0.106 | 0.106 | 0.360 | 0.097 | 0.225 | 0.562 | 0.735 |
| C3-abaixo-do-alvo | nao_funciona | 0.097 | 0.097 | 0.242 | 0.097 | -0.170 | 0.170 | 0.242 | 0.242 | -0.360 | 0.225 | 0.414 | -0.562 | -0.735 |
| C3-acima-do-alvo | funciona | 0.097 | 0.097 | 0.242 | 0.097 | 0.097 | 0.170 | 0.242 | 0.242 | 0.360 | 0.225 | 0.414 | 0.562 | 0.735 |
| D-E3 | funciona | 0.034 | 0.034 | 0.106 | 0.051 | 0.034 | 0.067 | 0.106 | 0.106 | 0.309 | 0.097 | 0.225 | 0.510 | 0.694 |
| D-N3 | nao_funciona | -0.067 | -0.067 | -0.184 | -0.170 | -0.067 | -0.067 | -0.184 | -0.184 | -0.360 | -0.170 | -0.340 | -0.562 | -0.735 |
| D-M21 | indeciso | 0.023 | 0.023 | 0.017 | 0.023 | 0.023 | 0.029 | 0.017 | 0.054 | 0.109 | 0.063 | 0.144 | 0.224 | 0.365 |
| P-E3-V5 | funciona | 0.052 | 0.052 | 0.245 | 0.048 | 0.052 | 0.058 | 0.245 | 0.108 | 0.177 | 0.137 | 0.292 | 0.350 | 0.553 |
| P-E3-V15 | funciona | 0.096 | 0.096 | 0.420 | 0.064 | 0.096 | 0.100 | 0.420 | 0.145 | 0.164 | 0.224 | 0.413 | 0.332 | 0.535 |
| Q-E3-R1-neg | indeciso | -0.005 | -0.005 | 0.084 | -0.052 | -0.005 | 0.023 | 0.084 | 0.084 | 0.240 | -0.012 | -0.022 | 0.375 | 0.490 |
| G-E2-passo | indeciso | 0.033 | 0.033 | 0.073 | 0.077 | 0.033 | 0.053 | 0.073 | 0.073 | 0.229 | 0.095 | 0.222 | 0.419 | 0.618 |
| G-V5-repetidos | indeciso | 0.040 | 0.040 | 0.167 | 0.086 | 0.040 | 0.040 | 0.167 | 0.040 | 0.086 | 0.111 | 0.249 | 0.206 | 0.390 |

## Cenários em que nenhuma variante acerta (limiar 0.3)

- `B-folga-0,001` (E3 com folga de 0,001 a 0,003 sobre o alvo): esperado `funciona`, porque três variações positivas com evolução (qualquer melhora conta).


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

## Propriedades

| Variante | Propriedade | Verificados | Violações | Exemplo |
|---|---|---|---|---|
| atual | limites | 40 | 0 |  |
| atual | determinismo | 40 | 0 |  |
| atual | ordem_de_entrada | 40 | 0 |  |
| atual | monotonicidade | 80 | 0 |  |
| atual | simetria | 35 | 27 | E2: +0.0332 e espelhado -0.0533 |
| atual | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| sem_falhas_em_nconfig | limites | 40 | 0 |  |
| sem_falhas_em_nconfig | determinismo | 40 | 0 |  |
| sem_falhas_em_nconfig | ordem_de_entrada | 40 | 0 |  |
| sem_falhas_em_nconfig | monotonicidade | 80 | 0 |  |
| sem_falhas_em_nconfig | simetria | 35 | 26 | E2: +0.0332 e espelhado -0.0533 |
| sem_falhas_em_nconfig | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| por_tipo | limites | 40 | 0 |  |
| por_tipo | determinismo | 40 | 0 |  |
| por_tipo | ordem_de_entrada | 40 | 0 |  |
| por_tipo | monotonicidade | 80 | 0 |  |
| por_tipo | simetria | 35 | 27 | E2: +0.0733 e espelhado -0.1111 |
| por_tipo | volume_sem_ganho | 1 |  | V3 +0.1064, V20 +0.4447, razão 4.18 |
| folga | limites | 40 | 0 |  |
| folga | determinismo | 40 | 0 |  |
| folga | ordem_de_entrada | 40 | 0 |  |
| folga | monotonicidade | 80 | 0 |  |
| folga | simetria | 35 | 34 | E1: +0.0123 e espelhado -0.0400 |
| folga | volume_sem_ganho | 1 |  | V3 +0.0005, V20 +0.0021, razão 4.31 |
| exige_alvo | limites | 40 | 0 |  |
| exige_alvo | determinismo | 40 | 0 |  |
| exige_alvo | ordem_de_entrada | 40 | 0 |  |
| exige_alvo | monotonicidade | 80 | 0 |  |
| exige_alvo | simetria | 35 | 27 | E2: +0.0332 e espelhado -0.0533 |
| exige_alvo | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| b_variacao_sem_ganho | limites | 40 | 0 |  |
| b_variacao_sem_ganho | determinismo | 40 | 0 |  |
| b_variacao_sem_ganho | ordem_de_entrada | 40 | 0 |  |
| b_variacao_sem_ganho | monotonicidade | 80 | 0 |  |
| b_variacao_sem_ganho | simetria | 35 | 15 | V3: +0.0340 e espelhado -0.0672 |
| b_variacao_sem_ganho | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| por_tipo+sem_falhas | limites | 40 | 0 |  |
| por_tipo+sem_falhas | determinismo | 40 | 0 |  |
| por_tipo+sem_falhas | ordem_de_entrada | 40 | 0 |  |
| por_tipo+sem_falhas | monotonicidade | 80 | 0 |  |
| por_tipo+sem_falhas | simetria | 35 | 26 | E2: +0.0733 e espelhado -0.1111 |
| por_tipo+sem_falhas | volume_sem_ganho | 1 |  | V3 +0.1064, V20 +0.4447, razão 4.18 |
| por_tipo+melhora | limites | 40 | 0 |  |
| por_tipo+melhora | determinismo | 40 | 0 |  |
| por_tipo+melhora | ordem_de_entrada | 40 | 0 |  |
| por_tipo+melhora | monotonicidade | 80 | 8 | E5 + positiva de nó novo: 0.1674 -> 0.1655 |
| por_tipo+melhora | simetria | 35 | 27 | E2: +0.0733 e espelhado -0.0533 |
| por_tipo+melhora | volume_sem_ganho | 1 |  | V3 +0.0340, V20 +0.1053, razão 3.10 |
| completa | limites | 40 | 0 |  |
| completa | determinismo | 40 | 0 |  |
| completa | ordem_de_entrada | 40 | 0 |  |
| completa | monotonicidade | 80 | 13 | E5 + positiva de nó novo: 0.3787 -> 0.3114 |
| completa | simetria | 35 | 34 | E1: +0.0123 e espelhado -0.0400 |
| completa | volume_sem_ganho | 1 |  | V3 +0.0005, V20 +0.0021, razão 4.31 |
| prior_0_5 | limites | 40 | 0 |  |
| prior_0_5 | determinismo | 40 | 0 |  |
| prior_0_5 | ordem_de_entrada | 40 | 0 |  |
| prior_0_5 | monotonicidade | 80 | 0 |  |
| prior_0_5 | simetria | 35 | 27 | E2: +0.0950 e espelhado -0.1406 |
| prior_0_5 | volume_sem_ganho | 1 |  | V3 +0.0968, V20 +0.2401, razão 2.48 |
| prior_0_25 | limites | 40 | 0 |  |
| prior_0_25 | determinismo | 40 | 0 |  |
| prior_0_25 | ordem_de_entrada | 40 | 0 |  |
| prior_0_25 | monotonicidade | 80 | 0 |  |
| prior_0_25 | simetria | 35 | 27 | E2: +0.2220 e espelhado -0.2975 |
| prior_0_25 | volume_sem_ganho | 1 |  | V3 +0.2253, V20 +0.4326, razão 1.92 |
| completa+prior_0_5 | limites | 40 | 0 |  |
| completa+prior_0_5 | determinismo | 40 | 0 |  |
| completa+prior_0_5 | ordem_de_entrada | 40 | 0 |  |
| completa+prior_0_5 | monotonicidade | 80 | 13 | E5 + positiva de nó novo: 0.5805 -> 0.5131 |
| completa+prior_0_5 | simetria | 35 | 34 | E1: +0.0400 e espelhado -0.1111 |
| completa+prior_0_5 | volume_sem_ganho | 1 |  | V3 +0.0019, V20 +0.0077, razão 4.11 |
| completa+prior_0_25 | limites | 40 | 0 |  |
| completa+prior_0_25 | determinismo | 40 | 0 |  |
| completa+prior_0_25 | ordem_de_entrada | 40 | 0 |  |
| completa+prior_0_25 | monotonicidade | 80 | 13 | E5 + positiva de nó novo: 0.7480 -> 0.6967 |
| completa+prior_0_25 | simetria | 35 | 34 | E1: +0.1111 e espelhado -0.2500 |
| completa+prior_0_25 | volume_sem_ganho | 1 |  | V3 +0.0069, V20 +0.0260, razão 3.78 |
