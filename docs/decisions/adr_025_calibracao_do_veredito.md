# ADR 025 — Calibração do Veredito: Exploração e Teste dos Parâmetros

**Status:** Aprovado (2026-10-18: plano de exploração aprovado pelo pesquisador; nenhum valor ou fórmula é decidido neste ADR)
**Data:** 2026-10-15 · **Atualizado:** 2026-10-18 (etapa 1 concluída; decisões do pesquisador)
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** [`roadmaps/roadmap_V18.8.md`](../../roadmaps/roadmap_V18.8.md)
**ADRs relacionados:** ADR 015 §9 (equação de confiança e parâmetros calibráveis), ADR 021 §4 e §5 (hipóteses concluídas, parada pelo objetivo), ADR 012 (Curator)

**O que este ADR muda em outros ADRs:** nada ainda. Se a exploração propuser mudar a fórmula ou as tabelas do ADR 015 §9, a mudança entra em revisão do ADR 015, aprovada pelo pesquisador, depois dos resultados.

---

## Contexto

### Decisão do pesquisador (2026-10-15)

Ainda será rodada uma bateria de testes para calibrar o veredito. Este ADR é o rascunho que reúne as informações preliminares e o plano para explorar e testar os valores. Os parâmetros do veredito e o limiar `SOLUTION_MIN_VERDICT` foram deixados para essa etapa quando a V18.7 foi especificada.

### O que é o veredito

Número em [−1, +1] calculado por `src/knowledge/verdict.py` (`compute_verdict`, módulo puro) a partir das tentativas de uma hipótese, pela equação de confiança do ADR 015 §9. Cada tentativa vira evidência com peso `w = q · m · d · b`: qualidade da validação (`q`), magnitude do efeito (`m`), independência (`d`) e penalidade de busca (`b`). O peso entra em `α` (positivas) ou `β` (negativas), a partir de 1; `veredito = f · (α + β − 2)(α − β) / (α + β)²`, com `f` o fator de conclusão (tentativas ambíguas).

Parâmetros em `src/config.py` (variáveis `VERDICT_*`), valores iniciais do ADR 015 §9.8:

| Parâmetro | Variável | Valor atual |
|---|---|---|
| `q`: validado e contrato completo / incompleto / divergente | `VERDICT_Q_VALIDATED_COMPLETE`, `VERDICT_Q_VALIDATED_INCOMPLETE`, `VERDICT_Q_DIVERGENT` | 1,0 / 0,7 / 0,3 |
| `d`: nó ou dataset novo / sessão nova / semente nova | `VERDICT_D_NEW_NODE_OR_DATASET`, `VERDICT_D_NEW_SESSION`, `VERDICT_D_NEW_SEED` | 1,0 / 0,5 / 0,2 |
| `γ`: penalidade de busca `b = 1 / (1 + γ · ln n_config)` | `VERDICT_GAMMA` | 0,5 |
| `λ`: peso das tentativas ambíguas em `f` | `VERDICT_LAMBDA_AMBIGUOUS` | 0,5 |
| Falha da abordagem reproduzida: `q` e mínimo de repetições | `VERDICT_APPROACH_FAILURE_Q`, `VERDICT_APPROACH_FAILURE_MIN_REPEATS` | 0,3 / 2 |
| Ponto de partida de `α` e `β` | `VERDICT_PRIOR` | 1,0 |
| Faixas de leitura (fraca / moderada / forte) | `VERDICT_THRESHOLDS` | 0,1 / 0,3 / 0,5 |

`m` não tem variável: vem de uma conta fixa (com `δ` definido pelo pesquisador, `m = min(1, Δ / (2δ))` para evidência positiva; sem baseline, `m = 0,5`).

### Onde o veredito é usado

| Uso | Parâmetro | Valor |
|---|---|---|
| Hipótese passa a `validada` ou `refutada` (e a `Decisao` é avaliada) | `DECISION_EVAL_MIN_VERDICT` (`src/knowledge/hypothesis_cycle.py`, `sync_statuses`) | `\|veredito\| ≥ 0,3` |
| Atalhos de conhecimento `FUNCIONOU_PARA` / `FALHOU_PARA` | `KNOWLEDGE_SHORTCUT_MIN_VERDICT` (`src/knowledge/service.py`, `curator_writes.py`) | `\|veredito\| ≥ 0,1` |
| Tipo da `Descoberta` (`funciona` / `nao_funciona`) | faixa "insuficiente" do ADR 015 §9.5 | `\|veredito\| > 0,1` |
| Critério de "solução encontrada" (parada da sessão) | `SOLUTION_MIN_VERDICT` | removido como critério de parada pela `v18.7-exploration-limits` (a parada passa a ser pelo objetivo tipado do `Problema`, ADR 021 §5) |

