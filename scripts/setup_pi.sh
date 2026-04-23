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
  echo -e "${RED}[!] Este script precisa ser executado como root (sudo).${NC}"
  exit 1
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

echo -e "${GREEN}[*] Instalando/Atualizando dphys-swapfile...${NC}"
apt-get update
apt-get install -y dphys-swapfile

echo -e "${GREEN}[*] Configurando SWAP de 4GB...${NC}"
# Substitui o valor do CONF_SWAPSIZE por 4096 (4GB) no arquivo de configuração do swapfile
sed -i 's/^#*CONF_SWAPSIZE=.*/CONF_SWAPSIZE=4096/' /etc/dphys-swapfile

# Reinicia o serviço para aplicar as mudanças
dphys-swapfile setup
systemctl restart dphys-swapfile

echo -e "${GREEN}[*] Otimizando vm.swappiness (evita thrashing desnecessário)...${NC}"
sysctl vm.swappiness=10
# Deixar persistente
if ! grep -q "^vm.swappiness=10" /etc/sysctl.conf; then
    echo "vm.swappiness=10" >> /etc/sysctl.conf
fi

echo -e "${GREEN}[*] Verificando Docker e docker-compose...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}[!] Docker não encontrado. Instalando Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    usermod -aG docker $SUDO_USER
    rm get-docker.sh
fi

apt-get install -y docker-compose-plugin

echo -e "${GREEN}[*] Configurando rede Docker...${NC}"
docker network inspect geminiclaw-net &>/dev/null || docker network create geminiclaw-net >/dev/null

echo -e "${GREEN}[*] Preparando containers (Pre-pull)...${NC}"
docker pull python:3.11-slim
docker pull qdrant/qdrant:latest

echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}   Setup concluído com sucesso!               ${NC}"
echo -e "${GREEN}   Reinicie o terminal se o docker foi insta- ${NC}"
echo -e "${GREEN}   lado pela primeira vez.                    ${NC}"
echo -e "${GREEN}==============================================${NC}"
