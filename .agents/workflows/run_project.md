---
description: Workflow para execução do projeto e validação de agentes com diferentes LLMs
---

# Workflow de Execução — GeminiClaw

Este workflow descreve os passos para preparar o ambiente e executar o projeto para resolver problemas complexos, testando a integração com provedores de LLM locais e em nuvem.

---

## 1. Preparação do Ambiente

Antes de executar, garanta que o ambiente virtual está ativo e as dependências (incluindo as de Ciência de Dados para o dataset Iris) estão instaladas.

```bash
# Ativar ambiente virtual
source .venv/bin/activate

# Sincronizar dependências (incluindo grupos opcionais)
uv sync --all-groups
```

---

## 2. Benchmark: Execução Local (Ollama)

Execução do pipeline usando inferência local para medir desempenho e qualidade no hardware atual (ex: Raspberry Pi 5).

```bash
# Configurações para Ollama
export LLM_PROVIDER=ollama
export LLM_MODEL=qwen3.5:4b
export OLLAMA_BASE_URL=http://localhost:11434

# Definir diretório de saída para comparação
export OUTPUT_BASE_DIR=outputs/local

# Executar o problema do Iris
uv run main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

---

## 3. Benchmark: Execução em Nuvem (Google)

Execução do mesmo problema usando a API do Google para referência de "gold standard" e comparação de latência.

```bash
# Configurações para Google
export LLM_PROVIDER=google
export LLM_MODEL=gemini-2.0-flash
# export GEMINI_API_KEY=sua_chave_aqui

# Definir diretório de saída para comparação
export OUTPUT_BASE_DIR=outputs/cloud

# Executar o mesmo problema (mesmo prompt)
uv run main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

---

## 4. Comparação de Resultados e Performance

Após ambas as execuções, compare os tempos e a qualidade dos artefatos.

### Comparação de Tempo de Execução
Use o comando de histórico para ver a duração de cada execução:

```bash
uv run main.py history
```

### Comparação de Artefatos
Compare os arquivos gerados nos dois diretórios:
- **Local**: `outputs/local/`
- **Cloud**: `outputs/cloud/`

Verifique:
1.  **Acurácia**: Os modelos treinados localmente são tão bons quanto os da nuvem?
2.  **Qualidade do Código**: O código gerado pelo modelo local (Qwen) é funcional e bem estruturado?
3.  **Visualizações**: Os gráficos de análise exploratória foram gerados corretamente em ambos?
4.  **Justificativa**: A recomendação final faz sentido em ambos os casos?

---

## Dicas de Performance (Pi 5)
- Se estiver no Raspberry Pi 5, use `DEPLOYMENT_PROFILE=pi5`.
- Se o modelo local demorar demais ou falhar por timeout, aumente `AGENT_TIMEOUT_SECONDS=600`.
- Monitore a temperatura com `vcgencmd measure_temp`.
