# Tarefas: v17-graph-cli

## 1. Visualização
- [x] 1.1 `src/knowledge/graph_views.py` com renderizadores `text`, `table`, `json`, `mermaid`.
- [x] 1.2 `geminiclaw graph show` com filtros e truncamento (`GRAPH_SHOW_MAX_NODES`).
- [x] 1.3 `geminiclaw graph node <id>` com auditoria e detalhamento do veredito.

## 2. Alteração
- [x] 2.1 `src/knowledge/change_proposals.py`: tipos de operação e validação a seco.
- [x] 2.2 Modo de edição do Curator com `propose_changes` e somente ferramentas de leitura.
- [x] 2.3 `geminiclaw graph edit`: exibir proposta, aplicar/cancelar/ajustar (até 3 rodadas), aplicar com `Actor(pesquisador)`.

## 3. Testes
- [x] 3.1 `graph show` não chama nenhum provedor LLM (mock que falha se chamado).
- [x] 3.2 Os quatro formatos para um subgrafo de exemplo; `json` é válido.
- [x] 3.3 Operação inválida na proposta é apontada antes da confirmação.
- [x] 3.4 Cancelar não altera o grafo; aplicar grava com autoria `pesquisador` e auditoria com o pedido.
- [x] 3.5 Pedido de remoção vira mudança de status.
- [x] 3.6 No modo de edição, o Curator não tem ferramentas de escrita.

## 4. Fechamento
- [x] 4.1 Ruff, testes, revisão nos 7 eixos, PR.
