# Proposta: Calibração do veredito (modelo v2 da equação de confiança)

**ID:** `v18.8-verdict-calibration` · **Versão:** V18.8

**Capacidades:** `evidence-scoring`, `hypothesis-loop`

**ADRs de origem:** [ADR 025](../../../docs/decisions/adr_025_calibracao_do_veredito.md) §4.2 (critério de aceite de 2 % de falsa validação) e "Decisões do pesquisador (2026-10-18 e 2026-10-19)"; [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9 (equação de confiança, revisada por esta mudança); [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §4 (hipóteses concluídas aceitam replicação).

**Depende de:** `v18.8-verdict-lab` (mergeada: #222, #224, #225), que mediu as variantes e produziu a variante `completa2` escolhida. Relatórios: [etapa 1](../../../docs/calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md), [etapa 2](../../../docs/calibracao-veredito/2026-10-18-etapa-2-grade-sintetica.md) e [segunda rodada](../../../docs/calibracao-veredito/2026-10-18-etapa-2b-criterio-de-2-por-cento.md).

**Nota de data:** escrita em 2026-10-19, a partir das decisões do pesquisador da mesma data (seção "Decisões").

## Por quê

Com a equação do ADR 015 §9, nenhuma das 30 hipóteses testadas nas baterias passou de 0,111, e o limiar de conclusão (`DECISION_EVAL_MIN_VERDICT` = 0,3) praticamente não é alcançável por uma exploração em um nó: 1 % das hipóteses verdadeiras são validadas na simulação. Variar os valores dos parâmetros quase não muda isso; o que muda é a estrutura da equação: o peso de independência (`d`) trata uma configuração nova no mesmo nó como "semente nova" (0,2), a penalidade de busca (`b`) conta as falhas, e o alvo é ignorado quando há baseline.

A variante `completa2`, escolhida pelo critério do pesquisador, leva o poder de 1 % a 30 % com **1,1 % de falsa validação** (teto de 2 %) no limiar atual 0,3, e acerta 45 dos 46 cenários do catálogo (a equação atual, 23).

## O que muda

### Modificado

- **`compute_verdict`** ganha o **modelo v2** da equação (ADR 015 §9, revisado), com estes comportamentos:
  1. **Independência por tipo (`d`).** Cada evidência é classificada, em ordem cronológica, pelo que tem de novo para a hipótese: *variação* (configuração nunca executada em nenhum nó), *réplica em outro nó*, *dataset novo*, *sessão nova* ou *semente nova*. Variação pesa mais que réplica em outro nó (decisão do pesquisador).
  2. **Variação útil.** Uma variação só vale como exploração se superar o melhor valor anterior da hipótese, no sentido da métrica, por qualquer quantidade (`VERDICT_USEFUL_VARIATION_EPSILON` = 0). Uma variação positiva sem ganho pesa zero (o volume não produz conclusão).
  3. **Penalidade de busca (`b`) acumulada.** `n_config` conta, até a própria evidência, as variações que não melhoraram; as falhas não entram. Uma evidência posterior não reduz o peso das anteriores.
  4. **Alvo exigido com baseline.** Com baseline e alvo, a evidência só é positiva se supera o baseline por `δ` **e** alcança o alvo (como o objetivo `limiar` do `Problema`); caso contrário é negativa.
  5. **Magnitude pela folga sem baseline.** Com alvo e `δ`, `m = max(0,5; min(1, folga / (2δ)))` na positiva e `m = min(1, falta / δ)` na negativa.
  6. **Réplica contrária pesa cheio.** Uma evidência negativa em configuração já vista tem `d` = 1,0.
- **Configuração:** `VERDICT_MODEL` (`v2` por padrão; `adr015` restaura a equação anterior sem alterar código) e os valores do modelo v2 (design §3).
- **Revisão do ADR 015 §9** (9.2, 9.4 e 9.5), aprovada pelo pesquisador antes da implementação.

### Novo

- Os valores calibrados e o método ficam registrados nos relatórios de `docs/calibracao-veredito/`; a mudança acrescenta o teste de equivalência com o laboratório (`scripts/verdict_lab`) sobre os 46 cenários do catálogo.

### Fora do escopo

- Direção da evidência pela predição da hipótese (`v18.8-verdict-direction`).
- Sessões controladas com agentes (ADR 025, etapa 3) e bateria no Raspberry Pi (etapa 4), que reconferem o teto de 2 % com dados novos.
- Alterar `DECISION_EVAL_MIN_VERDICT` (continua 0,3). O limiar dos atalhos de conhecimento é uma **questão em aberto** (design §7).

## Impacto

- **Código:** `src/knowledge/verdict.py` (modelo v2 em módulo puro), `src/knowledge/service.py` (passa a configuração), `src/config.py` e `.env.example` (variáveis `VERDICT_*` do v2), testes de `evidence-scoring`.
- **Contratos:** o `VerdictResult` e o detalhamento por tentativa não mudam de forma. `EvidenceBreakdown` ganha o campo `tipo` (variação, réplica, dataset, sessão, semente) para auditoria.
- **Schema:** nenhum. Os vereditos gravados nos nós `Hipotese` e `Descoberta` são recalculados pelas rotinas existentes na próxima execução do Curator (`recompute_hypothesis`, `recompute_discovery`).
- **Custo:** nenhuma chamada LLM; o cálculo continua sendo uma função pura de microssegundos.

## Aprovações necessárias

- Revisão do ADR 015 §9 pelo pesquisador (esta mudança só é implementada depois da aprovação).
- Nenhuma de schema, Dockerfile, `docker-compose.yml`, `AGENTS.md` ou exclusão de arquivo.

## Decisões do pesquisador (2026-10-18 e 2026-10-19)

- Falsa validação de no máximo 2 %, como média sobre a grade (ADR 025 §4.2).
- Concluir `funciona` exige **cerca de cinco variações com evolução** (e não três): o teto de 2 % não comporta três.
- Variante `completa2` no limiar atual 0,3.
- Variação pesa mais que réplica em outro nó: a mesma configuração confirmada em três ou cinco nós **não** conclui sozinha.
- Variação útil: superar o melhor anterior por qualquer quantidade.
