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

## 2. Benchmark Comparativo: Pipeline Iris

O objetivo deste teste é resolver o **mesmo problema** em dois ambientes distintos para comparar tempo de execução, qualidade do código e precisão dos resultados.

### O Problema
> "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."

---

### Execução A: LLM Local (Ollama)

Ideal para o Raspberry Pi 5. Utiliza o modelo configurado no Ollama.

```bash
# Configurações para Ollama
export LLM_PROVIDER=ollama
export LLM_MODEL=qwen3.5:4b
export OLLAMA_BASE_URL=http://localhost:11434

# Definir diretório de saída exclusivo para o benchmark local
export OUTPUT_BASE_DIR=outputs/local

# Executar a resolução do problema
uv run python main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

---

### Execução B: LLM Terceiro (Google)

Utiliza o Google Gemini via API (Cloud). Serve como referência de "Gold Standard".

```bash
# Configurações para Google
export LLM_PROVIDER=google
export LLM_MODEL=gemini-2.0-flash
# export GEMINI_API_KEY=sua_chave_aqui

# Definir diretório de saída exclusivo para o benchmark cloud
export OUTPUT_BASE_DIR=outputs/cloud

# Executar a resolução do problema (mesmo prompt)
uv run python main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

---

## 3. Comparação de Resultados

Após concluir ambas as execuções, realize a comparação técnica:

### 1. Performance (Tempo de Execução)
Consulte o histórico para ver a duração de cada tarefa:
```bash
uv run python main.py history
```

### 2. Qualidade dos Artefatos
Compare os diretórios gerados:
- **Local**: `outputs/local/`
- **Cloud**: `outputs/cloud/`

**Critérios de avaliação:**
- Os gráficos gerados são legíveis?
- O modelo local conseguiu treinar algoritmos válidos?
- A justificativa da recomendação final é coerente em ambos?

---

## Dicas de Performance (Pi 5)

- **Perfil**: Se estiver no Raspberry Pi 5, certifique-se de usar `DEPLOYMENT_PROFILE=pi5`.
- **Timeout**: Se a execução local demorar demais, você pode aumentar o limite: `export AGENT_TIMEOUT_SECONDS=600`.
- **Memória**: Monitore o uso de RAM do Ollama; se ocorrer OOM, reduza `OLLAMA_NUM_CTX` no `.env`.
