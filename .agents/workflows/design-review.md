---
description: Auditoria de design e conformidade visual para o futuro frontend do GeminiClaw
---

# Workflow: Auditoria de Design

> **Nota:** Este workflow será ativado em etapas futuras do roadmap do GeminiClaw, quando interfaces visuais de monitoramento e controle forem implementadas.

Procedimento para auditoria de conformidade visual, tokens e acessibilidade do GeminiClaw.

---

## Quando Usar

- Após implementação de novos componentes visuais.
- Em revisões periódicas de conformidade do Design System.
- Quando há suspeita de inconsistência visual ou violação de padrões.

---

## Checklist de Auditoria

### 1. Tokens e Design System

- [ ] Todas as cores utilizam tokens do Design System (nunca hex/rgb hardcoded).
- [ ] Tipografia segue a escala definida no Design System.
- [ ] Espaçamento usa tokens de spacing (nunca valores px arbitrários).
- [ ] Border-radius, shadows e motion seguem os tokens definidos.

### 2. Acessibilidade (WCAG AA)

- [ ] Contraste mínimo 4.5:1 para texto normal.
- [ ] Contraste mínimo 3:1 para texto grande (>18px bold ou >24px).
- [ ] Todos os elementos interativos são navegáveis por teclado.
- [ ] Focus indicators visíveis e com contraste adequado.
- [ ] Labels descritivos em todos os inputs e botões.

### 3. Dark Mode

- [ ] Dark mode funciona como padrão.
- [ ] Respeita `prefers-color-scheme`.
- [ ] Contrastes mantidos em ambos os modos.

### 4. Responsividade

- [ ] Funciona em 1080p (uso principal com Pi 5 + HDMI).
- [ ] Funciona em tablet (acesso remoto).
- [ ] Funciona em mobile (acesso remoto).

### 5. Estados de Componentes

- [ ] Todos os estados documentados na especificação estão implementados.
- [ ] Estados de agente (running, idle, failed, retrying) exibidos corretamente.
- [ ] Loading states são informativos (skeleton, spinner com contexto).
- [ ] Error states exibem mensagem acionável.

---

## Relatório de Auditoria

```markdown
## Auditoria de Design — [Data]

### Componentes Auditados
- [Lista de componentes]

### Conformidades ✅
- [Itens que passaram]

### Não Conformidades ❌
| NC | Componente | Descrição | Severidade |
|---|---|---|---|
| NC-001 | ... | ... | Alta/Média/Baixa |

### Recomendações
- [Sugestões de melhoria]
```

---

## Regras

- Não conformidades de acessibilidade com severidade Alta devem ser corrigidas antes do merge.
- Toda NC de design deve ser tratada conforme [`fix-nc.md`](fix-nc.md).
- O Design System é a fonte de verdade — qualquer desvio deve ser justificado.
