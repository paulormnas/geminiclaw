# Simulação do veredito com resposta conhecida

Gerado por `scripts.verdict_lab` em 2026-10-18T23:54:36Z, commit `5323325558f8`, comando `simulacao`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

96 pontos de grade, 40 repetições por tipo de hipótese e ponto, até 20 tentativas. A decisão é tomada na primeira vez em que |veredito| alcança o limiar. As taxas são médias sobre os pontos da grade (detalhe por ponto em `resultados.csv`).

- **Falsa validação:** hipóteses `falsa` ou `sem_efeito` validadas (registradas sem contribuir).
- **Poder:** hipóteses `verdadeira` validadas.
- **Custo por validação útil:** tentativas gastas em todas as hipóteses por `verdadeira` validada.

## Resumo por variante (limiar 0.2, orçamento 20)

| Variante | Falsa validação (sem efeito) | Falsa validação (falsa) | Poder | Falsa refutação | Indecisão (verdadeira) | Refutação correta | Custo por validação útil |
|---|---|---|---|---|---|---|---|
| atual | 0.003 | 0.000 | 0.093 | 0.000 | 0.907 | 0.515 | 505.384 |
| sem_falhas_em_nconfig | 0.003 | 0.000 | 0.094 | 0.000 | 0.906 | 0.515 | 504.249 |
| por_tipo | 0.023 | 0.001 | 0.588 | 0.023 | 0.389 | 0.959 | 145.114 |
| folga | 0.012 | 0.001 | 0.229 | 0.008 | 0.763 | 0.895 | 394.746 |
| exige_alvo | 0.003 | 0.000 | 0.093 | 0.000 | 0.907 | 0.515 | 505.384 |
| b_variacao_sem_ganho | 0.003 | 0.000 | 0.096 | 0.000 | 0.904 | 0.514 | 473.246 |
| por_tipo+sem_falhas | 0.023 | 0.001 | 0.595 | 0.023 | 0.382 | 0.957 | 131.360 |
| por_tipo+melhora | 0.006 | 0.000 | 0.141 | 0.001 | 0.858 | 0.597 | 740.351 |
| completa | 0.050 | 0.004 | 0.578 | 0.008 | 0.415 | 0.858 | 109.918 |
| prior_0_5 | 0.052 | 0.004 | 0.373 | 0.020 | 0.607 | 0.897 | 305.772 |
| prior_0_25 | 0.450 | 0.130 | 0.830 | 0.137 | 0.033 | 0.862 | 8.615 |
| completa+prior_0_5 | 0.250 | 0.045 | 0.875 | 0.068 | 0.057 | 0.926 | 20.603 |
| completa+prior_0_25 | 0.400 | 0.085 | 0.893 | 0.103 | 0.004 | 0.911 | 9.399 |
| base_alvo | 0.006 | 0.000 | 0.141 | 0.001 | 0.858 | 0.597 | 740.351 |
| completa2 | 0.080 | 0.006 | 0.624 | 0.031 | 0.344 | 0.872 | 70.543 |
| completa2@eps=0 | 0.080 | 0.006 | 0.624 | 0.031 | 0.344 | 0.872 | 70.543 |
| completa2@eps=delta | 0.027 | 0.002 | 0.309 | 0.035 | 0.657 | 0.895 | 358.585 |
| completa2@eps=sigma | 0.019 | 0.001 | 0.315 | 0.038 | 0.646 | 0.903 | 460.225 |
| completa2@d_replica=0.3 | 0.075 | 0.005 | 0.611 | 0.032 | 0.357 | 0.873 | 73.141 |
| completa2@d_replica=0.5 | 0.080 | 0.006 | 0.624 | 0.031 | 0.344 | 0.872 | 70.543 |
| completa2@d_replica=0.7 | 0.086 | 0.006 | 0.639 | 0.030 | 0.331 | 0.871 | 68.275 |
| completa2@d_replica=0.9 | 0.091 | 0.007 | 0.648 | 0.030 | 0.322 | 0.870 | 67.071 |
| completa2+prior_0_75 | 0.164 | 0.016 | 0.778 | 0.042 | 0.180 | 0.902 | 39.472 |
| completa2+prior_0_5 | 0.334 | 0.054 | 0.887 | 0.080 | 0.033 | 0.915 | 16.729 |
| completa2+prior_0_25 | 0.549 | 0.148 | 0.894 | 0.104 | 0.002 | 0.851 | 5.847 |

