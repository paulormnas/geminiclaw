# Tarefas: v16-local-embeddings

## 1. Provedor local
- [ ] 1.1 Verificar wheel ARM64 do `fastembed` e do `onnxruntime` na versão a fixar.
- [ ] 1.2 Criar `src/embeddings/base.py` (`EmbeddingInfo`, `EmbeddingProvider`, `text_hash`, `embedding_payload`, `get_embedding_provider`).
- [ ] 1.3 Criar `src/embeddings/fastembed_provider.py` com carregamento preguiçoso e lotes.
- [ ] 1.4 Novas configs em `src/config.py` e `.env.example`.
- [ ] 1.5 Testes unitários com provedor falso determinístico (hash → vetor); teste de `text_hash` (normalização).

## 2. Indexadores
- [ ] 2.1 `VectorIndexer`: remover `_generate_mock_embedding`; usar `embed_documents`/`embed_query`; gravar `embedding_payload`.
- [ ] 2.2 `DocumentIndexer`: idem em `_index_vectors` e `search`.
- [ ] 2.3 Verificação de dimensão em `_ensure_collection` (sem recriação automática).
- [ ] 2.4 Filtro de pontos desatualizados em `search` com aviso.
- [ ] 2.5 Testes: indexar e buscar com provedor falso retorna o documento mais próximo; coleção com dimensão diferente desabilita a busca com aviso.

## 3. Reindexação
- [ ] 3.1 Comando `geminiclaw embeddings reindex` em `src/cli.py` (confirmação, `--collection`, `--yes`).
- [ ] 3.2 Testes de integração com Qdrant de teste: pontos antigos são atualizados; pontos sem texto de origem são reportados.

## 4. Setup do Pi
- [ ] 4.1 `scripts/setup_pi.sh`: pré-download do modelo e `EMBEDDING_OFFLINE=true`.
- [ ] 4.2 Mover `fastembed` para dependência usada pelo núcleo (ou extra `knowledge`) e `uv lock`.

## 5. Fechamento
- [ ] 5.1 **Com aprovação do pesquisador**, rodar a reindexação no ambiente com dados.
- [ ] 5.2 Ruff, testes, revisão nos 7 eixos, PR.
