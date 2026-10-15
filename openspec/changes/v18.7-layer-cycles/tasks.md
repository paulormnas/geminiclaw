# Tarefas: v18.7-layer-cycles

**Estado (2026-10-15):** não iniciada.

## 1. Preparação
- [ ] 1.1 Confirmar que `v18.7-source-layout` está mergeada e que a verificação de contratos acusa só a exceção `egress` ↔ `llm`; criar a worktree `.worktrees/refactor-layer-cycles`.

## 2. Arestas de llm para egress
- [ ] 2.1 Mover `Destination` para `src/llm/destination.py` sem alterar o corpo; ajustar `src/egress/gate.py`, `src/llm/vision.py`, `scripts/benchmark/comm_judge.py`, as importações nos testes e os alvos de `patch` em texto (design §5).
- [ ] 2.2 `LLMProvider.unwrap()` (padrão: o próprio provedor) e `GatedProvider.unwrap()` (provedor interno); `src/llm/metering.py` usa `unwrap()`; teste de `provider_name` com e sem filtro.
- [ ] 2.3 Mover o roteador de `src/llm/model_router.py` para `src/egress/routing.py` sem alterar o corpo; ajustar quem o importa.
- [ ] 2.4 `set_provider_resolver`, erro explícito em `get_provider()` sem resolvedor e recusa de provedor não envolvido (`unwrap() is provider`, design §5 S2); `install_provider_resolver()` em `src/egress/routing.py`, chamada no início de `main()` de `src/cli/main.py`; fixture `autouse` em `tests/conftest.py` que registra o resolvedor e o restaura; testes dos cenários "Sem registro, falha explícita", "Partida registra o roteador" e "Resolvedor que devolve provedor cru é recusado".
- [ ] 2.5 Triagem (`_triage` em `src/orchestration/autonomous_loop.py`): o `RuntimeError` do resolvedor propaga em vez de virar COMPLEX; teste do cenário "Triagem não engole a falta de resolvedor" (design §5 S3).

## 3. Garantia do filtro
- [ ] 3.1 Teste: todo provedor obtido por `get_provider()` e por `ModelRouter.get_provider(papel)` é `GatedProvider`, para `researcher`, `developer`, `validator`, `summarizer`, `curator`, `base` e `planner`.
- [ ] 3.2 Teste estático em `src/` e `scripts/` com as listas explícitas do design §5 (S1): construtores de provedor só em `src/llm/providers/`; `create_provider(` só em `src/egress/routing.py`, `src/llm/availability.py` e `scripts/benchmark/comm_judge.py`; `default_provider_factory(` só em `src/llm/availability.py`; `.unwrap()` só em `src/llm/metering.py`; `.inner` só em `src/egress/`; e o caso negativo em `tmp_path`. Substitui a regra "contém `GatedProvider(`" de `test_nenhum_ponto_de_chamada_envia_sem_gated_provider`.
- [ ] 3.3 Rodar `tests/unit/egress/test_wiring.py` sem alteração de asserções além da 3.2; só mudam caminhos (`src/egress/routing.py` no lugar de `src/llm/model_router.py`) e importações de `Destination`.

## 4. Contrato
- [ ] 4.1 Contrato de camadas com a ordem final do design §3 e a lista de exceções vazia; o teste da verificação de contratos passa.

## 5. Validação
- [ ] 5.1 `uv run ruff check .`, verificação de contratos e `uv run pytest -m "unit or integration"` verdes.
- [ ] 5.2 Atualizar esta lista e a linha de estado no PR.
