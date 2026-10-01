# Roadmap V17 — Camada de Conhecimento Experimental e Curator

## Objetivo

Dar ao assistente memória experimental: um grafo de conhecimento (Apache AGE) com o modelo de
dados do ADR 015, ligado a embeddings locais (Qdrant), alimentado por fatos determinísticos e
pelo agente Curator, com veredito de evidência objetivo e acesso do pesquisador pela CLI
(ADRs 009, 012, 015).

## Dependências

- V16 concluída (embeddings locais, agentes em processo, registro de provedores).
- ADRs 009, 012 e 015 aceitos.

## Tarefas

### Tarefa 1: Armazenamento do grafo
- **Spec:** [`v17-graph-store`](../openspec/changes/v17-graph-store/proposal.md)
- **Critérios de aceite:** [ ] AGE no PostgreSQL do Pi 5 · [ ] schema declarativo · [ ] escrita tipada sem injeção · [ ] papel somente-leitura
- **Complexidade estimada:** Alta

### Tarefa 2: Vocabulário controlado
- **Spec:** [`v17-controlled-vocabulary`](../openspec/changes/v17-controlled-vocabulary/proposal.md)
- **Critérios de aceite:** [ ] domínios do CNPq carregados · [ ] catálogo de métricas · [ ] candidatos e decisão pela CLI
- **Complexidade estimada:** Média

### Tarefa 3: Veredito de evidência
- **Spec:** [`v17-evidence-verdict`](../openspec/changes/v17-evidence-verdict/proposal.md)
- **Critérios de aceite:** [ ] testes-ouro do ADR 015 verdes · [ ] parâmetros configuráveis
- **Complexidade estimada:** Média

### Tarefa 4: Projeto de pesquisa e problema confirmado
- **Spec:** [`v17-research-project`](../openspec/changes/v17-research-project/proposal.md)
- **Critérios de aceite:** [ ] projetos na CLI · [ ] problema redigido pelo Researcher e confirmado pelo pesquisador
- **Complexidade estimada:** Média

### Tarefa 5: Ingestão de fatos estruturais
- **Spec:** [`v17-structural-fact-ingestion`](../openspec/changes/v17-structural-fact-ingestion/proposal.md)
- **Critérios de aceite:** [ ] fatos gravados sem LLM · [ ] causa de falha classificada · [ ] idempotente · [ ] resiliente a grafo indisponível
- **Complexidade estimada:** Alta

### Tarefa 6: Índice semântico e fila de similaridade
- **Spec:** [`v17-knowledge-semantic-index`](../openspec/changes/v17-knowledge-semantic-index/proposal.md)
- **Critérios de aceite:** [ ] mesmo ID no grafo e no Qdrant · [ ] consulta híbrida · [ ] fila fora do grafo sem limite de conexões
- **Complexidade estimada:** Alta

### Tarefa 7: Agente Curator
- **Spec:** [`v17-curator-agent`](../openspec/changes/v17-curator-agent/proposal.md)
- **Critérios de aceite:** [ ] diretrizes do ADR 015 §10 aplicadas pelas ferramentas · [ ] veredito recalculado sem LLM · [ ] promoção de configuração
- **Complexidade estimada:** Alta

### Tarefa 8: CLI do grafo
- **Spec:** [`v17-graph-cli`](../openspec/changes/v17-graph-cli/proposal.md)
- **Critérios de aceite:** [ ] visualização sem LLM · [ ] alteração via Curator com confirmação
- **Complexidade estimada:** Média

### Tarefa 9: Indexação dos insumos com metadados
- **Spec:** [`v17-input-document-index`](../openspec/changes/v17-input-document-index/proposal.md)
- **Critérios de aceite:** [ ] indexação automática e idempotente por projeto · [ ] texto enriquecido com metadados · [ ] datasets e imagens só como descritor · [ ] busca restrita ao projeto
- **Complexidade estimada:** Média

## Ordem de implementação

```
Tarefa 1 ─► Tarefa 2 ─► Tarefa 4 ─► Tarefa 5 ─┐
       └──► Tarefa 6 (após V16 embeddings) ────┼─► Tarefa 7 ─► Tarefa 8
Tarefa 3 (independente, a qualquer momento) ───┘
Tarefa 5 ─► Tarefa 9 (pesquisador decidiu tratá-la depois do ciclo de hipóteses da V18)
```

## Validação da Etapa

- [ ] Todos os testes unitários e de integração passam.
- [ ] Uma sessão real no Pi 5 produz fatos, veredito, descobertas e visualização coerentes.
- [ ] Carga sintética de 10 mil nós com tempos de consulta registrados.
- [ ] Revisões do Analista de Segurança (grafo e CLI).
- [ ] ADRs 009, 012 e 015 marcados como Aceitos.
- [ ] PRs merged em `dev`; mudanças arquivadas.
