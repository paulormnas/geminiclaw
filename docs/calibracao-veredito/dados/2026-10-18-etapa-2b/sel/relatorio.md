# Seleção de variante pelos dois instrumentos

Gerado por `scripts.verdict_lab` em 2026-10-18T23:54:47Z, commit `5323325558f8`, comando `selecao`. Sem chamada de LLM.

Uma variante e um limiar são **aceitos** quando (1) a falsa validação média na simulação não passa de 2% e (2) a variante não conclui `funciona` em nenhum cenário do catálogo cujo esperado não é `funciona` (por exemplo, volume sem evolução ou recordes por acaso). A simulação não mede o segundo caso, e a grade não mede o primeiro (ADR 025 §4.2).

## Aceitos, ordenados por poder

| Variante | Limiar | Falsa validação (sim) | Pior ponto | Poder (sim) | Falsa refutação | Acertos da grade |
|---|---|---|---|---|---|---|
| completa2+prior_0_75 | 0.35 | 0.018 | 0.125 | 0.368 | 0.011 | 36/43 |
| completa2 | 0.3 | 0.011 | 0.075 | 0.299 | 0.010 | 36/43 |
| completa2+prior_0_75 | 0.4 | 0.006 | 0.050 | 0.233 | 0.006 | 32/43 |
| completa | 0.3 | 0.005 | 0.050 | 0.233 | 0.001 | 33/43 |
| folga | 0.2 | 0.012 | 0.125 | 0.229 | 0.008 | 24/43 |
| completa2 | 0.35 | 0.003 | 0.050 | 0.171 | 0.005 | 32/43 |
| base_alvo | 0.2 | 0.006 | 0.150 | 0.141 | 0.001 | 28/43 |
| completa | 0.35 | 0.002 | 0.025 | 0.135 | 0.000 | 31/43 |
| folga | 0.25 | 0.004 | 0.075 | 0.130 | 0.002 | 23/43 |
| prior_0_5 | 0.35 | 0.004 | 0.100 | 0.103 | 0.000 | 24/43 |
| b_variacao_sem_ganho | 0.2 | 0.003 | 0.075 | 0.096 | 0.000 | 23/43 |
| sem_falhas_em_nconfig | 0.2 | 0.003 | 0.075 | 0.094 | 0.000 | 23/43 |
| atual | 0.2 | 0.003 | 0.075 | 0.093 | 0.000 | 23/43 |
| exige_alvo | 0.2 | 0.003 | 0.075 | 0.093 | 0.000 | 23/43 |
| completa2 | 0.4 | 0.001 | 0.025 | 0.088 | 0.002 | 26/43 |
| folga | 0.3 | 0.001 | 0.025 | 0.085 | 0.001 | 23/43 |
| base_alvo | 0.25 | 0.002 | 0.050 | 0.079 | 0.000 | 24/43 |
| por_tipo+melhora | 0.25 | 0.002 | 0.050 | 0.079 | 0.000 | 23/43 |
| completa | 0.4 | 0.000 | 0.025 | 0.070 | 0.000 | 24/43 |
| prior_0_5 | 0.4 | 0.001 | 0.050 | 0.065 | 0.000 | 23/43 |
| folga | 0.35 | 0.000 | 0.025 | 0.055 | 0.000 | 22/43 |
| b_variacao_sem_ganho | 0.25 | 0.001 | 0.025 | 0.045 | 0.000 | 23/43 |
| sem_falhas_em_nconfig | 0.25 | 0.001 | 0.025 | 0.043 | 0.000 | 23/43 |
| atual | 0.25 | 0.001 | 0.025 | 0.043 | 0.000 | 23/43 |
| exige_alvo | 0.25 | 0.001 | 0.025 | 0.043 | 0.000 | 23/43 |
| base_alvo | 0.3 | 0.001 | 0.025 | 0.043 | 0.000 | 23/43 |
| por_tipo+melhora | 0.3 | 0.001 | 0.025 | 0.043 | 0.000 | 22/43 |
| folga | 0.4 | 0.000 | 0.000 | 0.028 | 0.000 | 22/43 |
| base_alvo | 0.35 | 0.000 | 0.025 | 0.016 | 0.000 | 23/43 |
| por_tipo+melhora | 0.35 | 0.000 | 0.025 | 0.016 | 0.000 | 22/43 |
| b_variacao_sem_ganho | 0.3 | 0.000 | 0.000 | 0.010 | 0.000 | 23/43 |
| atual | 0.3 | 0.000 | 0.000 | 0.010 | 0.000 | 23/43 |
| exige_alvo | 0.3 | 0.000 | 0.000 | 0.010 | 0.000 | 23/43 |
| sem_falhas_em_nconfig | 0.3 | 0.000 | 0.000 | 0.010 | 0.000 | 23/43 |
| base_alvo | 0.4 | 0.000 | 0.025 | 0.003 | 0.000 | 22/43 |
| por_tipo+melhora | 0.4 | 0.000 | 0.025 | 0.003 | 0.000 | 22/43 |
| atual | 0.35 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |
| atual | 0.4 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |
| b_variacao_sem_ganho | 0.35 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |
| b_variacao_sem_ganho | 0.4 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |
| exige_alvo | 0.35 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |
| exige_alvo | 0.4 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |
| sem_falhas_em_nconfig | 0.35 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |
| sem_falhas_em_nconfig | 0.4 | 0.000 | 0.000 | 0.000 | 0.000 | 22/43 |

## Rejeitados pelo catálogo (dentro do teto na simulação)

| Variante | Limiar | Poder (sim) | Cenários falsamente validados |
|---|---|---|---|
| por_tipo+sem_falhas | 0.25 | 0.473 | V20 |
| por_tipo | 0.25 | 0.466 | V20 |
| por_tipo+sem_falhas | 0.3 | 0.339 | V20 |
| por_tipo | 0.3 | 0.333 | V20 |
| por_tipo+sem_falhas | 0.35 | 0.227 | V20 |
| por_tipo | 0.35 | 0.221 | V20 |
| prior_0_5 | 0.3 | 0.145 | S10 |
| por_tipo+melhora | 0.2 | 0.141 | C3-abaixo-do-alvo |
| por_tipo+sem_falhas | 0.4 | 0.129 | V20 |
| por_tipo | 0.4 | 0.129 | V20 |
