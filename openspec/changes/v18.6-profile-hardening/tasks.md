# Tarefas: v18.6-profile-hardening

**Estado (2026-10-13):** Aprovada pelo pesquisador (correção de todas as NC-PERFIL). Implementada na branch `fix/v18.6-profile-hardening` (código, testes e documentação); `ruff` e `pytest -m unit` verdes (3457 passed, 2 skipped). Falta a validação no Pi 5 (orquestrador) e o merge do PR.

## 0. Pré-requisitos
- [x] 0.1 Mudança OpenSpec criada (proposal, design, delta de `pipeline-robustness` e `data-egress`).
- [x] 0.2 Worktree `.worktrees/fix-v18.6-profile-hardening`.

## 1. Configuração
- [x] 1.1 `REVIEW_PROFILE_MAX_COLUMNS`, `_MAX_ROWS`, `_MAX_SECONDS`, `_MAX_JSON_LINES` em `src/config.py` e `.env.example`.

## 2. `src/artifact_profile.py`
- [x] 2.1 Leitor `O_NOFOLLOW` + `S_ISREG`; `is_confined`; `read_head_text` (R2).
- [x] 2.2 Rótulos seguros e marcador numérico (R3, R6).
- [x] 2.3 Cabeçalho verificado (R1).
- [x] 2.4 Limites de colunas, linhas, tempo e linhas JSON (R5).
- [x] 2.5 Profundidade JSON, mapas, captura de exceções e `LOCALITY_MIN_GROUP_SIZE` ausente (R4, R6).

## 3. Revisor e egresso
- [x] 3.1 `build_artifact_evidence_fragments`: recusa de symlink/fora da sessão em todos os ramos; perfil em fragmento próprio.
- [x] 3.2 `ARTIFACT_PROFILE_SOURCE` e delimitação no `EgressGate`; instrução do revisor (dado observado).

## 4. Testes
- [x] 4.1 Um teste por cenário da spec delta, incluindo os ataques do parecer.

## 5. Documentação
- [x] 5.1 Parecer de segurança e roadmap V18.6 marcam NC-PERFIL-1 a 6 como corrigidas.
- [x] 5.2 `ruff` e `pytest -m unit` verdes; PR para `dev`.
