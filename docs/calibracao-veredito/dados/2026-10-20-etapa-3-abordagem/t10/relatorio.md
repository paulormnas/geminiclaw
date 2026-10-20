# Falha de abordagem reproduzida: avaliação offline do peso `q`

Gerado por `scripts.verdict_lab` em 2026-10-20T02:07:14Z, commit `99660fe06feb`, comando `abordagem`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.

Limiar de conclusão 0.3. Simulação: 1000 hipóteses por tipo e ponto, até 10 tentativas, conclusão pela primeira travessia do limiar. As sequências são as mesmas em todas as variantes.

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
| completa2 | 0.300 | 1.000 | 9.000 | 0.002 | 0.493 | 0.000 | 0.009 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.002 | 0.493 | 0.000 | 0.009 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.002 | 0.493 | 0.000 | 0.009 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.002 | 0.493 | 0.000 | 0.009 |

### Ponto 1: Developer incapaz em 10% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 1.000 | 9.000 | 0.000 | 0.363 | 0.000 | 0.005 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.000 | 0.354 | 0.000 | 0.005 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.002 | 0.353 | 0.000 | 0.005 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.009 | 0.353 | 0.000 | 0.005 |

### Ponto 2: Developer incapaz em 20% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 1.000 | 9.000 | 0.000 | 0.232 | 0.000 | 0.002 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.002 | 0.219 | 0.000 | 0.002 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.012 | 0.218 | 0.000 | 0.002 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.061 | 0.218 | 0.000 | 0.002 |

### Ponto 3: Developer incapaz em 30% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 1.000 | 9.000 | 0.000 | 0.142 | 0.000 | 0.000 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.012 | 0.128 | 0.000 | 0.000 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.046 | 0.125 | 0.000 | 0.000 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.168 | 0.125 | 0.000 | 0.000 |

### Ponto 4: Developer incapaz em 50% das tentativas (sigma 0.01, tau 0.01, efeito 0.02, p_variacao 0.5)

| Variante | q | Abordagem plantada refutada | Tentativas até refutar (mediana) | Falsa refutação (verdadeira refutada) | Poder (verdadeira validada) | Falsa validação (falsa) | Falsa validação (sem efeito) |
|---|---|---|---|---|---|---|---|
| completa2 | 0.300 | 1.000 | 9.000 | 0.010 | 0.030 | 0.000 | 0.000 |
| completa2+q_abordagem_0_5 | 0.500 | 1.000 | 5.000 | 0.106 | 0.025 | 0.000 | 0.000 |
| completa2+q_abordagem_0_7 | 0.700 | 1.000 | 4.000 | 0.295 | 0.025 | 0.000 | 0.000 |
| completa2+q_abordagem_1_0 | 1.000 | 1.000 | 3.000 | 0.602 | 0.025 | 0.000 | 0.000 |

## Leitura

- Subir `q` aumenta a conclusão correta da abordagem plantada, mas também a falsa refutação das hipóteses verdadeiras quando o Developer falha por incapacidade; a coluna de falsa validação não deve mudar.
- O valor só muda em `src/config.py` com aprovação do pesquisador, em PR próprio com revisão do ADR 015 §9.9.
