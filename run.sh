#!/bin/bash
# Único container de execução: a imagem do sandbox de código (os agentes rodam como processo local).
docker build -t geminiclaw-base -f containers/Dockerfile .
docker compose up -d
uv venv .venv
source .venv/bin/activate && uv sync && uv run python main.py "Implemente um pipeline de classificação supervisionada para o dataset Iris. O pipeline deve incluir análise exploratória dos dados, pré-processamento, treinamento de ao menos dois algoritmos diferentes, avaliação comparativa dos modelos e uma recomendação final justificada sobre qual modelo usar em produção. Todos os artefatos gerados devem ser salvos em disco."