## Resumo por variante (limiar 0.25, orçamento 20)

| Variante | Falsa validação (sem efeito) | Falsa validação (falsa) | Poder | Falsa refutação | Indecisão (verdadeira) | Refutação correta | Custo por validação útil |
|---|---|---|---|---|---|---|---|
| atual | 0.001 | 0.000 | 0.043 | 0.000 | 0.957 | 0.300 | 592.683 |
| sem_falhas_em_nconfig | 0.001 | 0.000 | 0.043 | 0.000 | 0.957 | 0.300 | 705.515 |
| por_tipo | 0.009 | 0.000 | 0.466 | 0.011 | 0.522 | 0.921 | 275.429 |
| folga | 0.004 | 0.000 | 0.130 | 0.002 | 0.868 | 0.806 | 315.624 |
| exige_alvo | 0.001 | 0.000 | 0.043 | 0.000 | 0.957 | 0.300 | 592.683 |
| b_variacao_sem_ganho | 0.001 | 0.000 | 0.045 | 0.000 | 0.955 | 0.300 | 676.044 |
| por_tipo+sem_falhas | 0.009 | 0.000 | 0.473 | 0.011 | 0.516 | 0.920 | 285.598 |
| por_tipo+melhora | 0.002 | 0.000 | 0.079 | 0.000 | 0.921 | 0.424 | 647.360 |
| completa | 0.021 | 0.002 | 0.400 | 0.003 | 0.597 | 0.777 | 288.203 |
| prior_0_5 | 0.036 | 0.001 | 0.214 | 0.007 | 0.779 | 0.833 | 355.661 |
| prior_0_25 | 0.440 | 0.128 | 0.812 | 0.132 | 0.057 | 0.857 | 10.717 |
| completa+prior_0_5 | 0.187 | 0.030 | 0.840 | 0.058 | 0.102 | 0.917 | 27.746 |
| completa+prior_0_25 | 0.354 | 0.073 | 0.891 | 0.096 | 0.013 | 0.917 | 12.063 |
| base_alvo | 0.002 | 0.000 | 0.079 | 0.000 | 0.921 | 0.424 | 647.360 |
| completa2 | 0.035 | 0.002 | 0.457 | 0.019 | 0.524 | 0.815 | 155.757 |
| completa2@eps=0 | 0.035 | 0.002 | 0.457 | 0.019 | 0.524 | 0.815 | 155.757 |
| completa2@eps=delta | 0.009 | 0.000 | 0.182 | 0.022 | 0.796 | 0.833 | 620.181 |
| completa2@eps=sigma | 0.006 | 0.000 | 0.190 | 0.024 | 0.785 | 0.841 | 691.858 |
| completa2@d_replica=0.3 | 0.032 | 0.002 | 0.440 | 0.020 | 0.541 | 0.815 | 160.102 |
| completa2@d_replica=0.5 | 0.035 | 0.002 | 0.457 | 0.019 | 0.524 | 0.815 | 155.757 |
| completa2@d_replica=0.7 | 0.041 | 0.002 | 0.470 | 0.019 | 0.511 | 0.814 | 152.270 |
| completa2@d_replica=0.9 | 0.045 | 0.003 | 0.482 | 0.019 | 0.499 | 0.813 | 149.348 |
| completa2+prior_0_75 | 0.098 | 0.009 | 0.664 | 0.031 | 0.305 | 0.864 | 61.062 |
| completa2+prior_0_5 | 0.258 | 0.037 | 0.853 | 0.071 | 0.077 | 0.905 | 22.720 |
| completa2+prior_0_25 | 0.531 | 0.143 | 0.896 | 0.097 | 0.006 | 0.851 | 7.108 |

## Resumo por variante (limiar 0.3, orçamento 20)

