# Tarefas: v17-input-document-index

## 0. Pré-requisitos
- [x] 0.1 `v17-research-project` e `v17-structural-fact-ingestion` concluídas (`projeto_id`, `Insumo`).
- [x] 0.2 Respostas do pesquisador às questões em aberto do design §9 (metadados, momento, avaliação, datasets).

## 1. Enriquecimento e divisão
- [x] 1.1 Cabeçalho fixo (design §3) com truncamento; `versao_enriquecimento`; `hash_cabecalho_projeto`.
- [x] 1.2 `chunker.py`: `content` só com o trecho (remove o prefixo atual); texto para embedding = cabeçalho + trecho.
- [x] 1.3 Descritores sem valores para `dataset`, imagens e `outro` (design §2).

## 2. Indexador
- [x] 2.1 IDs determinísticos (`uuid5`) de documento e de trecho.
- [x] 2.2 Deduplicação por (`projeto_id`, `hash_conteudo`) via `metadata_json`; reenriquecimento quando versão ou cabeçalho mudam.
- [x] 2.3 Payload novo e índices de payload `projeto_id` e `insumo_id`.
- [x] 2.4 `vetorizacao: pendente|ok` e recuperação de pendentes.
- [ ] 2.5 Busca e lista filtradas por projeto; `todos_os_projetos`.

## 3. Orquestração
- [x] 3.1 `src/knowledge/input_index.py`: `index_input_snapshot(sessao, projeto)` com limites de tempo e tamanho; `payload["input_index"]`.
- [ ] 3.2 Chamada no orquestrador após o snapshot e a gravação dos `Insumo`s, antes do planejamento.
- [ ] 3.3 `document_processor ingest` usa o mesmo caminho para `artifacts/`.
- [ ] 3.4 `agents/base/agent.py`: lista só do projeto da sessão.
- [ ] 3.5 `src/embeddings/reindex.py`: refaz o texto enriquecido.
- [x] 3.6 Variáveis do design §6 em `src/config.py`.

## 4. Testes
- [x] 4.1 Primeira sessão, mesma sessão repetida, outro projeto, limite de tempo.
- [x] 4.2 Texto enviado ao embedding (provedor falso que registra entradas); busca sem cabeçalho; mudança de objetivo do projeto.
- [x] 4.3 CSV e imagem só como descritor, sem valores.
- [x] 4.4 Payload completo; grafo indisponível.
- [ ] 4.5 Busca por projeto e em todos os projetos.
- [x] 4.6 Qdrant fora do ar e recuperação.

## 5. Fechamento
- [x] 5.1 `.env.example`.
- [ ] 5.2 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 5.3 Sessão real no Pi 5 com PDFs e um CSV: tempo de indexação e número de pontos registrados no PR.
- [ ] 5.4 Revisão nos 7 eixos; PR para `dev`.
