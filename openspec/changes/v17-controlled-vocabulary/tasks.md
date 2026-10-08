# Tarefas: v17-controlled-vocabulary

**Estado (2026-10-08):** Implementada, com pendências — PR #96. Os itens abertos abaixo são validação em ambiente real (AGE/Qdrant/Pi 5, adiada para a bateria final) e débitos documentados.

## 1. Carga inicial
- [x] 1.1 Obter a Tabela de Áreas do Conhecimento do CNPq da fonte oficial; gerar `data/vocabulary/cnpq_areas.csv`; registrar fonte e data em `data/vocabulary/README.md`.
- [x] 1.2 Criar `data/vocabulary/metrics.yaml` com o catálogo do design.
- [x] 1.3 `scripts/seed_vocabulary.py` idempotente (domínios, hierarquia, métricas, `RELACIONADA_A`).
- [x] 1.4 Acrescentar `rejeitado` às enumerações de status de `Dominio` e `Metrica` em `schema.py`.

## 2. Resolução
- [x] 2.1 `src/knowledge/vocabulary.py` com `resolve_domain` e `resolve_metric` (exato → sinônimo → semântico → candidato).
- [x] 2.2 Reutilizar a normalização de `validator_agent._normalize_metric_name` (extrair para função compartilhada).
- [x] 2.3 `VOCAB_MATCH_THRESHOLD` em `src/config.py` e `.env.example`.

## 3. CLI
- [x] 3.1 `geminiclaw vocab pending|approve|reject|map`.

## 4. Testes
- [x] 4.1 Normalização: "F1-Score", "f1_score" e "F1" resolvem para `f1`; "Química Orgânica" e "quimica organica" resolvem para o mesmo domínio.
- [x] 4.2 Termo inexistente cria candidato utilizável; `approve`, `reject` e `map` mudam status sem apagar nós; `map` transfere arestas.
- [x] 4.3 Reexecutar a carga não duplica nós.

## 5. Fechamento
- [x] 5.1 Ruff, testes, revisão nos 7 eixos, PR.
