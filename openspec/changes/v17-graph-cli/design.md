# Design: Acesso do Pesquisador ao Grafo pela CLI

## 1. Visualização (sem LLM)

```
geminiclaw graph show [--project ID] [--label ROTULO ...] [--dominio TERMO]
                      [--status STATUS] [--depth N] [--format text|table|json|mermaid]
geminiclaw graph node <id> [--format text|json]
```

- Projeto padrão: o de `geminiclaw project use`; sem projeto, erro orientando `--project`.
- Implementação em `src/knowledge/graph_views.py` usando **apenas** `GraphStore`
  (`project_subgraph`, `find_nodes`, `neighbors`, `get_node`) — consultas fixas, conexão
  somente-leitura. Nenhum LLM é chamado.
- `text` (padrão): agrupado por rótulo, com as relações de cada nó em árvore; nós com
  veredito mostram valor e leitura (ex.: `+0,36 funciona (moderada)`).
- `table`: uma tabela por rótulo com as propriedades principais.
- `json`: `{"nodes": [...], "edges": [...]}` para uso por outras ferramentas.
- `mermaid`: diagrama `graph LR` para colar em Markdown (útil até existir o frontend).
- `graph node <id>`: todas as propriedades, relações de entrada e saída, histórico de
  `knowledge_audit` e, para `Hipotese`/`Descoberta`, o detalhamento do veredito
  (`verdict_breakdown`: q, m, d, b, w por tentativa).
- Paginação: acima de `GRAPH_SHOW_MAX_NODES` (200), a saída é truncada com aviso e sugestão
  de filtros.

## 2. Alteração (com o Curator)

```
geminiclaw graph edit "marque a descoberta X como contestada: o dataset estava corrompido"
geminiclaw graph edit --project ID "adicione a abordagem 'random forest' como variante de 'árvores de decisão'"
```

Fluxo:

1. A CLI chama o Curator em **modo de edição**, com o pedido e o contexto do projeto. Nesse
   modo o Curator tem só as ferramentas de **leitura** e `propose_changes(ops, explicacao)` —
   não tem ferramentas de escrita.
2. `ops` é uma lista de operações tipadas (`src/knowledge/change_proposals.py`):

   ```json
   [
     {"op": "update_node", "id": "…", "changes": {"status": "contestada"}, "motivo": "…"},
     {"op": "create_node", "label": "Abordagem", "props": {"nome": "random forest", "tipo": "algoritmo", "descricao": "…"}},
     {"op": "create_edge", "src": "…", "rel": "VARIANTE_DE", "dst": "…", "props": {}},
     {"op": "set_edge_status", "src": "…", "rel": "FUNCIONOU_PARA", "dst": "…", "status": "contestada"}
   ]
   ```

3. A CLI faz **validação a seco** de cada operação contra o schema (mesmas regras do
   `GraphStore`) e exibe: explicação do Curator, operações em linguagem clara, e para
   `update_node` o valor atual → novo.
4. O pesquisador responde **aplicar**, **cancelar** ou **ajustar** (texto que volta ao
   Curator para nova proposta; até 3 rodadas).
5. Ao aplicar, a CLI executa as operações pelo `GraphStore` com
   `Actor(kind="pesquisador")` — autoria `pesquisador` e auditoria em `knowledge_audit`,
   com o pedido original anexado.

Pedidos de **remoção** são convertidos pelo Curator em mudança de status (`contestada`,
`substituida`, `rejeitada`), pois nada é apagado; a explicação informa isso ao pesquisador.
Nós criados manualmente pelo pesquisador passam pelas mesmas verificações de duplicata do
Curator, exibidas como aviso (o pesquisador pode prosseguir mesmo assim).

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum. |
| Agentes & Prompts | Modo de edição do Curator (somente proposta). |
| Sandboxes & Containers | Nenhum. |
| Persistência | Escritas autorizadas pelo pesquisador, auditadas. |
| Segurança | Visualização sem LLM; edição só com confirmação humana; operações tipadas; sem acesso direto ao banco. |
| Testes & Telemetria | Testes de formatos, validação a seco e fluxo de confirmação. |

## Segurança

Modelo de ameaças do `graph edit` (nota de 2026-10-07, após a revisão de segurança do PR #107):

- **Entradas não confiáveis:** pedido e ajustes do pesquisador (podem conter texto colado), conteúdo do grafo e saída
  do LLM. Pedido e ajuste entram no prompt como dado delimitado; a explicação do modelo é exibida **depois** das
  operações e rotulada "não verificada".
- **Mostrado == aplicado (2026-10-07):** todo valor a gravar é exibido por inteiro, em JSON canônico; a mesma
  sanitização vale para a tela e para o que é gravado; proposta que não cabe em `GRAPH_EDIT_MAX_DISPLAY_CHARS` é
  recusada, nunca truncada. A impressão digital (SHA-256 da serialização canônica de operações, alvos, valores efetivos,
  estado anterior e decisão) é mostrada e conferida em `apply_plan`.
- **Prova de confirmação:** `apply_plan` exige `HumanConfirmation` (palavra exata `aplicar`, TTY, impressão digital da
  proposta); só `src/cli_graph.py` a emite e usa `apply_plan`. Guarda estática em `tests/unit/research_project/
  test_hardening.py` e `test_graph_cli_review_fixes.py` proíbe o uso em `agents/` e `src/skills/`.
- **Propriedades de relação:** `origem`, `status`, `evidencias`, `criado_*` e as derivadas (`score`, `modelo`, `versao`,
  `config`, `hash_params`, `peso`) nunca vêm do pedido; a relação nasce `afirmado`/`confirmada`/sem evidências.
- **Rótulos e relações:** `Problema`, `Projeto`, `Dominio`, `Metrica` e fatos estruturais não são alterados nem origem
  de relação; relações derivadas (`SUSTENTA`, `REFUTA`, `FUNCIONOU_PARA`, `FALHOU_PARA`, `SEMELHANTE_A`) não são
  criadas à mão, mas **podem ser contestadas** (`set_edge_status` para `contestada`; ADR 015 §7: contestar não apaga).
- **Aplicação:** estado reconferido (inclusive `create_edge`) imediatamente antes de escrever; reversão do que for
  reversível, com falhas de reversão reportadas e auditadas; nós criados permanecem. A janela entre a conferência e a
  escrita não é atômica contra escritores concorrentes (sem compare-and-set no store): limitação registrada.
- **Risco residual (2026-10-07):** um TTY real não distingue um humano de um processo que abre um pty (`script`,
  `expect`, `pexpect`) e digita `aplicar`. Está **fora do modelo de ameaça local** (o processo com pty já controla a conta
  do pesquisador e poderia usar a CLI diretamente). A mitigação é a conferência do estado, a auditoria com o pedido e os
  ajustes, e a exibição integral antes da confirmação.
- **Reversão e `None`:** restaurar um campo antes ausente grava `None`; neste projeto `None` equivale a "sem valor".
  Confirmar essa semântica no AGE real é tarefa pendente (ver `tasks.md`).
