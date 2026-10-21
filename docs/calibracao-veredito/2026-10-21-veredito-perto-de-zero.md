# Veredito perto de zero nas sessões controladas (2026-10-21)

**Pergunta.** Por que nenhuma hipótese das sessões controladas da etapa 3 (ADR 025) passou de |0,07|, mesmo depois das correções #238 e #240?

**Método.** Sem LLM. (1) Decomposição do veredito por tentativa (`q`, `m`, `d`, `b`, `w`) nas 20 hipóteses testadas dos grafos arquivados (`~/bench/piloto_v18_8_parcial`, `~/bench/piloto_v18_8_sem_credito`, `~/bench/verificacao_v18_8`, `~/bench/verificacao_v18_8b`). (2) Recálculo dessas hipóteses com variantes do tratamento das tentativas e da equação. (3) Grade sintética do laboratório (`scripts.verdict_lab.simulation`, grade padrão, 40 repetições, até 20 tentativas, semente 20261021) com uma variante nova: prior menor **só quando a evidência líquida é negativa**. Scripts e saídas em [`dados/2026-10-21-veredito-perto-de-zero/`](dados/2026-10-21-veredito-perto-de-zero/). Commit `f1f1b1a`.

## Resultados

### Três causas

1. **Evidência medida descartada antes do cálculo.** Um experimento que mediu a métrica abaixo do alvo, mas foi reprovado também por outro critério, fica `falha`/`criterio_nao_atendido` e entra como `ambigua` (peso 0). O `Resultado` existe no grafo e é ignorado. Recuperar esses valores (V1) leva 10 das 20 hipóteses de ≈0 para −0,08 a −0,37.
2. **`divergente_documentado` com `q` = 0,3.** Quando o Developer grava `divergence_note` ("abaixo do alvo, h1 não confirmada"), a revisão aprova antes de olhar o limiar e o resultado pesa 30 %. Tratado como validado (V2), −0,017 vira −0,111.
3. **Teto estrutural da equação** (`f · certeza · (2·suporte − 1)`, prior 1). Com k evidências concordantes de peso cheio e nada contra:

| k | atual | prior 0,5 | prior 0,25 | (α−β)/(α+β) |
|---|---|---|---|---|
| 1 | 0,111 | 0,250 | 0,444 | 0,333 |
| 2 | 0,250 | 0,444 | 0,640 | 0,500 |
| 3 | 0,360 | 0,562 | 0,735 | 0,600 |

O Developer testa cada hipótese 1 a 3 vezes; a maioria tem uma evidência só. O teto de 0,111 da etapa 1 é este.

### Variantes sobre as 20 hipóteses reais

| Variante | Refutadas (≤ −0,3) | Validadas (≥ 0,3) |
|---|---|---|
| V0 atual | 0 | 0 |
| V1 falha com valor vira resultado | 1 | 0 |
| V2 = V1 + divergente vale validado | 1 | 0 |
| V3 = V2 + prior 0,5 | 8 | 0 |
| V4 = V2 + prior 0,25 | 13 | 0 |
| V5 = V2 + forma (α−β)/(α+β) | 11 | 0 |

Nenhuma variante valida: as hipóteses com resultado acima do alvo em P têm um resultado só. As refutações de T são corretas (teto 0,90 < alvo 0,93).

### Grade sintética: prior menor só na refutação

Média sobre a grade, limiar 0,3; V = hipótese verdadeira, F = falsa, 0 = sem efeito.

| Variante | Orçamento | Valida V | Refuta V | Refuta F | Valida 0 | Refuta 0 |
|---|---|---|---|---|---|---|
| `completa2` (sistema) | 3 | 1,7 % | 0,1 % | 12,1 % | 0,0 % | 1,1 % |
| | 10 | 14,7 % | 0,2 % | 68,6 % | 0,5 % | 4,3 % |
| `+ref_prior_0_5` | 3 | 1,7 % | 0,5 % | **65,2 %** | 0,0 % | 5,6 % |
| | 10 | 14,7 % | 0,8 % | 91,1 % | 0,5 % | 9,9 % |
| `+ref_prior_0_25` | 3 | 1,7 % | 1,8 % | 88,9 % | 0,0 % | 15,0 % |
| | 10 | 14,7 % | 2,0 % | 95,4 % | 0,5 % | 18,4 % |
| `+prior_0_5` (simétrico) | 3 | 23,3 % | 0,5 % | 65,2 % | 3,4 % | 5,6 % |
| | 10 | 50,8 % | 0,8 % | 91,1 % | **11,2 %** | 9,9 % |

## Leitura

- As causas 1 e 2 são defeitos do pipeline, não calibração: descartam ou rebaixam evidência medida. Corrigidas sozinhas, mudam pouco o número de decisões (o teto continua), mas tornam o veredito fiel aos dados.
- O prior simétrico menor compra poder de validação com falsa validação (11 % das hipóteses sem efeito com 10 tentativas), como a etapa 2 já mostrou.
- **O prior 0,5 só na refutação** deixa a validação idêntica por construção (mesma falsa validação, mesmo poder) e leva a refutação de hipóteses falsas em 3 tentativas de 12 % para 65 %, com falsa refutação de verdadeiras de 0,5 % (0,8 % com 10). Com prior 0,25 a falsa refutação passa de 1,8 %.
- Na prática: uma refutação continua exigindo duas evidências contrárias de peso cheio (uma sozinha dá −0,25), e a validação continua exigindo três.

## Limitações

- A variante assimétrica foi aplicada sobre o resultado (`α`, `β`, `f`) de `completa2`, em script fora do laboratório; para adotar, entra como variante própria em `variants.py` com teste de equivalência.
- A refutação de hipóteses "sem efeito" (exatamente no alvo) sobe de 4 % para 10 % com 10 tentativas; se isso conta como erro depende da leitura do critério (o alvo exige superar).
- A verdade por hipótese não foi rotulada nas sessões reais de P; só a de T (todas falsas) é certa.
- A exploração T da verificação 2 foi censurada por falta de crédito na Anthropic.

## Próximos passos propostos (decisão do pesquisador)

1. Spec das correções 1 e 2 (evidência de `falha` com valor e `divergence_note` com limiar não atendido).
2. Se aprovado, prior de refutação 0,5 como parâmetro novo (`VERDICT_PRIOR_REFUTATION`), com revisão do ADR 015 §9 e variante no laboratório.
3. Nova verificação curta depois do crédito recarregado.
