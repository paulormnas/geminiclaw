#!/usr/bin/env bash
set -e

echo "==============================================="
echo "  Construindo a imagem do sandbox de código     "
echo "==============================================="

# Os agentes rodam como processo local (ADR 014); a única imagem de execução é a do sandbox
# de código, usada pela skill de código (ADR 018). Até a v16-platform-images, este script
# constrói a imagem na arquitetura do host. O nome vem de SANDBOX_IMAGE (padrão code-sandbox:latest).
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_SANDBOX="${SANDBOX_IMAGE:-code-sandbox:latest}"

docker build \
  --progress=plain \
  -t "$IMAGE_SANDBOX" \
  -f "$PROJECT_ROOT/containers/sandbox/Dockerfile" \
  "$PROJECT_ROOT"

echo ""
echo "==============================================="
echo "  Build concluído com sucesso!"
echo "==============================================="
docker images "$IMAGE_SANDBOX"
