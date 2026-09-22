---
description: Correção de Não Conformidades (NCs) em agentes, sandbox e orquestrador
---

# Workflow: Correção de Não Conformidades (NCs)

Procedimento para tratamento de desvios reportados pelo Tester / QA ou identificados durante revisão de código no GeminiClaw.

---

## Quando Usar

- Quando o Tester / QA reporta uma NC (teste falhando, comportamento inesperado, desvio de critério de aceite).
- Quando o Code Reviewer identifica um defeito ou vulnerabilidade durante revisão.
- Quando um desvio é detectado em produção/homologação.

---

## Processo

### 1. Registro da NC

Documentar a NC com:
- **Descrição:** O que foi observado vs. o que era esperado.
- **Módulo afetado:** Arquivo(s) e função(ões) envolvidos.
- **Teste que falha:** Comando para reproduzir (ex: `uv run pytest tests/unit/test_sandbox.py::test_volume_permissions -v`).
- **Severidade:** Crítica / Alta / Média / Baixa.
- **Referência:** Roadmap, ADR ou critério de aceite violado.

### 2. Análise de Causa Raiz

1. Reproduzir a falha localmente no ambiente de testes.
2. Identificar a causa raiz (bug de lógica, erro de configuração, regressão, etc.).
3. Avaliar se a correção pode introduzir outras regressões.

### 3. Correção

1. Implementar a correção na worktree ativa, seguindo as regras de [`backend-dev.md`](../rules/backend-dev.md).
2. Escrever ou atualizar o teste que valida a correção.
3. Commit semântico:
   ```bash
   git add -A && git commit -m "fix(<escopo>): <descrição da correção>"
   ```

### 4. Validação

1. Rodar o teste específico que falhava:
   ```bash
   uv run pytest <caminho_do_teste> -v
   ```
2. Rodar a suite completa para garantir ausência de regressões:
   ```bash
   uv run pytest -m "unit or integration" -v
   ```

### 5. Encerramento

- Se a NC foi encontrada durante o PR, push da correção na mesma branch.
- Se a NC foi encontrada após merge, abrir nova branch `fix/` e seguir o workflow [`do-pull-request.md`](do-pull-request.md).

---

## Regras

- Toda NC deve ter um teste automatizado que a reproduz antes da correção.
- Nunca feche uma NC sem validação completa (teste específico + suite completa).
- Nunca mascare a falha alterando a asserção.