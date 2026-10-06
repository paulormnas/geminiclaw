# Imagem do sandbox de código (ADR 018 §1; usada por src/skills/code/sandbox.py).
# Mínima: Python, uv e o conjunto científico básico travado com hashes. Sem código do projeto
# (src/, agents/), extras do projeto nem SDKs de provedores LLM. Pacotes fora do conjunto básico
# são instalados sob demanda em /deps, sem root, pelo próprio sandbox.
#
# Contexto de build: raiz do repositório (ver scripts/build_images.sh). Sem --platform fixo:
# constrói na arquitetura do host (a seleção de imagens por plataforma é da v16-platform-images).
FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8.9 /uv /bin/uv

COPY containers/sandbox/requirements.lock /tmp/requirements.lock
RUN uv venv /opt/sandbox-venv \
 && uv pip install --python /opt/sandbox-venv/bin/python --require-hashes --no-cache \
      -r /tmp/requirements.lock \
 && rm /tmp/requirements.lock

# /opt/sandbox-venv pertence a root e é somente leitura para o usuário do script (UID do host,
# definido na criação do container).
ENV PATH=/opt/sandbox-venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp \
    HOME=/tmp

WORKDIR /outputs
