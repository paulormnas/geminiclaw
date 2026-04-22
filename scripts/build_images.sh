#!/usr/bin/env bash
set -e

echo "==============================================="
echo "  Construindo imagens Docker GeminiClaw (ARM64) "
echo "==============================================="

# Diretório raiz do projeto (um nível acima do script)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Define as tags
IMAGE_FULL="geminiclaw-base:latest"
IMAGE_SLIM="geminiclaw-base-slim:latest"

echo ""
echo "[1/2] Construindo imagem SLIM (sem dependências pesadas)..."
docker build \
  --progress=plain \
  -t "$IMAGE_SLIM" \
  -f "$PROJECT_ROOT/containers/Dockerfile.slim" \
  "$PROJECT_ROOT"

echo ""
echo "[2/2] Construindo imagem FULL (com fastembed e qdrant-client)..."
docker build \
  --progress=plain \
  -t "$IMAGE_FULL" \
  -f "$PROJECT_ROOT/containers/Dockerfile" \
  "$PROJECT_ROOT"

echo ""
echo "==============================================="
echo "  Build concluído com sucesso!"
echo "==============================================="
docker images | grep -E "geminiclaw-base"
