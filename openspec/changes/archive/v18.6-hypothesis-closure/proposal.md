# Proposta: Fechamento de Hipóteses e Resultado Negativo como Progresso

**ID:** `v18.6-hypothesis-closure` · **Versão:** V18.6 (correções do benchmark de 2026-10-13) ·
**Capacidade:** `hypothesis-loop` (reutilizada de `v18-hypothesis-loop`)
**ADRs de origem:** [ADR 009](../../../../docs/decisions/adr_009_camada_conhecimento_experimental.md)
(resultados negativos são conhecimento de primeira classe),
[ADR 010](../../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md) (o assistente
formula e testa hipóteses), [ADR 012](../../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md)
(ciclo de exploração e critérios de parada), [ADR 015](../../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md)
(veredito calculado, `Resultado-MEDE->Metrica`) e
[ADR 019](../../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §6
(verificação de afirmações). Não há ADR novo: a mudança faz o código cumprir decisões já aprovadas.
**Origem dos requisitos:** benchmark de 2026-10-13, investigação do grafo do Pi 5 e decisão do
pesquisador de 2026-10-13: **um resultado científico negativo (hipótese refutada) é progresso,
não falha**.
**Depende de:** [`v18.6-review-evidence`](../v18.6-review-evidence/proposal.md) (qualificador de
métrica, para `test_accuracy` ganhar `MEDE`; e a classificação da reprovação)
**Habilita:** a primeira sessão que fecha por `solucao_encontrada` ou por hipóteses refutadas com
veredito calculado.

## Por quê

A investigação do grafo do Pi, depois do benchmark, mostrou que o ciclo de hipóteses nunca
concluiu uma hipótese:

| Observação no Pi (2026-10-13) | Causa |
|---|---|
| Todos os eventos `hypothesis_evaluation` com `hipoteses_concluidas: 0`, nas cinco sessões | Todas as `Hipotese` ficaram com `veredito` 0.0 e `status` `em_teste` |
| Zero arestas `MEDE` no grafo inteiro | O vocabulário nunca foi semeado no Pi; o `Problema` usa uma `Metrica` "acurácia" `candidato` sem sinônimos; `test_accuracy` não casaria nem com o sinônimo `accuracy`. Sem `MEDE`, `ServicoConhecimento.collect_attempts` (`src/knowledge/service.py:331`) não encontra tentativas e o veredito fica em 0 |
| Gemini: regressão logística com acurácia 0,933 contra alvo 0,95 virou `Experimento.status = "falha"` | `_experiment_status` (`src/knowledge/ingestion.py:709`) trata toda reprovação do revisor como falha; o resultado entra no veredito como falha de execução, não como evidência contra a hipótese |
| Gemini: depois da reprovação legítima, 4 replanejamentos e o disjuntor de zero progresso fechou com `erro` | `CycleProgress` (`src/autonomous_loop.py:62`) conta só subtarefas `success`; a reprovação por critério repete a mesma assinatura e conta como "sem progresso" |
| Sonnet: `sem_caminhos_promissores` em 2,7 min, com 1 de 2 subtarefas e as hipóteses em `em_teste` sem nenhuma tentativa | `has_open_paths` (`src/exploration.py:439`) ignora hipóteses que estão no plano; o ciclo ocioso fecha a sessão mesmo sem nenhuma hipótese testada |
| Verificação de afirmações: Haiku 53 e Luna 58 `nao_verificavel`; o Sonnet não gerou `afirmacoes.json` | O pacote de evidência da conclusão do relatório só é montado a partir de códigos de referência numérica citados na frase (`src/claims/evidence.py:92`); frase sem código fica sem evidência. A ausência do arquivo no Sonnet não foi explicada |

## O que muda

- **Novo:** **resultado negativo** na revisão. Quando a única razão da reprovação é um critério
  quantitativo avaliado de forma determinística (métrica presente, numérica, abaixo do limiar) numa
  subtarefa ligada a uma hipótese, a revisão devolve `outcome = "resultado_negativo"`:
  - a subtarefa fica `concluded_negative` no DAG: não é repetida e libera as dependentes;
  - o `Experimento` é gravado com `status = "sucesso"` e `criterio_plano_atendido = false`; o
    `Resultado` fica `validado` e entra no veredito como evidência contra a hipótese;
  - o disjuntor de zero progresso conta a subtarefa como progresso;
  - o próximo ciclo recebe o feedback "h<n> refutada por <métrica> = <valor> < <limiar>; proponha
    outra abordagem", sem repetir a mesma configuração.
- **Novo:** **conferência do veredito no início da sessão.** Se a `Metrica` do `Problema` não está
  aprovada no vocabulário, a sessão registra `veredito_indisponivel` e avisa no banner. No modo
  `auto`, a sessão não inicia (o critério de parada depende do veredito; AGENTS.md §1.6).
- **Novo:** sinal `sem_mede`: a ingestão registra quando um `Resultado` tem o nome base da métrica
  do `Problema` e não ganhou `MEDE` (ex.: vocabulário incompleto). Aparece nas métricas de
  operação.
- **Modificado:** **critério `sem_caminhos_promissores`.** A sessão só fecha por esse motivo quando
  nenhuma hipótese `em_teste` do projeto está sem tentativa (`n_tentativas = 0`). Hipótese no plano
  e nunca testada é caminho aberto.
- **Modificado:** **evidência das afirmações do relatório.** Frase sem código de referência recebe,
  como evidência, a tabela dos `Resultado`s validados da sessão (nome, valor, qualificador, subtarefa),
  limitada por `CLAIM_EVIDENCE_MAX_CHARS`. O arquivo `afirmacoes.json` é sempre gravado quando há
  relatório final, mesmo vazio, com o motivo.
- **Fora do escopo:**
  - Nomes de métrica, perfil de artefatos e regra do limiar: `v18.6-review-evidence`.
  - Mudar `compute_verdict`, os pesos ou `DECISION_EVAL_MIN_VERDICT`.
  - Mudar o alvo do `Problema` (decisão do pesquisador; segue 0,95 no benchmark).

## Impacto

- **Código:** `src/agents/validator_agent.py` (`ReviewResult.outcome`), `src/autonomous_loop.py`
  (estado `concluded_negative`, `CycleProgress`, feedback, fechamento por `sem_caminhos_promissores`),
  `src/exploration.py` (`has_open_paths`), `src/knowledge/ingestion.py` (`_experiment_status`,
  `criterio_plano_atendido`, sinal `sem_mede`), `src/knowledge/schema.py` (propriedade opcional
  nova em `Experimento`), `src/claims/evidence.py` e `src/claims/service.py` (tabela de resultados,
  arquivo sempre gravado), início de sessão (`src/orchestrator.py`), `src/config.py`.
- **Contratos:** evento `subtask_review` ganha `outcome`; evento novo `veredito_indisponivel`;
  `operation_metrics` ganha `resultados_sem_mede`, `subtarefas_resultado_negativo` e
  `hipoteses_sem_tentativa_no_fechamento`. `Experimento` ganha `criterio_plano_atendido` (opcional).
- **Schema de banco:** nenhuma tabela ou coluna nova; o grafo ganha uma propriedade opcional,
  validada pelo schema do grafo em código.
- **Compatibilidade:** `NEGATIVE_RESULT_AS_PROGRESS=false` volta ao tratamento atual, para
  comparar nas avaliações.
- **Custo:** menos replanejamentos inúteis; nenhuma chamada LLM nova. A tabela de resultados
  aumenta o pacote do verificador de afirmações dentro do limite já existente.

## Aprovações necessárias

- Nenhuma alteração de schema relacional, Dockerfile, `docker-compose.yml`, exclusão de arquivos
  ou `AGENTS.md`.
- **Decisão do pesquisador** sobre as questões em aberto do `design.md` §8, em especial a recusa de
  iniciar no modo `auto` sem métrica aprovada (§8.1).