| Variante | Falsa validação (sem efeito) | Falsa validação (falsa) | Poder | Falsa refutação | Indecisão (verdadeira) | Refutação correta | Custo por validação útil |
|---|---|---|---|---|---|---|---|
| atual | 0.000 | 0.000 | 0.010 | 0.000 | 0.990 | 0.060 | 1161.966 |
| sem_falhas_em_nconfig | 0.000 | 0.000 | 0.010 | 0.000 | 0.990 | 0.060 | 1161.966 |
| por_tipo | 0.003 | 0.000 | 0.333 | 0.003 | 0.664 | 0.864 | 511.249 |
| folga | 0.001 | 0.000 | 0.085 | 0.001 | 0.915 | 0.679 | 447.083 |
| exige_alvo | 0.000 | 0.000 | 0.010 | 0.000 | 0.990 | 0.060 | 1161.966 |
| b_variacao_sem_ganho | 0.000 | 0.000 | 0.010 | 0.000 | 0.990 | 0.060 | 1159.307 |
| por_tipo+sem_falhas | 0.003 | 0.000 | 0.339 | 0.003 | 0.658 | 0.863 | 482.242 |
| por_tipo+melhora | 0.001 | 0.000 | 0.043 | 0.000 | 0.957 | 0.266 | 794.331 |
| completa | 0.005 | 0.000 | 0.233 | 0.001 | 0.767 | 0.679 | 608.230 |
| prior_0_5 | 0.013 | 0.000 | 0.145 | 0.002 | 0.854 | 0.721 | 237.588 |
| prior_0_25 | 0.068 | 0.006 | 0.515 | 0.034 | 0.451 | 0.906 | 236.103 |
| completa+prior_0_5 | 0.095 | 0.009 | 0.732 | 0.013 | 0.255 | 0.888 | 55.470 |
| completa+prior_0_25 | 0.302 | 0.059 | 0.881 | 0.085 | 0.034 | 0.917 | 15.657 |
| base_alvo | 0.001 | 0.000 | 0.043 | 0.000 | 0.957 | 0.266 | 794.331 |
| completa2 | 0.011 | 0.001 | 0.299 | 0.010 | 0.691 | 0.753 | 375.153 |
| completa2@eps=0 | 0.011 | 0.001 | 0.299 | 0.010 | 0.691 | 0.753 | 375.153 |
| completa2@eps=delta | 0.003 | 0.000 | 0.105 | 0.012 | 0.883 | 0.759 | 922.461 |
| completa2@eps=sigma | 0.002 | 0.000 | 0.113 | 0.013 | 0.874 | 0.767 | 988.599 |
| completa2@d_replica=0.3 | 0.010 | 0.001 | 0.273 | 0.010 | 0.717 | 0.754 | 385.210 |
| completa2@d_replica=0.5 | 0.011 | 0.001 | 0.299 | 0.010 | 0.691 | 0.753 | 375.153 |
| completa2@d_replica=0.7 | 0.013 | 0.001 | 0.317 | 0.010 | 0.673 | 0.751 | 366.297 |
| completa2@d_replica=0.9 | 0.016 | 0.001 | 0.329 | 0.009 | 0.662 | 0.751 | 360.821 |
| completa2+prior_0_75 | 0.048 | 0.003 | 0.510 | 0.020 | 0.471 | 0.817 | 122.086 |
| completa2+prior_0_5 | 0.142 | 0.014 | 0.746 | 0.035 | 0.220 | 0.875 | 45.295 |
| completa2+prior_0_25 | 0.388 | 0.070 | 0.888 | 0.091 | 0.021 | 0.901 | 13.123 |

## Resumo por variante (limiar 0.35, orçamento 20)

