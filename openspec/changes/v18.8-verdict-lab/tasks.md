# Tarefas: v18.8-verdict-lab

**Estado (2026-10-18):** especificada; aguarda aprovação do pesquisador. Nenhuma tarefa iniciada.

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada pelo pesquisador (sem aprovação de schema).
- [ ] 0.2 Worktree `.worktrees/feat-v18.8-verdict-lab`; spec confrontada com o código (design §1).

## 1. Variantes
- [ ] 1.1 `scripts/verdict_lab/variants.py`: `Variant`, carga e validação do JSON, `lab_verdict` (delega a `compute_verdict` sem `estrutura`; reimplementação com as alternativas do design §3.2).
- [ ] 1.2 `scripts/verdict_lab/variantes.json` com as variantes padrão (design §3.3).
- [ ] 1.3 Testes dos requisitos "Variante atual idêntica ao veredito do sistema" e "Variantes declaradas em arquivo".

## 2. Repetição sobre grafos arquivados
- [ ] 2.1 `scripts/verdict_lab/replay.py`: carga em `InMemoryGraphStore`, `KnowledgeService.collect_attempts`, reconstrução da métrica para arquivos antigos.
- [ ] 2.2 `scripts/benchmark/footprint.py`: `Metrica` e `MEDE` em `project_graph_full`.
- [ ] 2.3 Testes de "Repetição sobre grafos arquivados" e de `specs/benchmark/spec.md`.

## 3. Grade, simulação, sensibilidade e propriedades
- [ ] 3.1 `scripts/verdict_lab/scenarios.py`: catálogo das famílias E, V, R, S, N, F, M e B com `esperado` proposto (design §4).
- [ ] 3.2 `scripts/verdict_lab/simulation.py` (design §5).
- [ ] 3.3 `scripts/verdict_lab/properties.py` e o comando `sensibilidade` (design §6).
- [ ] 3.4 Testes de "Grade sintética com desfecho esperado", "Simulação com resposta conhecida" e "Sensibilidade e propriedades por variante".

## 4. Saída e linha de comando
- [ ] 4.1 `scripts/verdict_lab/output.py` e `__main__.py` (design §7).
- [ ] 4.2 Testes de "Saída reprodutível" e de "Laboratório do veredito sem efeito no sistema".

## 5. Validação
- [ ] 5.1 `uv run ruff check .`, `uv run lint-imports` e `uv run pytest -m "unit or integration" -v` verdes no Raspberry Pi.
- [ ] 5.2 `replay` sobre os 18 grafos de `~/bench/` reproduz as tabelas 5.1 a 5.4 do [relatório da etapa 1](../../../docs/calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md).
- [ ] 5.3 Revisão do `esperado` do catálogo pelo pesquisador (design §12, questão 1) antes de usar a grade para escolher variantes.
- [ ] 5.4 `grade`, `simulacao` e `sensibilidade` executadas no Raspberry Pi; relatório da etapa 2 em `docs/calibracao-veredito/`, com leitura e limitações, em PR próprio.
- [ ] 5.5 `tasks.md` com caixas e linha **Estado** atualizadas no PR; ADR 025 (etapas 1 e 2) confirmado pelo Arquiteto depois do merge.
