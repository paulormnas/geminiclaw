# Regras de Desenvolvimento — GeminiClaw

Stack: **Python 3.11+, Google ADK, Docker, uv**. Sem arquivos `.js`, `.ts` ou `.mjs`.

---

## Aprovação do usuário — REGRA CRÍTICA

**O agente DEVE parar e aguardar aprovação explícita do usuário antes de:**
- Iniciar qualquer implementação após apresentar um plano ou solicitar revisão
- Deletar arquivos ou diretórios
- Alterar schema do banco de dados SQLite
- Modificar `Dockerfile` base, `AGENTS.md` ou `GEMINI.md`
- Atualizar versões major de dependências
- Executar comandos que afetam serviços systemd
- Qualquer operação irreversível

> **Quando o agente solicitar revisão do usuário, ele DEVE aguardar a resposta antes de prosseguir. Nunca implemente tarefas imediatamente após propor um plano.**

---

## Princípios

1. **100% Python** — Node.js existe apenas como runtime do Gemini CLI, nunca do projeto.
2. **Footprint mínimo** — justifique cada nova dependência; prefira a stdlib.
3. **Single-process por agente** — estado compartilhado apenas via SQLite.
4. **Idempotência** — scripts de setup re-executáveis sem efeitos colaterais.
5. **Configuração explícita** — via `.env`; nada de detecção automática que silencie erros.
6. **Logs antes de ação** — toda operação com efeito colateral (API, disco, container) é logada em JSON **antes** de executar.

---

## Pacotes — sempre `uv`, nunca `pip`

```bash
uv venv .venv && source .venv/bin/activate  # setup
uv sync --all-groups                         # instalar tudo
uv add <pacote>                              # produção
uv add --dev <pacote>                        # dev
uv run pytest / uv run adk web              # executar
```

> `uv.lock` deve ser versionado. `pip install` é proibido.

---

## Convenções Python

| Regra | ✅ Correto | ❌ Errado |
|---|---|---|
| Type hints em funções públicas | `def f(x: str) -> int` | `def f(x)` |
| Logging | `logger.info("msg", extra={...})` | `print(...)` |
| I/O | `async/await` | `time.sleep()` |
| Erros | logar ou propagar | `except Exception: pass` |
| Type ignore | com comentário explicativo | `# type: ignore` sem contexto |
| Subprocessos | lista de args | `shell=True` |

**Docstrings:** Google Style com `Args`, `Returns`, `Raises`.

**Nomeação:** módulos `snake_case.py` · classes `PascalCase` · funções `snake_case` · constantes `UPPER_CASE` · tabelas SQLite `snake_case` · pastas ADK `snake_case/`.

---

## Docker

```python
client.containers.run(
    image="geminiclaw-agent:latest",
    mem_limit="512m",
    nano_cpus=1_000_000_000,
    network="geminiclaw-net",
    volumes={str(data_dir): {"bind": "/data", "mode": "rw"}},
    detach=True, remove=True, user="appuser",
)
```

Regras: imagem `python:3.11-slim`, usuário non-root, rede interna isolada, portas em `127.0.0.1` apenas.

---

## Segurança

- Nunca versione `.env`, `*.db` ou logs
- Variáveis sensíveis via `python-dotenv` em runtime

---

## Fluxo de desenvolvimento

```
1. git worktree add ../geminiclaw-<feature> -b <feature>
2. uv sync
3. Escreva testes antes do código (TDD)
4. uv run pytest  ← todos devem passar antes do commit
5. Siga o workflow /commit
```

**Commits:** `feat:` `fix:` `docs:` `test:` `refactor:` `chore:`

---

## Referências

- [uv](https://docs.astral.sh/uv/) · [Google ADK](https://google.github.io/adk-docs/get-started/quickstart/) · [docker-py](https://docker-py.readthedocs.io/)