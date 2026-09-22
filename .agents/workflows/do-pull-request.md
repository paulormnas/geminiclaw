---
description: Abertura, Code Review e Merge de Pull Request para o GeminiClaw
---

# Workflow: Abertura, Code Review e Merge de Pull Request

Este workflow orquestra o processo completo de fechamento de um ciclo de desenvolvimento: desde a criação do Pull Request a partir de uma Git Worktree ativa, passando pela revisão técnica, aplicação de melhorias, até o merge na branch `dev`, sincronização local e limpeza do ambiente.

---

## 1. Visão Geral e Papéis

- **Agente Reviewer (Code Reviewer)**: Análise crítica do código contra segurança, arquitetura, clean code e cobertura de testes. Segue as regras de [`review.md`](../rules/review.md).
- **Agente Desenvolvedor** (orientado por [`backend-dev.md`](../rules/backend-dev.md)): Implementa melhorias solicitadas pelo Reviewer, valida localmente e registra commits semânticos.
- **Agente Tester / QA** (orientado por [`tester.md`](../rules/tester.md)): Garante que nenhuma regressão foi introduzida pelas melhorias aplicadas.

---

## 2. Gatilho e Pré-requisitos

### Gatilho:
Conclusão do desenvolvimento em worktree dedicada (`.worktrees/<nome-da-branch>`).

### Pré-requisitos Obrigatórios:
1. Todas as alterações estão commitadas na branch da worktree usando Conventional Commits.
2. Validações locais aprovadas:
   ```bash
   uv run pytest -m "unit or integration" -v
   ```
3. Nenhum arquivo sensível no staging (`.env`, `*.db`, `*.log`).

---

## 3. Fases do Workflow

### Fase 1: Publicação da Branch e Criação do Pull Request

1. Rodar todos os testes:
   ```bash
   uv run pytest -m "unit or integration" -v
   ```
   Só avance se todos os testes passarem.

2. Verificar arquivos sensíveis no staging:
   ```bash
   git diff --cached --name-only | grep -E "\.env$|\.db$|\.log$"
   ```

3. Push da branch:
   ```bash
   git push origin HEAD
   ```

4. Gerar token do GitHub App e criar o PR:
   ```bash
   export GH_TOKEN=$(uv run python .agents/skills/github_app_auth.py)
   REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
   git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
   gh pr create --fill --base dev --reviewer paulormnas
   ```

---

### Fase 2: Revisão Técnica (Code Review)

O Reviewer analisa o diff do PR nos seguintes eixos (conforme [`review.md`](../rules/review.md)):

1. **Segurança:** Vulnerabilidades óbvias, exposição de portas/segredos, logs com dados sensíveis.
2. **Performance:** Loops bloqueantes na event loop, vazamento de memória, má gestão de conexões.
3. **Estabilidade:** Tratamento de exceções que mascaram erros (`except Exception: pass`).
4. **Arquitetura:** Conformidade com a stack 100% Python, uso correto de `uv`, padrões do projeto.

Emitir parecer via GitHub CLI:
```bash
# Aprovação
gh pr review <numero> --approve -b "Tudo certo! Código alinhado com a arquitetura."

# Solicitar mudanças
gh pr review <numero> --request-changes -b "Pontos de atenção: ..."
```

---

### Fase 3: Ciclo de Melhorias (se necessário)

Se o Reviewer solicitar mudanças:

1. Desenvolvedor analisa o feedback e implementa correções na worktree.
2. Executa validações locais novamente.
3. Commits semânticos e push:
   ```bash
   git add -A && git commit -m "fix(<escopo>): <descrição da correção>"
   git push origin HEAD
   ```
4. Reviewer reavalia as alterações.

---

### Fase 4: Merge e Limpeza

Após aprovação:

1. Merge do PR via GitHub (squash ou merge commit conforme preferência).

2. Sincronizar branch `dev` local:
   ```bash
   git checkout dev
   git pull origin dev
   ```

3. Limpar worktree e branch:
   ```bash
   git worktree remove .worktrees/<nome-da-branch>
   git branch -d <nome-da-branch>
   ```

4. Limpar referências remotas obsoletas:
   ```bash
   git fetch origin --prune
   ```