| Variante | Falsa validação (sem efeito) | Falsa validação (falsa) | Poder | Falsa refutação | Indecisão (verdadeira) | Refutação correta | Custo por validação útil |
|---|---|---|---|---|---|---|---|
| atual | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| sem_falhas_em_nconfig | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| por_tipo | 0.002 | 0.000 | 0.221 | 0.001 | 0.778 | 0.779 | 556.819 |
| folga | 0.000 | 0.000 | 0.055 | 0.000 | 0.945 | 0.507 | 561.907 |
| exige_alvo | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| b_variacao_sem_ganho | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| por_tipo+sem_falhas | 0.002 | 0.000 | 0.227 | 0.001 | 0.773 | 0.775 | 596.438 |
| por_tipo+melhora | 0.000 | 0.000 | 0.016 | 0.000 | 0.984 | 0.145 | 1064.158 |
| completa | 0.002 | 0.000 | 0.135 | 0.000 | 0.865 | 0.552 | 898.671 |
| prior_0_5 | 0.004 | 0.000 | 0.103 | 0.000 | 0.897 | 0.548 | 358.947 |
| prior_0_25 | 0.052 | 0.005 | 0.397 | 0.016 | 0.587 | 0.868 | 322.755 |
| completa+prior_0_5 | 0.057 | 0.005 | 0.604 | 0.008 | 0.387 | 0.839 | 94.475 |
| completa+prior_0_25 | 0.244 | 0.049 | 0.863 | 0.072 | 0.065 | 0.910 | 20.699 |
| base_alvo | 0.000 | 0.000 | 0.016 | 0.000 | 0.984 | 0.145 | 1064.158 |
| completa2 | 0.003 | 0.000 | 0.171 | 0.005 | 0.823 | 0.681 | 673.553 |
| completa2@eps=0 | 0.003 | 0.000 | 0.171 | 0.005 | 0.823 | 0.681 | 673.553 |
| completa2@eps=delta | 0.001 | 0.000 | 0.053 | 0.006 | 0.941 | 0.665 | 691.683 |
| completa2@eps=sigma | 0.001 | 0.000 | 0.058 | 0.008 | 0.935 | 0.676 | 740.937 |
| completa2@d_replica=0.3 | 0.003 | 0.000 | 0.148 | 0.006 | 0.846 | 0.683 | 710.329 |
| completa2@d_replica=0.5 | 0.003 | 0.000 | 0.171 | 0.005 | 0.823 | 0.681 | 673.553 |
| completa2@d_replica=0.7 | 0.004 | 0.000 | 0.191 | 0.005 | 0.804 | 0.679 | 645.105 |
| completa2@d_replica=0.9 | 0.005 | 0.000 | 0.207 | 0.005 | 0.788 | 0.676 | 628.237 |
| completa2+prior_0_75 | 0.018 | 0.001 | 0.368 | 0.011 | 0.621 | 0.762 | 252.292 |
| completa2+prior_0_5 | 0.095 | 0.009 | 0.647 | 0.027 | 0.326 | 0.837 | 66.761 |
| completa2+prior_0_25 | 0.322 | 0.056 | 0.872 | 0.080 | 0.049 | 0.894 | 17.357 |

## Resumo por variante (limiar 0.4, orçamento 20)

| Variante | Falsa validação (sem efeito) | Falsa validação (falsa) | Poder | Falsa refutação | Indecisão (verdadeira) | Refutação correta | Custo por validação útil |
|---|---|---|---|---|---|---|---|
| atual | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| sem_falhas_em_nconfig | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| por_tipo | 0.001 | 0.000 | 0.129 | 0.000 | 0.871 | 0.670 | 805.222 |
| folga | 0.000 | 0.000 | 0.028 | 0.000 | 0.972 | 0.339 | 943.798 |
| exige_alvo | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| b_variacao_sem_ganho | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | — |
| por_tipo+sem_falhas | 0.001 | 0.000 | 0.129 | 0.000 | 0.871 | 0.667 | 795.961 |
| por_tipo+melhora | 0.000 | 0.000 | 0.003 | 0.000 | 0.997 | 0.064 | 1785.833 |
| completa | 0.000 | 0.000 | 0.070 | 0.000 | 0.930 | 0.413 | 1182.564 |
| prior_0_5 | 0.001 | 0.000 | 0.065 | 0.000 | 0.935 | 0.387 | 698.330 |
| prior_0_25 | 0.039 | 0.002 | 0.299 | 0.007 | 0.694 | 0.814 | 419.136 |
| completa+prior_0_5 | 0.029 | 0.003 | 0.465 | 0.004 | 0.531 | 0.776 | 199.087 |
| completa+prior_0_25 | 0.195 | 0.038 | 0.833 | 0.064 | 0.103 | 0.897 | 26.286 |
| base_alvo | 0.000 | 0.000 | 0.003 | 0.000 | 0.997 | 0.064 | 1785.833 |
| completa2 | 0.001 | 0.000 | 0.088 | 0.002 | 0.910 | 0.589 | 1101.272 |
| completa2@eps=0 | 0.001 | 0.000 | 0.088 | 0.002 | 0.910 | 0.589 | 1101.272 |
| completa2@eps=delta | 0.000 | 0.000 | 0.022 | 0.003 | 0.974 | 0.562 | 1097.646 |
| completa2@eps=sigma | 0.000 | 0.000 | 0.026 | 0.005 | 0.969 | 0.578 | 931.839 |
| completa2@d_replica=0.3 | 0.001 | 0.000 | 0.069 | 0.002 | 0.928 | 0.592 | 1165.262 |
| completa2@d_replica=0.5 | 0.001 | 0.000 | 0.088 | 0.002 | 0.910 | 0.589 | 1101.272 |
| completa2@d_replica=0.7 | 0.001 | 0.000 | 0.110 | 0.002 | 0.888 | 0.588 | 989.915 |
| completa2@d_replica=0.9 | 0.002 | 0.000 | 0.128 | 0.002 | 0.870 | 0.587 | 974.223 |
| completa2+prior_0_75 | 0.006 | 0.001 | 0.233 | 0.006 | 0.761 | 0.703 | 493.180 |
| completa2+prior_0_5 | 0.047 | 0.003 | 0.518 | 0.017 | 0.465 | 0.794 | 116.364 |
| completa2+prior_0_25 | 0.261 | 0.043 | 0.846 | 0.072 | 0.082 | 0.885 | 22.309 |

