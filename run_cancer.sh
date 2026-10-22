#!/bin/bash
# Tarefa do corpus de memória entre projetos: classificação no dataset cancer.
uv run python -m scripts.platform_images ensure --imagens sandbox --yes
docker compose up -d
uv venv .venv
source .venv/bin/activate && uv sync && uv run python main.py "$(cat scripts/benchmark/task_cancer.txt)"
