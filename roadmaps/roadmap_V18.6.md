# Roadmap V18.6 — Correções do Benchmark de 2026-10-13

> **Estado (2026-10-13):** as Tarefas 1 a 5 e a correção NC-PERFIL (`v18.6-profile-hardening`) estão
> concluídas, mergeadas em `dev` (#142, #144, #145, #146, #154, #155) e arquivadas em
> `openspec/changes/archive/`, com os requisitos consolidados em `openspec/specs/`. A etapa **não está
> encerrada**: faltam a matriz com bancos isolados e 3 repetições no Pi 5 (só com confirmação do
> pesquisador), a composição da matriz e as respostas do pesquisador às questões de design (ver
> "Pendências conhecidas"). Itens abertos: [`PENDENCIAS.md`](../openspec/changes/archive/PENDENCIAS.md).

## Objetivo

Fazer o ciclo de pesquisa autônomo concluir por critério científico, não por regra do framework, e
tornar o benchmark capaz de medir isso. A etapa nasce da revisão do benchmark de 2026-10-13
([`docs/benchmarks/2026-10-13-modelos-v18-resultados.md`](../docs/benchmarks/2026-10-13-modelos-v18-resultados.md))
e da investigação dos eventos e do grafo gravados no Pi 5:

- o revisor reprovava resultados válidos (nomes de métrica, `metrics.json` aninhado, conteúdo de
  dados retido pelo filtro de localidade, scripts e modelos com nome diferente);
- nenhuma hipótese foi concluída, porque o grafo não tinha nenhuma aresta `MEDE` e resultados
  negativos eram tratados como falha;
- o placar do benchmark lia números do texto (a acurácia 1,000 era uma contagem);
- o Validator julgava o trabalho do próprio modelo.

ADRs de origem: 002, 005, 009, 010, 012, 015, 019 e o ADR 020 (aceito em 2026-10-13).

## Decisões do pesquisador (2026-10-13)

- Resultado negativo (hipótese refutada) é progresso, não falha.
- O Validator usa família de modelo diferente da do Developer; Researcher e Developer podem
  coincidir (ADR 020).
- O alvo do `Problema` (0,95) fica fixo no benchmark; é requisito do pesquisador.
- Os bancos (relacional, vetorial, grafo) são zerados antes de cada execução do benchmark, e o
  crescimento das memórias é observado.

## Dependências

- V18.5 mergeada em `dev` (todas as mudanças estão mergeadas).
- ADR 020 aprovado, para a Tarefa 3 e o item de juiz da Tarefa 2 (atendido em 2026-10-13, PR #143).

## Tarefas

### Tarefa 1: Evidência e tolerância na revisão
- **Spec:** [`v18.6-review-evidence`](../openspec/changes/archive/v18.6-review-evidence/proposal.md) · **Estado (2026-10-13):** concluída e arquivada, #142
- **Critérios de aceite:** [x] `test_accuracy` satisfaz critério de acurácia; `cv_*` não · [x] `metrics.json` com `metricas` e grupos por modelo · [x] critério com várias comparações · [x] perfil estrutural de CSV/JSON como `esquema_agregado` · [x] `script.py` resolve o `.py` esperado · [x] baseline `validation` sem hipótese não exige limiar
- **Complexidade estimada:** Média

### Tarefa 2: Benchmark com bancos isolados e placar independente
- **Spec:** [`v18.6-benchmark-harness`](../openspec/changes/archive/v18.6-benchmark-harness/proposal.md) · **Estado (2026-10-13):** concluída e arquivada, #144
- **Critérios de aceite:** [x] reset com quatro guardas e arquivo de segurança · [x] vocabulário semeado e conferido · [x] série de crescimento das memórias · [x] acurácia oficial só de resultado validado · [x] arquivamento da sessão · [x] `--repeat N` com agregados · [x] juiz declarado por combinação e combinação de controle
- **Complexidade estimada:** Média

### Tarefa 3: Independência do julgamento
- **Spec:** [`v18.6-validator-independence`](../openspec/changes/archive/v18.6-validator-independence/proposal.md) · **Estado (2026-10-13):** concluída e arquivada, #145
- **Critérios de aceite:** [x] `validator` de família diferente do `developer` na inicialização · [x] conferência de dicas e da reserva do 429 · [x] modo por política · [x] registro no banner, payload, relatório e retomada
- **Complexidade estimada:** Média

### Tarefa 4: Fechamento de hipóteses e resultado negativo
- **Spec:** [`v18.6-hypothesis-closure`](../openspec/changes/archive/v18.6-hypothesis-closure/proposal.md) · **Estado (2026-10-13):** concluída e arquivada, #146
- **Critérios de aceite:** [x] resultado negativo conclui a subtarefa e conta como progresso · [x] `Experimento` em `sucesso` e veredito com a tentativa · [x] `veredito_indisponivel` no início da sessão · [x] `sem_caminhos_promissores` só com todas as hipóteses testadas · [x] evidência para frases sem código e `afirmacoes.json` sempre gravado
- **Complexidade estimada:** Alta

### Tarefa 5: Remoção de agentes e papéis sem uso
- **Spec:** [`v18.6-remove-unused-agents`](../openspec/changes/archive/v18.6-remove-unused-agents/proposal.md) · **Estado (2026-10-13):** concluída e arquivada, #155 (Pi 5: 3549 passed, 0 falhas)
- **Critérios de aceite:** [x] agente `reviewer` removido do código, catálogo e benchmark · [x] papéis de subtarefa só `developer` e `researcher` · [x] revisão de subtarefa registrada como `validator` · [x] atalho `agent_tasks` e `REVIEW_MODE=end_only` removidos
- **Complexidade estimada:** Baixa

### Correção NC-PERFIL: endurecimento do perfil estrutural
- **Spec:** [`v18.6-profile-hardening`](../openspec/changes/archive/v18.6-profile-hardening/proposal.md) · **Estado (2026-10-13):** concluída e arquivada, #154 (Pi 5: 3558 passed, 0 falhas)
- **Critérios de aceite:** [x] cabeçalho verificado (NC-PERFIL-1) · [x] symlink e arquivo fora da sessão nunca lidos (NC-PERFIL-2) · [x] perfil delimitado como dado e rótulos seguros (NC-PERFIL-3 e 6) · [x] perfil sem exceção, JSON profundo e `LOCALITY_MIN_GROUP_SIZE` ausente (NC-PERFIL-4) · [x] limites de colunas, linhas, tempo e linhas de chaves (NC-PERFIL-5)
- **Complexidade estimada:** Baixa

## Ordem de implementação

```
Onda 1 (paralelo): Tarefa 1 (review-evidence) · Tarefa 2 (benchmark-harness, sem o item de juiz)
Onda 2:            Tarefa 5 (remove-unused-agents, antes da Tarefa 3, que ela simplifica) · Tarefa 3 (validator-independence, após aprovação do ADR 020) · item de juiz da Tarefa 2
Onda 3:            Tarefa 4 (hypothesis-closure, depende da Tarefa 1)
Depois:            bateria no Pi (com confirmação do pesquisador) e matriz com 3 repetições por combinação
```

## Validação da Etapa
- [x] Todos os testes unitários e de integração passam. _Pi 5, 2026-10-13, `uv run pytest -m "unit or integration"`: #142 3434 passed; #144 3468; #145 3475; #146 3534 (todos com 1 falha preexistente, `test_similarity_queue_integration::test_fluxo_completo_da_fila`, corrigida no #151); #154 3558 passed, 0 falhas; #155 3549 passed, 0 falhas._
- [ ] Validação real no Raspberry Pi 5: matriz com bancos isolados e 3 repetições, só depois da confirmação do pesquisador. _Pendente. A composição de `scripts/benchmark/matrix_modelos_v18_6.json` (três combinações com juiz de outra família e `controle-gemini-todos`) também aguarda confirmação._
- [x] Revisões do Analista de Segurança concluídas (Tarefas 1 e 3). _Tarefa 3: feita no design §6 de `v18.6-validator-independence`, sem bloqueio (requisitos S1 a S6). Tarefa 1: parecer de 2026-10-13 em `docs/security/parecer_v18_6_perfil_estrutural.md`, aprovado com ressalvas (2 achados altos, 3 médios, 1 baixo); as correções NC-PERFIL-1 a 6 foram feitas pela mudança `v18.6-profile-hardening` (#154) e validadas no Pi 5 (3558 passed, 0 falhas)._
- [x] ADR 020 Aceito. _Aceito pelo pesquisador em 2026-10-13, embora a matriz com bancos isolados e 3 repetições fique para depois; a revisão prevista no ADR após essa rodada é acompanhamento, não bloqueio._
- [x] PRs merged em `dev`; mudanças arquivadas. _#142, #144, #145 e #146 mergeados; as 4 mudanças arquivadas e os ADRs 002, 005, 009, 010, 012, 015, 019 e 020 atualizados (#147); #154 e #155 mergeados, com `v18.6-profile-hardening` e `v18.6-remove-unused-agents` arquivadas e os ADRs 007, 017, 019 e 020 atualizados (PR de fechamento documental)._

## Pendências conhecidas

- **Questões do design §8:** as respostas do pesquisador a `v18.6-review-evidence` e a `v18.6-hypothesis-closure` (e a `v18.6-benchmark-harness`, 0.1) não foram dadas; vigoram as propostas dos designs.
- **`v18.6-review-evidence` 7.2 (parcial):** a conferência exata sobre os `metrics.json`, planos e nós `Resultado` do benchmark de 2026-10-13 não é possível (apagados do Pi); só há a classificação textual dos eventos, com limites superiores.
- **`v18.6-hypothesis-closure` 6.1:** a causa da ausência de `afirmacoes.json` na sessão do Sonnet (2026-10-12 21:53) **NÃO foi confirmada** (sem acesso aos eventos do Pi). É preciso reexecutar a sessão com o modelo Sonnet, no Pi, quando o pesquisador autorizar a bateria, e investigar pelos eventos. Hipóteses já levantadas: `CLAIM_VERIFY_ENABLED` desligado, falta de `render`, exceção antes de `store.save()`. O que observar: os eventos do estágio `claims` e as exceções. A tarefa 6.3 elimina o sintoma (arquivo sempre gravado, com `motivo_vazio`), não confirma a causa.
- **Composição da matriz `matrix_modelos_v18_6.json`:** a confirmar com o pesquisador antes da rodada.
- **Execução curta no Pi (`v18.6-benchmark-harness` 7.2):** uma combinação, `--repeat 1`, `--reset-stores`, só após confirmação do pesquisador.
