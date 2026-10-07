# Tarefas: v17-curator-agent

## 1. Schema (requer aprovação explícita)
- [x] 1.1 **Aprovação:** `Abordagem.status` (`ativa`|`fundida`), relação `FUNDIDA_EM`, `Descoberta.filtro_condicoes` (aprovado pelo pesquisador em 2026-10-06; extensão aditiva do schema, sem DDL relacional — o rótulo `FUNDIDA_EM` é criado por `scripts/migrate_v17_knowledge.py`, idempotente).

## 2. KnowledgeService
- [x] 2.1 Coleta de tentativas e `Criterion` a partir do grafo.
- [x] 2.2 `recompute_hypothesis` e `recompute_discovery` (com `filtro_condicoes`).
- [x] 2.3 Arestas `SUSTENTA`/`REFUTA` com `peso`; atalhos `FUNCIONOU_PARA`/`FALHOU_PARA`.
- [x] 2.4 `promotion_candidates` e `promote_configuration` (≥ 3 positivos validados em ≥ 2 projetos).
- [x] 2.5 Chamada após cada subtarefa ingerida.

## 3. Ferramentas do Curator
- [x] 3.1 Leitura (`get_node`, `neighbors`, `find_nodes`, `similar`, `related_experience`, `read_query`, `pending_flags`, `next_similarity_batch`, `verdict_breakdown`).
- [x] 3.2 Escrita com regras embutidas (`create_discovery`, `reinforce_discovery`, `set_discovery_status`, `link_contradiction`, `create_opportunity`, `review_similarity`, `merge_approaches`, `register_open_path`).
- [x] 3.3 Registrar a ferramenta somente leitura `buscar_dominio` (`v17-domain-search`; `domain_search_tools("curator")` em `src/skills/vocabulary`) para o papel `curator` ao criar o agente; o papel ainda não existe em `src/agent_runtime/definitions.py`.

## 4. Sinalizações
- [x] 4.1 `flag_for_curator` para Researcher, Developer e Validator; `curator_flags.jsonl`.
- [x] 4.2 Consumo e marcação (`registrada`/`descartada`) pelo Curator.

## 5. Agente
- [x] 5.1 `agents/curator/agent.py` com a instrução do design (diretrizes do ADR 015 §10 literais).
- [x] 5.2 Papel `curator` no `ModelRouter` e em `AGENT_DEFINITIONS`; configs em `src/config.py`.
- [x] 5.3 `consolidate` e `close_session` chamados pelo `AutonomousLoop`; orçamento por execução.
- [x] 5.4 Chamar `reconcile_on_session_start` (`src/knowledge/semantic_runtime.py`, mudança `v17-knowledge-semantic-index`) no início da sessão, antes de qualquer consulta ao grafo, e abrir o grafo por `factory.open_graph_store()` (store indexado).

## 6. Testes
- [x] 6.1 `create_discovery` com duplicata ≥ 0,90 é recusada e devolve o ID existente.
- [x] 6.2 Faixa relacionada sem `diferenca` é recusada; com `diferenca` cria e liga `VARIANTE_DE`/`SEMELHANTE_A`.
- [x] 6.3 Descoberta sem evidência é recusada; `caminho_sem_conclusao` exige ponto de parada.
- [x] 6.4 `nos_consultados` preenchido automaticamente.
- [x] 6.5 Recálculo reproduz os testes-ouro do veredito a partir de nós no grafo.
- [x] 6.6 Descoberta condicional por dataset (+0,28 / −0,08 do ADR 015).
- [x] 6.7 Promoção: 3 positivos em 1 projeto não promove; 3 positivos em 2 projetos promove; reexecução não duplica.
- [x] 6.8 Sinalização é consumida e marcada.
- [x] 6.9 `merge_approaches` não apaga; veredito da canônica passa a incluir as tentativas da fundida.
- [x] 6.10 Orçamento: com 50 pares na fila e lote 20, restam 30 pendentes.
- [x] 6.11 Falha do LLM do Curator não interrompe a sessão.

- [x] 6.99 (parcial, ver design nota 3: o gate é registro/auditoria ligado a 2 das 5 decisões; a barreira real é o input interativo + `validate_human_only`; as demais decisões não têm ponto no código: tarefas em `v18-usage-limits` e `v19-equipment-control`) Gate humano não pode aceitar resposta do consultor: aprovação de Oportunidade, confirmação de Problema, aprovação de termo de vocabulário, autorização de escrita em instrumento e ativação do modo sem limite exigem ação explícita do pesquisador (terminal/CLI); a resposta de `ask_researcher` (inclusive do Researcher consultor, `v18-researcher-consult`) nunca conta como autorização. Teste: gate com resposta do consultor continua pendente.

## 7. Fechamento
- [x] 7.1 Ruff, testes, revisão nos 7 eixos, PR.

## 8. Pendências adiadas (revisão do PR #106, 2026-10-06)
- [ ] 8.1 Validar com **Apache AGE real**: `update_edge`, `FUNDIDA_EM`, auditoria de arestas e as consultas do `KnowledgeService`.
- [ ] 8.2 **Benchmark do `KnowledgeService` no Raspberry Pi 5** (~200 tentativas): mede o ganho do memo de leituras; considerar atualização incremental.
- [ ] 8.3 Rodar `scripts/migrate_v17_knowledge.py` nos ambientes já migrados (cria o rótulo `FUNDIDA_EM`).
- [ ] 8.4 Dividir `src/knowledge/curator_tools.py` (leitura, escrita, orçamento) em módulos.
- [ ] 8.5 Comando humano para reverter fusão/substituição (hoje: `update_node` com autoria `pesquisador`).
- [ ] 8.6 `VARIANTE_DE` entre `Descoberta`s (hoje `SEMELHANTE_A` + `diferenca`): extensão de schema a aprovar.
- [ ] 8.7 Fechar a limitação residual de `read_query` (provar que todo nó casado é do projeto da sessão: reescrita do Cypher ou views por projeto no AGE).
