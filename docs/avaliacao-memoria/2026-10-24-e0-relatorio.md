# Relatório do E0 (replay dos candidatos estruturais)

**Data:** 2026-10-24 · **Pré-registro:** [2026-10-24-e0-pre-registro.md](2026-10-24-e0-pre-registro.md) (commit
`deec13e`; posterior a uma execução exploratória do mesmo código, declarada no pré-registro) · **Custo de LLM:** nenhum.
**Artefatos:** `2026-10-24-e0/instantaneo.json` (sha256 `d38c3322…f46f55`), `replay.json` e
`replay_entre_problemas_distintos.json` (com commit, sementes e configuração).

## Corpus efetivo
17 problemas (um por projeto) e 33 tentativas válidas ligadas a hipóteses. Quatro projetos ficaram de fora por não ter
nenhuma tentativa válida (inclui a sessão vazia por cota). Quatro conjuntos de dados (Iris 2 projetos, Wine 2, Glass 6,
Breast Cancer 7). Cortes: 17. Pares avaliados: 1186, dos quais 26 positivos.

## Resultado (AUC, IC 95% por bootstrap de projetos)

| Ordenação | Principal (todos os pares) | Entre problemas distintos | Somente tentados (principal) |
|---|---|---|---|
| padrão | 0,53 [0,41; 0,83] | 0,31 [0,11; 0,85] | 0,16 [0,00; 0,65] |
| semelhança | **0,85** [0,64; 0,89] | 0,29 [0,08; 0,86] | 0,75 [0,50; 1,00] |
| grau da abordagem | 0,55 [0,46; 0,77] | 0,55 [0,46; 0,77] | 0,10 [0,05; 0,22] |
| aleatória (100 sementes) | 0,51 [0,37; 0,64] | 0,51 [0,37; 0,64] | 0,51 [0,32; 0,68] |

## Decisão
**A regra de decisão do pré-registro não foi cumprida:** a AUC da ordenação padrão (0,53) não supera a da semelhança
sozinha (0,85), e seu intervalo não se separa do da aleatória. Portanto os candidatos **não** seguem para
`v18.9-cross-project-context` por este critério, e `CROSS_PROJECT_CANDIDATES` permanece `false`.

## O que o resultado diz e o que não diz
- A semelhança textual prevê bem **quando o mesmo conjunto de dados reaparece em outro projeto**: o par positivo
  típico é "a abordagem que funcionou no Iris funciona no outro Iris". Ao zerar a semelhança entre Problemas da mesma
  assinatura de dados (análise 2), nenhuma ordenação se distingue do acaso (intervalos de 0,1 a 0,9).
- A ordenação padrão fica abaixo da semelhança porque multiplica pela margem e pelas réplicas: abordagens com grande
  ganho em um problema distante sobem à frente de abordagens modestas em problemas idênticos.
- Com 26 positivos e 17 projetos, os intervalos são largos. O resultado **não é evidência de que a estrutura do grafo
  não ajuda**; é evidência de que este corpus (um nível de dificuldade alto de teto, 4 conjuntos de dados, abordagens
  quase sempre as mesmas) não discrimina a ordenação padrão da semelhança.
- Limitações herdadas: sem arestas `VARIANTE_DE`, só há candidatos de transferência; o nome normalizado da abordagem
  mistura técnicas parecidas com nomes diferentes; a maioria dos positivos vem de `random forest` e regressão logística,
  que funcionam em qualquer um dos problemas (efeito-teto).

## Próximos passos possíveis (decisão do pesquisador)
1. Ampliar o corpus com as famílias do gerador (`families.py`; custo de LLM, com confirmação) ou com problemas mais
   difíceis e abordagens mais variadas.
2. Reformular a ordenação padrão (por exemplo, `semelhança` como fator dominante e margem/réplicas como desempate) e
   registrar como nova rodada pré-registrada; esta decisão **não** deve ser tomada olhando estes mesmos dados sem
   declarar o reuso.
3. Usar a semelhança de Problemas (já prevista em `v18.9-cross-project-context` §3) como principal sinal do bloco de
   experiência e adiar `CROSS_PROJECT_CANDIDATES`.
