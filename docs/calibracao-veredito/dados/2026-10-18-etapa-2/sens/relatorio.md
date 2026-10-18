# Sensibilidade do veredito aos parâmetros

Gerado por `scripts.verdict_lab` em 2026-10-18T22:18:12Z, commit `fa5573b7f8d6`, comando `sensibilidade`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

Efeito = média de |Δ veredito| sobre 40 cenários do catálogo.

## Variante `atual`: parâmetros por efeito (variação isolada)

| Posição | Parâmetro | Valor base | Valor de maior efeito | Efeito médio | Efeito máximo |
|---|---|---|---|---|---|
| 1 | prior | 1.000 | 0.500 | 0.085 | 0.202 |
| 2 | q_validated_complete | 1.000 | 1.500 | 0.042 | 0.117 |
| 3 | d_new_node_or_dataset | 1.000 | 1.500 | 0.030 | 0.117 |
| 4 | d_new_seed | 0.200 | 0.300 | 0.013 | 0.061 |
| 5 | gamma | 0.500 | 0.250 | 0.013 | 0.060 |
| 6 | approach_failure_q | 0.300 | 0.450 | 0.001 | 0.033 |
| 7 | d_new_session | 0.500 | 0.750 | 0.001 | 0.037 |
| 8 | lambda_ambiguous | 0.500 | 0.750 | 0.000 | 0.005 |
| 9 | q_validated_incomplete | 0.700 | 0.350 | 0.000 | 0.000 |
| 10 | q_divergent | 0.300 | 0.150 | 0.000 | 0.000 |

Pares (os quatro de maior efeito, ambos × 0,75 ou × 1,25; interação = efeito do par − soma dos isolados):

| Par | Fator | Efeito médio | Interação |
|---|---|---|---|
| prior+q_validated_complete | 0.750 | 0.001 | -0.048 |
| prior+q_validated_complete | 1.250 | 0.000 | -0.037 |
| prior+d_new_node_or_dataset | 0.750 | 0.009 | -0.034 |
| prior+d_new_node_or_dataset | 1.250 | 0.006 | -0.026 |
| prior+d_new_seed | 0.750 | 0.020 | -0.015 |
| prior+d_new_seed | 1.250 | 0.012 | -0.011 |
| q_validated_complete+d_new_node_or_dataset | 0.750 | 0.031 | -0.004 |
| q_validated_complete+d_new_node_or_dataset | 1.250 | 0.039 | 0.004 |
| q_validated_complete+d_new_seed | 0.750 | 0.025 | -0.002 |
| q_validated_complete+d_new_seed | 1.250 | 0.029 | 0.001 |
| d_new_node_or_dataset+d_new_seed | 0.750 | 0.020 | -0.001 |
| d_new_node_or_dataset+d_new_seed | 1.250 | 0.021 | -0.000 |

## Variante `por_tipo`: parâmetros por efeito (variação isolada)

| Posição | Parâmetro | Valor base | Valor de maior efeito | Efeito médio | Efeito máximo |
|---|---|---|---|---|---|
| 1 | prior | 1.000 | 0.500 | 0.132 | 0.202 |
| 2 | q_validated_complete | 1.000 | 0.500 | 0.079 | 0.194 |
| 3 | d_variacao | 1.000 | 0.500 | 0.076 | 0.194 |
| 4 | gamma | 0.500 | 0.250 | 0.029 | 0.104 |
| 5 | d_replica_no | 0.500 | 0.250 | 0.003 | 0.073 |
| 6 | approach_failure_q | 0.300 | 0.450 | 0.003 | 0.084 |
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
| prior+d_variacao | 0.750 | 0.004 | -0.082 |
| prior+d_variacao | 1.250 | 0.003 | -0.064 |
| prior+gamma | 0.750 | 0.063 | 0.001 |
| prior+gamma | 1.250 | 0.041 | -0.002 |
| q_validated_complete+d_variacao | 0.750 | 0.068 | -0.008 |
| q_validated_complete+d_variacao | 1.250 | 0.075 | 0.004 |
| q_validated_complete+gamma | 0.750 | 0.029 | -0.023 |
| q_validated_complete+gamma | 1.250 | 0.025 | -0.022 |
| d_variacao+gamma | 0.750 | 0.027 | -0.023 |
| d_variacao+gamma | 1.250 | 0.023 | -0.022 |

## Variante `completa`: parâmetros por efeito (variação isolada)

| Posição | Parâmetro | Valor base | Valor de maior efeito | Efeito médio | Efeito máximo |
|---|---|---|---|---|---|
| 1 | prior | 1.000 | 0.500 | 0.135 | 0.203 |
| 2 | q_validated_complete | 1.000 | 0.500 | 0.093 | 0.202 |
| 3 | d_variacao | 1.000 | 0.500 | 0.089 | 0.202 |
| 4 | variacao_util_epsilon | 0.000 | 0.010 | 0.037 | 0.504 |
| 5 | gamma | 0.500 | 0.250 | 0.008 | 0.076 |
| 6 | d_semente | 0.200 | 0.300 | 0.007 | 0.061 |
| 7 | d_replica_no | 0.500 | 0.250 | 0.004 | 0.073 |
| 8 | approach_failure_q | 0.300 | 0.450 | 0.003 | 0.084 |
| 9 | lambda_ambiguous | 0.500 | 0.250 | 0.002 | 0.039 |
| 10 | d_sessao | 0.500 | 0.750 | 0.001 | 0.037 |
| 11 | q_validated_incomplete | 0.700 | 0.350 | 0.000 | 0.000 |
| 12 | q_divergent | 0.300 | 0.150 | 0.000 | 0.000 |
| 13 | d_dataset | 1.000 | 0.500 | 0.000 | 0.000 |

Pares (os quatro de maior efeito, ambos × 0,75 ou × 1,25; interação = efeito do par − soma dos isolados):

| Par | Fator | Efeito médio | Interação |
|---|---|---|---|
| prior+q_validated_complete | 0.750 | 0.002 | -0.094 |
| prior+q_validated_complete | 1.250 | 0.001 | -0.073 |
| prior+d_variacao | 0.750 | 0.008 | -0.087 |
| prior+d_variacao | 1.250 | 0.005 | -0.068 |
| prior+variacao_util_epsilon | 0.750 | 0.073 | -0.017 |
| prior+variacao_util_epsilon | 1.250 | 0.068 | -0.006 |
| q_validated_complete+d_variacao | 0.750 | 0.079 | -0.007 |
| q_validated_complete+d_variacao | 1.250 | 0.078 | 0.003 |
| q_validated_complete+variacao_util_epsilon | 0.750 | 0.074 | -0.007 |
| q_validated_complete+variacao_util_epsilon | 1.250 | 0.063 | -0.013 |
| d_variacao+variacao_util_epsilon | 0.750 | 0.071 | -0.008 |
| d_variacao+variacao_util_epsilon | 1.250 | 0.063 | -0.012 |
