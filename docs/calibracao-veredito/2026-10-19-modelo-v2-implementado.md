# Modelo v2 do veredito implementado no sistema

**Data:** 2026-10-19 · **ADR:** [025](../decisions/adr_025_calibracao_do_veredito.md) · **Mudança:** [`v18.8-verdict-calibration`](../../openspec/changes/v18.8-verdict-calibration/proposal.md) · **Custo:** nenhuma chamada de LLM

## 1. O que entrou

- `compute_verdict` calcula o **modelo v2** por padrão (`VERDICT_MODEL=v2`); `VERDICT_MODEL=adr015` restaura a equação anterior. O modelo é a variante `completa2` do [laboratório](2026-10-18-etapa-2b-criterio-de-2-por-cento.md): independência por tipo de evidência, variação útil, penalidade de busca acumulada, alvo exigido com baseline, folga com piso e evidência contrária pesando cheio. Os valores estão em `src/config.py` e `.env.example`.
- `KNOWLEDGE_SHORTCUT_MIN_VERDICT` passou de 0,1 para **0,3**. No modelo v2, o limiar 0,1 deixaria 33 % das hipóteses sem efeito virarem atalhos de conhecimento; em 0,3 a falsa validação medida é de 1,1 %.
- `Hipotese` e `Descoberta` registram `modelo_veredito` a cada recálculo.
- Um teste de equivalência exige que o sistema reproduza o laboratório (`completa2`) em 46 cenários e em 30 sequências simuladas (diferença ≤ 10⁻¹²); outro roda a simulação reduzida e confere o teto de 2 %.

## 2. Repetição sobre os grafos arquivados (tarefa 5.2)

`replay` do laboratório sobre os 18 grafos de `~/bench/` (30 hipóteses com tentativas), commit desta mudança:

| Variante | Hipóteses ≥ 0,1 | ≥ 0,3 | ≥ 0,5 | Maior |
|---|---|---|---|---|
| Equação anterior (`atual`) | 6 | 0 | 0 | 0,111 |
| Modelo v2 (`completa2`) | 9 | 0 | 0 | 0,175 |

Nenhuma hipótese dessas baterias chega a 0,3 mesmo no modelo v2, porque cada uma tem no máximo duas evidências positivas (21 positivas em 63 tentativas; a maioria das tentativas são falhas ambíguas). Isso é esperado e coerente com a regra decidida: concluir `funciona` exige cerca de cinco variações com evolução. O modelo v2 não substitui a evidência; ele deixa de desperdiçá-la. A próxima bateria precisa produzir mais variações por hipótese para o veredito concluir; essa é a pergunta das etapas 3 e 4 do ADR 025.

## 3. O que falta

- Etapa 3 (sessões controladas com efeito conhecido, ADR 025 §3) e etapa 4 (bateria no Raspberry Pi), que reconferem o teto de 2 % com dados que o ajuste não viu.
- Caso conhecido que o modelo v2 não resolve: uma falha de abordagem reproduzida em quatro configurações dá veredito −0,14 e fica indecisa (cenário N-abordagem-4 do catálogo).
