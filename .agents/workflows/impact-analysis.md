---
description: Análise de impacto e proposta técnica para mudanças no GeminiClaw
---

# Workflow: Análise de Impacto & Proposta Técnica

Este workflow orienta a avaliação sistemática de impacto para qualquer mudança relevante no GeminiClaw — framework de orquestração de agentes Gemini para Raspberry Pi 5.

---

## Quando Usar

- Antes de implementar qualquer nova funcionalidade, refatoração ou correção estrutural.
- Quando uma mudança afeta mais de um módulo, agente ou contrato de IPC.
- Quando uma mudança pode impactar a infraestrutura Docker, banco de dados ou sandboxes.

---

## Eixos de Análise

Toda proposta deve avaliar o impacto nos seguintes eixos:

### 1. Orquestrador & Loop Autônomo
- Planejamento de subtarefas e DAG de execução.
- Dispatch de containers, retries, timeout.
- Injeção de contexto e manifest de workspace.
- Ciclo ReAct (Reasoning + Acting).

### 2. Agentes ADK & Prompts
- System instructions e tools registradas.
- Schemas de tool call e contratos IPC.
- Modelos atribuídos por papel.

### 3. Sandboxes & Containers Docker
- Volumes montados e isolamento de execução.
- Limites de memória/CPU para o Raspberry Pi 5.
- Rede `geminiclaw-net` e containers efêmeros.
- Permissões e usuário `appuser` non-root.

### 4. Persistência de Estado
- PostgreSQL: sessões, eventos, métricas, cache LLM.
- Qdrant: índices vetoriais e embeddings.
- SQLite: cache/runtime local.
- `manifest.json` por sessão.

### 5. Segurança & Hardening
- Isolamento de sandbox (rede desabilitada nos efêmeros).
- Controle de permissões em `/outputs`.
- Contenção de privilégios e prevenção de escape.
- Vazamento de segredos.

### 6. Testes & Telemetria
- Cobertura de testes unitários e de integração.
- Observabilidade e logs estruturados em JSON.
- Monitoramento de temperatura no Pi 5.

---

## Template de Proposta Técnica

```markdown
## Proposta Técnica: [Título da Mudança]

### Contexto
[O que motivou esta mudança? Qual problema resolve?]

### Referências
- Roadmap: `roadmaps/roadmap_V*.md`
- ADRs relevantes: `docs/decisions/adr_*.md`

### Análise de Impacto

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Alto/Médio/Baixo/Nenhum | ... |
| Agentes ADK & Prompts | Alto/Médio/Baixo/Nenhum | ... |
| Sandboxes & Containers | Alto/Médio/Baixo/Nenhum | ... |
| Persistência de Estado | Alto/Médio/Baixo/Nenhum | ... |
| Segurança & Hardening | Alto/Médio/Baixo/Nenhum | ... |
| Testes & Telemetria | Alto/Médio/Baixo/Nenhum | ... |

### Módulos Afetados
- [Lista de arquivos e módulos com descrição do impacto]

### Contratos Alterados
- [Breaking changes em IPC, tool calls ou schemas]

### Migrações Necessárias
- [PostgreSQL, Qdrant, configuração]

### Riscos e Mitigações
| Risco | Severidade | Mitigação |
|---|---|---|
| ... | ... | ... |

### Plano de Implementação
1. [Sequência de tarefas ordenadas por dependência]
2. ...

### Critérios de Aceite
- [ ] [Lista de critérios para considerar a mudança concluída]
```

---

## Entregáveis

1. **Proposta técnica completa** usando o template acima.
2. **ADR** em `docs/decisions/adr_<NNN>_<titulo>.md` se decisão arquitetural relevante.
3. **Atualização de roadmap** se necessário.

---

## Regras

- Nunca implemente antes de concluir a análise de impacto.
- Obtenha aprovação explícita do usuário antes de prosseguir para implementação.
- Referências cruzadas com ADRs e roadmaps são obrigatórias.
