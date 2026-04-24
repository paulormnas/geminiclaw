# Roadmap V4 — Inteligência Local (Gemma/Ollama)

Este roadmap descreve a transição do GeminiClaw de um framework dependente de nuvem para uma solução auto-hospedada, utilizando modelos como Gemma 2 através de provedores locais.

---

## Avaliação do Estado Atual (v3.0.0)

- **Orquestração**: Estável. O sistema de containers com volumes mapeados permite desenvolvimento rápido ("hot-reload") e isolamento eficiente.
- **Comunicação**: O protocolo IPC via Unix Sockets é performático para o Raspberry Pi 5.
- **Skills**: Robustas. O registro de ferramentas e a execução de código (PythonSandbox) estão validados.
- **Dependência**: Crítica. O framework é 100% dependente da API do Google Gemini, o que gera latência e riscos de disponibilidade (erros 503 observados).

---

## Etapa V17 — Abstração do Provedor LLM

Objetivo: Permitir que o framework suporte múltiplos backends (Gemini, OpenAI, Ollama).

### Tarefas

- [ ] Criar `src/llm/` para centralizar a lógica de inferência.
- [ ] Implementar `LLMProvider` (Interface Base) com métodos `generate()` e `generate_stream()`.
- [ ] Mover lógica do Google ADK para `src/llm/providers/gemini.py`.
- [ ] Implementar `src/llm/factory.py` para instanciar o provedor baseado no `.env`.
- [ ] Commit: `feat(llm): introduz abstração de provedores para suporte a modelos locais`

---

## Etapa V18 — Integração com Ollama (Gemma 2)

Objetivo: Rodar o modelo Gemma 2 localmente no Raspberry Pi 5 ou em servidor da rede.

### Tarefas

- [ ] Adicionar serviço `ollama` ao `docker-compose.yml` (opcional).
- [ ] Implementar `src/llm/providers/ollama.py` usando a API REST do Ollama.
- [ ] Configurar mapeamento de Tool Calling:
  - Converter definições do ADK para formato de prompt compatível com Gemma.
  - Implementar parser de saída para capturar chamadas de função locais.
- [ ] Otimização para Pi 5:
  - Configurar quantização 4-bit (GGUF) para Gemma 2 9B.
- [ ] Commit: `feat(llm): adiciona provedor Ollama com suporte a Gemma 2`

---

## Etapa V19 — Refatoração dos Agentes para Local-First

Objetivo: Atualizar o runtime dos agentes para usar a nova abstração.

### Tarefas

- [ ] Atualizar `agents/runner.py` para consumir `src.llm.factory`.
- [ ] Ajustar `agents/base/agent.py` para lidar com as diferenças de contexto entre modelos.
- [ ] Implementar fallback: se o modelo local falhar por recursos, tentar Gemini (opcional).
- [ ] Testar `CodeSkill` com código gerado pelo Gemma 2.
- [ ] Commit: `refactor(agents): agentes agora utilizam provedores abstraídos (Local ou Cloud)`

---

## Etapa V20 — Otimização de Recursos e Performance

Objetivo: Garantir fluidez no Raspberry Pi 5 8GB com modelo rodando simultaneamente.

### Tarefas

- [ ] Implementar `ContextCompression`: reduzir histórico de chat antes de enviar ao modelo local.
- [ ] Ajustar `Runner.py` para detectar uso de NPU (se disponível) ou otimizar threads CPU.
- [ ] Benchmark comparativo: Gemini vs Gemma 2 (Latência, Consumo de RAM, Precisão).
- [ ] Finalizar `SETUP.md` com instruções para modo offline total.
- [ ] Commit: `perf(pi): otimizações de memória para inferência local sustentada`

---

## Resumo Técnico

| Componente | Mudança Necessária |
|---|---|
| **Config** | Adicionar `LLM_BACKEND` (gemini/ollama) e `OLLAMA_URL`. |
| **Runner** | Parar de instanciar `google.adk.runners.InMemoryRunner` diretamente. |
| **Dockerfile** | Incluir bibliotecas de inferência se não usar servidor externo. |
| **Memória** | Reservar ~5GB de RAM para o modelo (Pi 5 8GB recomendado). |
