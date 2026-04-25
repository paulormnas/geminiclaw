#!/usr/bin/env bash
set -euo pipefail

# scripts/setup_ollama_pi5.sh - Configura Ollama no Raspberry Pi 5 para o GeminiClaw
# Roadmap V4 - Etapa V20.1

echo "=== Instalando Ollama no Raspberry Pi 5 ==="
curl -fsSL https://ollama.com/install.sh | sh

echo "=== Configurando serviço systemd ==="
# Cria override para configurações específicas do Pi 5
sudo mkdir -p /etc/systemd/system/ollama.service.d
cat <<EOF | sudo tee /etc/systemd/system/ollama.service.d/pi5.conf
[Service]
# Um request por vez (CPU-only — paralelismo causa thrashing)
Environment="OLLAMA_NUM_PARALLEL=1"
# Apenas 1 modelo na RAM — não trocar de modelo entre agentes
Environment="OLLAMA_MAX_LOADED_MODELS=1"
# Flash Attention reduz uso de memória (se disponível no runtime ARM)
Environment="OLLAMA_FLASH_ATTENTION=1"
# Aceitar conexões dos containers Docker
Environment="OLLAMA_HOST=0.0.0.0:11434"
# Keep-alive: manter modelo na RAM entre requests (evita reload lento)
Environment="OLLAMA_KEEP_ALIVE=10m"
EOF

sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama

echo "=== Baixando Qwen3.5-4B (aguarde ~2.3 GB de download) ==="
ollama pull qwen3.5:4b

echo "=== Testando inferência ==="
# Aguarda um pouco para o serviço subir totalmente
sleep 5
ollama run qwen3.5:4b "Responda apenas: OK" --nowordwrap

echo "=== Ollama configurado com sucesso! ==="
echo "Modelo ativo: qwen3.5:4b"
echo "Endpoint: http://localhost:11434"
echo "Dica: Use LLM_PROVIDER=ollama e LLM_MODEL=qwen3.5:4b no seu arquivo .env"
