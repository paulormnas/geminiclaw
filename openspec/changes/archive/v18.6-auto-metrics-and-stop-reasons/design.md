# Design: v18.6-auto-metrics-and-stop-reasons

Confronto com o código real (2026-10-13): o §4 da `v18.6-hypothesis-closure` está em
`ExplorationSession.verdict_availability` (`src/exploration.py`) e em `AutonomousLoop._check_verdict_available`
(`src/autonomous_loop.py`); o fechamento por hipótese sem tentativa em `_close_untested_hypotheses`; o enum de
motivos decididos pela exploração é `ExplorationStop` (`src/exploration.py`), e `StopReason` (`src/usage.py`) só
cobre os limites de uso. O novo motivo entra em `ExplorationStop` (mesma família de `limite_ciclos`,
`planos_rejeitados` e `erro`) e na enumeração de `Sessao.motivo_parada` (`src/knowledge/schema.py`), de onde
`MOTIVOS_PARADA` (ingestão e validação de checkpoint) é derivado. Padrão de nomes: `snake_case` em português,
substantivo + particípio/adjetivo (`sem_caminhos_promissores`, `planos_rejeitados`), logo `hipoteses_nao_testadas`.

## 1. Métricas definidas pelo agente (modo `auto`)

### 1.1 Quando se aplica

`ExplorationSession.verdict_availability()` já devolve `(motivo, correção)` quando a `Metrica` do `Problema` não está
aprovada ou não resolve. Novo: no modo `auto`, esse resultado **não** fecha a sessão; liga
`exploration.metric_definition_required = True`. Os modos `assisted` e `semi` continuam só avisando. O evento
`veredito_indisponivel` e o aviso permanecem em todos os modos; no `auto` o aviso diz que o Researcher definirá a métrica.

### 1.2 Formato no plano

Chave nova do envelope do plano (`hipoteses`, `decisoes`, `respostas_sugestoes`, `subtarefas`, **`metricas`**):

```json
"metricas": [
  {"nome": "acuracia", "sentido": "maior_melhor", "limiar": 0.95, "delta_min": 0.01,
   "justificativa": "Classes balanceadas; acurácia no conjunto de teste separado é a medida usual."}
]
```

- A primeira é a **principal** (alimenta `criterio_sucesso` e o veredito); as demais são complementares.
- Limites (`src/knowledge/metric_definition.py`): até `METRICS_MAX_PER_PLAN` (padrão 3), `nome` até
  `VOCAB_TERM_MAX_CHARS`, `justificativa` até `HYPOTHESIS_TEXT_MAX_CHARS`, `sentido` em
  `maior_melhor|menor_melhor`, `limiar` e `delta_min` números finitos (`delta_min` positivo). Tudo é texto de LLM:
  saneado por `clean_free_text`, entradas inválidas descartadas e contadas, nunca corrigidas em silêncio.
- `PlanExtras.metricas: tuple[MetricDecl, ...]`. O Researcher só recebe a instrução (em `prompt_block`) enquanto
  `metric_definition_required`; fora disso a chave é ignorada (sem efeito no grafo).

### 1.3 Validação (Validator, família diferente da do Developer)

`ValidatorAgent.validate_plan(plan, prompt, *, metric_definition=None)`. `metric_definition` só é passado quando a
definição é exigida: `{"required": True, "metricas": [...], "problema": {titulo, resumo, classe, criterio}}`.

- **Determinístico (reprova sem chamar o LLM):** definição exigida e `metricas` vazia; métrica sem `sentido` válido,
  `limiar` não finito, `justificativa` vazia ou nome repetido. As mensagens dizem como corrigir.
- **LLM:** o prompt do Validator ganha uma seção "DEFINIÇÃO DE MÉTRICAS" com o problema (dado delimitado) e a
  definição, pedindo `metricas_status` (`approved|revision_needed`) e `metricas_issues`. Critérios: a métrica é adequada ao
  tipo de problema (ex.: acurácia em classes muito desbalanceadas não é adequada); o limiar é plausível e foi
  justificado; não é métrica de vaidade (mede o que a hipótese não testa) nem tem risco de vazamento (calculada
  sobre dados de treino).
- O mesmo `provider` do papel `validator` já satisfaz o ADR 020 (R1: família diferente do Developer); nenhuma
  chamada nova. `ValidationResult.metrics_approved` é `True` **somente** quando o LLM devolveu
  `metricas_status="approved"` (independe de o plano em si ter sido aprovado; o orquestrador só grava quando também
  `is_valid`). Reprovação das métricas reprova o plano (`is_valid=False`,
  `issues` prefixadas com "Métricas:") e volta ao Researcher pelo ciclo normal.
