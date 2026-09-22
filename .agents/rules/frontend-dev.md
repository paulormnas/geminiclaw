# Regras do Agente: Desenvolvedor Frontend

> **Nota:** Este papel será ativado em etapas futuras do roadmap do GeminiClaw, quando um frontend de monitoramento e controle for implementado. A stack frontend será definida no momento da implementação. Estas regras devem ser adaptadas e expandidas quando o frontend for iniciado.

---

## Papel

- Entenda o fluxo do usuário (operador do GeminiClaw) e valide o design antes de escrever código.
- Priorize acessibilidade, performance e manutenibilidade.
- Componentes pequenos, compostos e reutilizáveis. Sem complexidade desnecessária.
- **Nenhum arquivo `.js`, `.ts` ou `.mjs` deve existir no projeto** até que a stack frontend seja formalmente decidida e documentada em um ADR.

---

## Contexto do GeminiClaw

O frontend do GeminiClaw, quando implementado, servirá como:

- **Dashboard de Monitoramento:** Visualização do estado de agentes, sessões ativas, uso de recursos (CPU, memória, temperatura) e logs em tempo real.
- **Painel de Controle:** Iniciar/parar execuções, configurar modelos LLM por agente, inspecionar manifests e artefatos de sessão.
- **Visualização de Resultados:** Exibição de outputs gerados pelos agentes (gráficos, CSVs, relatórios), histórico de execuções e métricas de performance.

---

## Consulta de Especificações

Antes de criar ou modificar qualquer componente, consulte obrigatoriamente:

1. **Roadmaps (`roadmaps/`):** Requisitos de interface e funcionalidades planejadas.
2. **Design System** *(a ser definido)*: Tokens, cores, tipografia e componentes base.
3. **Decisões Arquiteturais (`docs/decisions/`):** ADRs para entender o contexto da stack escolhida.
4. **API do Orquestrador (`src/`):** Endpoints e contratos disponíveis para consumo pelo frontend.

Se qualquer especificação estiver ambígua, solicite esclarecimento. Não tome decisões funcionais ou de design por conta própria.

---

## Stack e Ambiente (A Definir)

A stack frontend será decidida via ADR no momento da implementação. Possibilidades incluem:

- **Python-first:** Streamlit, Gradio, NiceGUI, ou FastHTML para manter a stack 100% Python.
- **Web tradicional:** Se aprovado via ADR, uma stack web poderá ser adotada em diretório isolado.

Independentemente da stack escolhida:
- O gerenciamento de dependências Python deve usar `uv`.
- O frontend deve ser containerizado e rodar na rede `geminiclaw-net`.
- Os arquivos de frontend devem ficar em diretório dedicado (`frontend/` ou similar).

---

## Git Flow

Seguir as mesmas regras de Git Worktree e Conventional Commits definidas em [`backend-dev.md`](backend-dev.md):

- Worktree obrigatória em `.worktrees/<nome-da-branch>`.
- Branches com prefixo semântico (`feat/`, `fix/`, etc.).
- Commits no padrão Conventional Commits.

---

## Acessibilidade

- Todas as interfaces devem ser navegáveis por teclado.
- Contraste mínimo de 4.5:1 para texto sobre fundo (WCAG AA).
- Labels descritivos em todos os elementos interativos.
- Suporte a dark mode (respeitando `prefers-color-scheme`).

---

## Testes

- Testes de componentes devem validar estados (default, loading, error, disabled).
- Cobertura mínima de 70% para componentes do frontend.
- Testes devem ser executáveis sem rede e sem dependência do backend em modo real.
