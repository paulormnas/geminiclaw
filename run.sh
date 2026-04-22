#!/bin/bash
docker build -t geminiclaw-base -f containers/Dockerfile
docker build -t geminiclaw-planner -f containers/Dockerfile.planner . && docker build -t geminiclaw-researcher -f containers/Dockerfile.researcher . && docker build -t geminiclaw-validator -f containers/Dockerfile.validator . 
docker compose up -d
uv venv .venv
source .venv/bin/activate && uv sync && uv run python main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."