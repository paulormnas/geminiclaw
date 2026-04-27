---
description: Workflow para execução do projeto e validação de agentes com diferentes LLMs
---

# Workflow de Execução — GeminiClaw

Este workflow descreve os passos para preparar o ambiente e executar o projeto para resolver problemas complexos, garantindo a validação em **ambos os ambientes** (local e nuvem) para fins de benchmark e comparação.

---

## 1. Preparação do Ambiente

Antes de iniciar os testes, garanta que o ambiente virtual está ativo e as dependências estão sincronizadas.

```bash
# Ativar ambiente virtual
source .venv/bin/activate

# Sincronizar dependências (incluindo grupos opcionais para Data Science)
uv sync --all-groups
```

---

## 2. FASE 1: Execução com LLM Local (Ollama)

O objetivo desta fase é validar a autonomia do agente em hardware local (ex: Raspberry Pi 5).

### Configuração e Sanidade
```bash
# Configurações para Ollama
export LLM_PROVIDER=ollama
export LLM_MODEL=qwen3.5:4b
export OLLAMA_BASE_URL=http://localhost:11434
export OUTPUT_BASE_DIR=outputs/local

# Teste de sanidade
uv run main.py "Diga olá e confirme que você é um agente rodando localmente."
```

### Resolução do Problema (Iris Pipeline)
**IMPORTANTE:** Execute o comando abaixo para gerar os resultados locais.

```bash
uv run main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

---

## 3. FASE 2: Execução com LLM em Nuvem (Google Gemini)

O objetivo desta fase é obter uma referência de alta performance ("gold standard") para comparar com a execução local.

### Configuração e Sanidade
```bash
# Configurações para Google
export LLM_PROVIDER=google
export LLM_MODEL=gemini-2.0-flash
export OUTPUT_BASE_DIR=outputs/cloud
# export GEMINI_API_KEY=sua_chave_aqui
unset OLLAMA_BASE_URL

# Teste de sanidade
uv run main.py "Diga olá e confirme que você é o modelo Gemini na nuvem."
```

### Resolução do Problema (Iris Pipeline)
**IMPORTANTE:** Execute o **mesmo** comando abaixo para gerar os resultados na nuvem.

```bash
uv run main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."
```

---

## 4. Comparação Final de Performance e Resultados

Após concluir as duas fases, realize a comparação técnica:

### Comparação de Tempo
Verifique a duração de cada execução no histórico do projeto:
```bash
uv run main.py history
```

### Comparação de Qualidade
Inspecione os diretórios de saída:
- **Local**: `outputs/local/`
- **Nuvem**: `outputs/cloud/`

Analise se o modelo local (Qwen) foi capaz de gerar artefatos com o mesmo rigor estatístico e qualidade de código que o modelo na nuvem (Gemini).

---

## Dicas de Performance (Pi 5)
- No Raspberry Pi 5, use `DEPLOYMENT_PROFILE=pi5`.
- Aumente `AGENT_TIMEOUT_SECONDS=600` para o Ollama se as tarefas de treinamento demorarem.
- Monitore a temperatura: `vcgencmd measure_temp`.
