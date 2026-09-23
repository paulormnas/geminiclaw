# Dockerfile para o Developer Agent do GeminiClaw (Roadmap V14.4)
ARG BASE_IMAGE=geminiclaw-base
FROM ${BASE_IMAGE} AS runtime
LABEL stage=runtime component=agent-developer

USER root

# Instala e pré-aquece dependências científicas exigidas pela V14.4
RUN /app/.venv/bin/pip install --no-cache-dir \
    numpy \
    pandas \
    scikit-learn \
    matplotlib \
    seaborn \
    scipy

USER appuser

# Comando padrão — executa o agente developer via loop IPC
CMD ["python", "-m", "agents.developer.agent"]
