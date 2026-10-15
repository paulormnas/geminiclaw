# Bateria V18.6: modelos Gemini 4, GPT-6.1 e Claude 5.5 com juiz de família diferente (2026-10-14/15)

Tarefa: pipeline de classificação supervisionada do dataset Iris (`scripts/benchmark/task_iris.txt`), modo
autônomo, Raspberry Pi 5, `dev` em `6ad37bb`. Matriz `scripts/benchmark/matrix_modelos_v18_6.json`:
4 combinações × 3 repetições, com reset isolado dos bancos (`geminiclaw_bench`) e do Qdrant antes de cada
execução, `Problema` confirmado (acurácia ≥ 0,95, ganho mínimo 0,01 sobre o baseline da classe
majoritária) e teto de US$ 14 por provedor **por rodada**. Dados brutos em `~/bench/bateria_v18_6.json` no
Pi (artefatos por execução em `~/bench/bateria_v18_6.json.d/`).

| Combinação | Researcher, Developer, Summarizer | Validator |
|---|---|---|
| `controle-gemini-todos` | `google/gemini-4-argon` | `google/gemini-4-argon` (independência desligada) |
| `gemini-dev-sonnet-juiz` | `google/gemini-4-argon` | `anthropic/claude-sonnet-5-5` |
| `haiku-dev-sol-juiz` | `anthropic/claude-haiku-5-5` | `openai/gpt-6.1-sol` (esforço `low`) |
| `sonnet-dev-gemini-juiz` | `anthropic/claude-sonnet-5-5` | `google/gemini-4-argon` |

## Resultado em uma frase

As 12 execuções terminaram com `exit 0`. Com Gemini 4 Argon como Researcher/Developer, a acurácia validada
ficou entre 0,967 e 1,0 em todas as repetições. Com Claude como Researcher/Developer, as 6 execuções
fecharam em 4 a 12 minutos **sem treinar nenhum modelo** (acurácia nula, `sem_mede`), por uma cadeia de
regras de governança das hipóteses e não por limitação do modelo. Nenhuma execução fechou por
`solucao_encontrada`.

## Resumo por combinação (média ± desvio das 3 repetições)

| Combinação | Tempo (min) | Custo (US$) | Acurácia validada | Paradas |
|---|---|---|---|---|
| `controle-gemini-todos` | 48 ± 10 | 4,10 ± 0,86 | 0,989 ± 0,019 | `hipoteses_nao_testadas` ×2, `sem_caminhos_promissores` ×1 |
| `gemini-dev-sonnet-juiz` | 36 ± 6 | 3,27 ± 0,48 | 0,978 ± 0,019 | `sem_caminhos_promissores` ×2, `hipoteses_nao_testadas` ×1 |
| `haiku-dev-sol-juiz` | 9 ± 2 | 0,22 ± 0,07 | nula ×3 | `hipoteses_nao_testadas` ×3 |
| `sonnet-dev-gemini-juiz` | 5 ± 1 | 0,52 ± 0,10 | nula ×3 | `hipoteses_nao_testadas` ×3 |

O gasto por rodada ficou abaixo de US$ 5 por provedor. Uma tentativa da rodada 3 parou pelo teto de gasto
mensal do projeto Google (HTTP 429 `RESOURCE_EXHAUSTED`, fora do controle do benchmark); depois do aumento
do teto, a rodada 3 foi refeita do zero.

## Achados

1. **Planos esvaziados pela governança (combinações com Claude).** O Researcher declara hipóteses e as liga
   às subtarefas de treino; o pré-processamento e o baseline ficam sem `hypothesis_ref`, são retirados por
   `sem_hipotese`, e todas as dependentes caem como `depende_de_subtarefa_retirada`. Só a EDA executa; a
   sessão fecha por `hipoteses_nao_testadas`. Os prompts do Researcher e do Validator e o código descrevem a
   regra de três formas diferentes, e o Researcher não é informado das retiradas. O Gemini não esbarra na
   regra porque agrupa o trabalho em subtarefas grandes. Tratado no ADR 021.
2. **O Developer não recebe o contrato da subtarefa.** Nos registros de egresso, o Developer recebe o prompt
   de sistema e o enunciado, mas nunca `validation_criteria`, `expected_artifacts`, a hipótese, a tarefa
   original nem o critério do Problema. Daí as reprovações por "artefato ausente" e "métrica `accuracy`
   ausente em `metrics.json`", e os nomes variados de métrica nos nós `Resultado`. Tratado no ADR 022.
3. **Critério de solução nunca disparou.** Mesmo com acurácia validada 1,0, os vereditos das hipóteses
   ficaram entre 0,007 e 0,11, abaixo de `SOLUTION_MIN_VERDICT = 0,3`: com evidências perfeitas, uma
   evidência leva o veredito a no máximo `(1/3)² ≈ 0,11` (ADR 015 §9.5). Questão em aberto do ADR 021, para a
   calibração.
4. **Laço autônomo replaneja em erro de cota.** O 429 por teto de gasto mensal do Google foi tratado como
   falha de tarefa; o laço replanejou por 3h20 até o `timeout_seconds` do benchmark. Correção pendente
   (falhar na hora em erro de cota/gasto).
