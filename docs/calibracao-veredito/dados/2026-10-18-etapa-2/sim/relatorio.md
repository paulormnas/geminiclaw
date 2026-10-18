# Simulação do veredito com resposta conhecida

Gerado por `scripts.verdict_lab` em 2026-10-18T22:23:11Z, commit `fa5573b7f8d6`, comando `simulacao`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

96 pontos de grade, 40 repetições por tipo de hipótese e ponto, até 20 tentativas. A decisão é tomada na primeira vez em que |veredito| alcança o limiar. As taxas são médias sobre os pontos da grade (detalhe por ponto em `resultados.csv`).

- **Falsa validação:** hipóteses `falsa` ou `sem_efeito` validadas (registradas sem contribuir).
- **Poder:** hipóteses `verdadeira` validadas.
- **Custo por validação útil:** tentativas gastas em todas as hipóteses por `verdadeira` validada.

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
| completa@eps=0 | 0.005 | 0.000 | 0.233 | 0.001 | 0.767 | 0.679 | 608.230 |
| completa@eps=delta | 0.002 | 0.000 | 0.105 | 0.000 | 0.895 | 0.656 | 821.771 |
| completa@eps=sigma | 0.002 | 0.000 | 0.111 | 0.000 | 0.889 | 0.664 | 727.977 |
| completa@d_replica=0.3 | 0.005 | 0.000 | 0.214 | 0.001 | 0.785 | 0.664 | 627.930 |
| completa@d_replica=0.5 | 0.005 | 0.000 | 0.233 | 0.001 | 0.767 | 0.679 | 608.230 |
| completa@d_replica=0.7 | 0.007 | 0.000 | 0.249 | 0.001 | 0.749 | 0.690 | 593.352 |
| completa@d_replica=0.9 | 0.010 | 0.000 | 0.260 | 0.001 | 0.739 | 0.698 | 587.078 |
| prior_0_5 | 0.013 | 0.000 | 0.145 | 0.002 | 0.854 | 0.721 | 237.588 |
| prior_0_25 | 0.068 | 0.006 | 0.515 | 0.034 | 0.451 | 0.906 | 236.103 |
| completa+prior_0_5 | 0.095 | 0.009 | 0.732 | 0.013 | 0.255 | 0.888 | 55.470 |
| completa+prior_0_25 | 0.302 | 0.059 | 0.881 | 0.085 | 0.034 | 0.917 | 15.657 |

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
| completa@eps=0 | 0.050 | 0.004 | 0.578 | 0.008 | 0.415 | 0.858 | 109.918 |
| completa@eps=delta | 0.022 | 0.001 | 0.351 | 0.004 | 0.645 | 0.870 | 414.684 |
| completa@eps=sigma | 0.015 | 0.000 | 0.347 | 0.004 | 0.649 | 0.875 | 546.982 |
| completa@d_replica=0.3 | 0.045 | 0.004 | 0.568 | 0.007 | 0.425 | 0.853 | 112.264 |
| completa@d_replica=0.5 | 0.050 | 0.004 | 0.578 | 0.008 | 0.415 | 0.858 | 109.918 |
| completa@d_replica=0.7 | 0.057 | 0.005 | 0.585 | 0.008 | 0.407 | 0.863 | 107.930 |
| completa@d_replica=0.9 | 0.061 | 0.005 | 0.588 | 0.009 | 0.403 | 0.866 | 106.880 |
| prior_0_5 | 0.052 | 0.004 | 0.373 | 0.020 | 0.607 | 0.897 | 305.772 |
| prior_0_25 | 0.450 | 0.130 | 0.830 | 0.137 | 0.033 | 0.862 | 8.615 |
| completa+prior_0_5 | 0.250 | 0.045 | 0.875 | 0.068 | 0.057 | 0.926 | 20.603 |
| completa+prior_0_25 | 0.400 | 0.085 | 0.893 | 0.103 | 0.004 | 0.911 | 9.399 |

## Curva de compromisso: falsa validação (sem efeito) / poder, por limiar

