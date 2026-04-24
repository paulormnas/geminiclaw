# Roadmap V4 — Inteligência Local (Gemma/Ollama)

Este roadmap descreve a transição do GeminiClaw de um framework dependente de nuvem para uma solução auto-hospedada, utilizando modelos como Gemma 4 através de provedores locais.

---

## Avaliação do Estado Atual (v3.0.0)

- **Orquestração**: Estável. O sistema de containers com volumes mapeados permite desenvolvimento rápido ("hot-reload") e isolamento eficiente.
- **Comunicação**: O protocolo IPC via Unix Sockets é performático para o Raspberry Pi 5.
- **Skills**: Robustas. O registro de ferramentas e a execução de código (PythonSandbox) estão validados.
- **Dependência**: Crítica. O framework é 100% dependente da API do Google Gemini, o que gera latência e riscos de disponibilidade (erros 503 observados).

---

## Etapa V17 — Abstração do Provedor LLM

Objetivo: Permitir que o framework suporte múltiplos backends (Gemini, OpenAI, Anthropic, Local).

### Tarefas

- [ ] Criar `src/llm/` para centralizar a lógica de inferência.
- [ ] Implementar `LLMProvider` (Interface Base) com métodos `generate()` e `generate_stream()`.
- [ ] **Atualizar `@[.env.example]`** com as novas variáveis globais:
  - `LLM_PROVIDER` (google | openai | anthropic | local)
  - `LLM_MODEL` (ex: gemini-2.0-flash, gpt-4o, gemma-4:9b)
  - `LLM_PROVIDER_REQUESTS_PER_MINUTE` (antigo GEMINI_REQUESTS_PER_MINUTE)
  - `LLM_PROVIDER_RATE_LIMIT_COOLDOWN_SECONDS` (antigo GEMINI_RATE_LIMIT_COOLDOWN_SECONDS)
  - Adicionar placeholders para `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.
- [ ] **Atualizar o código do projeto** (`src/config.py`, `src/runner.py`, `src/orchestrator.py`) para utilizar os novos nomes de variáveis.
- [ ] Mover lógica do Google ADK para `src/llm/providers/google.py`.
- [ ] Implementar `src/llm/factory.py` para instanciar o provedor baseado no `.env`.
- [ ] Commit: `feat(llm): introduz abstração de provedores e configuração genérica de LLM`

---

## Etapa V18 — Integração com Ollama (Gemma 4)

Objetivo: Rodar o modelo Gemma 4 localmente no Raspberry Pi 5 ou em servidor da rede via provedor `local`.

### Tarefas

- [ ] Adicionar serviço `ollama` ao `docker-compose.yml` (opcional).
- [ ] Implementar `src/llm/providers/local.py` (ou `ollama.py`) usando a API REST do Ollama.
- [ ] Garantir que o provedor respeite `LLM_PROVIDER_REQUESTS_PER_MINUTE` para evitar sobrecarga do hardware local.
- [ ] Configurar mapeamento de Tool Calling para o modelo local.
- [ ] Commit: `feat(llm): adiciona provedor local com suporte a Gemma 4`

---

## Etapa V19 — Refatoração dos Agentes e Config

Objetivo: Atualizar o runtime dos agentes e o módulo de configuração para usar a nova abstração genérica.

### Tarefas

- [ ] Atualizar `src/config.py` para carregar as novas variáveis `LLM_PROVIDER_*`.
- [ ] Atualizar `agents/runner.py` para consumir `src.llm.factory`.
- [ ] Garantir que o `session_id` e contexto sejam propagados corretamente através dos novos wrappers de provedor.
- [ ] Testar `CodeSkill` com código gerado por diferentes provedores configurados.
- [ ] Commit: `refactor(agents): agentes agora utilizam provedores abstraídos e configuração genérica`

---

## Etapa V20 — Otimização de Recursos e Performance

Objetivo: Garantir fluidez no Raspberry Pi 5 8GB com modelo local ou otimização de custos em nuvem.

### Tarefas

- [ ] Implementar `ContextCompression`: reduzir histórico de chat antes de enviar ao modelo (especialmente relevante para provedores locais).
- [ ] Benchmark comparativo: Google vs Local (Gemma 4) usando as novas métricas de rate limit genéricas.
- [ ] Finalizar `SETUP.md` com instruções para alternância entre provedores.
- [ ] Commit: `perf(pi): otimizações de memória e suporte multi-provider finalizado`

---

## Resumo Técnico

| Componente | Mudança Necessária |
|---|---|
| **Config** | Mudar de `GEMINI_*` para `LLM_PROVIDER_*`. |
| **Runner** | Parar de instanciar `google.adk.runners.InMemoryRunner` diretamente; usar Factory. |
| **Env** | Adicionar chaves para OpenAI/Anthropic para redundância. |
| **Memória** | Reservar RAM quando `LLM_PROVIDER=local`. |
