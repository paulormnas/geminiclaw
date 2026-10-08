# Tarefas: v17-graph-cli

**Estado (2026-10-08):** Implementada, com pendências — PR #107. Os itens abertos abaixo são validação em ambiente real (AGE/Qdrant/Pi 5, adiada para a bateria final) e débitos documentados.

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

## 5. Revisão de segurança do PR #107 (2026-10-07)
- [x] 5.1 Mostrar por inteiro o que é gravado; propriedades de relação restritas; invariante gravado == exibido.
- [x] 5.2 Regras de rótulo/fato/derivada em `create_edge` e `set_edge_status`.
- [x] 5.3 `HumanConfirmation` exigida por `apply_plan`; guarda estática ampliada.
- [x] 5.4 Requisitos e cenários de segurança na spec; seção "Segurança" no design.
- [x] 5.5 Confirmação só com a palavra exata `aplicar`.
- [x] 5.6 Mermaid escapa `#`; sugestões (contagem oculta, JSON, auditoria de ajustes, rótulo da explicação,
  reconferência de `create_edge`, auto-laço, nan/inf, prompt do gate, `decidido_em`).
- [x] 5.7 Falha de reversão reportada e auditada.

## 6. Adiado (tarefas futuras)
- [ ] 6.1 Validar com Apache AGE real: `audit_history`, `record_audit_note` e a reversão (inclui a semântica de `None`).
- [ ] 6.2 Usar o papel `knowledge_reader` (ou transação `READ ONLY`) na visualização, em vez da fachada apenas.
- [ ] 6.3 Carregar o subgrafo em streaming (hoje o projeto inteiro vai para a memória antes do corte); limite de 10.000
  domínios em `--dominio`.
- [ ] 6.4 Compare-and-set no store para eliminar a janela entre conferência e escrita.
- [ ] 6.5 `HumanConfirmation` é construível por qualquer código Python do mesmo processo; a guarda estática é regex e
  cai com `getattr`/`importlib`. A fronteira real é o sandbox/processo (ADR 014), não a guarda. Avaliar assinatura/canal
  fora do processo se o modelo de ameaça mudar.
- [ ] 6.6 O prompt do `HumanGate` da Oportunidade corta a descrição em 400 caracteres (a tela principal da proposta é
  íntegra); exibir a operação completa no prompt.
- [ ] 6.7 A reversão grava `None` em campos que antes não existiam (equivalente a "sem valor" no store em memória);
  confirmar no AGE real (junto com 6.1).
