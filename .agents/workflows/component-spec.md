---
description: Especificação de componentes visuais para o futuro frontend do GeminiClaw
---

# Workflow: Especificação de Componente Visual

> **Nota:** Este workflow será ativado em etapas futuras do roadmap do GeminiClaw, quando interfaces visuais de monitoramento e controle forem implementadas.

Procedimento para design e especificação de componentes visuais do GeminiClaw.

---

## Quando Usar

- Ao criar um novo componente visual para o dashboard de monitoramento.
- Ao redesenhar um componente existente.
- Ao adicionar novos estados ou variantes a um componente.

---

## Processo

### 1. Contexto e Requisitos

1. Consultar o roadmap (`roadmaps/`) para entender o contexto da funcionalidade.
2. Identificar os dados disponíveis na API do orquestrador (`src/`).
3. Definir os estados do componente no contexto do GeminiClaw:
   - **Status de agente:** running, idle, failed, retrying.
   - **Status de sessão:** active, completed, error.
   - **Métricas do Pi 5:** temperatura, CPU, memória.

### 2. Especificação

```markdown
## Componente: [Nome]

### Propósito
[Para que serve e onde será usado no dashboard]

### Dados de Entrada
- [Props/dados consumidos da API do orquestrador]

### Estados
| Estado | Descrição | Visual |
|---|---|---|
| Default | ... | ... |
| Loading | ... | ... |
| Error | ... | ... |
| Empty | ... | ... |

### Variantes
- [Variantes do componente (ex: compact, expanded)]

### Tokens Utilizados
- [Cores, tipografia, espaçamento do Design System]

### Acessibilidade
- [Requisitos de contraste, teclado, screen reader]

### Responsividade
- Desktop (1080p) | Tablet | Mobile
```

### 3. Revisão

1. O Designer valida a conformidade visual (`designer.md`).
2. O Desenvolvedor Frontend avalia a viabilidade técnica (`frontend-dev.md`).
3. Aprovação do usuário antes da implementação.

---

## Regras

- Nunca implemente um componente sem especificação aprovada.
- Todos os estados devem ser documentados antes da implementação.
- Tokens do Design System são obrigatórios — nunca use valores hardcoded.
