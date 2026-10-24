# Regras do Agente: Desenvolvedor Frontend

> **Nota:** Este papel será ativado em etapas futuras do roadmap do GeminiClaw, quando um frontend de monitoramento e controle for implementado. A stack frontend será definida no momento da implementação. Estas regras devem ser adaptadas e expandidas quando o frontend for iniciado.

---

## Papel

- Entenda o fluxo do usuário (operador do GeminiClaw) e valide o design antes de escrever código.
- Priorize acessibilidade, performance e manutenibilidade.
- Componentes pequenos, compostos e reutilizáveis. Sem complexidade desnecessária.
- **JavaScript/TypeScript é permitido somente no diretório do frontend** (AGENTS.md §1). A stack, o diretório, o gerenciador de pacotes e as ferramentas de build e teste serão definidos em ADR e spec próprios antes da implementação.

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

- **Web com JavaScript/TypeScript:** permitida pelo AGENTS.md, em diretório isolado do backend. Lógica de servidor em JS/TS (desenvolvimento, renderização, proxy) é permitida só a serviço da própria interface, falando com o backend Python pela API; nunca acessa bancos, gate ou orquestrador.
- **Python-first:** Streamlit, Gradio, NiceGUI ou FastHTML, se o ADR concluir que atendem melhor.

Independentemente da stack escolhida:
- O gerenciamento de dependências Python usa `uv`; o do frontend usa `pnpm` (ADR 027), com `packageManager` fixado no `package.json` e `pnpm-lock.yaml` versionado. Nunca `npm`/`yarn`.
- O frontend é um projeto próprio em `frontend/` (React + TypeScript estrito + Vite); tokens do design system em `frontend/src/styles/tokens.css`, sem valor de cor, espaçamento ou fonte fora deles.
- Execução: ADR 027 §9 — containers `geminiclaw-web` e `geminiclaw-web-frontend` (mudança `v18.10-web-containers`); até lá, `uv run python -m src.web` + `pnpm --dir frontend dev`.
- Testes: `pnpm --dir frontend test` (Vitest + Testing Library + MSW, cobertura ≥ 70%), `lint`, `typecheck` e `build` antes de cada commit que altere `frontend/`. `react/no-danger` é erro.

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
