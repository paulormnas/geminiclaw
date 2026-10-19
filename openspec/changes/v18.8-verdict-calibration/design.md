# Design: v18.8-verdict-calibration

## 1. Confronto com o código (2026-10-19)

| Ponto | Onde está hoje | O que muda |
|---|---|---|
| Equação | `compute_verdict`, `VerdictParams` (`src/knowledge/verdict.py`), módulo puro; `_independence_factor`, `_search_penalty`, `_direction_and_magnitude` | Modelo v2 ao lado do modelo `adr015` (mesmo módulo, mesma assinatura) |
| Coleta | `KnowledgeService.collect_attempts` e `_attempt_from` (`src/knowledge/service.py`) já entregam `config_hash`, nó, sessão, semente, datasets, `timestamp` e `baseline` | Nada muda: o modelo v2 usa os mesmos campos de `Attempt` |
| Parâmetros | `VerdictParams.from_config()` lê `VERDICT_*` de `src/config.py` | Novos campos e variáveis (§3) |
| Consumidores | `sync_statuses` (`DECISION_EVAL_MIN_VERDICT`, `src/knowledge/hypothesis_cycle.py`), atalhos (`KNOWLEDGE_SHORTCUT_MIN_VERDICT`, `src/knowledge/service.py:573`, `curator_writes.py:132`) | Limiar de conclusão continua 0,3; atalhos: questão em aberto (§7) |
| Laboratório | `scripts/verdict_lab` (`lab_verdict`, variante `completa2`) | Vira a referência de equivalência (§6); a variante `atual` do laboratório passa a fixar `modelo = adr015` |

## 2. O modelo v2

Entrada e saída iguais às do `compute_verdict` atual. Os passos, em ordem cronológica por `timestamp`:

1. **Classificação da tentativa** (inalterada, exceto o critério de direção do passo 3): `positiva`, `negativa`, `ambigua`, `infraestrutura` ou `nao_evidencia`; falha de abordagem reproduzida vira negativa com `q = VERDICT_APPROACH_FAILURE_Q` e `m = 1`.
2. **`q`** inalterado (1,0 / 0,7 / 0,3).
3. **Direção e magnitude (`o`, `m`).** Com `δ` e baseline: `Δ` contra o baseline, como hoje (`m = min(1, Δ/2δ)` na positiva e `m = min(1, (δ − Δ)/δ)` na negativa). Se `VERDICT_REQUIRE_TARGET` e o critério tem alvo, uma evidência que supera o baseline por `δ` mas não alcança o alvo é **negativa**, com `m = min(1, falta/δ)`, `falta` a distância ao alvo no sentido desfavorável. Sem baseline e com alvo: positiva se alcança o alvo, negativa se não; com `δ`, `m = max(VERDICT_M_FLOOR_NO_BASELINE, min(1, folga/(2δ)))` na positiva e `m = min(1, falta/δ)` na negativa; sem `δ`, `m = 0,5` (como hoje). Sem baseline nem alvo: ambígua.
4. **Independência (`d`).** Para cada evidência (positiva ou negativa), com os conjuntos de "já visto" da própria hipótese, nesta ordem:

   | Ordem | Tipo | Definição | `d` |
   |---|---|---|---|
   | 1 | variação | `config_hash` ainda não visto em nenhuma evidência da hipótese, em qualquer nó | `VERDICT_D_VARIATION` (1,0) se **útil**; senão, a positiva recebe `VERDICT_D_VARIATION_NO_GAIN` (0,0) e a negativa `VERDICT_D_NEW_SEED` (0,2) |
   | 2 | réplica em outro nó | `config_hash` já visto, mas não neste nó | `VERDICT_D_REPLICA_NODE` (0,5); se a evidência é negativa, `VERDICT_D_REPLICA_AGAINST` (1,0) |
   | 3 | dataset novo | configuração e nó já vistos, dataset ainda não usado | `VERDICT_D_NEW_DATASET` (1,0) |
   | 4 | sessão nova | configuração, nó e datasets já vistos, sessão nova | `VERDICT_D_NEW_SESSION` (0,5) |
   | 5 | semente nova | demais casos | `VERDICT_D_NEW_SEED` (0,2) |

   Uma variação é **útil** quando é a primeira evidência com valor da hipótese ou supera o melhor valor anterior, no sentido da métrica, em mais que `VERDICT_USEFUL_VARIATION_EPSILON` (0). O "melhor valor anterior" só avança em melhora estrita; evidência sem valor numérico (falha de abordagem) conta como útil.
5. **Penalidade de busca (`b`)** só nas positivas: `b = 1` se a configuração já foi replicada por outra evidência positiva de outro nó ou sessão; senão `b = 1 / (1 + γ · ln n_config)`, com `n_config` = 1 + número de variações **até a própria evidência** (inclusive) que não foram úteis. As falhas e as tentativas sem valor não entram.
6. **Peso, acúmulo e veredito** inalterados: `w = q · m · d · b`, `α`/`β` a partir de `VERDICT_PRIOR`, `f = 1 − λ · n_ambiguas / n_validas`, `veredito = f · (α + β − 2)(α − β) / (α + β)²`.

`EvidenceBreakdown` ganha `tipo` (`variacao`, `replica_no`, `dataset`, `sessao`, `semente`; `None` fora das evidências) e `util` (booleano, só na variação).

