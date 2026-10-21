# Roadmap V18.9 — Memória por Registros de Resultado e Correlação entre Pesquisas

> **Estado (2026-10-21):** especificada; aguarda aprovação das mudanças pelo pesquisador. Nada implementado.

## Objetivo

Substituir o veredito por registros de resultado medidos e por uma regra de estado da hipótese, levar a experiência de problemas semelhantes ao planejamento e avaliar a memória com métricas comparáveis às de outros estudos. ADR de origem: [026](../docs/decisions/adr_026_memoria_por_registros_de_resultado.md), que substitui o ADR 015 §9 e o ADR 025.

## Dependências

- `v18.8-verdict-controlled-sessions`, encerrada pelo ADR 026. O gerador `scripts/verdict_lab/controlled/` e o orquestrador de exploração são reaproveitados.

## Tarefas

### Tarefa 1: Registros de resultado e regra de estado
- **Spec:** [`v18.9-result-records`](../openspec/changes/v18.9-result-records/proposal.md)
- **Critérios de aceite:**
  - [ ] `RegistroResultado` recalculado na ingestão;
  - [ ] estado pela regra de réplicas;
  - [ ] atalhos derivados dos registros;
  - [ ] variáveis do veredito com erro de remoção;
  - [ ] migração idempotente.
- **Complexidade estimada:** Alta

### Tarefa 2: Memória de falhas
- **Spec:** [`v18.9-failure-memory`](../openspec/changes/v18.9-failure-memory/proposal.md)
- **Critérios de aceite:**
  - [ ] bloco "NÃO / USE" no prompt do Developer, com teto;
  - [ ] desligável para o E1.
- **Complexidade estimada:** Baixa

### Tarefa 3: Avaliação da memória
- **Spec:** [`v18.9-memory-evaluation`](../openspec/changes/v18.9-memory-evaluation/proposal.md)
- **Critérios de aceite:**
  - [ ] candidatos estruturais sem LLM;
  - [ ] replay com AUC e linhas de base;
  - [ ] métricas do núcleo com intervalo;
  - [ ] famílias reprodutíveis;
  - [ ] pré-registro antes de cada rodada.
- **Complexidade estimada:** Média

### Tarefa 4: Experiência de outros projetos e candidatos no ciclo
- **Spec:** [`v18.9-cross-project-context`](../openspec/changes/v18.9-cross-project-context/proposal.md)
- **Critérios de aceite:**
  - [ ] bloco no primeiro plano;
  - [ ] semelhança por texto e dados;
  - [ ] candidatos no ciclo;
  - [ ] fila só de duplicatas.
- **Complexidade estimada:** Média

## Ordem de implementação

```
Tarefa 1 ──→ Tarefa 3 (candidatos, replay, métricas) ──→ E0 ──→ Tarefa 4
Tarefa 2 (paralela) ──────────────────────────────────→ E1
Tarefas 2 e 4 ─────────────────────────────────────────→ E2
```

## Validação da Etapa
- [ ] Todos os testes unitários e de integração passam.
- [ ] E0, E1 e E2 com pré-registro e relatório em `docs/avaliacao-memoria/`.
- [ ] Migração aplicada nos bancos de desenvolvimento e no Pi.
- [ ] ADR 026 marcado como Aceito; ADRs 015 e 025 atualizados.
- [ ] PRs mergeados em `dev`; mudanças arquivadas.
