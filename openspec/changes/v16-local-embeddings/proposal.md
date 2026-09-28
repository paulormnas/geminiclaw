# Proposta: Embeddings Locais e Versionados

**ID:** `v16-local-embeddings` · **Versão:** V16 · **Capacidade:** `embeddings`
**ADRs de origem:** [ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) §3

## Por quê

Levantamento do código (2026-09-28): os dois indexadores do Qdrant **não geram embeddings
reais**. `src/skills/search_deep/indexer.py::_generate_mock_embedding` e
`src/skills/document_processor/indexer.py::_index_vectors`/`search` usam vetores aleatórios de
384 dimensões. A busca semântica, portanto, não funciona hoje. `config.EMBEDDING_MODEL`
existe (`sentence-transformers/all-MiniLM-L6-v2`) mas não é usado, e o pacote `fastembed` já
está no extra `deep_search`.

O ADR 011 decidiu que embeddings são **locais**, usados **somente** para o banco vetorial
interno, **nunca** enviados a provedores externos, e que a versão do modelo é registrada como
**metadado** de cada vetor. Essa é a base da camada de conhecimento (V17).

## O que muda

- **Novo:** pacote `src/embeddings/` com a interface `EmbeddingProvider` e a implementação
  local `FastEmbedProvider` (ONNX, CPU, adequada ao Pi 5).
- **Modificado:** `VectorIndexer` (deep search) e `DocumentIndexer` passam a usar o provedor
  local — os vetores aleatórios são removidos.
- **Novo:** todo ponto gravado no Qdrant carrega os metadados `embedding_model`,
  `embedding_version`, `embedding_dim` e `text_hash`, e o texto de origem permanece
  recuperável.
- **Novo:** comando `geminiclaw embeddings reindex` para revetorizar coleções após troca de
  modelo, e verificação de compatibilidade na inicialização.
- **Fora do escopo:** coleção do grafo de conhecimento (mudança
  `v17-knowledge-semantic-index`).

## Impacto

- **Código:** `src/embeddings/` (novo), `src/skills/search_deep/indexer.py`,
  `src/skills/document_processor/indexer.py`, `src/config.py`, `src/cli.py`,
  `pyproject.toml` (mover `fastembed` para o extra adequado), `scripts/setup_pi.sh`
  (pré-download do modelo).
- **Dados:** vetores existentes são aleatórios e **sem valor** — devem ser regenerados.
- **Memória no Pi 5:** modelo ONNX `all-MiniLM-L6-v2` ~90 MB em RAM; carregado sob demanda e
  uma única vez por processo.

## Aprovações necessárias

- **Reindexação das coleções Qdrant existentes** (`geminiclaw_knowledge`,
  `geminiclaw_documents`): apaga os vetores aleatórios atuais e grava vetores reais. É uma
  operação sobre dados — exige aprovação explícita do pesquisador antes de rodar em ambiente
  com dados.
