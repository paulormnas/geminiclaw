# Tarefas: v17-graph-cli

## 1. Visualização
- [ ] 1.1 `src/knowledge/graph_views.py` com renderizadores `text`, `table`, `json`, `mermaid`.
- [ ] 1.2 `geminiclaw graph show` com filtros e truncamento (`GRAPH_SHOW_MAX_NODES`).
- [ ] 1.3 `geminiclaw graph node <id>` com auditoria e detalhamento do veredito.

## 2. Alteração
- [ ] 2.1 `src/knowledge/change_proposals.py`: tipos de operação e validação a seco.
- [ ] 2.2 Modo de edição do Curator com `propose_changes` e somente ferramentas de leitura.
- [ ] 2.3 `geminiclaw graph edit`: exibir proposta, aplicar/cancelar/ajustar (até 3 rodadas), aplicar com `Actor(pesquisador)`.

## 3. Testes
- [ ] 3.1 `graph show` não chama nenhum provedor LLM (mock que falha se chamado).
- [ ] 3.2 Os quatro formatos para um subgrafo de exemplo; `json` é válido.
- [ ] 3.3 Operação inválida na proposta é apontada antes da confirmação.
- [ ] 3.4 Cancelar não altera o grafo; aplicar grava com autoria `pesquisador` e auditoria com o pedido.
- [ ] 3.5 Pedido de remoção vira mudança de status.
- [ ] 3.6 No modo de edição, o Curator não tem ferramentas de escrita.

## 4. Fechamento
- [ ] 4.1 Ruff, testes, revisão nos 7 eixos, PR.