| Variante | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 |
|---|---|---|---|---|---|---|
| atual | 0.05 / 0.32 | 0.00 / 0.09 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| sem_falhas_em_nconfig | 0.05 / 0.32 | 0.00 / 0.09 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| por_tipo | 0.17 / 0.83 | 0.02 / 0.59 | 0.00 / 0.33 | 0.00 / 0.13 | 0.00 / 0.01 | 0.00 / 0.00 |
| folga | 0.10 / 0.64 | 0.01 / 0.23 | 0.00 / 0.08 | 0.00 / 0.03 | 0.00 / 0.00 | 0.00 / 0.00 |
| exige_alvo | 0.05 / 0.32 | 0.00 / 0.09 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| b_variacao_sem_ganho | 0.05 / 0.34 | 0.00 / 0.10 | 0.00 / 0.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| por_tipo+sem_falhas | 0.18 / 0.83 | 0.02 / 0.60 | 0.00 / 0.34 | 0.00 / 0.13 | 0.00 / 0.01 | 0.00 / 0.00 |
| por_tipo+melhora | 0.09 / 0.59 | 0.01 / 0.14 | 0.00 / 0.04 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| completa | 0.25 / 0.88 | 0.05 / 0.58 | 0.01 / 0.23 | 0.00 / 0.07 | 0.00 / 0.02 | 0.00 / 0.00 |
| completa@eps=0 | 0.25 / 0.88 | 0.05 / 0.58 | 0.01 / 0.23 | 0.00 / 0.07 | 0.00 / 0.02 | 0.00 / 0.00 |
| completa@eps=delta | 0.17 / 0.78 | 0.02 / 0.35 | 0.00 / 0.11 | 0.00 / 0.04 | 0.00 / 0.00 | 0.00 / 0.00 |
| completa@eps=sigma | 0.15 / 0.77 | 0.01 / 0.35 | 0.00 / 0.11 | 0.00 / 0.04 | 0.00 / 0.01 | 0.00 / 0.00 |
| completa@d_replica=0.3 | 0.25 / 0.88 | 0.04 / 0.57 | 0.00 / 0.21 | 0.00 / 0.05 | 0.00 / 0.01 | 0.00 / 0.00 |
| completa@d_replica=0.5 | 0.25 / 0.88 | 0.05 / 0.58 | 0.01 / 0.23 | 0.00 / 0.07 | 0.00 / 0.02 | 0.00 / 0.00 |
| completa@d_replica=0.7 | 0.25 / 0.88 | 0.06 / 0.58 | 0.01 / 0.25 | 0.00 / 0.09 | 0.00 / 0.03 | 0.00 / 0.00 |
| completa@d_replica=0.9 | 0.25 / 0.88 | 0.06 / 0.59 | 0.01 / 0.26 | 0.00 / 0.10 | 0.00 / 0.04 | 0.00 / 0.01 |
| prior_0_5 | 0.44 / 0.83 | 0.05 / 0.37 | 0.01 / 0.14 | 0.00 / 0.07 | 0.00 / 0.01 | 0.00 / 0.00 |
| prior_0_25 | 0.50 / 0.85 | 0.45 / 0.83 | 0.07 / 0.51 | 0.04 / 0.30 | 0.01 / 0.12 | 0.00 / 0.05 |
| completa+prior_0_5 | 0.40 / 0.90 | 0.25 / 0.87 | 0.09 / 0.73 | 0.03 / 0.46 | 0.00 / 0.20 | 0.00 / 0.06 |
| completa+prior_0_25 | 0.46 / 0.88 | 0.40 / 0.89 | 0.30 / 0.88 | 0.20 / 0.83 | 0.08 / 0.64 | 0.02 / 0.40 |

## Falsa validação (sem efeito) por ruído `sigma` e por variação sempre (`p_variacao = 1`), limiar 0.3

| Variante | sigma 0.005 | sigma 0.01 | sigma 0.02 |
|---|---|---|---|
| atual | 0.000 | 0.000 | 0.000 |
| sem_falhas_em_nconfig | 0.000 | 0.000 | 0.000 |
| por_tipo | 0.000 | 0.000 | 0.000 |
| folga | 0.000 | 0.000 | 0.000 |
| exige_alvo | 0.000 | 0.000 | 0.000 |
| b_variacao_sem_ganho | 0.000 | 0.000 | 0.000 |
| por_tipo+sem_falhas | 0.000 | 0.000 | 0.000 |
| por_tipo+melhora | 0.000 | 0.000 | 0.000 |
| completa | 0.000 | 0.000 | 0.009 |
| completa@eps=0 | 0.000 | 0.000 | 0.009 |
| completa@eps=delta | 0.000 | 0.000 | 0.000 |
| completa@eps=sigma | 0.000 | 0.000 | 0.000 |
| completa@d_replica=0.3 | 0.000 | 0.000 | 0.009 |
| completa@d_replica=0.5 | 0.000 | 0.000 | 0.009 |
| completa@d_replica=0.7 | 0.000 | 0.000 | 0.009 |
| completa@d_replica=0.9 | 0.000 | 0.000 | 0.009 |
| prior_0_5 | 0.000 | 0.000 | 0.000 |
| prior_0_25 | 0.003 | 0.000 | 0.003 |
| completa+prior_0_5 | 0.027 | 0.089 | 0.150 |
| completa+prior_0_25 | 0.156 | 0.334 | 0.420 |

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
| completa@eps=0 | 0.95 cruzam; mediana 2 | 0.23 cruzam; mediana 9 | 0.02 cruzam; mediana 17 |
| completa@eps=delta | 0.84 cruzam; mediana 2 | 0.11 cruzam; mediana 12 | 0.00 cruzam; mediana 18 |
| completa@eps=sigma | 0.84 cruzam; mediana 2 | 0.11 cruzam; mediana 12 | 0.01 cruzam; mediana 16.5 |
| completa@d_replica=0.3 | 0.94 cruzam; mediana 2 | 0.21 cruzam; mediana 9 | 0.01 cruzam; mediana 17 |
| completa@d_replica=0.5 | 0.95 cruzam; mediana 2 | 0.23 cruzam; mediana 9 | 0.02 cruzam; mediana 17 |
| completa@d_replica=0.7 | 0.95 cruzam; mediana 2 | 0.25 cruzam; mediana 8 | 0.03 cruzam; mediana 16 |
| completa@d_replica=0.9 | 0.95 cruzam; mediana 2 | 0.26 cruzam; mediana 8 | 0.04 cruzam; mediana 16 |
| prior_0_5 | 0.97 cruzam; mediana 1 | 0.15 cruzam; mediana 10.5 | 0.01 cruzam; mediana 20 |
| prior_0_25 | 1.00 cruzam; mediana 1 | 0.55 cruzam; mediana 8 | 0.12 cruzam; mediana 9.5 |
| completa+prior_0_5 | 1.00 cruzam; mediana 1 | 0.74 cruzam; mediana 4.5 | 0.20 cruzam; mediana 8.5 |
| completa+prior_0_25 | 1.00 cruzam; mediana 1 | 0.97 cruzam; mediana 1 | 0.65 cruzam; mediana 4 |
