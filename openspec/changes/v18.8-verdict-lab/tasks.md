# Tarefas: v18.8-verdict-lab

**Estado (2026-10-18):** aprovada pelo pesquisador depois da revisão metodológica (design §13); implementada (um PR). `replay` sobre os 18 grafos de `~/bench/` reproduz a etapa 1 (29 de 30 hipóteses iguais ao gravado; 6, 0 e 0 hipóteses em 0,1, 0,3 e 0,5; maior 0,111). Falta 5.4: relatório da etapa 2 em `docs/calibracao-veredito/`, em PR próprio, depois do merge (para que o commit do manifesto seja o do código mergeado), e 5.5 (confirmação do Arquiteto para o ADR 025).

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada pelo pesquisador (sem aprovação de schema), com a revisão do design §13 e as respostas do §12.
- [x] 0.2 Worktree `.worktrees/feat-v18.8-verdict-lab`; spec confrontada com o código (design §1).

## 1. Variantes
- [x] 1.1 `scripts/verdict_lab/variants.py`: `Variant`, carga e validação do JSON, `lab_verdict` (delega a `compute_verdict` sem `estrutura`; reimplementação com as alternativas do design §3.2).
- [x] 1.2 `scripts/verdict_lab/variantes.json` com as variantes padrão (design §3.3).
- [x] 1.3 Testes dos requisitos "Variante atual idêntica ao veredito do sistema" e "Variantes declaradas em arquivo".

## 2. Repetição sobre grafos arquivados
- [x] 2.1 `scripts/verdict_lab/replay.py`: carga em `InMemoryGraphStore`, `KnowledgeService.collect_attempts`, reconstrução da métrica para arquivos antigos.
- [x] 2.2 `scripts/benchmark/footprint.py`: `Metrica` e `MEDE` em `project_graph_full`.
- [x] 2.3 Testes de "Repetição sobre grafos arquivados" e de `specs/benchmark/spec.md`.

## 3. Grade, simulação, sensibilidade e propriedades
- [x] 3.1 `scripts/verdict_lab/scenarios.py`: catálogo das famílias E, V, R, S, N, F, M e B com `esperado` proposto (design §4).
- [x] 3.2 `scripts/verdict_lab/simulation.py` (design §5).
- [x] 3.3 `scripts/verdict_lab/properties.py` e o comando `sensibilidade` (design §6).
- [x] 3.4 Testes de "Grade sintética com desfecho esperado", "Simulação com resposta conhecida" e "Sensibilidade e propriedades por variante".

## 4. Saída e linha de comando
- [x] 4.1 `scripts/verdict_lab/output.py` e `__main__.py` (design §7).
- [x] 4.2 Testes de "Saída reprodutível" e de "Laboratório do veredito sem efeito no sistema".

## 5. Validação
- [x] 5.1 `uv run ruff check .`, `uv run lint-imports` e `uv run pytest -m "unit or integration" -v` verdes no Raspberry Pi.
- [x] 5.2 `replay` sobre os 18 grafos de `~/bench/` reproduz as tabelas 5.1 a 5.4 do [relatório da etapa 1](../../../docs/calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md).
- [x] 5.3 Regras do `esperado` decididas pelo pesquisador (design §4 e §12, questão 1).
- [ ] 5.4 `grade`, `simulacao` e `sensibilidade` executadas no Raspberry Pi; relatório da etapa 2 em `docs/calibracao-veredito/`, com leitura e limitações, em PR próprio.
- [ ] 5.5 `tasks.md` com caixas e linha **Estado** atualizadas no PR; ADR 025 (etapas 1 e 2) confirmado pelo Arquiteto depois do merge.

## 6. Ajustes depois da etapa 2 (2026-10-18)
- [x] 6.1 Correções da `completa`: `b_por = variacao_sem_ganho_acumulada` (monotonicidade), `m_folga_piso`, `d_replica_contraria` e `d_variacao_sem_ganho`; variantes `base_alvo` e `completa2` (com `prior` 0,75, 0,5 e 0,25).
- [x] 6.2 Família A (recordes por acaso) no catálogo.
- [x] 6.3 Critério de aceite na simulação (`--fv-max`, tabela `aceite`).
- [x] 6.4 Testes dos requisitos "Alternativas de ajuste depois da etapa 2" e "Critério de aceite na simulação".
- [x] 6.5 Comando `selecao` (design §14): combina o critério de aceite da simulação com o catálogo da grade.
- [ ] 6.6 Segunda rodada da grade, da simulação e da sensibilidade no Raspberry Pi, com o relatório em `docs/calibracao-veredito/`, em PR próprio.
- [x] 6.7 Catálogo revisado em 2026-10-19 (cinco variações bastam; réplica em outros nós não conclui; campo `aceitaveis`; cenários Q-E5-R3-neg e E4), com os testes ajustados.