5. **Cadeia de proveniência "divergente" com retentativas.** 6 das 8 execuções com Gemini saíram com a
   cadeia `divergente` (0 órfãs). Nos registros, tentativas anteriores de uma subtarefa guardam o hash de um
   `metrics.json` que a tentativa seguinte sobrescreveu; hipótese a confirmar: a verificação conta isso como
   arquivo alterado. Correção pendente.
6. **Egresso acima de 2 MB sem recusa.** Não é violação: `EGRESS_SESSION_MAX_BYTES` limita só as saídas de
   execução novas (`saida_execucao`, de 3 KB a 0,4 MB nas execuções); o relatório compara o limite com o
   total, que inclui as instruções. A tabela do relatório será corrigida.
7. **Temperatura.** 10 das 12 execuções registraram o limite de temperatura do Pi (máximas de 79 a
   82 °C).

## Defeitos corrigidos durante a bateria

| PR | Defeito |
|---|---|
| #163 | O teto de orçamento por provedor valia para a bateria inteira, não por rodada |
| #164 | `gpt-6.1-sol` recusa `reasoning_effort=none` (HTTP 400); a matriz usa `low` |
| #165 | O Validator com `gpt-6.1-sol` devolve problemas como objetos; o laço autônomo quebrava em `"; ".join(issues)` |

## Relatório gerado (`scripts/benchmark/report.py`)

| Combinação | Rep. | Status | Tempo (s) | Tokens in | Tokens out | Subtarefas ok | Checklist | Acurácia | CPU sis. máx (%) | RAM máx (MB) | Temp máx (°C) | Throttling | Custo (USD) | Retentativas |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| controle-gemini-todos | 1 | exit 0 | 3382.4 | 1210232 | 294489 | 8/13 | 4/6 | 1.000 | 100.0 | 2448.9 | 78.75 | não | 5.0075 | 0 |
| gemini-dev-sonnet-juiz | 1 | exit 0 | 2556.4 | 1232818 | 163525 | 4/5 | 4/6 | 1.000 | 100.0 | 1983.8 | 80.4 | não | 3.8254 | 0 |
| haiku-dev-sol-juiz | 1 | exit 0 | 509.5 | 230450 | 72415 | 2/2 | 2/6 | - | 100.0 | 1904.8 | 81.5 | limite de temperatura ocorreu | 0.2168 | 0 |
| sonnet-dev-gemini-juiz | 1 | exit 0 | 251.6 | 124053 | 19804 | 2/2 | 2/6 | - | 100.0 | 1910.8 | 79.85 | limite de temperatura ocorreu | 0.4461 | 0 |
| gemini-dev-sonnet-juiz | 2 | exit 0 | 2094.5 | 638817 | 178996 | 7/7 | 4/6 | 0.967 | 100.0 | 1918.7 | 82.05 | limite de temperatura agora, limite de temperatura ocorreu | 3.0098 | 0 |
| haiku-dev-sol-juiz | 2 | exit 0 | 697.8 | 438027 | 115243 | 3/3 | 3/6 | - | 100.0 | 1945.8 | 80.4 | limite de temperatura ocorreu | 0.2846 | 0 |
| sonnet-dev-gemini-juiz | 2 | exit 0 | 332.3 | 177310 | 27963 | 2/2 | 2/6 | - | 100.0 | 1939.2 | 80.4 | limite de temperatura ocorreu | 0.6342 | 0 |
| controle-gemini-todos | 2 | exit 0 | 2194.4 | 864300 | 170789 | 6/6 | 5/6 | 0.967 | 100.0 | 2039.7 | 81.5 | limite de temperatura ocorreu | 3.3079 | 0 |
| gemini-dev-sonnet-juiz | 3 | exit 0 | 1867.3 | 723147 | 161602 | 6/6 | 4/6 | 0.967 | 100.0 | 2064.4 | 79.3 | limite de temperatura ocorreu | 2.9828 | 0 |
| haiku-dev-sol-juiz | 3 | exit 0 | 420.5 | 232472 | 56010 | 2/2 | 2/6 | - | 100.0 | 1994.0 | 80.4 | limite de temperatura ocorreu | 0.1443 | 0 |
| sonnet-dev-gemini-juiz | 3 | exit 0 | 283.7 | 127502 | 22079 | 2/2 | 3/6 | - | 100.0 | 1977.5 | 79.85 | limite de temperatura ocorreu | 0.4758 | 0 |
| controle-gemini-todos | 3 | exit 0 | 3140.6 | 1033924 | 222136 | 6/7 | 4/6 | 1.000 | 100.0 | 1966.7 | 80.95 | limite de temperatura ocorreu | 3.9786 | 0 |