## Curva de compromisso: falsa validação (sem efeito) / poder, por limiar

| Variante | 0.1 | 0.2 | 0.25 | 0.3 | 0.35 | 0.4 | 0.5 | 0.6 |
|---|---|---|---|---|---|---|---|---|
| atual | 0.05 / 0.32 | 0.00 / 0.09 | 0.00 / 0.04 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| sem_falhas_em_nconfig | 0.05 / 0.32 | 0.00 / 0.09 | 0.00 / 0.04 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| por_tipo | 0.17 / 0.83 | 0.02 / 0.59 | 0.01 / 0.47 | 0.00 / 0.33 | 0.00 / 0.22 | 0.00 / 0.13 | 0.00 / 0.01 | 0.00 / 0.00 |
| folga | 0.10 / 0.64 | 0.01 / 0.23 | 0.00 / 0.13 | 0.00 / 0.08 | 0.00 / 0.05 | 0.00 / 0.03 | 0.00 / 0.00 | 0.00 / 0.00 |
| exige_alvo | 0.05 / 0.32 | 0.00 / 0.09 | 0.00 / 0.04 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| b_variacao_sem_ganho | 0.05 / 0.34 | 0.00 / 0.10 | 0.00 / 0.04 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| por_tipo+sem_falhas | 0.18 / 0.83 | 0.02 / 0.60 | 0.01 / 0.47 | 0.00 / 0.34 | 0.00 / 0.23 | 0.00 / 0.13 | 0.00 / 0.01 | 0.00 / 0.00 |
| por_tipo+melhora | 0.09 / 0.59 | 0.01 / 0.14 | 0.00 / 0.08 | 0.00 / 0.04 | 0.00 / 0.02 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| completa | 0.25 / 0.88 | 0.05 / 0.58 | 0.02 / 0.40 | 0.01 / 0.23 | 0.00 / 0.13 | 0.00 / 0.07 | 0.00 / 0.02 | 0.00 / 0.00 |
| prior_0_5 | 0.44 / 0.83 | 0.05 / 0.37 | 0.04 / 0.21 | 0.01 / 0.14 | 0.00 / 0.10 | 0.00 / 0.07 | 0.00 / 0.01 | 0.00 / 0.00 |
| prior_0_25 | 0.50 / 0.85 | 0.45 / 0.83 | 0.44 / 0.81 | 0.07 / 0.51 | 0.05 / 0.40 | 0.04 / 0.30 | 0.01 / 0.12 | 0.00 / 0.05 |
| completa+prior_0_5 | 0.40 / 0.90 | 0.25 / 0.87 | 0.19 / 0.84 | 0.09 / 0.73 | 0.06 / 0.60 | 0.03 / 0.46 | 0.00 / 0.20 | 0.00 / 0.06 |
| completa+prior_0_25 | 0.46 / 0.88 | 0.40 / 0.89 | 0.35 / 0.89 | 0.30 / 0.88 | 0.24 / 0.86 | 0.20 / 0.83 | 0.08 / 0.64 | 0.02 / 0.40 |
| base_alvo | 0.09 / 0.59 | 0.01 / 0.14 | 0.00 / 0.08 | 0.00 / 0.04 | 0.00 / 0.02 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| completa2 | 0.33 / 0.88 | 0.08 / 0.62 | 0.04 / 0.46 | 0.01 / 0.30 | 0.00 / 0.17 | 0.00 / 0.09 | 0.00 / 0.01 | 0.00 / 0.00 |
| completa2@eps=0 | 0.33 / 0.88 | 0.08 / 0.62 | 0.04 / 0.46 | 0.01 / 0.30 | 0.00 / 0.17 | 0.00 / 0.09 | 0.00 / 0.01 | 0.00 / 0.00 |
| completa2@eps=delta | 0.19 / 0.74 | 0.03 / 0.31 | 0.01 / 0.18 | 0.00 / 0.11 | 0.00 / 0.05 | 0.00 / 0.02 | 0.00 / 0.00 | 0.00 / 0.00 |
| completa2@eps=sigma | 0.18 / 0.75 | 0.02 / 0.32 | 0.01 / 0.19 | 0.00 / 0.11 | 0.00 / 0.06 | 0.00 / 0.03 | 0.00 / 0.00 | 0.00 / 0.00 |
| completa2@d_replica=0.3 | 0.32 / 0.88 | 0.07 / 0.61 | 0.03 / 0.44 | 0.01 / 0.27 | 0.00 / 0.15 | 0.00 / 0.07 | 0.00 / 0.01 | 0.00 / 0.00 |
| completa2@d_replica=0.5 | 0.33 / 0.88 | 0.08 / 0.62 | 0.04 / 0.46 | 0.01 / 0.30 | 0.00 / 0.17 | 0.00 / 0.09 | 0.00 / 0.01 | 0.00 / 0.00 |
| completa2@d_replica=0.7 | 0.33 / 0.89 | 0.09 / 0.64 | 0.04 / 0.47 | 0.01 / 0.32 | 0.00 / 0.19 | 0.00 / 0.11 | 0.00 / 0.02 | 0.00 / 0.00 |
| completa2@d_replica=0.9 | 0.34 / 0.89 | 0.09 / 0.65 | 0.04 / 0.48 | 0.02 / 0.33 | 0.01 / 0.21 | 0.00 / 0.13 | 0.00 / 0.04 | 0.00 / 0.01 |
| completa2+prior_0_75 | 0.42 / 0.90 | 0.16 / 0.78 | 0.10 / 0.66 | 0.05 / 0.51 | 0.02 / 0.37 | 0.01 / 0.23 | 0.00 / 0.06 | 0.00 / 0.01 |
| completa2+prior_0_5 | 0.56 / 0.90 | 0.33 / 0.89 | 0.26 / 0.85 | 0.14 / 0.75 | 0.09 / 0.65 | 0.05 / 0.52 | 0.01 / 0.26 | 0.00 / 0.08 |
| completa2+prior_0_25 | 0.54 / 0.88 | 0.55 / 0.89 | 0.53 / 0.90 | 0.39 / 0.89 | 0.32 / 0.87 | 0.26 / 0.85 | 0.11 / 0.67 | 0.04 / 0.45 |

