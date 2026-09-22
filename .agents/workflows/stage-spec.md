---
description: Especificação de nova etapa do roadmap do GeminiClaw
---

# Workflow: Especificação de Nova Etapa do Roadmap

Este workflow define o processo de criação coordenada de especificações para novas etapas do roadmap do GeminiClaw — framework de orquestração de agentes Gemini para Raspberry Pi 5.

---

## Quando Usar

- Ao iniciar uma nova versão ou etapa no roadmap (ex: V14.1, V15.0).
- Quando uma etapa existente precisa ser decomposta em sub-etapas menores.
- Quando funcionalidades cross-cutting precisam ser especificadas de forma coordenada.

---

## Processo

### 1. Levantamento de Requisitos

1. Consultar o roadmap atual (`roadmaps/roadmap_V*.md`).
2. Consultar ADRs existentes (`docs/decisions/`) para contexto de decisões anteriores.
3. Identificar dependências entre etapas anteriores e a nova etapa.
4. Listar funcionalidades, melhorias e correções planejadas.

### 2. Definição da Etapa

Criar ou atualizar o arquivo de roadmap em `roadmaps/roadmap_V<versao>.md`:

```markdown
# Roadmap V<versão> — <Título da Etapa>

## Objetivo
[Descrição clara do objetivo desta etapa]

## Dependências
- [Etapas anteriores que devem estar concluídas]

## Tarefas

### Tarefa 1: [Título]
- **Módulos afetados:** `src/...`, `agents/...`
- **Critérios de aceite:**
  - [ ] [Critério 1]
  - [ ] [Critério 2]
- **Complexidade estimada:** Baixa/Média/Alta

### Tarefa 2: [Título]
...

## Validação da Etapa
- [ ] Todos os testes unitários e de integração passam
- [ ] Cobertura mínima atingida nos módulos afetados
- [ ] ADRs criados para decisões relevantes
- [ ] PR merged em `dev`
```

### 3. Revisão

1. O Arquiteto revisa a especificação da etapa contra os princípios de design (`architect.md`).
2. O Analista de Segurança avalia implicações de segurança (`security-analyst.md`).
3. O usuário aprova a especificação antes da implementação.

### 4. Decomposição em Features

Cada tarefa da etapa é decomposta em features individuais que seguem o workflow [`new-feature.md`](new-feature.md).

---

## Entregáveis

1. **Arquivo de roadmap** em `roadmaps/roadmap_V<versao>.md`.
2. **ADRs** para decisões arquiteturais da etapa.
3. **Lista de features** decompostas com dependências e ordem de implementação.

---

## Regras

- Nunca inicie a implementação de uma etapa sem especificação aprovada.
- Toda etapa deve ter critérios de aceite mensuráveis.
- Mantenha rastreabilidade entre etapas, features e ADRs.
