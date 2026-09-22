---
description: Criação, revisão e squash merge automatizado de Pull Requests via GitHub App
---

# Workflow: Pull Request, Revisão e Squash Merge Automatizado (GitHub App)

Este workflow orquestra o processo ponta a ponta de fechamento de um ciclo de desenvolvimento: desde a autenticação via GitHub App, validação e publicação da branch da Git Worktree, passando pela revisão técnica formal pelo agente Revisor ([`reviewer.md`](../rules/reviewer.md)), até o **merge automático com squash**, deleção da branch e limpeza da worktree local.

---

## 1. Visão Geral e Papéis

- **Skill GitHub App (`.agents/skills/github_app_auth.py`):** Gera Installation Tokens de curta duração (1 hora) e configura o remote Git para operações autenticadas sem prompts manuais.
- **Agente Desenvolvedor** ([`backend-dev.md`](../rules/backend-dev.md)): Conclui a implementação na worktree, garante suíte de testes 100% verde e abre o PR.
- **Agente Reviewer / Tech Lead** ([`reviewer.md`](../rules/reviewer.md)): Audita o diff nos 7 eixos técnicos e emite o parecer de aprovação (`gh pr review --approve`).
- **Automação de Squash Merge:** Realiza o merge via GitHub CLI com squash, preservando a linearidade e clareza do histórico da branch `dev`.

---

## 2. Gatilho e Pré-requisitos

### Gatilho:
Conclusão bem-sucedida do desenvolvimento e testes em worktree dedicada (`.worktrees/<nome-da-branch>`).

### Pré-requisitos Obrigatórios:
1. Variáveis do GitHub App configuradas em `.env`:
   ```bash
   grep -E "GITHUB_APP_ID|GITHUB_APP_INSTALLATION_ID|GITHUB_APP_PRIVATE_KEY_PATH|GITHUB_REPO" .env
   ```
2. Todas as alterações locais commitadas na worktree usando Conventional Commits (`git status` limpo).
3. Testes automatizados 100% aprovados localmente:
   ```bash
   uv run pytest -m "unit or integration" -v
   ```
4. Nenhum arquivo sensível ou proibido no histórico ou staging (`.env`, `*.db`, `*.log`).

---

## 3. Fases do Workflow Automatizado

### Fase 1: Autenticação via GitHub App e Preparação

Execute a autenticação temporária antes de interagir com o GitHub:

```bash
# 1. Gerar token de instalação do GitHub App (válido por 1 hora)
export GH_TOKEN=$(uv run python .agents/skills/github_app_auth.py)

# 2. Configurar o remote do Git com o token autenticado
REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"

# 3. Confirmar branch atual da worktree (nunca main ou dev)
BRANCH=$(git branch --show-current)
echo "Branch ativa: $BRANCH"
```

---

### Fase 2: Publicação da Branch e Criação do Pull Request

1. **Push da branch para o repositório remoto:**
   ```bash
   git push -u origin "$BRANCH"
   ```

2. **Criação do Pull Request apontando para `dev`:**
   ```bash
   PR_URL=$(gh pr create \
     --base dev \
     --head "$BRANCH" \
     --title "<tipo>(<escopo>): <descrição no imperativo do Conventional Commits>" \
     --body "## Contexto
   <Descrição clara do objetivo e funcionalidade implementada na worktree>

   ## Alterações Realizadas
   - <resumo 1>
   - <resumo 2>

   ## Validações Automatizadas
   - [x] Testes unitários/integração aprovados (\`uv run pytest\`)
   - [x] Zero secrets e sem arquivos residuais (.env, *.db, *.log)
   - [x] Conformidade de arquitetura e isolamento de containers

   ---
   *Pull Request gerado e auditado automaticamente via GitHub App.*")

   PR_NUM=$(echo "$PR_URL" | grep -oE '[0-9]+$')
   echo "Pull Request #$PR_NUM criado com sucesso: $PR_URL"
   ```

---

### Fase 3: Revisão Técnica Automatizada (Code Review)

