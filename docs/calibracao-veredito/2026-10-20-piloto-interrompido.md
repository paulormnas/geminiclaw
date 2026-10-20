# Piloto da etapa 3 interrompido (2026-10-20)

Pergunta: o piloto (`plano_piloto.json`, Validator `gpt-6-luna` em `xhigh`) produziu dados utilizáveis para a bateria?
Resposta: não. Foi interrompido pelo pesquisador depois de US$ 8,34 e mais de 4 horas, com dois defeitos que
distorceriam a taxa de indecisão que a bateria mede.

## O que rodou

| Exploração | Fim | US$ | Sessões |
|---|---|---|---|
| haiku-dev-luna-juiz / P | `limite_tokens`, censurada | 1,94 | 3 |
| sonnet-dev-luna-juiz / P | falha (revisão reprovou o `metrics.json`) | 2,02 | 1 |
| haiku-dev-luna-juiz / T | `limite_tokens`, censurada | 2,56 | 4 |
| sonnet-dev-luna-juiz / T | interrompida | — | — |

Uma primeira rodada (2026-10-20, antes da recarga de crédito) gastou US$ 8,34 em P e esbarrou em
`limite_cota_provedor` nas demais; seus diretórios foram guardados fora do repositório.

## Onde o tempo foi (Haiku em T, 308 min)

| Atividade | Min | Chamadas |
|---|---|---|
| Researcher gerando plano | 143 | 181 |
| Validator validando plano | 131 | 133 |
| Sandbox, revisão de subtarefa e curator | ≈ 20 | 28 subtarefas |

Foram 43 planos e 90 reprovações em 133 validações (75 do Validator LLM, 15 determinísticas). Um plano chegou a 14
rodadas. As sessões 3 e 4 gastaram cerca de 3M tokens cada sem nenhum experimento novo. As objeções do Validator LLM
eram, em geral, metodológicas e legítimas (vazamento de teste na validação cruzada aninhada, atributo de `delta_min`
sem fonte), mas mudavam a cada plano e não repetiam a assinatura, de modo que o limite `PLAN_REJECTION_STALL_LIMIT`
nunca as tornava consultivas.

## Por que o veredito ficou em 0,0

Dos 28 experimentos do Haiku em T, 22 terminaram em `falha`, 19 com `causa_falha = ambigua` e
`assinatura_falha = sem_metricas`. O plano declarava `metrics_<tarefa>.json` em `expected_artifacts` (nomes
únicos evitam a reprovação `colisao_artefato`), o Developer gravava esse nome, e a ingestão só lia `metrics.json`
(`src/knowledge/ingestion_io.py`). Os números existiam e estavam corretos. Falha ambígua pesa zero na equação v2,
então certeza 0 e veredito 0 eram o comportamento correto para uma evidência que nunca chegou a ela. A equação não
foi alterada; a taxa de ambiguidade que sobrar depois das correções diz se `lambda_ambiguous` precisa de revisão.

## Correções (PR `fix/contrato-metricas-e-laco-de-planejamento`)

1. Reprovação determinística do plano para `metrics_*.json` e `params_*.json` em `expected_artifacts`
   (`artefato_de_metrica_fora_do_contrato`, com a correção na mensagem) e o esquema do plano passa a dizer
   `metrics.json` e `params.json`. A ingestão lê o único `metrics_*.json` da pasta quando falta o `metrics.json`
   (avisa; dois candidatos continuam ausentes).
2. `hypothesis` e `scientific_rationale` vazios deixam de reprovar em subtarefas de papel `preparacao` ou
   `referencia`.
3. `PLAN_LLM_REJECTION_LIMIT` (padrão 3): depois de 3 reprovações do Validator LLM no mesmo planejamento, a seguinte
   vira consultiva (aprova com avisos). Métricas e objetivo seguem exigidos; reprovação determinística não é afetada.

## Verificação antes de retomar

`plano_verificacao.json`: Haiku, P e T, uma exploração cada, teto US$ 2 por exploração (máximo US$ 4). Critérios de
leitura: fração de experimentos `sem_metricas`, rodadas de plano por plano aprovado, tempo em planejamento sobre o
tempo total e se ao menos uma hipótese ganha veredito diferente de 0.
