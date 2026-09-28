# Proposta: Índice Semântico do Grafo e Fila de Similaridade

**ID:** `v17-knowledge-semantic-index` · **Versão:** V17 · **Capacidade:** `knowledge-semantics`
**ADRs de origem:** [ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) §3,
[ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §6; discussão, questão 5

## Por quê

O grafo guarda relações explícitas; a similaridade semântica encontra o que está **próximo em
significado** — é ela que revela que uma descoberta em química pode interessar a um problema
em história. O ADR 015 decidiu: o ponto no Qdrant usa o **mesmo ID** do nó; três faixas de
similaridade (≥ 0,90 duplicata; 0,60–0,90 relacionado; < 0,60 ignorar), com a faixa
0,60–0,70 valendo **só entre domínios diferentes**; **sem limite de conexões**; os pares
candidatos ficam numa **fila fora do grafo** e só viram aresta `SEMELHANTE_A` quando o Curator
confirma.

## O que muda

- **Novo:** coleção Qdrant `knowledge_nodes` com um ponto por nó vetorizável, ID
  compartilhado e metadados de embedding (ADR 011).
- **Novo:** texto canônico por tipo de nó, estado de vetorização e rotina de reconciliação.
- **Novo:** API de busca semântica e **consulta híbrida** (Qdrant → travessia no grafo →
  ranking por similaridade × confiança × recência).
- **Novo:** tabela `similarity_queue` com os pares candidatos, prioridade e decisão; geração
  automática de candidatos quando nós são criados ou alterados.
- **Novo:** `geminiclaw knowledge stats` com a taxa de confirmação da fila e sugestão de
  ajuste de limiares.
- **Fora do escopo:** a revisão dos candidatos (Curator).

## Impacto

- **Código:** `src/knowledge/semantic_index.py` (novo), `src/knowledge/similarity_queue.py`
  (novo), `src/knowledge/graph_store.py` (gancho pós-escrita), `src/knowledge/schema.py`
  (propriedade `estado_vetorizacao`), `src/config.py`, `src/cli.py`.
- **Dependência:** `v16-local-embeddings` (provedor local e metadados).

## Aprovações necessárias

1. **Nova tabela relacional `similarity_queue`** (mudança de schema) — aprovação explícita.
2. **Nova coleção Qdrant `knowledge_nodes`** — coberta por esta proposta aprovada.