## Critério de aceite: falsa validação de no máximo 2% (ADR 025 §4.2)

Falsa validação = maior, entre os tipos `falsa` e `sem_efeito`, da fração de hipóteses validadas (média sobre a grade). Para cada variante, o menor limiar da curva que respeita o teto, com o poder nesse limiar; o pior ponto da grade mostra o regime mais difícil. As variantes estão ordenadas por poder.

| Variante | Menor limiar aceito | Falsa validação (média) | Falsa validação (pior ponto) | Poder | Falsa refutação | Custo por validação útil |
|---|---|---|---|---|---|---|
| por_tipo+sem_falhas | 0.25 | 0.009 | 0.125 | 0.473 | 0.011 | 285.598 |
| por_tipo | 0.25 | 0.009 | 0.125 | 0.466 | 0.011 | 275.429 |
| completa2+prior_0_75 | 0.35 | 0.018 | 0.125 | 0.368 | 0.011 | 252.292 |
| completa2@d_replica=0.9 | 0.3 | 0.016 | 0.125 | 0.329 | 0.009 | 360.821 |
| completa2@d_replica=0.7 | 0.3 | 0.013 | 0.100 | 0.317 | 0.010 | 366.297 |
| completa2@eps=sigma | 0.2 | 0.019 | 0.250 | 0.315 | 0.038 | 460.225 |
| completa2 | 0.3 | 0.011 | 0.075 | 0.299 | 0.010 | 375.153 |
| completa2@eps=0 | 0.3 | 0.011 | 0.075 | 0.299 | 0.010 | 375.153 |
| completa2@d_replica=0.5 | 0.3 | 0.011 | 0.075 | 0.299 | 0.010 | 375.153 |
| completa2@d_replica=0.3 | 0.3 | 0.010 | 0.075 | 0.273 | 0.010 | 385.210 |
| completa2+prior_0_5 | 0.5 | 0.009 | 0.075 | 0.258 | 0.005 | 480.304 |
| completa | 0.3 | 0.005 | 0.050 | 0.233 | 0.001 | 608.230 |
| folga | 0.2 | 0.012 | 0.125 | 0.229 | 0.008 | 394.746 |
| completa+prior_0_5 | 0.5 | 0.004 | 0.050 | 0.202 | 0.001 | 683.469 |
| completa2@eps=delta | 0.25 | 0.009 | 0.100 | 0.182 | 0.022 | 620.181 |
| prior_0_5 | 0.3 | 0.013 | 0.225 | 0.145 | 0.002 | 237.588 |
| por_tipo+melhora | 0.2 | 0.006 | 0.150 | 0.141 | 0.001 | 740.351 |
| base_alvo | 0.2 | 0.006 | 0.150 | 0.141 | 0.001 | 740.351 |
| prior_0_25 | 0.5 | 0.009 | 0.150 | 0.122 | 0.001 | 303.453 |
| b_variacao_sem_ganho | 0.2 | 0.003 | 0.075 | 0.096 | 0.000 | 473.246 |
| sem_falhas_em_nconfig | 0.2 | 0.003 | 0.075 | 0.094 | 0.000 | 504.249 |
| atual | 0.2 | 0.003 | 0.075 | 0.093 | 0.000 | 505.384 |
| exige_alvo | 0.2 | 0.003 | 0.075 | 0.093 | 0.000 | 505.384 |
| completa+prior_0_25 | nenhum | — | — | — | — | — |
| completa2+prior_0_25 | nenhum | — | — | — | — | — |

