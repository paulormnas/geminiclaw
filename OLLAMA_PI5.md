# 🦙 Configuração do Ollama no Raspberry Pi 5

Este guia descreve como configurar o **Ollama** com o modelo **Qwen3.5-4B** para rodar o GeminiClaw localmente no Raspberry Pi 5 (8 GB RAM).

## 🚀 Instalação Automatizada

O projeto fornece um script que automatiza a instalação do Ollama, a configuração do serviço systemd otimizado para o Pi 5 e o download do modelo:

```bash
chmod +x scripts/setup_ollama_pi5.sh
./scripts/setup_ollama_pi5.sh
```

## ⚙️ O que o script configura?

O script aplica as seguintes otimizações no serviço `ollama.service` (via override em `/etc/systemd/system/ollama.service.d/pi5.conf`):

1.  **OLLAMA_NUM_PARALLEL=1**: Força o processamento de uma requisição por vez. Isso é crítico no Pi 5 para evitar que múltiplos agentes simultâneos causem falta de memória (OOM) ou lentidão extrema na CPU.
2.  **OLLAMA_MAX_LOADED_MODELS=1**: Garante que apenas o modelo Qwen3.5-4B fique carregado na RAM.
3.  **OLLAMA_FLASH_ATTENTION=1**: Habilita Flash Attention para reduzir o uso de memória.
4.  **OLLAMA_HOST=0.0.0.0:11434**: Permite que os containers Docker dos agentes acessem o serviço Ollama rodando no host.
5.  **OLLAMA_KEEP_ALIVE=10m**: Mantém o modelo na RAM por 10 minutos após a última requisição, evitando o tempo de carregamento (reload) em tarefas sequenciais.

## 🤖 Por que Qwen3.5-4B?

O modelo **Qwen3.5-4B** (lançado em Março de 2026) foi escolhido para o Pi 5 por oferecer o melhor equilíbrio entre:
- **Tamanho**: ~2.5 GB em Q4_K_M, deixando margem segura nos 8 GB do Pi 5.
- **Velocidade**: ~10-14 tokens/s em CPU pura.
- **Tool Calling**: Excelente suporte para o formato de ferramentas do OpenAI, essencial para o Planner e Validator do GeminiClaw.

## 📝 Configuração do .env

Após rodar o script, atualize seu arquivo `.env`:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen3.5:4b
DEPLOYMENT_PROFILE=pi5
OLLAMA_BASE_URL=http://localhost:11434
```

---

## 🛠️ Desenvolvimento em x86 (Docker)

Se você estiver desenvolvendo em uma máquina x86 (Mac/Linux/Windows) e quiser rodar o Ollama via Docker em vez de nativo, use o profile `local-llm`:

```bash
docker compose --profile local-llm up -d
```

> **Nota:** No Raspberry Pi 5, a instalação **nativa** (via script) é altamente recomendada para obter o máximo desempenho da CPU.
