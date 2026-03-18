---
description: Sequência de passos para commit
---

# Workflow de Commit — GeminiClaw

Sequência obrigatória que o agente deve seguir para registrar
uma mudança no projeto. Execute os passos na ordem apresentada.

---

## 1. Rodar os testes

```bash
uv run pytest -m "unit or integration" -v
```

Só avance se todos os testes passarem. Nunca faça commit com testes falhando.

---

## 2. Verificar arquivos sensíveis no staging

```bash
git diff --cached --name-only | grep -E "\.env$|\.db$|\.log$"
```

Se retornar qualquer arquivo, remova-o do staging antes de continuar:

```bash
git restore --staged <arquivo>
```

---

## 3. Revisar o diff

```bash
git diff --cached
```

Confirme que apenas as mudanças intencionais estão incluídas.

---

## 4. Fazer o commit

```bash
git commit -m "<tipo>(<escopo>): <descrição no imperativo>"
```

### Tipos permitidos

| Tipo | Quando usar |
|---|---|
| `feat` | Nova funcionalidade ou agente |
| `fix` | Correção de bug |
| `test` | Adição ou correção de testes |
| `refactor` | Reorganização sem mudar comportamento |
| `docs` | Arquivos `.md`, docstrings, comentários |
| `chore` | Dependências, configuração, arquivos de projeto |
| `perf` | Melhoria de performance |
| `ci` | Dockerfile, systemd, scripts de automação |

### Escopos sugeridos

`runner`, `session`, `ipc`, `logger`, `agents`, `containers`, `tests`, `config`, `docs`

### Exemplos

```
feat(agents): adiciona agente researcher com busca via Gemini
fix(session): corrige condição de corrida em criação concorrente
test(runner): adiciona cobertura para timeout de container
chore(deps): adiciona docker>=7.1.0 ao pyproject.toml
docs(setup): atualiza checklist com passo de uv sync
```