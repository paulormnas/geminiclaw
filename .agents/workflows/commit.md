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

`runner`, `session`, `ipc`, `logger`, `agents`, `memory`, `containers`, `tests`, `config`, `docs`

### Exemplos

```
feat(agents): adiciona agente researcher com busca via Gemini
fix(session): corrige condição de corrida em criação concorrente
test(runner): adiciona cobertura para timeout de container
chore(deps): adiciona docker>=7.1.0 ao pyproject.toml
docs(setup): atualiza checklist com passo de uv sync
```

---

## 5. Push para o repositório remoto

```bash
git push origin HEAD
```

Sempre faça o push para garantir que as alterações estejam disponíveis no repositório remoto.

---

## 6. Autenticar e Criar Pull Request (GitHub App)

Gere o token do App e configure o ambiente antes de criar o PR:

```bash
# Gerar token do GitHub App (válido por 1h)
export GH_TOKEN=$(uv run python .agents/skills/github_app_auth.py)

# Configurar remote para usar o token (evita prompt de senha)
REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"

# Criar PR com revisor e assignee padrão
gh pr create --fill \
  --reviewer paulormnas \
  --assignee "ideagent[bot]"
```

> Para um corpo de PR mais estruturado, consulte `.agents/skills/github_app.md` (Passo 2).

---

## 7. Limpeza da worktree

Volte para o diretório raiz e remova a worktree da feature:

```bash
cd /home/agent/Documentos/Workspace/geminiclaw
git worktree remove --force <caminho-da-worktree>
```

Execute este comando após o push e abertura do PR para manter o ambiente limpo. Certifique-se de que não há arquivos não commitados que você deseja manter.