## Falsa validação (sem efeito) por ruído `sigma` e por variação sempre (`p_variacao = 1`), limiar 0.2

| Variante | sigma 0.005 | sigma 0.01 | sigma 0.02 |
|---|---|---|---|
| atual | 0.000 | 0.000 | 0.000 |
| sem_falhas_em_nconfig | 0.000 | 0.000 | 0.000 |
| por_tipo | 0.011 | 0.009 | 0.016 |
| folga | 0.000 | 0.000 | 0.000 |
| exige_alvo | 0.000 | 0.000 | 0.000 |
| b_variacao_sem_ganho | 0.000 | 0.000 | 0.000 |
| por_tipo+sem_falhas | 0.011 | 0.011 | 0.019 |
| por_tipo+melhora | 0.000 | 0.000 | 0.000 |
| completa | 0.016 | 0.025 | 0.086 |
| prior_0_5 | 0.000 | 0.000 | 0.000 |
| prior_0_25 | 0.433 | 0.472 | 0.434 |
| completa+prior_0_5 | 0.108 | 0.248 | 0.383 |
| completa+prior_0_25 | 0.300 | 0.452 | 0.484 |
| base_alvo | 0.000 | 0.000 | 0.000 |
| completa2 | 0.041 | 0.075 | 0.133 |
| completa2@eps=0 | 0.041 | 0.075 | 0.133 |
| completa2@eps=delta | 0.000 | 0.003 | 0.053 |
| completa2@eps=sigma | 0.006 | 0.003 | 0.014 |
| completa2@d_replica=0.3 | 0.041 | 0.075 | 0.133 |
| completa2@d_replica=0.5 | 0.041 | 0.075 | 0.133 |
| completa2@d_replica=0.7 | 0.041 | 0.075 | 0.133 |
| completa2@d_replica=0.9 | 0.041 | 0.075 | 0.133 |
| completa2+prior_0_75 | 0.105 | 0.178 | 0.263 |
| completa2+prior_0_5 | 0.284 | 0.384 | 0.445 |
| completa2+prior_0_25 | 0.588 | 0.583 | 0.537 |

