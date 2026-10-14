# Design: v18.6-hypothesis-closure

## 1. Classificação da reprovação

`ReviewResult` ganha `outcome: Literal["aprovado", "reprovado", "resultado_negativo"]`.

`review_result` devolve `resultado_negativo` quando **todas** as condições valem:

1. a subtarefa tem `hypothesis_id` resolvido (`v18-hypothesis-loop`);
2. todos os artefatos esperados foram resolvidos (nenhum `missing`);
3. as reprovações vieram só de comparações determinísticas de `_evaluate_metric_criteria`, com a
   métrica presente e numérica (nunca "métrica ausente", "não numérico" ou "indecidido",
   `v18.6-review-evidence` §3);
4. os critérios restantes, se houver, foram aprovados pelo revisor LLM ou não existem.

Em qualquer outro caso, a reprovação continua `reprovado`, como hoje. `NEGATIVE_RESULT_AS_PROGRESS`
(padrão `true`); com `false`, `outcome` nunca é `resultado_negativo`.

## 2. Efeitos no laço

### 2.1 DAG

- Estado novo `concluded_negative` em `dag_state[task]["status"]`.
- A subtarefa não é repetida (as retentativas de `SESSION_MAX_TASK_RETRIES` servem para corrigir
  formato ou erro, não para mudar um número).
- Para dependências, `concluded_negative` conta como concluída: a subtarefa de comparação que
  depende de "treinar regressão logística" roda e recebe o resultado negativo no contexto.
- `AgentResult.status` fica `"success"` com `response["outcome"] = "resultado_negativo"`, para
  que o relatório, a ingestão e as contagens existentes não confundam com erro.

### 2.2 Disjuntor de progresso

`CycleProgress.succeeded` passa a incluir as subtarefas `concluded_negative`. Um ciclo que só
produziu resultados negativos novos é progresso.

### 2.3 Feedback do próximo ciclo

O feedback ao Researcher (`execution_feedback`) ganha uma linha por resultado negativo:

```
Resultado negativo: h2 (subtarefa treinar_regressao_logistica): acuracia = 0.933 < 0.95. A hipótese
recebeu evidência contra ela. Não repita a mesma configuração; proponha outra abordagem ou encerre a hipótese.
```

Os números vêm de `metrics.json` (`saida_execucao`, já permitido pelo filtro de localidade).

## 3. Ingestão

- `_experiment_status` devolve `"sucesso"` quando `sub.review_outcome == "resultado_negativo"`.
- `Experimento.criterio_plano_atendido = false` nesse caso, e `true` quando a revisão aprovou com
  critério quantitativo. Sem critério quantitativo, a propriedade não é gravada.
- O `Resultado` da métrica avaliada já fica `validado` (`_status_validacao`,
  `src/knowledge/ingestion.py:857`); com o `Experimento` em `sucesso`, `_attempt_from` cria uma
  tentativa `resultado`, e `compute_verdict` a compara com o `alvo` e o `delta_min` do `Problema`.
- **Sinal `sem_mede`:** depois de `_mede`, se o nome base do `Resultado` (`split_metric_name`) é
  igual ao nome ou a um sinônimo da `Metrica` do `Problema` e a aresta não foi criada, a ingestão
  registra o evento `resultado_sem_mede` com o nome e o motivo (`metrica_nao_aprovada`,
  `qualificador_excluido`, `resolucao_falhou`).

## 4. Conferência do veredito no início da sessão

Antes do primeiro planejamento, com projeto ativo:

1. `ServicoConhecimento.criterion_for(problema)` resolve a `Metrica`.
2. Se a `Metrica` não tem status aprovado (`aprovado` no vocabulário), ou se `criterion_for` falha:
   - evento `veredito_indisponivel` com `motivo` e a correção ("rode `scripts/seed_vocabulary.py`"
     ou "aprove a métrica com `geminiclaw vocab ...`");
   - aviso no banner;
   - modo `auto`: a sessão termina com `erro` antes de planejar (o critério de solução depende do
     veredito); modos `assisted` e `semi`: a sessão segue com o aviso.

## 5. Critério `sem_caminhos_promissores`

`ExplorationDriver.has_open_paths(in_plan)` passa a considerar também as hipóteses **do plano**:
há caminho aberto se alguma hipótese `em_teste` do projeto tem `n_tentativas == 0` e não foi
retirada pela governança (motivos de `retiradas_por_motivo`). O limite atual de dois ciclos
ociosos (`idle_cycles < 2`) continua. Quando ele estoura com hipótese sem tentativa, a sessão fecha
com `erro` e a mensagem "hipóteses sem tentativa após N ciclos ociosos: h1, h2", sem membro novo
em `StopReason` (alternativa na questão §8.2).

O feedback do ciclo ocioso cita as hipóteses sem tentativa por `ref` e enunciado.

## 6. Evidência das afirmações do relatório

### 6.1 Tabela de resultados

`claims/evidence.py` ganha `session_results_item(session_id)`: um `EvidenceItem` com a tabela dos
`Resultado`s da sessão com `status_validacao` em (`validado`, `divergente_documentado`): nome
original, qualificador, valor, subtarefa e `exec_id`. Origem `GRAFO`.

- O construtor de evidência da conclusão do relatório inclui esse item para **toda** frase que não
  tem código de referência.
- O tamanho segue `CLAIM_EVIDENCE_MAX_CHARS` (divisão em lotes já existente).

### 6.2 `afirmacoes.json` sempre gravado

Quando há `relatorio_final.md`, o fechamento grava `afirmacoes.json`, mesmo sem afirmações, com
`{"afirmacoes": [], "motivo_vazio": "<motivo>"}`. Motivos: `sem_conclusoes`,
`verificacao_desligada`, `orcamento_esgotado`, `falha_verificador`. A tarefa 6.1 investiga por que
a sessão do Sonnet não gravou o arquivo e registra a causa no PR.

