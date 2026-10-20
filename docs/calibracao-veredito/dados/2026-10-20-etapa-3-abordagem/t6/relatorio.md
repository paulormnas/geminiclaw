# Falha de abordagem reproduzida: avaliação offline do peso `q`

Gerado por `scripts.verdict_lab` em 2026-10-20T02:06:36Z, commit `99660fe06feb`, comando `abordagem`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

Limiar de conclusão 0.3. Simulação: 1000 hipóteses por tipo e ponto, até 6 tentativas, conclusão pela primeira travessia do limiar. As sequências são as mesmas em todas as variantes.

## Cenários do catálogo

| Cenário | Esperado | completa2 (veredito; conclusão) | completa2+q_abordagem_0_5 (veredito; conclusão) | completa2+q_abordagem_0_7 (veredito; conclusão) | completa2+q_abordagem_1_0 (veredito; conclusão) |
|---|---|---|---|---|---|
| N-abordagem-2 | indeciso | -0.053; indeciso | -0.111; indeciso | -0.170; indeciso | -0.250; indeciso |
| N-abordagem-3 | indeciso | -0.096; indeciso | -0.184; indeciso | -0.262; indeciso | -0.360; nao_funciona |
| N-abordagem-4 | nao_funciona | -0.141; indeciso | -0.250; indeciso | -0.340; nao_funciona | -0.444; nao_funciona |
| N-abordagem-ruido | funciona | +0.355; funciona | +0.281; indeciso | +0.214; indeciso | +0.125; indeciso |

## Simulação

### Ponto 0: Developer incapaz em 0% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 0.000 | — | 0.002 | 0.251 | 0.000 | 0.003 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.002 | 0.251 | 0.000 | 0.003 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.002 | 0.251 | 0.000 | 0.003 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.002 | 0.251 | 0.000 | 0.003 |

### Ponto 1: Developer incapaz em 10% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 0.000 | — | 0.000 | 0.160 | 0.000 | 0.001 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.000 | 0.160 | 0.000 | 0.001 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.001 | 0.160 | 0.000 | 0.001 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.004 | 0.160 | 0.000 | 0.001 |

### Ponto 2: Developer incapaz em 20% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 0.000 | — | 0.000 | 0.114 | 0.000 | 0.000 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.001 | 0.114 | 0.000 | 0.000 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.010 | 0.114 | 0.000 | 0.000 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.036 | 0.114 | 0.000 | 0.000 |

### Ponto 3: Developer incapaz em 30% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 0.000 | — | 0.000 | 0.073 | 0.000 | 0.000 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.004 | 0.072 | 0.000 | 0.000 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.021 | 0.072 | 0.000 | 0.000 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.092 | 0.072 | 0.000 | 0.000 |

### Ponto 4: Developer incapaz em 50% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 0.000 | — | 0.001 | 0.021 | 0.000 | 0.000 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.035 | 0.020 | 0.000 | 0.000 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.146 | 0.020 | 0.000 | 0.000 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.346 | 0.020 | 0.000 | 0.000 |

## Leitura

- Subir `q` aumenta a conclusão correta da abordagem plantada, mas também a falsa refutação das hipóteses verdadeiras quando o Developer falha por incapacidade; a coluna de falsa validação não deve mudar.
- O valor só muda em `src/config.py` com aprovação do pesquisador, em PR próprio com revisão do ADR 015 §9.9.
