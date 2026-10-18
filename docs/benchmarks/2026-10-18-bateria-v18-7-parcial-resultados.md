# Bateria parcial da V18.7: validação das tarefas que dependiam de LLMs reais (2026-10-18)

Tarefa: pipeline de classificação do Iris (`scripts/benchmark/task_iris.txt`), modo `auto`, Raspberry Pi 5, `dev` em
`1ff38d1` (V18.7 com as seções 0 a 10 de `v18.7-exploration-limits`). Matriz derivada de
`scripts/benchmark/matrix_modelos_v18_6.json` (teto `SESSION_MAX_COST_USD=10`), **uma repetição por combinação**, com
reset isolado do banco `geminiclaw_bench` e do Qdrant. Não é a bateria completa: o objetivo foi fechar as tarefas
abertas por falta de execução com modelos reais, não comparar modelos. Dados brutos em `~/bench/bateria_v18_7*.json` no Pi.

| Combinação | Resultado | Tempo | Custo (US$) |
|---|---|---|---|
| `gemini-dev-sonnet-juiz` | `limite_cota_provedor` (exit 3): teto de gasto do projeto Google esgotado (HTTP 429) | 19 min | 1,87 |
| `haiku-dev-sol-juiz` | `erro` (exit 1): disjuntor de zero progresso; 8 experimentos, 28 resultados, 5 de 7 subtarefas aprovadas; acurácia validada nula (`sem_mede`) | 14 min | 0,27 |
| `sonnet-dev-sol-juiz` (nova, sem Google) | `solucao_encontrada` (exit 0): acurácia validada 0,975 (alvo 0,95), cadeia de proveniência `integra`, 6 de 7 subtarefas aprovadas | 14 min | 2,10 |

`sonnet-dev-gemini-juiz` e `controle-gemini-todos` não rodaram: dependem do Google, cujo projeto estava sem cota.

## O que a bateria confirma

1. **Nenhuma parada por `limite_ciclos` ou `limite_execucoes`** (`v18.7-exploration-limits`, 10.4): as três execuções
   fecharam por outros motivos.
2. **`solucao_encontrada` com acurácia validada no alvo** (10.4): `sonnet-dev-sol-juiz`. Na V18.6 nenhuma das 12
   execuções fechou assim (vereditos abaixo de `SOLUTION_MIN_VERDICT`); o critério por tipo de objetivo, sem filtro de
   veredito, resolveu.
3. **Cota esgotada fecha a sessão em minutos** (`v18.7-benchmark-fixes`, 6.3): o primeiro 429 do Google foi às
   23:55:18 e o fechamento por `limite_cota_provedor` às 23:56:42, com o evento `cota_provedor_esgotada`
   (`google/gemini-4-argon`), em vez do replanejamento por 3h20 da V18.6.
4. **Sem cadeia de proveniência `divergente`** (6.3): `sonnet-dev-sol-juiz` saiu `integra` (0 órfãs, 0 motivos).
5. **Os Claude agora treinam modelos.** Na V18.6 as combinações com Claude fechavam em 4 a 12 minutos sem treinar
   nenhum modelo (`hipoteses_nao_testadas`); agora registram experimentos e resultados.

## O que a bateria expõe (não regressões da V18.7)

1. **Contrato da subtarefa (ADR 022, `v18.7-subtask-contract`, não iniciada).** Na `haiku-dev-sol-juiz`,
   `treinar_regressao_logistica` falhou em ciclos seguidos porque `/outputs/baseline_metrics.json` e
   `y_train.csv` das dependências não estavam no sandbox da subtarefa; o disjuntor fechou a sessão com `erro`.
2. **Nomes de métrica.** Na mesma execução, 28 `Resultado` e nenhum `MEDE` para a métrica aprovada (`sem_mede`): o
   Developer grava chaves como `test_accuracy`, e a chave exigida pelo contrato (ADR 022, "chaves de métrica exigidas") ainda não é
   entregue a ele. Na `sonnet-dev-sol-juiz`, 4 dos 58 resultados mediram a métrica, o bastante para validar a acurácia.
3. **Teto de gasto do Google.** Bloqueia as combinações com Gemini até o limite do projeto ser elevado.

## Limites da evidência

Uma repetição por combinação não ordena modelos (a variância já foi medida na V18.6). A bateria completa, com
repetições e as combinações do Google, continua pendente de cota.
