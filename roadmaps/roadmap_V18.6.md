# Roadmap V18.6 — Correções do Benchmark de 2026-10-13

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

ADRs de origem: 002, 005, 009, 010, 012, 015, 019 e o ADR 020 (novo, Proposto).

## Decisões do pesquisador (2026-10-13)

- Resultado negativo (hipótese refutada) é progresso, não falha.
- O Validator usa família de modelo diferente da do Developer; Researcher e Developer podem
  coincidir (ADR 020).
- O alvo do `Problema` (0,95) fica fixo no benchmark; é requisito do pesquisador.
- Os bancos (relacional, vetorial, grafo) são zerados antes de cada execução do benchmark, e o
  crescimento das memórias é observado.

## Dependências

- V18.5 mergeada em `dev` (todas as mudanças estão mergeadas).
- ADR 020 aprovado, para a Tarefa 3 e o item de juiz da Tarefa 4.

## Tarefas

### Tarefa 1: Evidência e tolerância na revisão
- **Spec:** [`v18.6-review-evidence`](../openspec/changes/v18.6-review-evidence/proposal.md)
- **Critérios de aceite:** [ ] `test_accuracy` satisfaz critério de acurácia; `cv_*` não · [ ] `metrics.json` com `metricas` e grupos por modelo · [ ] critério com várias comparações · [ ] perfil estrutural de CSV/JSON como `esquema_agregado` · [ ] `script.py` resolve o `.py` esperado · [ ] baseline `validation` sem hipótese não exige limiar
- **Complexidade estimada:** Média

### Tarefa 2: Benchmark com bancos isolados e placar independente
- **Spec:** [`v18.6-benchmark-harness`](../openspec/changes/v18.6-benchmark-harness/proposal.md)
- **Critérios de aceite:** [ ] reset com quatro guardas e arquivo de segurança · [ ] vocabulário semeado e conferido · [ ] série de crescimento das memórias · [ ] acurácia oficial só de resultado validado · [ ] arquivamento da sessão · [ ] `--repeat N` com agregados · [ ] juiz declarado por combinação e combinação de controle
- **Complexidade estimada:** Média

### Tarefa 3: Independência do julgamento
- **Spec:** [`v18.6-validator-independence`](../openspec/changes/v18.6-validator-independence/proposal.md)
- **Critérios de aceite:** [ ] `validator` de família diferente do `developer` na inicialização · [ ] conferência no despacho de dicas, `base`, `reviewer` e reserva do 429 · [ ] modo por política · [ ] registro no banner, payload, relatório e retomada
- **Complexidade estimada:** Média

### Tarefa 4: Fechamento de hipóteses e resultado negativo
- **Spec:** [`v18.6-hypothesis-closure`](../openspec/changes/v18.6-hypothesis-closure/proposal.md)
- **Critérios de aceite:** [ ] resultado negativo conclui a subtarefa e conta como progresso · [ ] `Experimento` em `sucesso` e veredito com a tentativa · [ ] `veredito_indisponivel` no início da sessão · [ ] `sem_caminhos_promissores` só com todas as hipóteses testadas · [ ] evidência para frases sem código e `afirmacoes.json` sempre gravado
- **Complexidade estimada:** Alta

## Ordem de implementação

```
Onda 1 (paralelo): Tarefa 1 (review-evidence) · Tarefa 2 (benchmark-harness, sem o item de juiz)
Onda 2:            Tarefa 3 (validator-independence, após aprovação do ADR 020) · item de juiz da Tarefa 2
Onda 3:            Tarefa 4 (hypothesis-closure, depende da Tarefa 1)
Depois:            bateria no Pi (com confirmação do pesquisador) e matriz com 3 repetições por combinação
```

## Validação da Etapa
- [ ] Todos os testes unitários e de integração passam.
- [ ] Validação real no Raspberry Pi 5: matriz com bancos isolados e 3 repetições, só depois da confirmação do pesquisador.
- [ ] Revisões do Analista de Segurança concluídas (Tarefas 1 e 3).
- [ ] ADR 020 Aceito.
- [ ] PRs merged em `dev`; mudanças arquivadas.
