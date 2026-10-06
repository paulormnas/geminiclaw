# Tarefas: v17-curator-agent

## 1. Schema (requer aprovação explícita)
- [ ] 1.1 **Aprovação:** `Abordagem.status` (`ativa`|`fundida`), relação `FUNDIDA_EM`, `Descoberta.filtro_condicoes`.

## 2. KnowledgeService
- [ ] 2.1 Coleta de tentativas e `Criterion` a partir do grafo.
- [ ] 2.2 `recompute_hypothesis` e `recompute_discovery` (com `filtro_condicoes`).
- [ ] 2.3 Arestas `SUSTENTA`/`REFUTA` com `peso`; atalhos `FUNCIONOU_PARA`/`FALHOU_PARA`.
- [ ] 2.4 `promotion_candidates` e `promote_configuration` (≥ 3 positivos validados em ≥ 2 projetos).
- [ ] 2.5 Chamada após cada subtarefa ingerida.

## 3. Ferramentas do Curator
- [ ] 3.1 Leitura (`get_node`, `neighbors`, `find_nodes`, `similar`, `related_experience`, `read_query`, `pending_flags`, `next_similarity_batch`, `verdict_breakdown`).
- [ ] 3.2 Escrita com regras embutidas (`create_discovery`, `reinforce_discovery`, `set_discovery_status`, `link_contradiction`, `create_opportunity`, `review_similarity`, `merge_approaches`, `register_open_path`).

## 4. Sinalizações
- [ ] 4.1 `flag_for_curator` para Researcher, Developer e Validator; `curator_flags.jsonl`.
- [ ] 4.2 Consumo e marcação (`registrada`/`descartada`) pelo Curator.

## 5. Agente
- [ ] 5.1 `agents/curator/agent.py` com a instrução do design (diretrizes do ADR 015 §10 literais).
- [ ] 5.2 Papel `curator` no `ModelRouter` e em `AGENT_DEFINITIONS`; configs em `src/config.py`.
- [ ] 5.3 `consolidate` e `close_session` chamados pelo `AutonomousLoop`; orçamento por execução.
- [ ] 5.4 Chamar `reconcile_on_session_start` (`src/knowledge/semantic_runtime.py`, mudança `v17-knowledge-semantic-index`) no início da sessão, antes de qualquer consulta ao grafo, e abrir o grafo por `factory.open_graph_store()` (store indexado).

## 6. Testes
- [ ] 6.1 `create_discovery` com duplicata ≥ 0,90 é recusada e devolve o ID existente.
- [ ] 6.2 Faixa relacionada sem `diferenca` é recusada; com `diferenca` cria e liga `VARIANTE_DE`/`SEMELHANTE_A`.
- [ ] 6.3 Descoberta sem evidência é recusada; `caminho_sem_conclusao` exige ponto de parada.
- [ ] 6.4 `nos_consultados` preenchido automaticamente.
- [ ] 6.5 Recálculo reproduz os testes-ouro do veredito a partir de nós no grafo.
- [ ] 6.6 Descoberta condicional por dataset (+0,28 / −0,08 do ADR 015).
- [ ] 6.7 Promoção: 3 positivos em 1 projeto não promove; 3 positivos em 2 projetos promove; reexecução não duplica.
- [ ] 6.8 Sinalização é consumida e marcada.
- [ ] 6.9 `merge_approaches` não apaga; veredito da canônica passa a incluir as tentativas da fundida.
- [ ] 6.10 Orçamento: com 50 pares na fila e lote 20, restam 30 pendentes.
- [ ] 6.11 Falha do LLM do Curator não interrompe a sessão.

## 7. Fechamento
- [ ] 7.1 Ruff, testes, revisão nos 7 eixos, PR.
