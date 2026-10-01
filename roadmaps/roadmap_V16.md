# Roadmap V16 — Fundações do Assistente de Pesquisa

## Objetivo

Preparar a base para o assistente digital de pesquisa (ADR 010): tornar o projeto agnóstico a
provedor (ADR 011), gerar embeddings reais e locais (hoje os indexadores usam vetores
aleatórios), executar agentes em processo com código apenas no sandbox (ADR 014) e alinhar os
prompts ao novo propósito.

## Dependências

- V15 (G1, G2, G5, G8, G9, G10) — **concluído** (PRs #50–#57).
- ADRs 010, 011 e 014 aceitos.

## Tarefas

Cada tarefa é uma mudança OpenSpec com proposta, design, tarefas e requisitos em
`openspec/changes/<id>/`.

### Tarefa 1: Registro único de provedores LLM
- **Spec:** [`v16-provider-registry`](../openspec/changes/v16-provider-registry/proposal.md)
- **Módulos afetados:** `src/llm/`, `src/model_router.py`, `pyproject.toml`
- **Critérios de aceite:**
  - [ ] Seleção global e por papel usam o mesmo registro.
  - [ ] Provedor `openai_compatible` com tool calling e streaming.
  - [ ] `google-adk` removido.
- **Complexidade estimada:** Média

### Tarefa 2: Embeddings locais e versionados
- **Spec:** [`v16-local-embeddings`](../openspec/changes/v16-local-embeddings/proposal.md)
- **Módulos afetados:** `src/embeddings/`, indexadores de `search_deep` e `document_processor`
- **Critérios de aceite:**
  - [ ] Nenhum vetor aleatório em código de produção.
  - [ ] Metadados de modelo/versão em todo ponto do Qdrant.
  - [ ] Reindexação sob confirmação.
- **Complexidade estimada:** Média

### Tarefa 3: Agentes em processo; containers só como sandbox
- **Spec:** [`v16-in-process-agents`](../openspec/changes/v16-in-process-agents/proposal.md)
- **Módulos afetados:** `src/orchestrator.py`, `src/agent_runtime/`, `agents/`, `src/runner.py`, `src/ipc.py`
- **Critérios de aceite:**
  - [ ] Fase 1: agentes em processo atrás de `AGENT_RUNTIME`, com salvaguardas do host.
  - [ ] Revisão do Analista de Segurança.
  - [ ] Fase 2 (com aprovação): remoção do modo container de agentes.
- **Complexidade estimada:** Alta

### Tarefa 4: Prompts alinhados ao novo propósito
- **Spec:** [`v16-research-assistant-prompts`](../openspec/changes/v16-research-assistant-prompts/proposal.md)
- **Módulos afetados:** `agents/*/agent.py`, `src/config.py`
- **Critérios de aceite:**
  - [ ] Teste de política de prompts verde.
  - [ ] Nome do produto só via `APP_NAME`.
- **Complexidade estimada:** Baixa

## Ordem de implementação

```
Tarefa 1 ─┬─► Tarefa 3 ─► Tarefa 4
Tarefa 2 ─┘ (independente; pode ser paralela a 1)
```

## Validação da Etapa

- [ ] Todos os testes unitários e de integração passam.
- [ ] Sessão completa no Pi 5 em modo em processo, com tempo e RAM registrados.
- [ ] ADRs 011 e 014 marcados como Aceitos; 003 §1/§3, 004 e 006 como Deprecados.
- [ ] PRs merged em `dev`; mudanças arquivadas em `openspec/changes/archive/`.

---

## Complementos (especificados em 2026-10-01)

Mudanças decorrentes dos ADRs 017 e 018, aprovados em 2026-10-01. Entram depois da etapa de
robustez do pipeline e podem andar em paralelo com a V17.

### Tarefa 5: Catálogo de modelos e roteador por papel
- **Spec:** [`v16-model-catalog-router`](../openspec/changes/v16-model-catalog-router/proposal.md)
- **Critérios de aceite:** [ ] catálogo versionado e validado · [ ] política `self_hosted_only` por padrão · [ ] roteador puro resolvido uma vez por sessão · [ ] `LLM_PROVIDER`/`LLM_MODEL`/`DEFAULT_MODEL` removidas
- **Complexidade estimada:** Alta

### Tarefa 6: Imagem enxuta do sandbox e execução sem root
- **Spec:** [`v16-sandbox-slim-image`](../openspec/changes/v16-sandbox-slim-image/proposal.md)
- **Critérios de aceite:** [ ] imagem sem código do projeto e sem extras · [ ] nenhum comando como root · [ ] falha de instalação fatal · [ ] script sem rede
- **Complexidade estimada:** Média

### Tarefa 7: Identificação de plataforma e seleção de imagens
- **Spec:** [`v16-platform-images`](../openspec/changes/v16-platform-images/proposal.md)
- **Critérios de aceite:** [ ] detecção de Pi 5, macOS e x86_64 · [ ] build e pull nativos com arquitetura conferida · [ ] imagem do sandbox conferida no início da sessão
- **Complexidade estimada:** Média

```
Tarefa 5 (independente)
Tarefa 6 ─► Tarefa 7
```

Validação dos complementos: sessão no Pi 5 com o mapa de modelos no banner e a nova imagem do
sandbox; ADRs 017 e 018 marcados como Aceitos.
