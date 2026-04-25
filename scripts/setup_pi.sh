#!/usr/bin/env bash
set -e

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}==============================================${NC}"
echo -e "${CYAN}   Setup GeminiClaw (Raspberry Pi 5)          ${NC}"
echo -e "${CYAN}==============================================${NC}"

# Detectar OS
OS_NAME=$(uname -s)
if [ "$OS_NAME" == "Darwin" ]; then
    echo -e "${YELLOW}[!] Detectado macOS (Darwin).${NC}"
    echo -e "${YELLOW}As configurações de SWAP e sysctl são exclusivas do Linux e serão ignoradas.${NC}"
    
    # Criar rede docker se não existir no mac
    if command -v docker &> /dev/null; then
        echo -e "${GREEN}[*] Verificando rede Docker geminiclaw-net...${NC}"
        docker network inspect geminiclaw-net &>/dev/null || docker network create geminiclaw-net >/dev/null
        echo -e "${GREEN}[*] Rede Docker configurada.${NC}"
        
        echo -e "${GREEN}[*] Fazendo pull das imagens base...${NC}"
        docker pull python:3.11-slim
        docker pull qdrant/qdrant:latest
    else
        echo -e "${RED}[!] Docker não encontrado no macOS. Instale o Docker Desktop.${NC}"
    fi
    
    echo -e "${GREEN}[*] Setup concluído para macOS.${NC}"
    exit 0
fi

# Checar Root para Linux
if [ "$EUID" -ne 0 ]; then
  echo -e "${YELLOW}[!] Este script não está sendo executado como root. Algumas operações (swap, sysctl, apt) podem falhar.${NC}"
  # exit 1 (Removido por solicitação do usuário para tentar sem sudo)
fi

echo -e "${GREEN}[*] Verificando espaço em disco...${NC}"
# Pegar o valor de blocos disponíveis (em kB)
AVAILABLE_KB=$(df / | awk 'NR==2 {print $4}')
# 10 GB = 10485760 kB
if [ "$AVAILABLE_KB" -lt 10485760 ]; then
    echo -e "${RED}[!] Espaço em disco insuficiente. Necessário no mínimo 10GB livres na partição root.${NC}"
    exit 1
fi
echo -e "${GREEN}[*] Espaço em disco OK.${NC}"

# Instalar dphys-swapfile se necessário
if ! dpkg -s dphys-swapfile &> /dev/null; then
    echo -e "${GREEN}[*] Instalando dphys-swapfile...${NC}"
    apt-get update
    apt-get install -y dphys-swapfile
else
    echo -e "${GREEN}[*] dphys-swapfile já está instalado.${NC}"
fi

# Configurar SWAP se necessário
CURRENT_SWAPSIZE=$(grep "^CONF_SWAPSIZE=" /etc/dphys-swapfile | cut -d'=' -f2 || echo "0")
if [ "$CURRENT_SWAPSIZE" != "4096" ]; then
    echo -e "${GREEN}[*] Tentando configurar SWAP de 4GB...${NC}"
    if sed -i 's/^#*CONF_SWAPSIZE=.*/CONF_SWAPSIZE=4096/' /etc/dphys-swapfile 2>/dev/null; then
        dphys-swapfile setup || true
        systemctl restart dphys-swapfile || true
        echo -e "${GREEN}[*] SWAP configurado para 4GB.${NC}"
    else
        echo -e "${YELLOW}[!] Falha ao configurar SWAP (Permissão negada). Pulando...${NC}"
    fi
else
    echo -e "${GREEN}[*] SWAP já configurado para 4GB.${NC}"
fi

# Otimizar vm.swappiness se necessário
CURRENT_SWAPPINESS=$(sysctl -n vm.swappiness 2>/dev/null || echo "0")
if [ "$CURRENT_SWAPPINESS" != "10" ]; then
    echo -e "${GREEN}[*] Tentando otimizar vm.swappiness...${NC}"
    if sysctl vm.swappiness=10 2>/dev/null; then
        if ! grep -q "^vm.swappiness=10" /etc/sysctl.conf 2>/dev/null; then
            echo "vm.swappiness=10" >> /etc/sysctl.conf 2>/dev/null || true
        fi
        echo -e "${GREEN}[*] vm.swappiness otimizado.${NC}"
    else
        echo -e "${YELLOW}[!] Falha ao otimizar vm.swappiness (Permissão negada). Pulando...${NC}"
    fi
else
    echo -e "${GREEN}[*] vm.swappiness já está em 10.${NC}"
fi

# Verificar Docker
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}[!] Docker não encontrado. Tentando instalar Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    if sh get-docker.sh 2>/dev/null; then
        usermod -aG docker $SUDO_USER || true
        rm get-docker.sh
    else
        echo -e "${RED}[!] Falha ao instalar Docker (Permissão negada).${NC}"
        rm -f get-docker.sh
    fi
else
    echo -e "${GREEN}[*] Docker já está instalado. $(docker --version)${NC}"
fi

# Verificar docker-compose-plugin
if ! dpkg -s docker-compose-plugin &> /dev/null; then
    echo -e "${GREEN}[*] Tentando instalar docker-compose-plugin...${NC}"
    apt-get install -y docker-compose-plugin 2>/dev/null || echo -e "${YELLOW}[!] Falha ao instalar docker-compose-plugin. Pulando...${NC}"
else
    echo -e "${GREEN}[*] docker-compose-plugin já está instalado.${NC}"
fi

echo -e "${GREEN}[*] Verificando rede Docker...${NC}"
if ! docker network inspect geminiclaw-net &>/dev/null; then
    echo -e "${GREEN}[*] Criando rede geminiclaw-net...${NC}"
    docker network create geminiclaw-net 2>/dev/null || echo -e "${YELLOW}[!] Falha ao criar rede Docker. Verifique se o docker está rodando e se você tem permissões.${NC}"
else
    echo -e "${GREEN}[*] Rede geminiclaw-net já existe.${NC}"
fi

echo -e "${GREEN}[*] Preparando containers (Pre-pull)...${NC}"
docker pull python:3.11-slim || echo -e "${YELLOW}[!] Falha ao fazer pull da imagem python:3.11-slim.${NC}"
docker pull qdrant/qdrant:latest || echo -e "${YELLOW}[!] Falha ao fazer pull da imagem qdrant:latest.${NC}"

echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}   Setup finalizado (com possíveis avisos).   ${NC}"
echo -e "${GREEN}==============================================${NC}"