Depois da V18.7, o veredito deixa de fechar sessões; ele passa a decidir o ciclo de vida das hipóteses (concluídas aceitam replicação, ADR 021 §4) e o que o grafo registra como conhecimento. Um veredito que nunca atinge 0,3 deixa as hipóteses sempre em `em_teste` e o grafo sem descobertas firmes.

### O que a bateria V18.6 mostrou

Em nenhuma das 12 execuções o veredito de uma hipótese chegou a 0,3 (valores entre 0,007 e 0,11 no relatório), mesmo com acurácia validada de 1,0 (`docs/benchmarks/2026-10-15-bateria-v18-6-resultados.md`, achado 3). O critério de solução nunca disparou por isso.

### Análise preliminar da equação (reproduzível)

Cálculo com `compute_verdict` e `VerdictParams` padrão, alvo absoluto de 0,95 (como no benchmark), todas as evidências validadas, contrato completo e acima do alvo; um nó, uma sessão, um dataset, exceto onde indicado:

| Cenário | Veredito |
|---|---|
| 1 evidência | +0,040 |
| 3 configurações diferentes | +0,034 |
| 5 configurações diferentes | +0,040 |
| 5 réplicas da mesma configuração (sementes) | +0,096 |
| 3 sessões, mesma configuração | +0,111 |
| 3 datasets, mesma configuração | +0,184 |
| 5 datasets, ou 5 nós, mesma configuração | +0,309 |
| 1 positiva e 1 negativa | +0,021 |
| 4 negativas, configurações diferentes | −0,082 |
| 1 evidência, contrato incompleto (`q` = 0,7) | +0,022 |

Observações a verificar (hipóteses de trabalho, não conclusões):

1. **Sem baseline, `m` é fixo em 0,5** e a evidência pesa metade; é o caso do benchmark (alvo absoluto). Com baseline e `δ`, uma evidência perfeita chega a 0,11 (ADR 015 §9.5).
2. **O limiar de 0,3 exige cerca de cinco datasets ou nós independentes.** Numa exploração com um nó e um dataset (o caso do Raspberry Pi e do benchmark), o veredito mal passa de 0,1 com muitas tentativas, então `validada`/`refutada` por 0,3 raramente acontece.
3. **Configurações diferentes sobre os mesmos dados não somam**: cada nova configuração entra com `d` = 0,2 (conta como "semente nova") e a penalidade de busca `b` cresce com `n_config`; cinco configurações valem o mesmo que uma.
4. **A fórmula não distingue o tipo de evidência por hipótese**: o que é uma réplica (mesma configuração) e o que é uma variação (outra configuração) é decidido só por `config_hash` e pelo contexto (nó, dataset, sessão, semente).
5. **A escala foi desenhada para múltiplos nós e datasets** (ADR 015 §9.5: evidência forte exige cerca de cinco réplicas independentes); o uso atual é de um nó, e a federação (V20) ainda não existe.
6. A direção `o` da evidência pela **predição** da hipótese (ADR 015 §9) não tem mudança OpenSpec dona; hoje a direção vem de `Δ` contra `δ` ou contra o alvo.

### Resultado da etapa 1 (2026-10-18)

Relatório: [`docs/calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md`](../calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md). Recálculo sobre os 18 grafos arquivados, sem LLM: 30 hipóteses com tentativas, 29 reproduzidas exatamente; nenhuma passa de 0,111. Cada hipótese tem no máximo duas evidências positivas, num nó e numa sessão, e nenhuma negativa; 39 das 63 tentativas são ambíguas. Variar `d` e `γ` não muda o resultado; só o `prior` muda, por baratear a evidência. Sem evidência negativa, o veredito é `(W/(2+W))²`, com `W` a soma dos pesos: 0,3 exige `W ≈ 2,4` (três evidências perfeitas e independentes). As observações 1 a 3 acima se confirmam; acrescentam-se duas: `n_config` conta as configurações das falhas (penaliza a evidência boa) e as falhas não produzem evidência negativa num nó.

### Decisões do pesquisador (2026-10-18)

