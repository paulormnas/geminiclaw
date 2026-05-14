---
description: Limpa logs, artefatos de output e registros nos bancos Postgres e Qdrant para iniciar novas avaliações
---

# Workflow de Limpeza — GeminiClaw

Remove todo o estado gerado por execuções anteriores (logs, artefatos,
registros no PostgreSQL e coleções no Qdrant), preparando um ambiente
limpo para novas avaliações do projeto.

> **Atenção:** Esta operação é destrutiva e irreversível. Execute apenas
> quando tiver certeza de que os dados anteriores não são mais necessários.
> Use `--dry-run` para inspecionar o que será removido antes de confirmar.

---

## 0. Pré-requisitos

- Containers de infraestrutura rodando (`docker ps` mostra `geminiclaw-postgres` e `geminiclaw-qdrant`)
- Ambiente virtual ativo (`source .venv/bin/activate` ou prefixo `uv run`)
- Variáveis de ambiente carregadas (`.env` presente na raiz)

---

## 1. Inspecionar antes de limpar (dry-run)

Visualize o que seria removido sem executar nenhuma ação:

```bash
uv run python .agents/skills/clean_dev.py --dry-run
```

---

## 2. Limpeza completa

Remove logs, artefatos de output, trunca todas as tabelas PostgreSQL e
deleta todas as coleções Qdrant:

```bash
uv run python .agents/skills/clean_dev.py
```

Saída esperada:

```
✅ Limpeza concluída
──────────────────────────────────────────────────
   Logs removidos:             3
   Sessões de output:          2
   Tabelas PG truncadas:      12
   Coleções Qdrant deletadas:  1
──────────────────────────────────────────────────
   Sem erros registrados.
```

---

## 3. Limpezas parciais

### Somente arquivos locais (sem tocar nos bancos)

```bash
uv run python .agents/skills/clean_dev.py --skip-postgres --skip-qdrant
```

### Somente bancos de dados (sem remover arquivos locais)

```bash
uv run python .agents/skills/clean_dev.py --skip-logs --skip-outputs
```

### Somente PostgreSQL

```bash
uv run python .agents/skills/clean_dev.py --skip-logs --skip-outputs --skip-qdrant
```

### Somente Qdrant

```bash
uv run python .agents/skills/clean_dev.py --skip-logs --skip-outputs --skip-postgres
```

---

## 4. O que é limpo

| Subsistema | O que é removido |
|---|---|
| **Logs** | Todos os arquivos `*.log` em `./logs/` (`.gitkeep` é preservado) |
| **Outputs** | Todos os subdiretórios de sessão em `./outputs/` |
| **PostgreSQL** | Registros de `execution_history`, `agent_sessions`, `agent_events`, `tool_usage`, `token_usage`, `hardware_snapshots`, `subtask_metrics`, `long_term_memory`, `deep_search_cache`, `llm_cache`, `documents`, `document_chunks` + reset de `llm_cache_stats` |
| **Qdrant** | Todas as coleções vetoriais (ex: `deep_search_index`, `documents_index`) |

---

## 5. Diretórios de destino customizados

```bash
uv run python .agents/skills/clean_dev.py \
  --logs-dir /caminho/para/logs \
  --outputs-dir /caminho/para/outputs
```

---

## 6. Verificar estado após limpeza

Confirme que as tabelas estão vazias:

```bash
docker exec geminiclaw-postgres psql -U geminiclaw -c \
  "SELECT schemaname, tablename, n_live_tup FROM pg_stat_user_tables ORDER BY tablename;"
```

Confirme que o Qdrant não tem coleções:

```bash
curl -s http://localhost:6333/collections | python3 -m json.tool
```

---

## Referência de flags

| Flag | Efeito |
|---|---|
| `--dry-run` | Exibe o que seria removido sem executar |
| `--skip-logs` | Pula remoção de arquivos de log |
| `--skip-outputs` | Pula remoção de artefatos de output |
| `--skip-postgres` | Pula truncagem das tabelas PostgreSQL |
| `--skip-qdrant` | Pula deleção das coleções Qdrant |
| `--logs-dir <path>` | Sobrescreve o diretório de logs (padrão: `./logs`) |
| `--outputs-dir <path>` | Sobrescreve o diretório de outputs (padrão: `./outputs`) |