### controle-gemini-todos
- Tokens por agente: developer 50.4% (39 chamadas), researcher 37.4% (34 chamadas), validator 10.2% (28 chamadas), summarizer 1.9% (2 chamadas)
- Mensagens entre agentes: 45 (eventos: {'knowledge_ingestion': 17, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 11, 'spawn': 32, 'complete': 33, 'plan_validation': 14, 'hypothesis_cycle': 14, 'plan_generated': 10, 'subtask_start': 12, 'sandbox_run': 20, 'subtask_review': 14, 'knowledge_recompute': 14, 'subtask_end': 14, 'resultado_sem_mede': 1, 'hypothesis_evaluation': 10, 'curator_run': 11, 'replan_triggered': 7, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 14/14 aprovadas
- Revisão de subtarefa: 7/14 aprovadas
  - reprovação: Artefato ausente no disco: model_comparison.csv; Artefato ausente no disco: model_comparison.png; Artefato ausente no disco: recomendacao_producao.md
  - reprovação: Artefato ausente no disco: model_comparison.csv; Artefato ausente no disco: model_comparison.png; Artefato ausente no disco: recomendacao_producao.md
  - reprovação: Artefato ausente no disco: model_comparison.csv; Artefato ausente no disco: model_comparison.png; Artefato ausente no disco: recomendacao_producao.md
  - reprovação: Artefato ausente no disco: model_comparison.csv; Artefato ausente no disco: model_comparison.png; Artefato ausente no disco: recomendacao_producao.md

### gemini-dev-sonnet-juiz
- Tokens por agente: developer 61.3% (41 chamadas), researcher 28.6% (26 chamadas), validator 8.8% (21 chamadas), summarizer 1.4% (2 chamadas)
- Mensagens entre agentes: 25 (eventos: {'knowledge_ingestion': 10, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 6, 'spawn': 18, 'complete': 19, 'plan_validation': 10, 'hypothesis_cycle': 7, 'plan_generated': 5, 'subtask_start': 4, 'sandbox_run': 16, 'subtask_review': 7, 'knowledge_recompute': 7, 'subtask_end': 7, 'hypothesis_evaluation': 5, 'curator_run': 6, 'replan_triggered': 3, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 7/10 aprovadas
- Revisão de subtarefa: 3/7 aprovadas
  - reprovação: Três tarefas gravam /outputs/metrics.json (eda_e_preprocessamento_iris, treinamento_e_avaliacao_modelos, validacao_comparativa_e_recomendacao), e as duas últimas exigem chaves como 'accuracy' com semâ; A tarefa 3 (validação) exige carregar 
  - reprovação: A tarefa 'validacao_comparativa_e_recomendacao' codifica no prompt resultados que ainda não foram observados (acurácia de teste 1.0, log-loss 0.0833, RF = 0.9667, 'empatado em CV') e pré-seleciona a R; Os hiperparâmetros usados na validação
  - reprovação: A tarefa 'avaliacao_ensemble_e_recomendacao_producao' fixa no prompt hiperparâmetros (LR C=10.0, RF n_estimators=50 e min_samples_split=5, SVC C=1.0) como 'melhores encontrados' em 'treinamento_e_aval; A chave 'accuracy' (e 'acuracia') não 
  - reprovação: Critério 'acurácia no teste da Regressão Logística >= 0.95': a métrica 'accuracy' não está em metrics.json (chaves existentes: ['dummybaseline_cv_acc_mean', 'dummybaseline_cv_acc_std', 'dummybaseline_; Critério 'ganho de acurácia sobre o Du

### haiku-dev-sol-juiz
- Tokens por agente: researcher 70.2% (7 chamadas), validator 13.9% (12 chamadas), developer 11.0% (2 chamadas), summarizer 5.0% (2 chamadas)
- Mensagens entre agentes: 6 (eventos: {'knowledge_ingestion': 4, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 2, 'spawn': 6, 'complete': 7, 'plan_validation': 4, 'hypothesis_cycle': 3, 'plan_generated': 1, 'subtask_start': 1, 'sandbox_run': 1, 'subtask_review': 1, 'knowledge_recompute': 1, 'subtask_end': 1, 'hypothesis_evaluation': 1, 'curator_run': 2, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 3/4 aprovadas
- Revisão de subtarefa: 1/1 aprovadas
  - reprovação: O StandardScaler é ajustado em todo o treino antes da validação cruzada e do GridSearchCV, contaminando os folds de validação. Faça essas etapas sobre os atributos originais usando Pipeline(StandardSc; O intervalo binomial de Wilson não é d

### sonnet-dev-gemini-juiz
- Tokens por agente: researcher 60.3% (4 chamadas), developer 18.8% (2 chamadas), validator 13.7% (10 chamadas), summarizer 7.1% (2 chamadas)
- Mensagens entre agentes: 5 (eventos: {'knowledge_ingestion': 4, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 2, 'spawn': 5, 'complete': 6, 'plan_validation': 3, 'hypothesis_cycle': 3, 'plan_generated': 1, 'subtask_start': 1, 'sandbox_run': 1, 'subtask_review': 1, 'knowledge_recompute': 1, 'subtask_end': 1, 'hypothesis_evaluation': 1, 'curator_run': 2, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 3/3 aprovadas
- Revisão de subtarefa: 1/1 aprovadas

### gemini-dev-sonnet-juiz
- Tokens por agente: developer 48.7% (27 chamadas), researcher 27.5% (14 chamadas), validator 19.6% (25 chamadas), summarizer 2.6% (2 chamadas), base 1.6% (3 chamadas)
- Mensagens entre agentes: 32 (eventos: {'knowledge_ingestion': 13, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 8, 'spawn': 23, 'complete': 24, 'plan_validation': 11, 'hypothesis_cycle': 9, 'plan_generated': 7, 'subtask_start': 6, 'sandbox_run': 14, 'subtask_review': 10, 'knowledge_recompute': 10, 'subtask_end': 10, 'hypothesis_evaluation': 7, 'curator_run': 8, 'replan_triggered': 4, 'memory_promotion': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 9/11 aprovadas
- Revisão de subtarefa: 6/10 aprovadas
  - reprovação: A tarefa 'otimizacao_hiperparametros_e_validacao_final' sobrescreve /outputs/metrics.json, /outputs/production_model.pkl e /outputs/final_recommendation_report.md, que já são produzidos por 'treinamen; A recomendação final de produção (sint
  - reprovação: Conflito de artefatos: treinamento_e_avaliacao_modelos, sintese_e_recomendacao_producao, validacao_separabilidade_eda, otimizacao_hiperparametros_e_validacao_final e consolidacao_final_pipeline_iris g; Dependências incoerentes e redundância
  - reprovação: Artefato ausente no disco: final_recommendation_report.md; Artefato ausente no disco: production_model.pkl
  - reprovação: Critério 1: validacao_separabilidade_eda/metrics.json não aparece na evidência em disco, então a correlação > 0.95 não foi confirmada nele.; Critério 2: não há evidência de que /outputs/metrics.json da raiz permaneceu sem sobrescrita.; O pe

### haiku-dev-sol-juiz
- Tokens por agente: researcher 47.7% (8 chamadas), developer 38.9% (9 chamadas), validator 9.9% (14 chamadas), summarizer 3.5% (2 chamadas)
- Mensagens entre agentes: 10 (eventos: {'knowledge_ingestion': 5, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 3, 'spawn': 9, 'complete': 10, 'plan_validation': 6, 'hypothesis_cycle': 4, 'plan_generated': 2, 'subtask_start': 2, 'sandbox_run': 5, 'subtask_review': 2, 'knowledge_recompute': 2, 'subtask_end': 2, 'hypothesis_evaluation': 2, 'curator_run': 3, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 4/6 aprovadas
- Revisão de subtarefa: 2/2 aprovadas
  - reprovação: As três tarefas de treinamento podem executar em paralelo e todas atualizam /outputs/metrics.json, sem mecanismo definido de sincronização. Isso pode sobrescrever métricas de outros modelos ou do base
  - reprovação: Subtarefa 'baseline_majoritario' possui 'hypothesis' vazia.; Subtarefa 'recomendacao_final' possui 'hypothesis' vazia.

### sonnet-dev-gemini-juiz
- Tokens por agente: researcher 55.3% (5 chamadas), developer 26.7% (4 chamadas), validator 13.2% (12 chamadas), summarizer 4.8% (2 chamadas)
- Mensagens entre agentes: 9 (eventos: {'knowledge_ingestion': 5, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 3, 'spawn': 7, 'complete': 8, 'plan_validation': 4, 'hypothesis_cycle': 4, 'plan_generated': 2, 'subtask_start': 1, 'sandbox_run': 2, 'subtask_review': 2, 'knowledge_recompute': 2, 'subtask_end': 2, 'hypothesis_evaluation': 2, 'curator_run': 3, 'replan_triggered': 1, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 4/4 aprovadas
- Revisão de subtarefa: 1/2 aprovadas
  - reprovação: Distribuição de classes registrada em eda_summary.json: O arquivo JSON salvo (`metrics.json`) registra apenas a quantidade de classes (`n_classes: 3`), mas não a distribuição das classes (ex.: 50 amos

### controle-gemini-todos
- Tokens por agente: developer 68.6% (39 chamadas), researcher 20.1% (14 chamadas), validator 8.4% (19 chamadas), summarizer 1.7% (2 chamadas), base 1.1% (3 chamadas)
- Mensagens entre agentes: 25 (eventos: {'knowledge_ingestion': 13, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 6, 'spawn': 20, 'complete': 21, 'plan_validation': 7, 'hypothesis_cycle': 7, 'plan_generated': 5, 'subtask_start': 5, 'sandbox_run': 25, 'subtask_review': 10, 'knowledge_recompute': 10, 'subtask_end': 10, 'hypothesis_evaluation': 5, 'curator_run': 6, 'replan_triggered': 3, 'memory_promotion': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 7/7 aprovadas
- Revisão de subtarefa: 5/10 aprovadas
  - reprovação: Critério 'Acurácia de teste >= 0.95 para ao menos um dos modelos não-lineares (SVC ou RandomForest) em /outputs/nonlinear_models_metrics.json': a métrica 'accuracy' não está em metrics.json (chaves ex; Critério 'Diferença de acurácia sobre 
  - reprovação: Critério 'Acurácia de teste da Regressão Logística >= 0.95 registrada em /outputs/linear_model_metrics.json': a métrica 'accuracy' não está em metrics.json (chaves existentes: ['baseline_cv_acuracia_m; Critério 'Diferença de acurácia em rel
  - reprovação: Critério 'Acurácia de teste >= 0.95 para ao menos um dos modelos não-lineares (SVC ou RandomForest) em /outputs/nonlinear_models_metrics.json': a métrica 'accuracy' não está em metrics.json (chaves ex; Critério 'Diferença de acurácia sobre 
  - reprovação: Critério 'Acurácia de teste da Regressão Logística >= 0.95 registrada em /outputs/linear_model_metrics.json': a métrica 'accuracy' não está em metrics.json (chaves existentes: ['baseline_cv_accuracy_m; Critério 'Diferença de acurácia em rel

### gemini-dev-sonnet-juiz
- Tokens por agente: developer 55.8% (26 chamadas), researcher 25.0% (14 chamadas), validator 15.5% (21 chamadas), summarizer 2.3% (2 chamadas), base 1.4% (3 chamadas)
- Mensagens entre agentes: 26 (eventos: {'knowledge_ingestion': 12, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 6, 'spawn': 21, 'complete': 22, 'plan_validation': 9, 'hypothesis_cycle': 7, 'plan_generated': 5, 'subtask_start': 5, 'sandbox_run': 15, 'subtask_review': 9, 'knowledge_recompute': 9, 'subtask_end': 9, 'hypothesis_evaluation': 5, 'curator_run': 6, 'replan_triggered': 3, 'memory_promotion': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 7/9 aprovadas
- Revisão de subtarefa: 4/9 aprovadas
  - reprovação: Quatro subtarefas gravam em /outputs/metrics.json. As duas tarefas de treino são independentes e podem rodar em paralelo, então uma sobrescreve a outra (condição de corrida). Cada tarefa deve gravar e; A tarefa de EDA salva os dados como '/
  - reprovação: A tarefa 'validacao_final_hipoteses_e_criterios' exige petal_length_width_corr >= 0.95 como critério de aceite, mas a correlação de Pearson entre comprimento e largura da pétala no Iris é ~0.962 no da; A tarefa 'avaliacao_comparativa_e_reco
  - reprovação: metrics.json não encontrado em /outputs/treinar_modelos_nao_lineares/ (existem: ['model_random_forest.pkl', 'model_svm.pkl', 'nonlinear_models_results.json', 'step_02.stderr.txt', 'step_04.stderr.txt'
  - reprovação: metrics.json não encontrado em /outputs/treinar_baseline_e_regressao_logistica/ (existem: ['logreg_results.json', 'model_logistic_regression.pkl', 'step_02.stderr.txt', 'step_04.stderr.txt', 'step_07.

### haiku-dev-sol-juiz
- Tokens por agente: developer 47.9% (5 chamadas), researcher 39.8% (4 chamadas), validator 8.8% (9 chamadas), summarizer 3.5% (2 chamadas)
- Mensagens entre agentes: 5 (eventos: {'knowledge_ingestion': 4, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 2, 'spawn': 5, 'complete': 6, 'plan_validation': 3, 'hypothesis_cycle': 3, 'plan_generated': 1, 'subtask_start': 1, 'sandbox_run': 2, 'subtask_review': 1, 'knowledge_recompute': 1, 'subtask_end': 1, 'hypothesis_evaluation': 1, 'curator_run': 2, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 3/3 aprovadas
- Revisão de subtarefa: 1/1 aprovadas

### sonnet-dev-gemini-juiz
- Tokens por agente: researcher 59.7% (4 chamadas), developer 19.2% (2 chamadas), validator 14.6% (10 chamadas), summarizer 6.5% (2 chamadas)
- Mensagens entre agentes: 5 (eventos: {'knowledge_ingestion': 4, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 2, 'spawn': 5, 'complete': 6, 'plan_validation': 3, 'hypothesis_cycle': 3, 'plan_generated': 1, 'subtask_start': 1, 'sandbox_run': 1, 'subtask_review': 1, 'knowledge_recompute': 1, 'subtask_end': 1, 'hypothesis_evaluation': 1, 'curator_run': 2, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 3/3 aprovadas
- Revisão de subtarefa: 1/1 aprovadas

### controle-gemini-todos
- Tokens por agente: developer 50.4% (27 chamadas), researcher 42.2% (34 chamadas), validator 6.2% (16 chamadas), summarizer 1.2% (1 chamadas)
- Mensagens entre agentes: 27 (eventos: {'knowledge_ingestion': 12, 'session_start': 1, 'input_index': 1, 'triage_decision': 1, 'curator_suggestions': 7, 'spawn': 21, 'complete': 22, 'plan_validation': 8, 'hypothesis_cycle': 8, 'plan_generated': 6, 'subtask_start': 6, 'sandbox_run': 16, 'subtask_review': 9, 'knowledge_recompute': 9, 'subtask_end': 9, 'hypothesis_evaluation': 6, 'curator_run': 7, 'replan_triggered': 4, 'hipoteses_sem_tentativa': 1, 'exploration_stop': 1, 'session_closing': 1})
- Validação de plano: 8/8 aprovadas
- Revisão de subtarefa: 4/9 aprovadas
  - reprovação: Critério 'acuracia >= 0.95 no conjunto de teste para LogisticRegression' avaliado contra metrics.json: 'acuracia' valor real = 0.9333333333333333, threshold >= 0.95 -> não atendido.
  - reprovação: Critério 'acuracia >= 0.95 no conjunto de teste para RandomForestClassifier (ou documentação exata da divergência caso fique em 0.9333 por 1 amostra em n=30)' avaliado contra metrics.json: 'acuracia' 
  - reprovação: Artefato ausente no disco: confusion_matrices_comparison.png; Artefato ausente no disco: model_comparison_chart.png; Artefato ausente no disco: rf_validation_metrics.json
  - reprovação: Critério 'acuracia >= 0.95 registrada em metrics.json (chave 'acuracia') no conjunto de teste holdout para o modelo otimizado via CV no treino': a métrica 'accuracy' não está em metrics.json (chaves e; Critério 'Diferença de acurácia em rel

### Modelos e versões
| Combinação | Rep. | Papel | Modelo pedido | Versão efetiva | Data | Preço (US$/1M: entrada/saída/cache) |
|---|---|---|---|---|---|---|
| controle-gemini-todos | 1 | base | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 1 | developer | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 1 | validator | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 1 | researcher | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 1 | summarizer | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 1 | base | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 1 | developer | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 1 | validator | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-14 | 2.0/10.0/0.2 |
| gemini-dev-sonnet-juiz | 1 | researcher | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 1 | summarizer | google/gemini-4-argon | gemini-4-argon | 2026-10-14 | 2.0/10.0/0.1, até 2026-11-30 |
| haiku-dev-sol-juiz | 1 | base | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 1 | developer | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 1 | validator | openai/gpt-6.1-sol | gpt-6.1-sol | 2026-10-15 | 2.0/10.0/0.1 |
| haiku-dev-sol-juiz | 1 | researcher | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 1 | summarizer | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| sonnet-dev-gemini-juiz | 1 | base | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 1 | developer | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 1 | validator | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| sonnet-dev-gemini-juiz | 1 | researcher | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 1 | summarizer | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| gemini-dev-sonnet-juiz | 2 | base | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 2 | developer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 2 | validator | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| gemini-dev-sonnet-juiz | 2 | researcher | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 2 | summarizer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| haiku-dev-sol-juiz | 2 | base | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 2 | developer | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 2 | validator | openai/gpt-6.1-sol | gpt-6.1-sol | 2026-10-15 | 2.0/10.0/0.1 |
| haiku-dev-sol-juiz | 2 | researcher | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 2 | summarizer | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| sonnet-dev-gemini-juiz | 2 | base | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 2 | developer | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 2 | validator | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| sonnet-dev-gemini-juiz | 2 | researcher | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 2 | summarizer | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| controle-gemini-todos | 2 | base | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 2 | developer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 2 | validator | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 2 | researcher | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 2 | summarizer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 3 | base | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 3 | developer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 3 | validator | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| gemini-dev-sonnet-juiz | 3 | researcher | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| gemini-dev-sonnet-juiz | 3 | summarizer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| haiku-dev-sol-juiz | 3 | base | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 3 | developer | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 3 | validator | openai/gpt-6.1-sol | gpt-6.1-sol | 2026-10-15 | 2.0/10.0/0.1 |
| haiku-dev-sol-juiz | 3 | researcher | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| haiku-dev-sol-juiz | 3 | summarizer | anthropic/claude-haiku-5-5 | claude-haiku-5-5 | 2026-10-15 | 0.1/0.5/0.01 |
| sonnet-dev-gemini-juiz | 3 | base | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 3 | developer | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 3 | validator | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| sonnet-dev-gemini-juiz | 3 | researcher | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| sonnet-dev-gemini-juiz | 3 | summarizer | anthropic/claude-sonnet-5-5 | claude-sonnet-5-5 | 2026-10-15 | 2.0/10.0/0.2 |
| controle-gemini-todos | 3 | base | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 3 | developer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 3 | validator | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 3 | researcher | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |
| controle-gemini-todos | 3 | summarizer | google/gemini-4-argon | gemini-4-argon | 2026-10-15 | 2.0/10.0/0.1, até 2026-11-30 |

| Combinação | Repetições | Tempo (s) | Custo (USD) | Acurácia validada | Acurácia nula | Subtarefas aprovadas | Motivos de parada |
|---|---|---|---|---|---|---|---|
| controle-gemini-todos | 3 | 2905.800 ± 627.841 [2194.400, 3382.400] | 4.098 ± 0.856 [3.308, 5.008] | 0.989 ± 0.019 [0.967, 1.000] | 0 | 6.667 ± 1.155 [6.000, 8.000] | hipoteses_nao_testadas: 2, sem_caminhos_promissores: 1 |
| gemini-dev-sonnet-juiz | 3 | 2172.733 ± 351.148 [1867.300, 2556.400] | 3.273 ± 0.479 [2.983, 3.825] | 0.978 ± 0.019 [0.967, 1.000] | 0 | 5.667 ± 1.528 [4.000, 7.000] | hipoteses_nao_testadas: 1, sem_caminhos_promissores: 2 |
| haiku-dev-sol-juiz | 3 | 542.600 ± 141.582 [420.500, 697.800] | 0.215 ± 0.070 [0.144, 0.285] | - | 3 | 2.333 ± 0.577 [2.000, 3.000] | hipoteses_nao_testadas: 3 |
| sonnet-dev-gemini-juiz | 3 | 289.200 ± 40.630 [251.600, 332.300] | 0.519 ± 0.101 [0.446, 0.634] | - | 3 | 2.000 ± 0.000 [2.000, 2.000] | hipoteses_nao_testadas: 3 |

### Paradas por hipóteses não testadas (parada de pesquisa, não erro)
- controle-gemini-todos (repetição 1)
- gemini-dev-sonnet-juiz (repetição 1)
- haiku-dev-sol-juiz (repetição 1)
- sonnet-dev-gemini-juiz (repetição 1)
- haiku-dev-sol-juiz (repetição 2)
- sonnet-dev-gemini-juiz (repetição 2)
- haiku-dev-sol-juiz (repetição 3)
- sonnet-dev-gemini-juiz (repetição 3)
- controle-gemini-todos (repetição 3)

| Combinação | Rep. | Duração (min) | Nós do grafo | Pontos do Qdrant | agent_events | egress_log | execution_records | Tamanho do banco (MB) |
|---|---|---|---|---|---|---|---|---|
| controle-gemini-todos | 1 | 56.373 | +156 (2.77/min) | +27 (0.48/min) | +240 (4.26/min) | +104 (1.84/min) | +40 (0.71/min) | +2.4 |
| gemini-dev-sonnet-juiz | 1 | 42.607 | +126 (2.96/min) | +21 (0.49/min) | +136 (3.19/min) | +92 (2.16/min) | +32 (0.75/min) | +2.1 |
| haiku-dev-sol-juiz | 1 | 8.492 | +54 (6.36/min) | +41 (4.83/min) | +41 (4.83/min) | +26 (3.06/min) | +2 (0.24/min) | +1.3 |
| sonnet-dev-gemini-juiz | 1 | 4.193 | +19 (4.53/min) | +13 (3.1/min) | +38 (9.06/min) | +19 (4.53/min) | +2 (0.48/min) | +0.8 |
| gemini-dev-sonnet-juiz | 2 | 34.908 | +145 (4.15/min) | +20 (0.57/min) | +170 (4.87/min) | +72 (2.06/min) | +28 (0.8/min) | +2.1 |
| haiku-dev-sol-juiz | 2 | 11.63 | +54 (4.64/min) | +34 (2.92/min) | +63 (5.42/min) | +34 (2.92/min) | +10 (0.86/min) | +1.4 |
| sonnet-dev-gemini-juiz | 2 | 5.538 | +29 (5.24/min) | +16 (2.89/min) | +54 (9.75/min) | +24 (4.33/min) | +4 (0.72/min) | +0.9 |
| controle-gemini-todos | 2 | 36.573 | +241 (6.59/min) | +18 (0.49/min) | +159 (4.35/min) | +78 (2.13/min) | +50 (1.37/min) | +2.3 |
| gemini-dev-sonnet-juiz | 3 | 31.122 | +102 (3.28/min) | +21 (0.67/min) | +149 (4.79/min) | +67 (2.15/min) | +30 (0.96/min) | +1.9 |
| haiku-dev-sol-juiz | 3 | 7.008 | +28 (4.0/min) | +20 (2.85/min) | +39 (5.56/min) | +21 (3.0/min) | +4 (0.57/min) | +1.0 |
| sonnet-dev-gemini-juiz | 3 | 4.728 | +12 (2.54/min) | +6 (1.27/min) | +38 (8.04/min) | +19 (4.02/min) | +2 (0.42/min) | +0.8 |
| controle-gemini-todos | 3 | 52.343 | +125 (2.39/min) | +21 (0.4/min) | +156 (2.98/min) | +81 (1.55/min) | +32 (0.61/min) | +2.1 |

| Combinação | Vetores novos (Qdrant) | Nós do projeto | Arestas do projeto | Nós por rótulo | Execuções registradas | Registros de egresso | Auditoria do grafo |
|---|---|---|---|---|---|---|---|
| controle-gemini-todos | 27 (knowledge_nodes: +27) | 158 | 191 | Abordagem 14, Decisao 7, Experimento 14, Hipotese 6, Problema 1, Projeto 1, Resultado 114, Sessao 1 | 40 | 104 | 46 |
| gemini-dev-sonnet-juiz | 21 (knowledge_nodes: +21) | 128 | 146 | Abordagem 11, Decisao 6, Experimento 7, Hipotese 4, Problema 1, Projeto 1, Resultado 97, Sessao 1 | 32 | 92 | 32 |
| haiku-dev-sol-juiz | 41 (knowledge_nodes: +41) | 56 | 58 | Abordagem 26, Decisao 10, Experimento 1, Hipotese 5, Problema 1, Projeto 1, Resultado 11, Sessao 1 | 2 | 26 | 47 |
| sonnet-dev-gemini-juiz | 13 (knowledge_nodes: +13) | 21 | 23 | Abordagem 8, Decisao 3, Experimento 1, Hipotese 2, Problema 1, Projeto 1, Resultado 4, Sessao 1 | 2 | 19 | 16 |
| gemini-dev-sonnet-juiz | 20 (knowledge_nodes: +20) | 147 | 166 | Abordagem 12, Decisao 4, Experimento 10, Hipotese 4, Problema 1, Projeto 1, Resultado 114, Sessao 1 | 28 | 72 | 32 |
| haiku-dev-sol-juiz | 34 (knowledge_nodes: +34) | 56 | 63 | Abordagem 20, Decisao 7, Experimento 2, Hipotese 7, Problema 1, Projeto 1, Resultado 17, Sessao 1 | 10 | 34 | 40 |
| sonnet-dev-gemini-juiz | 16 (knowledge_nodes: +16) | 31 | 35 | Abordagem 10, Decisao 4, Experimento 2, Hipotese 2, Problema 1, Projeto 1, Resultado 10, Sessao 1 | 4 | 24 | 19 |
| controle-gemini-todos | 18 (knowledge_nodes: +18) | 243 | 267 | Abordagem 10, Decisao 5, Experimento 10, Hipotese 3, Problema 1, Projeto 1, Resultado 212, Sessao 1 | 50 | 78 | 33 |
| gemini-dev-sonnet-juiz | 21 (knowledge_nodes: +21) | 104 | 123 | Abordagem 11, Decisao 6, Experimento 9, Hipotese 4, Problema 1, Projeto 1, Resultado 71, Sessao 1 | 30 | 67 | 33 |
| haiku-dev-sol-juiz | 20 (knowledge_nodes: +20) | 30 | 33 | Abordagem 11, Decisao 4, Experimento 1, Hipotese 5, Problema 1, Projeto 1, Resultado 6, Sessao 1 | 4 | 21 | 25 |
| sonnet-dev-gemini-juiz | 6 (knowledge_nodes: +6) | 14 | 14 | Abordagem 3, Decisao 1, Experimento 1, Hipotese 2, Problema 1, Projeto 1, Resultado 4, Sessao 1 | 2 | 19 | 9 |
| controle-gemini-todos | 21 (knowledge_nodes: +21) | 127 | 149 | Abordagem 10, Decisao 6, Experimento 9, Hipotese 5, Problema 1, Projeto 1, Resultado 94, Sessao 1 | 32 | 81 | 34 |

| Combinação | Egresso (bytes) | Chamadas de busca | Cadeia de execuções | Números res/calc/src | Não verificados | Afirmações (suportada/total) | Planos reprovados | Custo (USD) | CPU média (%) |
|---|---|---|---|---|---|---|---|---|---|
| controle-gemini-todos | 3942301 | 1 | divergente | 47/0/0 | 42 | 28/40 | 0 | 5.007506 | 1.8 |
| gemini-dev-sonnet-juiz | 3895423 | 2 | divergente | 49/0/0 | 9 | 26/41 | 3 | 3.825376 | 0.4 |
| haiku-dev-sol-juiz | 456575 | 3 | integra | 8/0/0 | 13 | 15/57 | 1 | 0.216762 | 0.0 |
| sonnet-dev-gemini-juiz | 236865 | 1 | integra | 7/0/0 | 12 | 12/22 | 0 | 0.446146 | 0.0 |
| gemini-dev-sonnet-juiz | 2020799 | 1 | divergente | 42/1/0 | 9 | 29/49 | 2 | 3.009754 | 0.5 |
| haiku-dev-sol-juiz | 818594 | 1 | integra | 16/0/0 | 32 | 19/61 | 2 | 0.284571 | 0.0 |
| sonnet-dev-gemini-juiz | 336205 | 1 | integra | 8/0/0 | 15 | 20/26 | 0 | 0.63425 | 3.8 |
| controle-gemini-todos | 2804623 | 1 | divergente | 45/0/0 | 9 | 19/31 | 0 | 3.307947 | 2.8 |
| gemini-dev-sonnet-juiz | 2258892 | 1 | divergente | 54/4/0 | 10 | 33/54 | 2 | 2.982788 | 3.0 |
| haiku-dev-sol-juiz | 434263 | 1 | integra | 0/0/0 | 24 | 5/55 | 0 | 0.144327 | 0.0 |
| sonnet-dev-gemini-juiz | 245663 | 1 | integra | 5/0/0 | 9 | 11/24 | 0 | 0.475794 | 0.0 |
| controle-gemini-todos | 3384652 | 3 | integra | 28/2/0 | 22 | 9/16 | 0 | 3.978619 | 0.0 |
