# Dockerfile base para agentes GeminiClaw
# Stage 1: Builder - Instala dependências usando uv
FROM python:3.11-slim AS builder
LABEL stage=builder component=geminiclaw-base

# Instalar gerenciador de pacotes uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Definir diretório de trabalho
WORKDIR /app

# Copiar arquivos de dependências
COPY pyproject.toml uv.lock ./

# Instalar dependências no virtualenv
RUN uv sync --no-dev --no-install-project

# Stage 2: Runtime - Imagem final otimizada
FROM python:3.11-slim AS runtime
LABEL stage=runtime component=geminiclaw-base

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

# Copiar o ambiente virtual da etapa builder
COPY --from=builder /app/.venv /app/.venv

# Copiar código do framework e dos agentes
COPY src/ /app/src/
COPY agents/ /app/agents/

# Ajustar permissões para o diretório de dados
RUN mkdir /data && chown appuser:appuser /data
VOLUME /data

# Criar diretório para socket IPC e outputs
RUN mkdir -p /tmp/geminiclaw-ipc && chown appuser:appuser /tmp/geminiclaw-ipc
RUN mkdir -p /outputs && chown appuser:appuser /outputs

# Configurações de ambiente para o agente
ENV OUTPUT_BASE_DIR=/outputs
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"

# Mudar para o usuário não-root
USER appuser

# Comando padrão - pode ser sobrescrito pelo docker-compose ou docker run
# Para o framework: python -m src.cli
# Para agentes: python -m agents.base.agent (default)
CMD ["python", "-m", "agents.base.agent"]
