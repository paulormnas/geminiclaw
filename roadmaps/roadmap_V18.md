# Roadmap V18 — Ciclo de Hipóteses, Limites de Uso e Continuidade

## Objetivo

Fazer o assistente conduzir a pesquisa: formular hipóteses, registrar decisões de caminho,
explorar ativamente com o Curator até uma solução ou um limite definido pelo pesquisador, e
nunca perder o avanço entre execuções (ADRs 010 e 012).

## Dependências

- V17 concluída (grafo, Curator, veredito, projetos).

## Tarefas

### Tarefa 1: Limites de uso como condições de parada
- **Spec:** [`v18-usage-limits`](../openspec/changes/v18-usage-limits/proposal.md)
- **Critérios de aceite:** [ ] tokens, tempo, retentativas por tarefa e de conexão · [ ] parada graciosa com reserva de fechamento · [ ] fonte única de limites
- **Complexidade estimada:** Média

### Tarefa 2: Continuidade entre execuções
- **Spec:** [`v18-research-continuity`](../openspec/changes/v18-research-continuity/proposal.md)
- **Critérios de aceite:** [ ] checkpoint atômico e incremental · [ ] detecção de paradas inesperadas · [ ] retomada sem recomeçar
- **Complexidade estimada:** Alta

### Tarefa 3: Ciclo de hipóteses e exploração ativa
- **Spec:** [`v18-hypothesis-loop`](../openspec/changes/v18-hypothesis-loop/proposal.md)
- **Critérios de aceite:** [ ] hipóteses formais e governança por modo · [ ] decisões registradas · [ ] sugestões do Curator respondidas · [ ] oportunidades só com decisão humana · [ ] critérios de parada
- **Complexidade estimada:** Alta

### Tarefa 4: Researcher como consultor nos modos autônomos
- **Spec:** [`v18-researcher-consult`](../openspec/changes/v18-researcher-consult/proposal.md)
- **Critérios de aceite:** [ ] `ask_researcher` respondido pelo Researcher em `semi`/`auto` · [ ] guarda de consulta antes do buscador · [ ] decisões reservadas ao humano · [ ] consultas registradas e dentro do orçamento
- **Complexidade estimada:** Média

## Ordem de implementação

```
Tarefa 1 ─► Tarefa 2 ─► Tarefa 3
       └──► Tarefa 4 (junto com a Tarefa 3, decisão do pesquisador de 2026-10-01)
```

## Validação da Etapa

- [ ] Todos os testes unitários e de integração passam.
- [ ] Sessão no modo `auto` no Pi 5 que para por limite e é retomada sem repetir trabalho.
- [ ] Sessão no modo `assisted` com aprovação de hipóteses e sugestões do Curator.
- [ ] ADR 010 marcado como Aceito; ADR 001 como Deprecado.
- [ ] PRs merged em `dev`; mudanças arquivadas.
