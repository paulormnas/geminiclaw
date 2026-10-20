# Falha de abordagem reproduzida: avaliação offline do peso `q`

**Data:** 2026-10-20 · **ADR:** [025](../decisions/adr_025_calibracao_do_veredito.md) · **Mudança:** [`v18.8-verdict-controlled-sessions`](../../openspec/changes/v18.8-verdict-controlled-sessions/proposal.md) (seção 4, design §7) · **Custo:** nenhuma chamada de LLM · **Decisão pendente:** valor de `VERDICT_APPROACH_FAILURE_Q` (pesquisador)

## 1. Pergunta

Quando a mesma falha de abordagem se reproduz em configurações diferentes (por exemplo, `MemoryError` em quatro variações), o modelo v2 com `q` = 0,3 dá veredito −0,141 e a hipótese de abordagem fica **indecisa**. Subir `q` faz o sistema concluir `nao_funciona` com menos tentativas, mas aumenta o risco de uma **falsa refutação**: um Developer fraco falha por incapacidade, e não porque a abordagem não funciona. Qual valor de `q` (0,3 atual, 0,5, 0,7 ou 1,0) equilibra os dois efeitos, antes de qualquer sessão com LLM?

## 2. Entradas

- Modelo v2 (`completa2` do laboratório), com `approach_failure_q` em 0,3 (`completa2`), 0,5, 0,7 e 1,0 (`completa2+q_abordagem_*` em `scripts/verdict_lab/variantes.json`). Os demais parâmetros não mudam.
- Catálogo do laboratório com dois cenários novos: **N-abordagem-3** (a mesma falha em três configurações) e **N-abordagem-ruido** (três falhas de abordagem reproduzidas e, depois, seis variações crescentes: o Developer falhou por incapacidade e depois acertou).
- Simulação com resposta conhecida (`scripts/verdict_lab/simulation.py`): 1000 hipóteses de cada tipo por ponto, semente 20261019, `sigma` 0,01, `tau` 0,01, efeito 0,02, probabilidade de variar 0,5. Os tipos são `verdadeira`, `falsa`, `sem_efeito` e o novo `abordagem_falha` (toda tentativa falha com a mesma assinatura). O parâmetro novo `p_falha_abordagem` é a fração das tentativas de uma hipótese em que o Developer falha com a mesma assinatura (0, 10, 20, 30 e 50 %). A hipótese é decidida na primeira vez em que `|veredito|` alcança 0,3. As sequências são idênticas em todas as variantes; a diferença entre as colunas vem só de `q`.
- Duas durações: até 10 e até 6 tentativas por hipótese.

## 3. Resultados

### 3.1 Cenários do catálogo (veredito; conclusão no limiar 0,3)

| Cenário | Esperado | `q` = 0,3 | `q` = 0,5 | `q` = 0,7 | `q` = 1,0 |
|---|---|---|---|---|---|
| N-abordagem-2 (2 falhas, 2 configurações) | indeciso | −0,053; indeciso | −0,111; indeciso | −0,170; indeciso | −0,250; indeciso |
| N-abordagem-3 | indeciso (aceita `nao_funciona`) | −0,096; indeciso | −0,184; indeciso | −0,262; indeciso | −0,360; nao_funciona |
| N-abordagem-4 | nao_funciona | −0,141; **indeciso** | −0,250; **indeciso** | −0,340; nao_funciona | −0,444; nao_funciona |
| N-abordagem-ruido | funciona (aceita indeciso) | +0,355; funciona | +0,281; indeciso | +0,214; indeciso | +0,125; indeciso |

Nenhum valor de `q` faz a hipótese que depois funcionou (N-abordagem-ruido) ser refutada: o custo de subir `q` aí é perder a conclusão `funciona` (de +0,355 para +0,281 já com `q` = 0,5), não uma refutação.

### 3.2 Abordagem plantada: quantas tentativas até refutar (mediana)

| Duração | `q` = 0,3 | `q` = 0,5 | `q` = 0,7 | `q` = 1,0 |
|---|---|---|---|---|
| até 10 tentativas | 9 | 5 | 4 | 3 |
| até 6 tentativas | **não refuta** | 5 | 4 | 3 |

Todas as hipóteses de abordagem plantada são refutadas em todas as variantes dentro de 10 tentativas, e a mediana não depende da incapacidade do Developer. Com `q` = 0,3 são necessárias 9 tentativas; numa exploração em que o Developer testa poucas variações (até 6), a abordagem plantada nunca é refutada.

### 3.3 Falsa refutação: hipóteses `verdadeira` concluídas como `nao_funciona`

Até 10 tentativas por hipótese:

| Developer incapaz | `q` = 0,3 | `q` = 0,5 | `q` = 0,7 | `q` = 1,0 |
|---|---|---|---|---|
| 0 % | 0,2 % | 0,2 % | 0,2 % | 0,2 % |
| 10 % | 0,0 % | 0,0 % | 0,2 % | 0,9 % |
| 20 % | 0,0 % | 0,2 % | 1,2 % | 6,1 % |
| 30 % | 0,0 % | 1,2 % | 4,6 % | 16,8 % |
| 50 % | 1,0 % | 10,6 % | 29,5 % | 60,2 % |

