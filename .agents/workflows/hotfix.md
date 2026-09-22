---
description: Hotfix acelerado para correção urgente no GeminiClaw
---

# Workflow: Hotfix em Produção

Procedimento acelerado para correções urgentes que afetam a estabilidade ou segurança do GeminiClaw em ambiente de produção ou homologação.

---

## Quando Usar

- Falha crítica em agentes ou orquestrador que impede execução.
- Vulnerabilidade de segurança em sandboxes, containers ou gestão de segredos.
- Corrupção de dados em PostgreSQL, Qdrant ou manifests.
- Crash ou loop infinito no Raspberry Pi 5.

---

## Processo

### 1. Criação da Branch de Hotfix

```bash
# Criar worktree a partir de main (ou dev, conforme o ambiente afetado)
git worktree add .worktrees/hotfix-<descricao> -b hotfix/<descricao> main
cd .worktrees/hotfix-<descricao>
uv sync
```

### 2. Diagnóstico Rápido

1. Reproduzir o problema localmente.
2. Identificar a causa raiz com logs estruturados (`logs/`).
3. Avaliar impacto nos 6 eixos (simplificado):
   - Orquestrador afetado?
   - Containers/sandboxes afetados?
   - Dados persistidos comprometidos?
   - Segurança comprometida?

### 3. Correção

1. Implementar a correção mínima necessária.
2. Escrever teste que reproduz o problema e valida a correção.
3. Commit:
   ```bash
   git add -A && git commit -m "fix(<escopo>): hotfix - <descrição>"
   ```

### 4. Validação

```bash
# Testes unitários e de integração
uv run pytest -m "unit or integration" -v

# Teste específico da correção
uv run pytest <caminho_do_teste> -v
```

### 5. Merge Acelerado

1. Push da branch:
   ```bash
   git push origin HEAD
   ```

2. Criar PR com prioridade:
   ```bash
   export GH_TOKEN=$(uv run python .agents/skills/github_app_auth.py)
   REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
   git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
   gh pr create --fill --base main --reviewer paulormnas --label "hotfix"
   ```

3. Após merge em `main`, cherry-pick para `dev`:
   ```bash
   git checkout dev
   git pull origin dev
   git cherry-pick <commit-hash>
   git push origin dev
   ```

### 6. Limpeza

```bash
git worktree remove .worktrees/hotfix-<descricao>
git branch -d hotfix/<descricao>
```

---

## Regras

- Hotfix deve ser a correção MÍNIMA necessária. Nunca aproveite para refatorar.
- O hotfix DEVE ter teste automatizado.
- Nunca skip a etapa de validação, mesmo em urgência.
- O cherry-pick para `dev` é OBRIGATÓRIO para manter as branches sincronizadas.