- **Reprovação repetida:** a conversão em "aprova com avisos" (`PLAN_REJECTION_STALL_LIMIT`, só para reprovação do LLM)
  **não** vale quando a definição é exigida e `metrics_approved` é falso: uma métrica nunca é validada por
  cansaço. O planejamento segue até `MAX_PLANNING_ITERATIONS` e a sessão acumula `planos_rejeitados`
  (cenário existente), ou `PlanningStalled` se a reprovação determinística se repetir.

### 1.4 Gravação (somente após a validação)

`src/knowledge/metric_definition.py::apply_validated_metrics(store, ctx, decls, validator_actor)`, chamado pelo
orquestrador logo depois que `validate_plan` aprova o plano com `metrics_approved`:

1. Cada `MetricDecl` passa por `vocabulary.resolve_metric` (ator `Researcher`, `sentido` informado). Ordem normal:
   nome exato, sinônimo, semântica, candidato novo.
2. Regras de governança, por `Metrica` resolvida:
   - **Rejeitada pelo pesquisador** (nó `rejeitado` com o mesmo nome ou sinônimo normalizado): a definição é
     descartada (`rejeitada_pelo_pesquisador`). `resolve_metric` ignora nós rejeitados, então a conferência é explícita.
   - **Aprovada pelo pesquisador** (status `aprovado` sem `aprovada_por="validator"`, inclui o catálogo semeado): **precedência
     total**; o nó não é alterado, nem o `sentido`. Se o `sentido` do agente diverge, a definição é descartada
     (`sentido_divergente`).
   - **Já aprovada pelo Validator**: nada a fazer.
   - **Candidata** (nova ou existente, p.ex. a do rascunho do `Problema`): se o `sentido` diverge, é descartada
     (`sentido_divergente`); senão `update_node` com `status="aprovado"`, `origem_definicao="agente"`, `aprovada_por="validator"` e
     `justificativa_definicao`. **O ator da escrita é o `orquestrador`**, não um agente: a barreira
     `AGENT_ALLOWED_VALUES` (`src/knowledge/validation.py`) proíbe que qualquer agente aprove `Metrica` e continua
     valendo para todos (Curator, Researcher, Validator). A aprovação só acontece neste caminho determinístico, que
     o orquestrador percorre depois de `ValidationResult.metrics_approved`; `aprovada_por="validator"` e
     `justificativa_definicao` registram quem decidiu e por quê, e a trilha de auditoria mostra o ator real.
3. **`criterio_sucesso` do `Problema`:** só quando a `Metrica` atual do `Problema` não está aprovada (a condição que
   ligou a definição). A métrica principal aprovada vira `metrica`/`metrica_id`; `alvo` é o `limiar` do agente, **exceto**
   quando o `Problema` já aponta para essa mesma métrica e tem `alvo` numérico (o valor do pesquisador prevalece);
   `delta_min` do `Problema` (obrigatório na confirmação) prevalece sobre o do agente e o do agente só preenche
   se estiver ausente; `metricas_adicionais` lista as complementares; `definido_por="agente"`. Uma `Metrica`
   aprovada pelo pesquisador no `Problema` nunca é substituída.
4. Resultado: eventos `metricas_definidas` (ids, nomes, `origem`, `aprovada_por`, `precedencia_pesquisador`) e, se alguma
   definição não valeu, `metricas_nao_aplicadas` (motivo por métrica). `metric_definition_required` só desliga se
   `verdict_availability()` voltar `None`; senão o feedback do próximo ciclo cita o motivo e a exigência continua.

Sem migração: `Metrica` antiga sem `origem_definicao`/`aprovada_por` equivale a `pesquisador`.

### 1.5 Esquema (aditivo)

`Metrica`: `origem_definicao` (enum `pesquisador|agente`), `aprovada_por` (enum `pesquisador|validator`),
`justificativa_definicao` (texto). Todas opcionais. Nenhuma relação nova.

## 2. `hipoteses_nao_testadas`

- `ExplorationStop.UNTESTED_HYPOTHESES = "hipoteses_nao_testadas"`; enum de `Sessao.motivo_parada` ganha o valor.
- `_close_untested_hypotheses` fecha com o novo motivo, **sem** acrescentar `AgentResult` de erro; a mensagem sai em
  `logger.warning`, `print_status("warning")` e no evento `hipoteses_sem_tentativa` (`motivo_parada`, `hipoteses`,
  `ciclos_ociosos`, `mensagem`).
