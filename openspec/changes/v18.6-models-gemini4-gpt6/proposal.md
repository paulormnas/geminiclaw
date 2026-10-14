# Proposta: Migração para Gemini 4 e GPT-6, com a versão dos modelos registrada por execução

**ID:** `v18.6-models-gemini4-gpt6` · **Versão:** V18.6 · **Capacidades:** `llm-providers`, `benchmark`
**ADRs de origem:** [ADR 017](../../../docs/decisions/adr_017_catalogo_modelos_roteador.md) (catálogo versionado de modelos),
[ADR 020](../../../docs/decisions/adr_020_independencia_validator.md) (matriz com juiz de outra família),
[ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) (proveniência: versão efetiva do modelo).
**Origem dos requisitos:** pedido do pesquisador (2026-10-14): usar a versão mais nova de cada modelo na matriz do benchmark,
aproveitando o preço promocional do Gemini 4, e registrar a versão usada, porque ela é informação de reprodutibilidade.
**Depende de:** `v18.6-benchmark-harness` e `v18.6-validator-independence` (arquivadas).

## Por quê

1. A matriz `matrix_modelos_v18_6.json` usa `google/gemini-3.8-flash` e `openai/gpt-5.6-terra`. Em 2026-10-14 existem
   `gemini-4-argon` (Google, estável, preço promocional até 2026-11-30) e a família GPT-6 (`gpt-6.1-sol`, `gpt-6-astra`,
   `gpt-6-luna`). Os IDs foram conferidos nas páginas oficiais e nas listas de modelos das contas do projeto (Pi 5, 2026-10-14).
   A Anthropic já está na geração mais nova (Claude 5.5: `claude-sonnet-5-5`, `claude-haiku-5-5`).
2. O benchmark guarda hoje só o modelo **pedido**. A versão que o provedor informa ter servido (`versao_efetiva`) existe
   na sessão (`allocation_profile`, `token_usage.versao_efetiva`), mas não entra no resultado nem no relatório. Sem ela, não
   se reproduz nem se compara uma rodada com outra.
3. O preço do Gemini 4 muda em 2026-12-01 (dobra). Um custo calculado sem a vigência distorceria comparações futuras.

## O que muda

### Modificado
- **Catálogo (`src/llm/catalog.yaml`, versão 5):** entram `google/gemini-4-argon` e `openai/gpt-6.1-sol`; saem
  `google/gemini-3.8-flash` e `openai/gpt-5.6-terra` (sem débito técnico: nenhuma configuração aponta para eles). Os modelos
  `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gpt-6-luna` e os da Anthropic ficam. A preferência de cada papel troca
  um modelo pelo outro na mesma posição.
- **Padrões:** `GOOGLE_FALLBACK_MODEL` passa a `gemini-4-argon`; o alias obsoleto de visão (`OCR_PROVIDER=gemini`) aponta para
  `google/gemini-4-argon`; `.env.example`, `.agents/workflows/run_project.md` e os testes trocam os nomes.
- **Preços (`src/llm/pricing.py`):** `gemini-4-argon` com a vigência promocional; `gpt-6.1-sol` com `cached_input` e a faixa de
  contexto longo; remoção dos dois modelos antigos.
- **Matriz:** `gemini-3.8-flash` → `gemini-4-argon` e `gpt-5.6-terra` → `gpt-6.1-sol`, mesmas quatro combinações; `budget_usd`
  de US$ 14 para `anthropic`, `openai` e `google`.

### Novo
- **Versão dos modelos por execução:** cada resultado do benchmark traz, por papel, o modelo pedido, a família e a
  `versao_efetiva` informada pelo provedor, mais a data da execução e os preços aplicados; o relatório mostra a tabela.
- **Preço com vigência:** `Price` aceita uma data de fim de promoção e o preço posterior.

### Fora do escopo
- Ajuste de esforço de raciocínio do Gemini 4 (ver questão 1 do design).
- Troca do modelo de embeddings, do Ollama e do `gpt-6-luna`.
- Segundo Qdrant: o benchmark continua no mesmo Qdrant (decisão do pesquisador, 2026-10-14); o reset apaga as coleções do
  sistema e elas são recriadas sob demanda.

## Impacto

- **Código:** `src/llm/catalog.yaml`, `src/llm/pricing.py`, `src/config.py`, `src/llm/vision.py`, `src/llm/base.py` (docstring),
  `scripts/benchmark/{run_benchmark,report}.py`, `scripts/benchmark/matrix_modelos_v18_6.json`, `.env.example`.
- **Testes:** os 21 arquivos que citam `gemini-3.8-flash` ou `gpt-5.6-terra` e as fixtures de catálogo.
- **Contratos:** `catalog.local.yaml` que cite os modelos removidos falha na inicialização com a mensagem de modelo
  desconhecido (comportamento existente). O JSON de resultados ganha campos aditivos.
- **Schema de banco:** nenhum.
- **Custo:** Gemini 4 Argon custa US$ 2/10 por 1M tokens (promoção) contra US$ 0,75/3,75 do 3.8 Flash.

## Aprovações necessárias

Nenhuma de schema, Dockerfile ou `docker-compose.yml`. A remoção dos dois modelos do catálogo é troca de configuração, não
exclusão de arquivo. O `.env` do Pi (`BENCHMARK_*`) não faz parte desta mudança e não entra no `.env.example`.