O agente Reviewer inspeciona o diff gerado (`gh pr diff "$PR_NUM"`) nos **7 eixos técnicos** ([`reviewer.md`](../rules/reviewer.md)):
1. **Conformidade e Rastreabilidade:** Branch base `dev`, Conventional Commits.
2. **Arquitetura & Separação:** Orquestrador (`src/`), Agentes (`agents/`), Containers (`containers/`) e IPC.
3. **Clean Code & Manutenibilidade:** SOLID, tipagem estrita, ausência de prints ou dead code.
4. **Segurança & Hardening:** Sem segredos, containers non-root (`appuser`), isolamento de sandboxes.
5. **Robustez & Tipagem:** Sem supressão cega de exceções, type hints completos.
6. **Performance & Recursos Pi 5:** Footprint mínimo, ausência de bloqueios síncronos na event loop.
7. **Qualidade de Testes:** Cobertura de cenários felizes e de borda.

Após constatar conformidade total, o Revisor aprova o PR formalmente:

```bash
gh pr review "$PR_NUM" --approve -b "## Parecer de Code Review: Aprovado (LGTM)

- [x] **Conformidade:** Branch base apontada exclusivamente para \`dev\`; commits semânticos.
- [x] **Arquitetura:** Camadas orquestrador, agentes e containers respeitadas.
- [x] **Clean Code:** Padrões estritos de tipagem e manutenibilidade.
- [x] **Segurança:** Isolamento de sandboxes e zero secrets.
- [x] **Testes:** Validações automatizadas 100% verdes.

Homologado para squash merge automático."
```

---

### Fase 4: Squash Merge Automático e Remoção Remota

Com a aprovação registrada e os checks validados, executa-se o merge com **squash**:

```bash
# Executa o squash merge e deleta a branch remota automaticamente
PR_TITLE=$(gh pr view "$PR_NUM" --json title -q .title)
gh pr merge "$PR_NUM" --squash --delete-branch --subject "$PR_TITLE"

echo "Pull Request #$PR_NUM mergeado com sucesso em dev via Squash Merge!"
```

---

### Fase 5: Sincronização da Branch `dev` e Limpeza da Worktree

Após o merge no GitHub, sincronize o ambiente local e descarte a worktree efêmera:

```bash
# 1. Obter caminho da raiz do repositório
REPO_ROOT="$(git rev-parse --show-toplevel)/../.."
cd "$REPO_ROOT" || cd /home/agent/Documentos/Workspace/geminiclaw

# 2. Atualizar a branch dev local
git checkout dev
git pull origin dev

# 3. Remover a worktree finalizada
git worktree remove ".worktrees/$BRANCH"

# 4. Remover a branch local da feature
git branch -d "$BRANCH"

# 5. Limpar referências remotas obsoletas
git fetch origin --prune

echo "Ambiente sincronizado e worktree .worktrees/$BRANCH limpa com sucesso!"
```

---

## 4. Script de Execução Automatizada (One-Liner)

Para rodar todo o pipeline de forma contínua a partir de dentro da worktree:

```bash
set -e

# Autenticação
export GH_TOKEN=$(uv run python .agents/skills/github_app_auth.py)
REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"

BRANCH=$(git branch --show-current)
TITLE=$(git log -1 --pretty=%s)

# Push e PR
git push -u origin "$BRANCH"
PR_URL=$(gh pr create --base dev --head "$BRANCH" --title "$TITLE" --fill)
PR_NUM=$(echo "$PR_URL" | grep -oE '[0-9]+$')

# Aprovação Técnica
gh pr review "$PR_NUM" --approve -b "Aprovado automaticamente via GitHub App após validação dos 7 eixos de qualidade técnica."

# Squash Merge
gh pr merge "$PR_NUM" --squash --delete-branch --subject "$TITLE"

# Retorno à raiz e limpeza
cd /home/agent/Documentos/Workspace/geminiclaw
git checkout dev
git pull origin dev
git worktree remove ".worktrees/$BRANCH"
git branch -d "$BRANCH"
git fetch origin --prune

echo "Pipeline de PR, Code Review e Squash Merge concluído com sucesso!"
```
