---
description: Workflow para execução do projeto e validação de agentes com diferentes LLMs
---

# Workflow de Benchmark Comparativo — GeminiClaw

Este workflow descreve os passos para executar o projeto e comparar o desempenho entre a inferência local (Ollama) e em nuvem (Google Gemini) resolvendo o mesmo problema complexo.

---

## 1. Preparação do Ambiente

```bash
source .venv/bin/activate
uv sync --all-groups
```

---

## 2. Execução do Benchmark: Pipeline Iris

O teste consiste em rodar o prompt abaixo em ambos os provedores e comparar os tempos e artefatos gerados.

**Prompt do Desafio:**
> "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."

### Passo A: Execução Local (Ollama)
```bash
export LLM_PROVIDER=ollama
export LLM_MODEL=qwen3.5:4b
export OLLAMA_BASE_URL=http://localhost:11434
export OUTPUT_BASE_DIR=outputs/local

uv run main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

### Passo B: Execução em Nuvem (Google Gemini)
```bash
export LLM_PROVIDER=google
export LLM_MODEL=gemini-2.0-flash
export OUTPUT_BASE_DIR=outputs/cloud
unset OLLAMA_BASE_URL

uv run main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

---

## 3. Comparação de Resultados

Após as duas execuções, utilize os comandos abaixo para realizar a comparação:

### Métricas de Tempo
```bash
uv run main.py history
```

### Validação de Artefatos
Compare os arquivos gerados:
- **Local (`outputs/local/`)**: Verifique se o Qwen3.5-4B conseguiu estruturar o código corretamente e salvar os `.json` e `.pkl`.
- **Nuvem (`outputs/cloud/`)**: Referência de qualidade (Gold Standard).

**Critérios de Comparação:**
1.  **Acurácia dos Modelos**: Os modelos treinados em ambos os ambientes atingiram métricas similares?
2.  **Qualidade da Recomendação**: A justificativa final (`recommendation.md`) é coerente em ambos?
3.  **Integridade**: Todos os 6 artefatos exigidos foram criados?

---

## Dicas para Raspberry Pi 5
- Use `DEPLOYMENT_PROFILE=pi5` para otimizar timeouts e concorrência.
- Se o Ollama falhar por timeout, ajuste `AGENT_TIMEOUT_SECONDS=600`.