## 7. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador e loop | Estado `concluded_negative`; disjuntor e fechamento por falta de caminhos mudam |
| Agentes e prompts | Feedback novo ao Researcher; nenhuma instrução de sistema muda |
| Sandbox | Nenhum |
| Persistência | Propriedade `criterio_plano_atendido`; eventos `veredito_indisponivel` e `resultado_sem_mede`; veredito passa a ser calculado com tentativas reais |
| Segurança | Feedback e evidência usam só agregados de `metrics.json` e do grafo, já permitidos pelo ADR 019 |
| Testes e telemetria | `operation_metrics` com três contadores novos; testes unitários com grafo em memória |

## 8. Questões em aberto

1. **Modo `auto` sem métrica aprovada (§4).** Proposta: não iniciar. Alternativa: iniciar e fechar
   por limite, com o aviso.
2. **Motivo de parada quando os ciclos ociosos estouram com hipótese sem tentativa (§5).** Proposta:
   `erro` com mensagem explícita. Alternativa: membro novo `hipoteses_nao_testadas` em `StopReason`
   (exige atualizar `src/knowledge/schema.py`, que enumera os motivos).
3. **Resultado negativo sem hipótese.** Uma subtarefa sem `hypothesis_id` que não atinge o próprio
   limiar continua `reprovado`. Proposta: manter, porque sem hipótese não há o que refutar.

## 8.1 Decisões adotadas na implementação (2026-10-13)

O pesquisador não respondeu as questões do §8 antes da implementação; foi adotada a hipótese mais conservadora de cada
uma, e o PR as lista para confirmação.

1. **Modo `auto` sem métrica aprovada:** a sessão não inicia (proposta do §4). `assisted` e `semi` avisam e seguem.
2. **Ciclos ociosos esgotados com hipótese sem tentativa:** fecha com `erro` e a mensagem do §5, sem membro novo em
   `StopReason`. O evento `hipoteses_sem_tentativa` leva a lista e alimenta `hipoteses_sem_tentativa_no_fechamento`.
3. **Resultado negativo sem hipótese:** continua `reprovado`.

Detalhes que o texto original deixava abertos:

- **Condição 4 do §1.** A reprovação por limiar é adiada (não retorna na hora): se há artefatos ausentes, o resultado é
  `reprovado`; se restam critérios qualitativos, só o parecer `pass` do revisor LLM mantém `resultado_negativo`; revisor
  indisponível ou ilegível dá `reprovado` (nada confirma o resto). Um critério parcialmente conhecido ou indecidido
  também dá `reprovado`.
- **`criterio_plano_atendido = true`** só quando a revisão foi `pass` verificada e o plano tinha critério quantitativo
  (métrica conhecida com limiar); sem critério quantitativo a propriedade não é gravada.
- **`resultado_sem_mede` (§3):** o nome base (com sinônimos e aliases do revisor) é comparado ao nome e aos sinônimos da
  `Metrica` do `Problema`; o evento sai quando não existe `Resultado-MEDE->Metrica` dessa métrica. Motivo
  `qualificador_excluido` para `cv`/`treino`/`validacao` e métrica de grupo, `metrica_nao_aprovada` se a `Metrica` do
  `Problema` não é `aprovado`, senão `resolucao_falhou`. O `MEDE` para um nó `candidato` continua sendo criado (sem
  mudança de comportamento).
- **Aviso no banner (§4):** o banner da CLI sai antes da sessão existir; o aviso é impresso no início da sessão
  (`print_status`) e registrado no evento `veredito_indisponivel`.
- **Hipótese "sem tentativa" (§5):** `n_tentativas` ausente vale 0; hipótese `em_teste` já exclui as retiradas pela
  governança (que viram `abandonada`/`proposta`). Identificadas pelo `id` do grafo (o `ref` do plano não é gravado).
- **Estado `concluded_negative`** conta como concluída em `completed_tasks` do fechamento, em `done_results` (não é
  reexecutada em ciclos seguintes) e em `succeeded_task_names` (disjuntor).
- **Tabela de resultados (§6.1):** limitada a `max(200, CLAIM_EVIDENCE_MAX_CHARS // 2)` caracteres.
- **`afirmacoes.json` (§6.2):** gravado após o pipeline do relatório; não sobrescreve afirmações existentes. Se o
  pipeline inteiro falhar antes, o arquivo não é gravado (o relatório já leva o aviso).
- **Tarefa 6.1 (Sonnet sem `afirmacoes.json`):** sem acesso aos logs do Pi nesta sessão, a causa não foi confirmada por
  eventos. Pelo código, o arquivo só nascia no fim do estágio `claims`; sem `CLAIM_VERIFY_ENABLED`, sem `render`, ou com
  exceção antes de `store.save()` o arquivo não era criado. A correção do §6.2 torna a ausência explícita
  (`motivo_vazio`); a confirmação por eventos fica pendente: reexecutar a sessão com o modelo Sonnet no Pi, quando o pesquisador autorizar a bateria, observando os eventos do estágio `claims` e as exceções (a causa continua NÃO confirmada).

## 9. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Modelo grava métrica errada abaixo do limiar e a subtarefa vira "resultado negativo" sem chance de correção | O `Resultado` fica no grafo com proveniência; a hipótese só muda de status quando o veredito passa de `DECISION_EVAL_MIN_VERDICT`, que exige mais de uma tentativa com os pesos atuais |
| Sessão fecha por solução cedo demais | O critério de solução não muda (`check_solution`) |
| Tabela de resultados grande no verificador | Limite `CLAIM_EVIDENCE_MAX_CHARS` e divisão em lotes existentes |
