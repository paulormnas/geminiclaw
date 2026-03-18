# AGENTS.md

Framework leve de orquestração de agentes Gemini para Raspberry Pi 5.
Stack: **Python 3.11+, Google ADK, Docker, pytest, uv**.
Nenhum arquivo `.js`, `.ts` ou `.mjs` deve existir neste projeto.

---

## Regras detalhadas

- Desenvolvimento → `.agents/rules/development.md`
- Testes → `.agents/rules/testing.md`

---

## Ambiente

```bash
# Criar ambiente virtual
uv venv .venv

# Ativar
source .venv/bin/activate

# Instalar dependências do projeto
uv sync

# Adicionar nova dependência (atualiza pyproject.toml e uv.lock)
uv add nome-do-pacote

# Adicionar dependência de desenvolvimento
uv add --dev nome-do-pacote

# Atualizar todas as dependências
uv sync --upgrade
```

> Nunca use `pip` diretamente. Sempre use `uv`.

---

## Comandos essenciais

```bash
# Rodar todos os testes
uv run pytest

# Rodar apenas testes unitários (rápido)
uv run pytest -m unit -v

# Rodar com cobertura
uv run pytest --cov=src --cov=agents --cov-report=term-missing

# Subir agente em modo desenvolvimento
cd agents/<nome-do-agente> && uv run adk web

# Verificar containers ativos
docker ps --filter "name=geminiclaw"
```

---

## Estrutura do projeto

```
geminiclaw/
├── AGENTS.md                  # Este arquivo
├── GEMINI.md                  # Contexto persistente do Gemini CLI
├── .agents/rules/             # Regras detalhadas para agentes de IA
│   ├── development.md
│   └── testing.md
├── pyproject.toml             # Dependências e configuração (fonte da verdade)
├── uv.lock                    # Lockfile gerado pelo uv (versionar)
├── .env / .env.example        # Credenciais (nunca versionar .env)
├── src/                       # Orquestrador Python
├── agents/                    # Agentes ADK
├── containers/                # Dockerfiles
├── tests/                     # Testes pytest
├── store/                     # SQLite (runtime)
└── logs/                      # Logs (runtime)
```

---

## Limites — o agente nunca deve

- Usar `pip install` em qualquer circunstância
- Criar arquivos `.js`, `.ts` ou `.mjs`
- Commitar `.env`, `*.db` ou arquivos de log
- Alterar `GEMINI.md` sem instrução explícita do usuário
- Executar operações destrutivas (`docker rm -f`, `DROP TABLE`) sem confirmação
- Commitar com testes falhando
