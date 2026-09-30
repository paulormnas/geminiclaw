#!/usr/bin/env bash
set -e

echo "==============================================="
echo "  Construindo a imagem do sandbox de código     "
echo "==============================================="

# Os agentes rodam como processo local (ADR 014); a única imagem de execução é a do sandbox
# de código, usada pela skill de código. A imagem ainda é grande e será enxugada (ADR 018).
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_SANDBOX="geminiclaw-base:latest"

docker build \
  --progress=plain \
  -t "$IMAGE_SANDBOX" \
  -f "$PROJECT_ROOT/containers/Dockerfile" \
  "$PROJECT_ROOT"

echo ""
echo "==============================================="
echo "  Build concluído com sucesso!"
echo "==============================================="
docker images | grep -E "geminiclaw-base"