Até 6 tentativas por hipótese:

| Developer incapaz | `q` = 0,3 | `q` = 0,5 | `q` = 0,7 | `q` = 1,0 |
|---|---|---|---|---|
| 0 % | 0,2 % | 0,2 % | 0,2 % | 0,2 % |
| 10 % | 0,0 % | 0,0 % | 0,1 % | 0,4 % |
| 20 % | 0,0 % | 0,1 % | 1,0 % | 3,6 % |
| 30 % | 0,0 % | 0,4 % | 2,1 % | 9,2 % |
| 50 % | 0,1 % | 3,5 % | 14,6 % | 34,6 % |

### 3.4 O que não muda com `q`

- **Falsa validação** (hipótese `falsa` ou `sem_efeito` concluída `funciona`): idêntica nas quatro colunas em todos os pontos (0 % para `falsa`; de 0,9 % a 0 % para `sem_efeito`, conforme a incapacidade). O teto de 2 % da etapa 2 não é afetado por `q`.
- **Poder** (hipótese `verdadeira` validada): cai com a incapacidade do Developer (49,3 % sem incapacidade; 21,9 % com 20 %; 2,5 % com 50 %), e `q` quase não o altera (de 23,2 % com `q` = 0,3 para 21,8 % com `q` = 1,0 a 20 % de incapacidade).

### 3.5 Reprodutibilidade

A mesma rodada foi executada no Raspberry Pi 5 (aarch64, commit `99660fe`) e no Mac (arm64): os `resultados.csv` são **idênticos byte a byte** nas duas durações (sha256 `19db7e5a…` para 6 tentativas e `8bd23d52…` para 10). Os dados versionados são os do Pi.

## 4. Leitura e proposta

- Com `q` = 0,3 (atual), o caso que motivou a mudança (N-abordagem-4) continua indeciso e a abordagem plantada só é refutada depois de 9 tentativas. Para o regime F da etapa 3, em que uma exploração pode ter poucas variações, isso significa que o sistema talvez nunca conclua que a abordagem não funciona.
- **`q` = 0,5** refuta a abordagem plantada em 5 tentativas e custa pouco em falsa refutação: 0,2 % com 20 % de incapacidade, 1,2 % com 30 % e 10,6 % só com 50 % (3,5 % em hipóteses curtas). N-abordagem-4 (−0,250) ainda não conclui no limiar 0,3; conclui só a partir de `q` = 0,7.
- **`q` = 0,7** é o menor valor para o qual N-abordagem-4 conclui `nao_funciona` (−0,340) e refuta em 4 tentativas, mas a falsa refutação já chega a 4,6 % com 30 % de incapacidade e 29,5 % com 50 %.
- **`q` = 1,0** conclui N-abordagem-3 e refuta em 3 tentativas, ao custo de 16,8 % de falsa refutação com 30 % de incapacidade; não recomendo.

**Proposta ao pesquisador:** manter `q` = 0,3 até o regime F medir quantas variações o Developer real tenta; se o piloto mostrar abordagem plantada não refutada, subir para **0,5** (melhor relação entre tentativas até refutar e falsa refutação) e só considerar 0,7 se o interesse for que N-abordagem-4 conclua. **O valor de `VERDICT_APPROACH_FAILURE_Q` em `src/config.py` não foi alterado**; qualquer mudança vai em PR próprio, com a revisão do ADR 015 §9.9.

## 5. Limitações

1. **Pior caso para a falsa refutação.** A simulação supõe que as falhas por incapacidade têm a **mesma assinatura** (`MemoryError`) e se repetem em configurações diferentes. Falhas de incapacidade com assinaturas variadas não são reproduzidas e entram como ambíguas, sem refutar. As taxas das seções 3.3 e 3.4 são, portanto, um limite superior.
2. **Incapacidade constante.** `p_falha_abordagem` é uma fração fixa por tentativa, independente do estado da hipótese; um Developer real aprende depois de falhar.
3. **Média constante.** As hipóteses simuladas não evoluem entre variações (os valores oscilam em torno de uma média); o poder absoluto é menor que o de hipóteses reais. As comparações entre valores de `q` usam as mesmas sequências e não dependem disso.
4. **Primeira travessia.** A conclusão da simulação é a primeira vez em que o veredito alcança 0,3; o sistema decide pelo veredito ao fim da exploração.
5. **Uma configuração de `sigma`, `tau` e efeito.** Não foi feita varredura desses parâmetros nesta rodada.

## 6. Comandos e commit

Commit `99660fe` (branch `feat/v18.8-approach-failure`). Raspberry Pi 5 e Mac:

```bash
for t in 6 10; do
  uv run python -m scripts.verdict_lab abordagem \
    --saida docs/calibracao-veredito/dados/2026-10-20-etapa-3-abordagem/t$t \
    --repeticoes 1000 --max-tentativas $t --p-falha-abordagem 0 0.1 0.2 0.3 0.5
done
```

Dados: [`dados/2026-10-20-etapa-3-abordagem/`](dados/2026-10-20-etapa-3-abordagem/README.md).