## Tentativas até cruzar cada faixa (hipóteses verdadeiras; mediana das medianas por ponto)

| Variante | 0,1 | 0,3 | 0,5 |
|---|---|---|---|
| atual | 0.34 cruzam; mediana 15 | 0.01 cruzam; mediana 20 | 0.00 cruzam |
| sem_falhas_em_nconfig | 0.34 cruzam; mediana 14.5 | 0.01 cruzam; mediana 20 | 0.00 cruzam |
| por_tipo | 0.92 cruzam; mediana 5.25 | 0.34 cruzam; mediana 16 | 0.01 cruzam; mediana 19 |
| folga | 0.72 cruzam; mediana 1 | 0.09 cruzam; mediana 12.75 | 0.00 cruzam; mediana 20 |
| exige_alvo | 0.34 cruzam; mediana 15 | 0.01 cruzam; mediana 20 | 0.00 cruzam |
| b_variacao_sem_ganho | 0.36 cruzam; mediana 14 | 0.01 cruzam; mediana 20 | 0.00 cruzam |
| por_tipo+sem_falhas | 0.92 cruzam; mediana 5 | 0.34 cruzam; mediana 15.75 | 0.01 cruzam; mediana 19 |
| por_tipo+melhora | 0.60 cruzam; mediana 9 | 0.04 cruzam; mediana 16.5 | 0.00 cruzam |
| completa | 0.95 cruzam; mediana 2 | 0.23 cruzam; mediana 9 | 0.02 cruzam; mediana 17 |
| prior_0_5 | 0.97 cruzam; mediana 1 | 0.15 cruzam; mediana 10.5 | 0.01 cruzam; mediana 20 |
| prior_0_25 | 1.00 cruzam; mediana 1 | 0.55 cruzam; mediana 8 | 0.12 cruzam; mediana 9.5 |
| completa+prior_0_5 | 1.00 cruzam; mediana 1 | 0.74 cruzam; mediana 4.5 | 0.20 cruzam; mediana 8.5 |
| completa+prior_0_25 | 1.00 cruzam; mediana 1 | 0.97 cruzam; mediana 1 | 0.65 cruzam; mediana 4 |
| base_alvo | 0.60 cruzam; mediana 9 | 0.04 cruzam; mediana 16.5 | 0.00 cruzam |
| completa2 | 0.96 cruzam; mediana 2 | 0.31 cruzam; mediana 10 | 0.01 cruzam; mediana 16.5 |
| completa2@eps=0 | 0.96 cruzam; mediana 2 | 0.31 cruzam; mediana 10 | 0.01 cruzam; mediana 16.5 |
| completa2@eps=delta | 0.83 cruzam; mediana 2 | 0.12 cruzam; mediana 12 | 0.00 cruzam; mediana 8 |
| completa2@eps=sigma | 0.84 cruzam; mediana 2 | 0.13 cruzam; mediana 12.5 | 0.00 cruzam; mediana 16.75 |
| completa2@d_replica=0.3 | 0.96 cruzam; mediana 2 | 0.28 cruzam; mediana 10 | 0.01 cruzam; mediana 15 |
| completa2@d_replica=0.5 | 0.96 cruzam; mediana 2 | 0.31 cruzam; mediana 10 | 0.01 cruzam; mediana 16.5 |
| completa2@d_replica=0.7 | 0.97 cruzam; mediana 2 | 0.33 cruzam; mediana 9.75 | 0.02 cruzam; mediana 15.5 |
| completa2@d_replica=0.9 | 0.97 cruzam; mediana 2 | 0.34 cruzam; mediana 9.5 | 0.04 cruzam; mediana 15.5 |
| completa2+prior_0_75 | 0.99 cruzam; mediana 1 | 0.53 cruzam; mediana 6.5 | 0.06 cruzam; mediana 13 |
| completa2+prior_0_5 | 1.00 cruzam; mediana 1 | 0.78 cruzam; mediana 4 | 0.26 cruzam; mediana 8 |
| completa2+prior_0_25 | 1.00 cruzam; mediana 1 | 0.98 cruzam; mediana 1 | 0.70 cruzam; mediana 4 |