- `src/continuity.py`: `evaluate_resumability` recusa a retomada com mensagem própria (mesmo critério de `erro`:
  repetir o mesmo planejamento não resolve; o pesquisador inicia nova sessão ou orienta o Researcher).
- Métricas de operação: `HypothesisClosureReader` ganha `fechada_por_hipoteses_nao_testadas` (bool, do evento
  `exploration_stop`). A seção Markdown acrescenta, para este motivo, a linha "Hipóteses sem tentativa no fechamento: N".
- Relatório e CLI: o "Motivo de parada" ganha descrição legível (`describe_stop_reason`), usada pelo relatório final e
  pela tela final da CLI.
- Benchmark: `scripts/benchmark/run_benchmark.py::stop_class(stop)` classifica o motivo em `limite`, `erro`,
  `interrupcao`, `criterio_pesquisa` ou `hipoteses_nao_testadas`; `anomalies()` passa a usar a classificação
  (comportamento atual preservado: só `limite`, `erro` e `interrupcao` são anomalia). `report.py` lista, abaixo dos
  agregados, as combinações cuja sessão fechou por `hipoteses_nao_testadas`.

## 3. `sem_hipotese`

- `ReviewResult.motivos: List[str]` (padrão `[]`). `review_result` acrescenta `"sem_hipotese"` quando a subtarefa **não
  tem** `hypothesis_id`, a reprovação veio só de comparações determinísticas de limiar (métrica presente e numérica, sem
  critério indecidido) e o resultado seria `resultado_negativo` caso houvesse hipótese. O `status`/`outcome` continuam
  `fail`/`reprovado` e `NEGATIVE_RESULT_AS_PROGRESS` não influi no registro.
- O retorno de `_review_subtask` e o evento `subtask_review` levam `motivos`.
- `scripts/benchmark/interactions.py`: `subtask_reviews.motivos` (contagem por motivo) e `report.py` imprime a linha;
  `HypothesisClosureReader` ganha `reprovacoes_sem_hipotese` (subtarefas distintas).

## 4. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador e loop | Modo `auto` deixa de fechar no início; `hipoteses_nao_testadas` substitui `erro`; planejamento passa a gravar métricas após a validação |
| Agentes e prompts | Researcher recebe a instrução de `metricas` só quando exigida; Validator ganha uma seção no prompt de validação do plano |
| Sandbox | Nenhum |
| Persistência | Três propriedades opcionais em `Metrica`, um valor de enumeração; atualização de `Problema.criterio_sucesso` (propriedade já livre) |
| Segurança | Definição do agente é dado não confiável (limites, saneamento, validação por outro agente de outra família); a barreira que impede agentes de aprovar `Metrica` não é relaxada (a escrita é do orquestrador, depois do parecer do Validator); aprovação nunca sobrescreve termo aprovado ou rejeitado pelo pesquisador |
| Testes e telemetria | Eventos e contadores novos; testes unitários com grafo em memória e Validator simulado |

## 5. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| O Researcher escolhe uma métrica fácil para "vencer" | O Validator avalia adequação, limiar e vaidade; a `justificativa_definicao` e `aprovada_por` ficam no grafo para o pesquisador revisar |
| Validator e Researcher concordam por viés comum | Famílias diferentes de Developer e Validator (ADR 020); o pesquisador pode rejeitar o termo (a rejeição vale nas definições futuras) |
| Sessão `auto` sem veredito por muitos ciclos | Cada ciclo repete o pedido; sem definição aprovada o teto `MAX_EXPLORATION_CYCLES`/`planos_rejeitados` fecha a sessão |
| `Problema` com métrica do rascunho candidata passa a valer sem o pesquisador | É exatamente a decisão de 2026-10-13; o evento `metricas_definidas` e o relatório registram a origem |

## 6. Questões em aberto

1. **Ratificação pelo pesquisador** de métricas aprovadas pelo agente (`geminiclaw vocab pending` listá-las, com
   `approve` ratificando e `reject` revogando). Proposta: tratar em mudança própria; aqui só se grava `aprovada_por`.
2. **Veredito multimétrica.** Hoje só a principal conta; as complementares ficam registradas.

## 7. Decisões adotadas na implementação (hipótese mais conservadora, a confirmar no PR)

- A métrica principal é a primeira de `metricas`; reprovação do Validator não aplica nada (nem parcialmente).
- Sentido divergente de um termo existente descarta a definição em vez de corrigir o termo.
- `hipoteses_nao_testadas` não é retomável sem nova sessão (herda a recusa de `erro`).
- `sem_hipotese` só é registrado no caso de limiar numérico puro (o único em que a hipótese mudaria o resultado).
