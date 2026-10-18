# Sensibilidade do veredito aos parâmetros

Gerado por `scripts.verdict_lab` em 2026-10-18T23:47:11Z, commit `5323325558f8`, comando `sensibilidade`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

Efeito = média de |Δ veredito| sobre 43 cenários do catálogo.

## Variante `atual`: parâmetros por efeito (variação isolada)

| Posição | Parâmetro | Valor base | Valor de maior efeito | Efeito médio | Efeito máximo |
|---|---|---|---|---|---|
| 1 | prior | 1.000 | 0.500 | 0.082 | 0.202 |
| 2 | q_validated_complete | 1.000 | 1.500 | 0.040 | 0.117 |
| 3 | d_new_node_or_dataset | 1.000 | 1.500 | 0.029 | 0.117 |
| 4 | d_new_seed | 0.200 | 0.300 | 0.014 | 0.061 |
| 5 | gamma | 0.500 | 0.250 | 0.014 | 0.060 |
| 6 | approach_failure_q | 0.300 | 0.450 | 0.001 | 0.033 |
| 7 | d_new_session | 0.500 | 0.750 | 0.001 | 0.037 |
| 8 | lambda_ambiguous | 0.500 | 0.750 | 0.000 | 0.005 |
| 9 | q_validated_incomplete | 0.700 | 0.350 | 0.000 | 0.000 |
| 10 | q_divergent | 0.300 | 0.150 | 0.000 | 0.000 |

Pares (os quatro de maior efeito, ambos × 0,75 ou × 1,25; interação = efeito do par − soma dos isolados):

| Par | Fator | Efeito médio | Interação |
|---|---|---|---|
| prior+q_validated_complete | 0.750 | 0.001 | -0.047 |
| prior+q_validated_complete | 1.250 | 0.000 | -0.036 |
| prior+d_new_node_or_dataset | 0.750 | 0.010 | -0.032 |
| prior+d_new_node_or_dataset | 1.250 | 0.006 | -0.025 |
| prior+d_new_seed | 0.750 | 0.020 | -0.015 |
| prior+d_new_seed | 1.250 | 0.012 | -0.012 |
| q_validated_complete+d_new_node_or_dataset | 0.750 | 0.030 | -0.004 |
| q_validated_complete+d_new_node_or_dataset | 1.250 | 0.038 | 0.003 |
| q_validated_complete+d_new_seed | 0.750 | 0.024 | -0.002 |
| q_validated_complete+d_new_seed | 1.250 | 0.029 | 0.002 |
| d_new_node_or_dataset+d_new_seed | 0.750 | 0.020 | -0.001 |
| d_new_node_or_dataset+d_new_seed | 1.250 | 0.020 | -0.001 |

## Variante `por_tipo`: parâmetros por efeito (variação isolada)

| Posição | Parâmetro | Valor base | Valor de maior efeito | Efeito médio | Efeito máximo |
|---|---|---|---|---|---|
| 1 | prior | 1.000 | 0.500 | 0.131 | 0.202 |
| 2 | q_validated_complete | 1.000 | 0.500 | 0.080 | 0.194 |
| 3 | d_variacao | 1.000 | 0.500 | 0.077 | 0.194 |
| 4 | gamma | 0.500 | 0.250 | 0.031 | 0.104 |
| 5 | d_replica_no | 0.500 | 0.250 | 0.003 | 0.073 |
| 6 | approach_failure_q | 0.300 | 0.450 | 0.002 | 0.084 |
| 7 | d_semente | 0.200 | 0.100 | 0.002 | 0.066 |
| 8 | d_sessao | 0.500 | 0.750 | 0.001 | 0.037 |
| 9 | lambda_ambiguous | 0.500 | 0.250 | 0.001 | 0.012 |
| 10 | q_validated_incomplete | 0.700 | 0.350 | 0.000 | 0.000 |
| 11 | q_divergent | 0.300 | 0.150 | 0.000 | 0.000 |
| 12 | d_dataset | 1.000 | 0.500 | 0.000 | 0.000 |