1. A equação deve permitir que uma exploração em **um único nó** chegue a um veredito, de solução ou de falha.
2. Hipóteses validadas em **outros nós continuam contribuindo** para uma solução melhor.
3. **Variar a configuração conta como exploração**, desde que a configuração ainda não tenha sido executada em outro nó. **Replicar em outro nó conta como validação, com peso menor que uma variação**: a variação tem mais chance de achar caminhos novos e resultados melhores; a réplica confirma o que já foi descoberto (resposta à pergunta 4 do §2, quanto à ordem; os valores saem da exploração).
4. **Cautela com volume:** a equação não pode premiar muitas buscas e variações que não melhoram a pesquisa. O ponto será aprofundado com os resultados da grade sintética.
5. Ordem: grade sintética (etapa 2) antes de qualquer mudança na fórmula; depois, ajuste da fórmula até resultados significativos.
6. Os resultados de calibração e validação de parâmetros ficam em `docs/calibracao-veredito/`; `docs/benchmarks/` fica só para benchmark. Os relatórios devem servir de base para a dissertação.

---

## Decisão

Este ADR não decide valores. Ao ser aprovado, autoriza explorar e testar os parâmetros e a escala do veredito conforme o plano abaixo, e exige que qualquer mudança de fórmula ou valor volte ao pesquisador, com os resultados, antes de entrar no código.

### 1. Restrições herdadas (valem durante toda a exploração)

- Nenhum peso é atribuído por LLM (ADR 015 §9.1); toda variante de peso é uma conta ou tabela fixa sobre dados do grafo e dos artefatos.
- O `delta_min` (`δ`) é definido pelo pesquisador antes dos experimentos; a calibração não o ajusta depois de ver o resultado.
- Todo valor fica em `src/config.py`, com variável de ambiente e padrão documentado; a calibração varia valores por variável de ambiente, sem alterar código.
- O alvo do `Problema` do benchmark (0,95) continua fixo (decisão de 2026-10-13).

### 2. Perguntas a responder

1. Qual o veredito esperado, por tipo de objetivo (`limiar`, `discriminacao`, `cobertura`, ADR 021 §5.2), para uma hipótese verdadeira, uma falsa e uma sem efeito, dado o número de tentativas, datasets e nós que o sistema consegue produzir hoje?
2. O limiar de 0,3 (`DECISION_EVAL_MIN_VERDICT`) é alcançável num nó e um dataset? Se não, o que deve mudar: o limiar, a escala (`d`, `b`, `m`) ou a exigência de evidência?
3. O fixo `m` = 0,5 sem baseline é adequado para alvo absoluto? Há uma conta fixa melhor (por exemplo, pela folga em relação ao alvo)?
4. O que conta como evidência independente para uma hipótese de abordagem: dataset, nó, sessão, semente ou configuração? A penalidade de busca `b` e o `d` da "semente nova" estão tratando variações de configuração como réplicas?
5. Como o veredito deve se comportar quando a concordância entre tentativas é alta e o número de tentativas é pequeno (exploração curta)?
6. A direção `o` por predição (ADR 015 §9) precisa de um dono: quando entra e como é calculada?
7. Existem faixas de leitura (0,1 / 0,3 / 0,5) diferentes para exploração e para conhecimento a ser reutilizado (`KNOWLEDGE_SHORTCUT_MIN_VERDICT`)?

### 3. Plano de exploração

Em ordem de custo crescente; cada etapa só começa depois de revisar a anterior com o pesquisador.

1. **Repetição offline (sem custo de LLM).** Recalcular o veredito com `compute_verdict` sobre os grafos arquivados da bateria V18.6 (`grafo_projeto.json` de cada execução, no Raspberry Pi), variando os parâmetros por variável de ambiente. Saída: tabela de veredito por hipótese e por conjunto de parâmetros, e evidências necessárias para cada faixa.
2. **Grade sintética e propriedades.** Cenários de evidência gerados (positivas, negativas, mistas, réplicas, variações, nós e datasets distintos, tentativas ambíguas e de infraestrutura) para varrer cada parâmetro isoladamente e em pares. Testes de propriedade: monotonicidade (mais evidência concordante nunca reduz `|veredito|`), simetria, ordem das tentativas, limites.
3. **Sessões controladas com resposta conhecida.** Tarefas com efeito plantado (hipótese verdadeira) e sem efeito (nula), em dados sintéticos, repetidas com sementes diferentes. Medidas: taxa de falsa validação, taxa de falsa refutação, número de tentativas até cruzar 0,3, estabilidade entre repetições e entre modelos. Esta etapa usa o caso de pesquisa e os dados sintéticos que o pesquisador pretende construir (também úteis para o caso de dados que o Developer precisa ver, ADR 019).
4. **Bateria no Raspberry Pi** com a configuração escolhida, só com confirmação do pesquisador, medindo custo e o efeito no ciclo de vida das hipóteses e no grafo.

