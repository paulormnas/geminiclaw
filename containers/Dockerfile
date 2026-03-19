# Dockerfile base para agentes GeminiClaw
FROM python:3.11-slim

# Evitar criação de arquivos .pyc e habilitar logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalar dependências de sistema mínimas se necessário
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Criar usuário não-root por segurança (conforme regras de desenvolvimento)
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Definir diretório de trabalho
WORKDIR /app

# Instalar gerenciador de pacotes uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copiar arquivos de dependências
COPY pyproject.toml uv.lock ./

# Instalar dependências (sem o orquestrador, apenas o necessário para agentes)
RUN uv sync --no-dev --no-install-project

# Copiar código do framework e dos agentes
COPY src/ /app/src/
COPY agents/ /app/agents/

# Ajustar permissões para o diretório de dados
RUN mkdir /data && chown appuser:appuser /data
VOLUME /data

# Criar diretório para socket IPC
RUN mkdir -p /tmp/geminiclaw-ipc && chown appuser:appuser /tmp/geminiclaw-ipc

# Mudar para o usuário não-root
USER appuser

# Mapear GENAI_API_KEY → GOOGLE_API_KEY (ADK espera GOOGLE_API_KEY)
ENV GOOGLE_API_KEY=${GENAI_API_KEY}

# Comando padrão
CMD ["python", "-m", "agents.base.agent"]
