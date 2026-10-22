#!/bin/bash
# Segunda tarefa do corpus de memória entre projetos (v18.9-memory-evaluation): classificação no dataset Wine.
# Mesmo molde do run.sh (Iris): único container de execução é a imagem do sandbox de código.
uv run python -m scripts.platform_images ensure --imagens sandbox --yes
docker compose up -d
uv venv .venv
source .venv/bin/activate && uv sync && uv run python main.py "$(cat scripts/benchmark/task_wine.txt)"
