---
description: Ciclo completo de desenvolvimento de nova feature no GeminiClaw
---

# Workflow: Ciclo de Nova Feature

Fluxo ponta a ponta desde a concepção até o merge de uma nova funcionalidade no GeminiClaw — framework de orquestração de agentes Gemini para Raspberry Pi 5.

---

## Visão Geral

```
Design ──→ Segurança ──→ Implementação ──→ Testes ──→ PR & Merge
```

---

## Fase 1: Design & Especificação (Arquiteto)

**Regras:** [`architect.md`](../rules/architect.md)

1. Consultar roadmaps (`roadmaps/`) e ADRs (`docs/decisions/`) para contexto.
2. Avaliar impacto nos 6 eixos conforme [`impact-analysis.md`](impact-analysis.md).
3. Produzir:
   - Proposta técnica com trade-offs.
   - ADR em `docs/decisions/adr_<NNN>_<titulo>.md` (se decisão arquitetural relevante).
   - Plano de implementação com sequência de tarefas.
4. Obter aprovação explícita do usuário antes de prosseguir.

---

## Fase 2: Avaliação de Segurança (Analista de Segurança)

**Regras:** [`security-analyst.md`](../rules/security-analyst.md)

1. Aplicar STRIDE adaptado para agentes de IA nos componentes afetados.
2. Verificar eixos de segurança: sandbox, segredos, contenção de recursos, rede.
3. Emitir parecer com mitigações necessárias.
4. Hardening obrigatório antes da implementação para features que envolvam containers, IPC ou acesso a dados.

---

## Fase 3: Implementação (Desenvolvedor Core/Agentes)

**Regras:** [`backend-dev.md`](../rules/backend-dev.md)

1. Criar worktree dedicada:
   ```bash
   git worktree add .worktrees/<nome-da-feature> -b feat/<nome-da-feature> dev
   cd .worktrees/<nome-da-feature>
   uv sync
   ```

2. Implementar respeitando:
   - Clean Architecture e DDD.
   - Type hints obrigatórios em funções públicas.
   - Docstrings Google Style.
   - Logging estruturado (JSON), nunca `print()`.
   - `async/await` para I/O, nunca `time.sleep()`.

3. Escrever testes junto com o código:
   - Unitários para cada módulo/classe nova.
   - De integração para fluxos com containers/banco.

4. Commits semânticos ao longo do desenvolvimento:
   ```bash
   git add -A && git commit -m "feat(<escopo>): <descrição>"
   ```

---

## Fase 4: Validação (Tester / QA)

**Regras:** [`tester.md`](../rules/tester.md)

1. Rodar todos os testes:
   ```bash
   uv run pytest -m "unit or integration" -v
   ```

2. Validar cobertura nos módulos afetados:
   ```bash
   uv run pytest --cov=src --cov=agents --cov-report=term-missing
   ```

3. Verificar regressões em testes existentes.
4. Reportar NCs (Não Conformidades) se encontradas. O desenvolvedor corrige seguindo [`fix-nc.md`](fix-nc.md).

---

## Fase 5: Pull Request & Merge

**Workflow:** [`do-pull-request.md`](do-pull-request.md)

1. Garantir que todos os testes passam.
2. Push da branch e criação do PR apontando para `dev`.
3. Code Review conforme [`review.md`](../rules/review.md).
4. Ciclo de melhorias se necessário.
5. Merge, sincronização local e limpeza da worktree.

---

## Checklist de Saída

- [ ] Todos os testes unitários e de integração passam
- [ ] Cobertura mínima atingida nos módulos afetados
- [ ] ADR criado (se decisão arquitetural relevante)
- [ ] Commits seguem Conventional Commits
- [ ] PR aprovado e merged em `dev`
- [ ] Worktree removida e branch local limpa
- [ ] Roadmap atualizado (se necessário)