Pares (os quatro de maior efeito, ambos × 0,75 ou × 1,25; interação = efeito do par − soma dos isolados):

| Par | Fator | Efeito médio | Interação |
|---|---|---|---|
| prior+q_validated_complete | 0.750 | 0.002 | -0.086 |
| prior+q_validated_complete | 1.250 | 0.001 | -0.067 |
| prior+d_variacao | 0.750 | 0.004 | -0.083 |
| prior+d_variacao | 1.250 | 0.002 | -0.064 |
| prior+gamma | 0.750 | 0.062 | -0.001 |
| prior+gamma | 1.250 | 0.040 | -0.004 |
| q_validated_complete+d_variacao | 0.750 | 0.069 | -0.008 |
| q_validated_complete+d_variacao | 1.250 | 0.075 | 0.004 |
| q_validated_complete+gamma | 0.750 | 0.030 | -0.023 |
| q_validated_complete+gamma | 1.250 | 0.026 | -0.022 |
| d_variacao+gamma | 0.750 | 0.028 | -0.023 |
| d_variacao+gamma | 1.250 | 0.024 | -0.022 |

## Variante `completa2`: parâmetros por efeito (variação isolada)

| Posição | Parâmetro | Valor base | Valor de maior efeito | Efeito médio | Efeito máximo |
|---|---|---|---|---|---|
| 1 | prior | 1.000 | 0.500 | 0.148 | 0.203 |
| 2 | d_variacao | 1.000 | 0.500 | 0.105 | 0.202 |
| 3 | q_validated_complete | 1.000 | 0.500 | 0.104 | 0.202 |
| 4 | variacao_util_epsilon | 0.000 | 0.010 | 0.058 | 0.545 |
| 5 | d_semente | 0.200 | 0.100 | 0.005 | 0.066 |
| 6 | d_replica_no | 0.500 | 0.250 | 0.003 | 0.073 |
| 7 | approach_failure_q | 0.300 | 0.450 | 0.003 | 0.084 |
| 8 | gamma | 0.500 | 0.250 | 0.002 | 0.041 |
| 9 | lambda_ambiguous | 0.500 | 0.250 | 0.002 | 0.039 |
| 10 | d_sessao | 0.500 | 0.750 | 0.001 | 0.037 |
| 11 | q_validated_incomplete | 0.700 | 0.350 | 0.000 | 0.000 |
| 12 | q_divergent | 0.300 | 0.150 | 0.000 | 0.000 |
| 13 | d_dataset | 1.000 | 0.500 | 0.000 | 0.000 |

Pares (os quatro de maior efeito, ambos × 0,75 ou × 1,25; interação = efeito do par − soma dos isolados):

| Par | Fator | Efeito médio | Interação |
|---|---|---|---|
| prior+d_variacao | 0.750 | 0.007 | -0.100 |
| prior+d_variacao | 1.250 | 0.004 | -0.079 |
| prior+q_validated_complete | 0.750 | 0.002 | -0.105 |
| prior+q_validated_complete | 1.250 | 0.001 | -0.081 |
| prior+variacao_util_epsilon | 0.750 | 0.093 | -0.023 |
| prior+variacao_util_epsilon | 1.250 | 0.089 | -0.009 |
| d_variacao+q_validated_complete | 0.750 | 0.091 | -0.008 |
| d_variacao+q_validated_complete | 1.250 | 0.090 | 0.003 |
| d_variacao+variacao_util_epsilon | 0.750 | 0.096 | -0.012 |
| d_variacao+variacao_util_epsilon | 1.250 | 0.082 | -0.019 |
| q_validated_complete+variacao_util_epsilon | 0.750 | 0.095 | -0.011 |
| q_validated_complete+variacao_util_epsilon | 1.250 | 0.083 | -0.017 |
