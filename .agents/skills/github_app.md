# Skill: GitHub App Collaborator

> **Invocação:** Quando o agente da IDE precisar abrir um Pull Request, fazer push de código ou responder a pedidos de ajuste em um PR existente.

---

## Visão Geral

Esta skill habilita o agente da IDE a atuar como colaborador autêntico do repositório `geminiclaw` via **GitHub App** (`geminiclaw-agent`), usando um **Installation Token** de curta duração (1h) em vez de um Personal Access Token pessoal.

**Regra de ouro:** o agente **abre e atualiza** PRs. O **merge é sempre exclusivo do usuário**.

---

## Pré-requisitos (verificar antes de qualquer ação)

```bash
# 1. Confirmar que as variáveis do App estão configuradas
grep -E "GITHUB_APP_ID|GITHUB_APP_INSTALLATION_ID|GITHUB_APP_PRIVATE_KEY_PATH|GITHUB_REPO" .env

# 2. Confirmar que o token é gerado com sucesso
uv run python scripts/github_app_auth.py && echo "✅ Autenticação OK"

# 3. Confirmar que está numa branch de feature (NUNCA main/master)
git branch --show-current

# 4. Confirmar que há uma worktree ativa para a feature
git worktree list
```

Se qualquer pré-requisito falhar, **parar e informar o usuário** antes de continuar.

---

## Passo 1 — Autenticar o ambiente

Execute este bloco **sempre** antes de qualquer operação com `gh` ou `git push`:

```bash
# Gerar token temporário do GitHub App
export GH_TOKEN=$(uv run python scripts/github_app_auth.py)

# Configurar o remote para usar o token (evita prompt de senha)
REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
```

> O token expira em **1 hora**. Se a operação demorar mais, regenere-o.

---

## Passo 2 — Abrir um Pull Request

```bash
gh pr create \
  --title "<tipo>(<escopo>): <descrição no imperativo>" \
  --body "## Contexto
<Por que esta mudança é necessária — problema ou objetivo>

## O que foi implementado
- <item 1>
- <item 2>

## Testes realizados
- [ ] \`uv run pytest -m unit -v\` — todos passando
- [ ] Nenhum arquivo sensível no commit (\`.env\`, \`*.db\`, logs)

## Como revisar
<Instrução objetiva: o que testar, qual comportamento esperar>

---
*PR aberto automaticamente pelo agente GeminiClaw via GitHub App.*" \
  --base main \
  --head "$(git branch --show-current)"
```

**Quando usar `--draft`:** se a implementação não estiver 100% finalizada ou os testes ainda não passarem na totalidade:

```bash
gh pr create --draft --title "..." --body "..."
```

---

## Passo 3 — Responder a pedidos de ajuste no PR

Quando o usuário solicitar mudanças via review, **sem fechar e reabrir o PR**:

```bash
# 1. Continuar na mesma branch da worktree
# 2. Implementar os ajustes solicitados
# 3. Commit seletivo (nunca git add .)
git add -p
git commit -m "fix(<escopo>): <descrição do ajuste solicitado>"

# 4. Push — o PR é atualizado automaticamente
git push origin HEAD

# 5. Notificar o usuário via comentário no PR
gh pr comment --body "Ajuste aplicado conforme solicitado. Aguardando nova revisão. 🔄"
```

---

## Regras de Segurança

| Regra | Detalhe |
|---|---|
| ❌ **Nunca mergear** | Merge é ação exclusiva do usuário |
| ❌ **Nunca `force-push`** | Preservar o histórico do PR |
| ❌ **Nunca commitar em `main`** | Sempre trabalhar em branch de feature |
| ❌ **Nunca logar o token** | Usar apenas `export GH_TOKEN=...` |
| ❌ **Nunca `git add .`** | Usar sempre `git add -p` para revisão seletiva |
| ✅ **Usar `--draft`** | Quando a implementação não está 100% pronta |
| ✅ **Comentar após cada push** | `gh pr comment` após cada correção aplicada |
| ✅ **Regenerar token** | Se a operação durar mais de 50 minutos |

---

## Integração com o Fluxo de Desenvolvimento

Esta skill é executada **após** o workflow `/commit` (que garante testes passando e commit semântico). A sequência completa é:

```
1. git worktree add  →  nova branch de feature
2. Implementar código + testes (TDD)
3. /commit           →  testes passam, commit semântico, push
4. [esta skill]      →  autenticar App + gh pr create
5. ✋ Usuário revisa  →  review no GitHub
6. [esta skill]      →  ajustes + git push → PR atualizado
7. ✋ Usuário aprova  →  merge + git worktree remove
```

---

## Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| `401 Unauthorized` | Token expirado ou App sem permissão | Regenerar token; verificar permissões do App |
| `422 Unprocessable` no `gh pr create` | PR já existe para a branch | Usar `gh pr edit` em vez de `create` |
| `git push` pede senha | Remote não foi atualizado com o token | Re-executar o Passo 1 |
| `.pem` not found | Caminho errado em `GITHUB_APP_PRIVATE_KEY_PATH` | Verificar `.env` e localização do arquivo |