## 3. Configuração

| Variável | Padrão | Papel |
|---|---|---|
| `VERDICT_MODEL` | `v2` | `adr015` restaura a equação anterior (reprodutibilidade das baterias V18.6 e V18.7 e retorno rápido) |
| `VERDICT_D_VARIATION` | 1,0 | `d` da variação útil |
| `VERDICT_D_REPLICA_NODE` | 0,5 | `d` da réplica em outro nó |
| `VERDICT_D_NEW_DATASET` | 1,0 | `d` do dataset novo (config e nó já vistos) |
| `VERDICT_D_VARIATION_NO_GAIN` | 0,0 | `d` da variação positiva sem ganho |
| `VERDICT_D_REPLICA_AGAINST` | 1,0 | `d` da evidência negativa em configuração já vista |
| `VERDICT_USEFUL_VARIATION_EPSILON` | 0,0 | Melhora mínima para a variação ser útil |
| `VERDICT_M_FLOOR_NO_BASELINE` | 0,5 | Piso do `m` positivo sem baseline |
| `VERDICT_REQUIRE_TARGET` | `true` | Com baseline e alvo, exige alcançar o alvo |

`VERDICT_D_NEW_SESSION` (0,5), `VERDICT_D_NEW_SEED` (0,2), `VERDICT_GAMMA`, `VERDICT_LAMBDA_AMBIGUOUS`, `VERDICT_PRIOR` e `VERDICT_THRESHOLDS` continuam com os mesmos nomes e valores; `VERDICT_D_NEW_NODE_OR_DATASET` só vale no modelo `adr015`. Valores novos entram em `.env.example` com a descrição.

## 4. Resultado esperado (medido pelo laboratório, ainda não no sistema)

Limiar 0,3, `prior` 1,0, simulação com 96 condições × 40 repetições × 20 tentativas: poder 29,9 %, falsa validação 1,1 % (pior ponto 7,5 %), falsa refutação 1,0 %. Catálogo: 45 de 46 (erro conhecido: N-abordagem-4, uma falha de abordagem reproduzida em quatro configurações, que dá −0,14 e fica indecisa). Cinco variações com evolução dão 0,405 (funciona); três dão 0,218 (indecisa); vinte variações iguais dão 0,040; resultados em torno do alvo, 0,14 a 0,15; a mesma configuração em cinco nós, 0,184.

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Arquitetura | Mesmo módulo puro, mesma assinatura. Nenhuma camada nova (`src/knowledge`). |
| Dados | Nenhum schema. Vereditos gravados mudam de valor quando recalculados; a leitura (`funciona_fraca` etc.) mantém as faixas 0,1/0,3/0,5. |
| Segurança | Nenhum peso vem de LLM (ADR 015 §9.1); toda entrada é dado do grafo. Sem rede, sem sandbox. |
| Desempenho | Função pura; o rastreio do melhor valor e dos conjuntos de "já visto" é linear. |
| Custo | Zero tokens. |
| Manutenção | Teste de equivalência com `scripts/verdict_lab` nos 46 cenários e na amostra da simulação. |

## 6. Testes

- Cenários da spec, um teste por cenário.
- **Equivalência:** `compute_verdict` com `modelo = v2` e os valores padrão coincide (≤ 1e-12) com `lab_verdict` da variante `completa2` em todos os cenários do catálogo e numa amostra de 30 sequências da simulação.
- **Regressão do modelo antigo:** os testes existentes de `evidence-scoring` (exemplo do ADR 015 §9.6 etc.) passam a rodar com `modelo = adr015`; um teste confere que `VERDICT_MODEL=adr015` reproduz o valor gravado de 29 das 30 hipóteses dos grafos arquivados (etapa 1).
- Propriedades: limites, determinismo, ordem de entrada e monotonicidade (0 violações no catálogo).

## 7. Questões em aberto (decisão do pesquisador)

1. **Limiar dos atalhos de conhecimento.** `KNOWLEDGE_SHORTCUT_MIN_VERDICT` (0,1) e o tipo da `Descoberta` (`|veredito| > 0,1`) usam o veredito como evidência suficiente para registrar `FUNCIONOU_PARA`/`FALHOU_PARA`. No modelo v2, a falsa validação no limiar 0,1 é de 33 % (simulação), contra o objetivo de minimizar registros que não contribuem. **Proposta:** subir para 0,3, o mesmo da conclusão da hipótese. Requer decisão: manter 0,1, ou subir para 0,3 (ou outro valor, como 0,2, com 8 % de falsa validação).
2. **Falha de abordagem reproduzida (N-abordagem-4).** O veredito de −0,14 deixa indecisa uma abordagem que falhou da mesma forma em quatro configurações. Aumentar `VERDICT_APPROACH_FAILURE_Q` (0,3) é uma opção para a etapa 3.
3. **Recálculo dos vereditos já gravados.** Os nós antigos mantêm o valor até o Curator recalcular. Registrar a versão do modelo na hipótese (`modelo_veredito`) exigiria nova propriedade (aprovação de schema).
4. **Simetria.** A penalidade de busca age só nas positivas, por decisão do ADR 015; o modelo v2 mantém isso e a violação de simetria continua registrada no relatório do laboratório.
