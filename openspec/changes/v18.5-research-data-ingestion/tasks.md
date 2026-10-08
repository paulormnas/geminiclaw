# Tarefas: v18.5-research-data-ingestion

**Estado (2026-10-08):** Não iniciada — nenhum código mergeado.

## 0. Pré-requisitos
- [ ] 0.1 `v18.5-egress-gate` implementada (`PromptFragment`, `EgressGate`, `classify_path`, `LOCALITY_MIN_GROUP_SIZE` definido).

## 1. Manifesto e classificação
- [ ] 1.1 `src/research_data/manifest.py`: leitura com `yaml.safe_load`, esquema estrito, globs, escape de diretório, conflitos, `WARNING` de padrão sem arquivo.
- [ ] 1.2 Extensão de `classify_path` com o manifesto e a regra padrão (design §2).
- [ ] 1.3 `ContextLoader` ignora `dados.yaml` como contexto; README de `input_context/` atualizado.

## 2. Resumo seguro
- [ ] 2.1 `SafeDatasetSummary`: esquema, unidades do cabeçalho, metadados, descritores de formato.
- [ ] 2.2 Estatísticas pela regra de k; faixa arredondada; categóricas e datas (design §4).
- [ ] 2.3 JSON não tabular, documentos marcados, imagens e não processados (design §3).
- [ ] 2.4 `ContextBundle.to_fragments()`; `to_prompt_context()` só com trechos seguros; plano inicial em `src/orchestrator.py` usa os trechos.

## 3. Visão
- [ ] 3.1 `VISION_MODEL` em `src/config.py` e `.env.example`; alias de `OCR_PROVIDER=gemini`.
- [ ] 3.2 `src/llm/vision.py` com Google (código movido) e Ollama (`images`).
- [ ] 3.3 `authorize_vision` antes do envio; recusa cai para OCR local; rotulagem da descrição.
- [ ] 3.4 Remover a chamada direta `genai.Client` de `src/context_loader.py`.

## 4. Registro
- [ ] 4.1 `payload["research_data_markings"]` e `payload["locality_min_group_size"]`.
- [ ] 4.2 Cópia de `dados.yaml` para `input_snapshot/`.
- [ ] 4.3 Banner com contagens por classe e compartilháveis.
- [ ] 4.4 Seção determinística "Dados de entrada e marcações" no relatório final.

## 5. Testes
- [ ] 5.1 Um teste por cenário da spec `research-data`.
- [ ] 5.2 Teste de regressão: o resumo seguro de um CSV de exemplo não contém nenhum valor de célula (varredura de todos os valores do DataFrame no texto).
- [ ] 5.3 Visão com provedores simulados (sem rede).

## 6. Fechamento
- [ ] 6.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 6.2 Revisão nos 7 eixos; PR para `dev`.