### 4. Medidas e critérios de comparação

- Erros de classificação: falsa validação, falsa refutação, indecisão (permanece em `em_teste`) por tipo de hipótese.
- Evidências necessárias (tentativas, datasets, nós) para cruzar 0,1, 0,3 e 0,5.
- Sensibilidade: variação do veredito por variação de cada parâmetro, para listar os que dominam.
- Robustez: variação entre sementes, modelos e repetições.
- Custo de obter a evidência (tokens e tempo) em relação ao veredito alcançado.

Os critérios de aceite de uma variante (por exemplo, taxa máxima de falsa validação) são propostos pelo Arquiteto com os resultados das etapas 1 e 2 e decididos pelo pesquisador.

### 5. Variantes candidatas a testar (não são recomendações)

- Ajustar apenas valores (`DECISION_EVAL_MIN_VERDICT`, `VERDICT_THRESHOLDS`, `VERDICT_D_*`, `VERDICT_GAMMA`).
- Substituir `m` = 0,5 sem baseline por uma conta fixa pela folga em relação ao alvo.
- Tratar configurações distintas de uma mesma abordagem com um `d` próprio, em vez de "semente nova".
- Limiares por contexto (número de datasets ou nós disponíveis), em vez de um limiar único.
- Separar "veredito" (para onde a evidência aponta) de "rigor da replicação" na leitura, mantendo a equação.

---

## Alternativas Consideradas

### A. Calibrar à mão com os resultados da bateria V18.6
**Rejeitada:** a bateria usa um dataset e um alvo; ajustar valores a ele ajusta o veredito ao caso, não à ciência.

### B. Reduzir só o limiar (`DECISION_EVAL_MIN_VERDICT`)
Simples e reversível. **Mantida como variante a testar:** pode mascarar o problema de escala (observações 1 a 3) e aumentar falsas validações; os erros de classificação da etapa 3 decidem.

### C. Tirar o veredito do ciclo de vida das hipóteses
**Não adotada:** o ADR 015 §9.1 e o ADR 021 §4 dependem de uma conta fixa e auditável, e o grafo registra conhecimento pelo veredito.

---

## Consequências

### Positivas
- O veredito passa a ser calibrado com dados e erros medidos, não por intuição.
- As etapas 1 e 2 não custam chamadas de LLM.
- Gera o caso sintético de pesquisa que o projeto ainda não tem.

### Negativas / Trade-offs
- Depende dos grafos arquivados e de sessões controladas que ainda precisam ser construídas.
- Uma mudança de fórmula exige revisar o ADR 015 e o código de `src/knowledge/verdict.py`.
- Conclusões sobre um nó e um dataset podem não valer quando houver vários nós (V20).

---

## Mudanças OpenSpec exigidas (depois da aprovação do plano)

| Mudança | Capacidade | O que cobre |
|---|---|---|
| [`v18.8-verdict-lab`](../../openspec/changes/v18.8-verdict-lab/proposal.md) (especificada em 2026-10-18) | `evidence-scoring`, `benchmark` | Ferramenta de repetição offline, grade sintética, simulação com resposta conhecida e sensibilidade, sem alterar o comportamento do sistema |
| `v18.8-verdict-calibration` | `evidence-scoring`, `hypothesis-loop` | Valores ou fórmula escolhidos depois dos resultados, com revisão do ADR 015 §9 |
| `v18.8-verdict-direction` | `evidence-scoring` | Direção `o` da evidência pela predição da hipótese (ADR 015 §9), se a etapa 1 confirmar a lacuna |

---

## Revisão

Revisar depois das etapas 1 e 2: se os cenários explicam o veredito da bateria V18.6, e qual das variantes do §5 vale levar às etapas 3 e 4.

## Estado da implementação

| Etapa (§3) | Estado (2026-10-18) |
|---|---|
| 1. Repetição offline | Concluída com scripts provisórios ([relatório](../calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md)); refeita pela ferramenta de `v18.8-verdict-lab` |
| 2. Grade sintética e propriedades | Especificada em `v18.8-verdict-lab` (aguarda aprovação) |
| 3. Sessões controladas | Não iniciada |
| 4. Bateria no Raspberry Pi | Não iniciada |
