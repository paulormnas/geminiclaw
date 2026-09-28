# Contexto do Projeto para Specs

Leia este arquivo antes de implementar qualquer mudança em `openspec/changes/`.

## Propósito

Assistente digital de pesquisa científica (ADR 010): conduz experimentos, formula hipóteses,
valida suposições e relata resultados, acumulando conhecimento experimental em um grafo
(ADR 009, ADR 015). O nome atual do projeto ("GeminiClaw") **será alterado** — código novo não
deve espalhar o nome (ADR 011).

## Stack

| Item | Valor |
|---|---|
| Linguagem | Python 3.11+ |
| Gerenciador | `uv` (nunca `pip`) |
| Banco relacional | PostgreSQL 16 (`scripts/init_db.sql`, `src/db.py`) |
| Banco vetorial | Qdrant (`QDRANT_URL`) |
| Banco de grafo | Apache AGE sobre o PostgreSQL (a partir da V17) |
| LLM | Camada própria em `src/llm/` (`LLMProvider`), sem SDK de agentes de fornecedor |
| Execução de código gerado | Somente no sandbox Docker (`src/skills/code/sandbox.py`) — ADR 014 |
| Hardware alvo | Raspberry Pi 5, 8 GB RAM, ARM64 |
| Testes | `pytest -m "unit or integration"`; lint com Ruff antes dos testes |

## Convenções obrigatórias

- **Governança (AGENTS.md):** um worktree por mudança em `.worktrees/<nome>`; Conventional
  Commits; nunca commitar em `main` ou `dev`; PR para `dev`.
- **Aprovação explícita do pesquisador antes de:** alterar schema de banco, alterar
  Dockerfiles base ou `docker-compose.yml`, apagar arquivos, alterar `AGENTS.md`/`GEMINI.md`,
  qualquer operação destrutiva. Toda spec que exige isso traz a seção **"Aprovações
  necessárias"** no `proposal.md`.
- **Segredos:** nunca em código; apenas via `.env` / `src/config.py`.
- **Configuração:** todo valor ajustável (limiares, pesos, limites) vai para `src/config.py`
  com variável de ambiente e default documentado — nunca espalhado no código.
- **Idioma:** código e identificadores em inglês ou português conforme o módulo vizinho;
  docstrings, logs e docs em português (padrão do repositório).
- **Nenhum código gerado por LLM executa no host** (ADR 014). Nenhuma ferramenta do host
  aceita código, comando de shell ou Cypher de escrita arbitrário vindo do LLM.
- **Embeddings são locais** e nunca enviados a provedores externos (ADR 011).
- **Fatos estruturais são escritos de forma determinística** pelo orquestrador; agentes só
  escrevem conhecimento interpretado, sempre com evidência (ADR 015).

## Definição de pronto (toda mudança)

- [ ] Todos os cenários da spec cobertos por testes (`unit` ou `integration`).
- [ ] `uv run ruff check .` sem erros novos; `uv run pytest -m "unit or integration"` verde.
- [ ] Nenhuma regressão nos testes existentes.
- [ ] Configurações novas documentadas em `.env.example`.
- [ ] Revisão nos 7 eixos (`.agents/rules/reviewer.md`) antes do merge.
- [ ] Mudança arquivada em `openspec/changes/archive/` após o merge.
