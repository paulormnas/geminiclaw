# Etapa 1 da calibração do veredito: repetição offline sobre os grafos arquivados

**Data:** 2026-10-18 · **ADR:** [025](../decisions/adr_025_calibracao_do_veredito.md) §3, etapa 1 · **Commit do código usado:** `01b854e` (`dev`) · **Custo:** nenhuma chamada de LLM

## 1. Pergunta

Por que nenhuma hipótese das baterias chegou ao limiar de 0,3 que a torna `validada` ou `refutada` (`DECISION_EVAL_MIN_VERDICT`), mesmo com acurácia validada acima do alvo? O problema está nos valores dos parâmetros, na quantidade de evidência que uma sessão produz ou na forma da equação?

## 2. O veredito em uma página

O veredito de uma hipótese é um número entre −1 e +1, calculado por `compute_verdict` (`src/knowledge/verdict.py`) pela equação de confiança do [ADR 015](../decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9. Valores positivos indicam que a abordagem funciona; negativos, que não funciona; perto de zero, evidência insuficiente.

1. **Cada tentativa é classificada** pelo desfecho: `positiva` (o resultado atinge o efeito relevante `δ` sobre o baseline ou, sem baseline, o alvo), `negativa` (não atinge), `ambigua` (falha sem causa objetiva, ou falha de abordagem ainda não reproduzida), `infraestrutura` (queda de energia, limite de uso; não pesa) ou `nao_evidencia`.
2. **Cada evidência recebe um peso** `w = q · m · d · b`, só de dados registrados (nenhum peso vem de LLM):
   - `q`, qualidade da validação: 1,0 (validado, contrato completo), 0,7 (validado, contrato incompleto), 0,3 (divergente documentado);
   - `m`, magnitude do efeito: `min(1, Δ/2δ)` com baseline; 0,5 fixo sem baseline;
   - `d`, independência: 1,0 para nó ou dataset ainda não usado na hipótese, 0,5 para sessão nova, 0,2 para semente nova na mesma sessão;
   - `b`, penalidade de busca (só positivas): `1 / (1 + γ · ln n_config)`, com `γ = 0,5` e `n_config` o número de configurações distintas tentadas na hipótese.
3. **Os pesos se acumulam** em `α` (positivas) e `β` (negativas), ambos começando em `α0 = β0 = 1` (o `prior`).
4. **O veredito** é `f · (α + β − 2)(α − β) / (α + β)²`, em que `f = 1 − λ · n_ambiguas / n_validas` (`λ = 0,5`) desconta tentativas ambíguas.

Uma consequência direta da forma da equação ajuda a ler os resultados. Sem evidência negativa e com `f = 1`, a soma dos pesos positivos `W` dá

```
veredito = (W / (2 + W))²
```

| Soma dos pesos `W` | 1 | 2 | 2,42 | 3 | 4 | 4,83 | 5 |
|---|---|---|---|---|---|---|---|
| Veredito | 0,111 | 0,250 | **0,300** | 0,360 | 0,444 | **0,500** | 0,510 |

Como cada evidência pesa no máximo 1, chegar a 0,3 exige pelo menos três evidências perfeitas e independentes (`q = m = d = b = 1`), e chegar a 0,5, pelo menos cinco. Uma única evidência, por melhor que seja, fica em 0,111.

## 3. Dados

- **Fonte:** os 18 arquivos `grafo_projeto.json` guardados no Raspberry Pi em `~/bench/<bateria>.json.d/<combinacao>/<repeticao>/`, das baterias V18.6 (14 execuções, incluindo 3 que falharam por cota ou erro e foram guardadas com sufixo `-falha-*`), V18.7, V18.7b, V18.7c e da bateria curta (`short`).
- **Tarefa de todas as execuções:** o pipeline de classificação do Iris do benchmark (`scripts/benchmark/task_iris.txt`), com critério do `Problema` `acuracia ≥ 0,95`, `δ = 0,01` e baseline majoritário de 0,333 quando o Developer o registrou.
- **Hipóteses:** 64 no total, 30 com ao menos uma tentativa (`Experimento -TESTA-> Hipotese`); as outras 34 nunca foram testadas e não entram nas contas.
- **Tentativas das 30 hipóteses:** 63 no total.

## 4. Método

1. Para cada hipótese, as tentativas foram reconstruídas do grafo exportado como o Curator as monta (`KnowledgeService._attempt_from`, `src/knowledge/service.py`): o experimento que testa a hipótese, a configuração pela aresta `APLICOU` (ou o `hash_params` do experimento), o nó, a sessão, a semente, os datasets e, para experimentos com sucesso, o `Resultado` da métrica do critério.
2. O veredito de cada hipótese foi recalculado com `compute_verdict` e os parâmetros padrão e comparado com o valor gravado no nó `Hipotese`, para conferir a reconstrução.
3. Cada parâmetro foi variado isoladamente (e em algumas combinações), contando quantas hipóteses passam de 0,1, 0,3 e 0,5.

O grafo exportado não traz o nó `Metrica` nem a aresta `MEDE`, por isso o `Resultado` da métrica foi identificado pelo nome original (`nome_original = "acuracia"`) e o sentido (`maior_melhor`) foi lido do critério. Os scripts desta etapa foram escritos fora do repositório (provisórios). A mudança [`v18.8-verdict-lab`](../../openspec/changes/v18.8-verdict-lab/proposal.md) refaz esta tabela com uma ferramenta versionada.

## 5. Resultados

### 5.1 A reconstrução reproduz o sistema

29 das 30 hipóteses têm veredito recalculado idêntico ao gravado (diferença menor que 10⁻⁴). A exceção (`bateria_v18_7c/sonnet-dev-sol-juiz/r1`, hipótese `…ed2837`: gravado 0,0137 com 4 tentativas, recalculado 0 com 2) vem de dois resultados que o Curator ligou à métrica por `MEDE` e que o grafo exportado não permite reconstruir. A conferência mostra que a leitura dos dados está correta e que os números abaixo descrevem o que o sistema calcula.

### 5.2 Nenhuma hipótese chega a 0,3

| Faixa do veredito | Hipóteses (de 30) |
|---|---|
| `|veredito| ≥ 0,1` (`funciona_fraca`) | 6 |
| `|veredito| ≥ 0,3` | 0 |
| Maior veredito observado | 0,111 |

### 5.3 O motivo é a pouca evidência por hipótese

| Classificação das 63 tentativas | Quantidade |
|---|---|
| Positiva | 21 |
| Negativa | 0 |
| Ambígua | 39 (34 falhas sem causa objetiva e 5 falhas de abordagem não reproduzidas) |
| Infraestrutura | 3 |

- **No máximo duas evidências positivas por hipótese**, todas no mesmo nó e na mesma sessão. O campo `dataset_ids` dos experimentos está vazio, então o dataset nunca conta como novo.
- **Nenhuma evidência negativa** em nenhuma hipótese. Não há como uma sessão de um nó refutar uma abordagem: as falhas viram tentativas ambíguas, e nenhum resultado ficou abaixo do alvo.
- **As tentativas ambíguas reduzem o veredito.** A hipótese `…459203` (bateria curta) teve 8 tentativas: 7 falhas ambíguas e 1 positiva. O fator de conclusão caiu para `f = 0,56` e o veredito para 0,014.
- **As falhas aumentam a penalidade de busca.** `n_config` conta as configurações de todas as tentativas, inclusive as que falharam. Na hipótese `…cfcd61`, duas falhas com configurações diferentes levaram `b` a 0,554 na única evidência boa (contando só as duas configurações com resultado, seria 0,743).
- **Uma configuração nova no mesmo nó conta como semente nova.** Na mesma hipótese `…cfcd61`, a segunda configuração positiva entrou com `d = 0,2`, o mesmo peso de repetir a configuração com outra semente.

Pesos das 21 evidências positivas: `w` médio 0,69 (máximo 1,0); `m = 1` em 17 delas (baseline presente) e 0,5 em 4 (sem baseline); `b = 1` em 10, 0,743 em 9 e 0,554 em 2.

### 5.4 Variar os parâmetros quase não muda o resultado

| Variante (os demais parâmetros no padrão) | ≥ 0,1 | ≥ 0,3 | ≥ 0,5 | Maior |
|---|---|---|---|---|
| Padrão do ADR 015 §9.8 | 6 | 0 | 0 | 0,111 |
| `d` de semente nova = 0,5, 0,8 ou 1,0 | 6 | 0 | 0 | 0,111 |
| `d` de sessão e de semente nova = 1,0 | 6 | 0 | 0 | 0,111 |
| `γ` = 0,25 ou 0 (sem penalidade de busca) | 6 | 0 | 0 | 0,111 |
| `d` de semente = 1,0 e `γ` = 0 | 7 | 0 | 0 | 0,175 |
| `prior` = 0,5 | 17 | 0 | 0 | 0,250 |
| `prior` = 0,25 | 19 | 7 | 0 | 0,444 |
| `prior` = 0,5, `d` de semente = 1,0 e `γ` = 0 | 17 | 1 | 0 | 0,311 |

Com uma ou duas evidências por hipótese, `d` e `γ` mal têm sobre o que agir. Só o `prior` muda o quadro, porque altera a curva inteira da equação: com `prior` = 0,25, uma evidência perfeita já vale 0,44. Reduzir o `prior` torna o veredito mais barato, mas não mais informativo: a mesma evidência única que hoje é "fraca" passaria a ser "moderada".

### 5.5 Detalhe de três hipóteses

| Hipótese | Tentativa | Desfecho | `q` | `m` | `d` | `b` | `w` |
|---|---|---|---|---|---|---|---|
| `…cfcd61` (V18.6, controle, r2): veredito 0,044 | 1 e 2 | falha, configurações diferentes | — | — | — | — | ambígua |
| | 3 | acurácia 0,967, baseline 0,333 | 1,0 | 1,0 | 1,0 | 0,554 | 0,554 |
| | 4 | falha, sem configuração | — | — | — | — | ambígua |
| | 5 | acurácia 0,967, outra configuração | 1,0 | 1,0 | **0,2** | 0,554 | 0,111 |
| `…459203` (curta): veredito 0,014 | 1 a 7 | falha | — | — | — | — | ambígua |
| | 8 | acurácia 0,967, sem baseline | 1,0 | **0,5** | 1,0 | 0,743 | 0,371 |
| `…abda4b` (V18.6, Gemini dev, r2): veredito 0,014 | 1 a 3 | falha | — | — | — | — | ambígua |
| | 4 | acurácia 0,967, sem semente | **0,7** | **0,5** | 1,0 | 1,0 | 0,350 |

## 6. Leitura

1. **O limiar de 0,3 não é alcançável em uma sessão de um nó** com a equação atual (ADR 025, pergunta 2). Seriam necessárias pelo menos três evidências de peso máximo e independentes, e a única forma de obter `d = 1` repetidamente é trocar de nó ou de dataset.
2. **A equação foi desenhada para replicação entre nós e datasets** (ADR 015 §9.5), e o uso atual é exploração em um nó. Nesse uso, a variação de configuração, que é o que o sistema mais faz, quase não conta (`d = 0,2` e `b < 1`).
3. **Ajustar só valores não resolve.** `d` e `γ` não mudam o resultado; o `prior` muda, mas por baratear a evidência, não por medi-la melhor.
4. **O sistema não consegue concluir "não funciona" em um nó.** As falhas viram ambíguas e reduzem `f`, sem gerar evidência negativa.
5. **Problemas de registro também pesam:** `dataset_ids` vazio, resultados sem baseline (`m = 0,5`) e sem semente (`q = 0,7`).

## 7. Decisões do pesquisador depois desta etapa (2026-10-18)

- A equação deve ser ajustada para que **uma exploração em um único nó consiga chegar a um veredito**, de solução ou de falha.
- **Hipóteses validadas em outros nós continuam contribuindo** para uma solução melhor.
- **Variar a configuração conta como exploração**, desde que a configuração ainda não tenha sido executada em outro nó.
- **Replicar em outro nó conta como validação, com peso menor que uma variação:** a variação tem mais chance de achar caminhos novos e resultados melhores, e a réplica só confirma o que já foi descoberto.
- **Cautela:** um agente pode fazer muitas buscas e variações que não melhoram a pesquisa. A equação não pode premiar volume de tentativas. O ponto será aprofundado com os resultados da grade sintética.
- A etapa 2 (grade sintética) vem antes de qualquer mudança na fórmula; a fórmula é ajustada depois, com os resultados.

## 8. Limitações

- Uma única tarefa (Iris), um alvo (0,95) e um nó; as hipóteses são parecidas entre si e quase todas verdadeiras (acurácia 0,967). O conjunto não tem hipóteses falsas ou sem efeito conhecidas, então não mede falsa validação nem falsa refutação; isso é papel das etapas 2 e 3.
- 34 das 64 hipóteses nunca foram testadas e ficaram de fora.
- A reconstrução depende do grafo exportado, sem `Metrica` e `MEDE` (uma hipótese divergente).

## 9. Como reproduzir

No Raspberry Pi, a partir da raiz do repositório no commit `01b854e`, com os grafos em `~/bench/`. A ferramenta versionada da mudança `v18.8-verdict-lab` (comando `replay`) substitui os scripts provisórios usados aqui e deve reproduzir as tabelas 5.1 a 5.4.
