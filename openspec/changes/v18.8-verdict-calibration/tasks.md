# Tarefas: v18.8-verdict-calibration

**Estado (2026-10-19):** especificada; aguarda aprovação do pesquisador (revisão do ADR 015 §9 e as questões do design §7). Nenhuma tarefa iniciada.

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada pelo pesquisador, com a decisão do limiar dos atalhos (design §7, questão 1).
- [ ] 0.2 Worktree `.worktrees/feat-v18.8-verdict-calibration`; spec confrontada com `src/knowledge/verdict.py` e `scripts/verdict_lab/variants.py`.

## 1. Configuração
- [ ] 1.1 `VERDICT_MODEL` e as variáveis do design §3 em `src/config.py` e `.env.example`, com validação (valor desconhecido é erro).
- [ ] 1.2 `VerdictParams` com os campos novos e `from_config()`.

## 2. Modelo v2
- [ ] 2.1 `src/knowledge/verdict.py`: classificação de tipo e variação útil, `d` por tipo, `b` acumulada, alvo exigido, folga com piso e réplica contrária; `EvidenceBreakdown.tipo` e `util`.
- [ ] 2.2 O modelo `adr015` continua com o código atual, sem alteração de resultado.
- [ ] 2.3 `scripts/verdict_lab`: a variante `atual` fixa `modelo = adr015`; `lab_verdict` das variantes sem `modelo` continua independente do padrão do sistema.

## 3. Testes
- [ ] 3.1 Um teste por cenário da spec (`tests/unit/knowledge/`), incluindo a equivalência com o laboratório nos 46 cenários e na amostra da simulação.
- [ ] 3.2 Testes antigos de `evidence-scoring` rodando com `adr015`; teste de que `VERDICT_MODEL=adr015` reproduz as 29 de 30 hipóteses arquivadas.
- [ ] 3.3 Teste de integração do ciclo de hipóteses (cinco variações validam; vinte sem evolução não).
- [ ] 3.4 Teste da simulação reduzida (teto de 2 %).

## 4. Documentação
- [ ] 4.1 ADR 015 §9 revisado (9.2, 9.4, 9.5) e tabela de estado; ADR 025 e índice dos ADRs.
- [ ] 4.2 `README.md` (variáveis) e `roadmaps/roadmap_V18.8.md`.

## 5. Validação
- [ ] 5.1 `uv run ruff check .`, `uv run lint-imports` e `uv run pytest -m "unit or integration" -v` verdes no Raspberry Pi.
- [ ] 5.2 Recalcular o veredito dos grafos arquivados com o modelo v2 (`replay`) e anexar a tabela ao relatório de calibração.
- [ ] 5.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR; ADRs 015 (§9) e 025 confirmados pelo Arquiteto depois do merge.
- [ ] 5.4 Etapas 3 e 4 do ADR 025 (sessões controladas e bateria no Raspberry Pi) com confirmação do pesquisador, reconferindo o teto de 2 % com dados novos.
