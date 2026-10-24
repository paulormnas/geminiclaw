# Design: v18.10-web-graph

## 1. Contrato

| Rota | Resposta |
|---|---|
| `GET /api/graph/schema` | `{rotulos: [{nome, estados?}], relacoes: [{nome, de, para}]}` lido de `src/knowledge/schema.py` |
| `GET /api/projects/{id}/graph?rotulos=Hipotese,Experimento&estado=validada&dominio=...&limite=...` | `{nos: [{id, rotulo, titulo, estado?}], arestas: [{de, rel, para, status?}], total_nos, omitidos, filtros}` |
| `GET /api/projects/{id}/graph/nodes/{node_id}` | `{id, rotulo, propriedades, vizinhos: [{id, rotulo, titulo, rel, direcao}], vizinhos_omitidos}` |
| `GET /api/projects/{id}/graph/nodes/{node_id}/audit` | `[{momento, ator, operacao, mudancas}]` (até 50) |

- Subgrafo por `project_subgraph(projeto_id, labels)`; filtros de estado e domínio aplicados em seguida. `rotulos` só aceita nomes do esquema (400 para outros).
- **Limite sem corte silencioso nem assimétrico:** o padrão de `WEB_GRAPH_MAX_NODES` sai da medição da tarefa 0.1 e fica acima do maior projeto do `geminiclaw_bench` (nenhum projeto atual é cortado). Acima do limite, o corte é por **vizinhança**: entram `Problema` e as `Hipotese` (mais recentes primeiro) **com os nós ligados a cada uma** (experimentos, resultados, abordagens), até o limite; a resposta traz `omitidos` por rótulo e um cursor, e a interface oferece "Carregar mais" (página seguinte com o cursor), além do filtro.
- **Nó fora do projeto:** o detalhe só é servido para nó do subgrafo do projeto ou vizinho direto dele (por exemplo, `Dominio` compartilhado); senão 404.
- **Título exibido:** a primeira propriedade presente entre `titulo`, `enunciado`, `nome`, `termo`, `descricao`, cortada em 120 caracteres; senão `rotulo + id curto`.
- Propriedades devolvidas como estão no grafo (texto saneado por `sanitize_text`); valores acima de `WEB_GRAPH_PROPERTY_MAX_CHARS` (padrão 4 000) vêm cortados com `truncado`, e `GET .../nodes/{node_id}/properties/{nome}` devolve o valor inteiro ("ver completo").
- Vizinhos do detalhe agrupados por relação e direção, com a contagem de cada grupo; cada grupo é paginado (200 por página, `GET .../nodes/{node_id}/neighbors?rel=&direcao=&pagina=`), e a expansão no canvas carrega um grupo por vez.

## 2. Frontend (Designer)

- `/p/:projetoId/grafo`: três colunas no 1080p (filtros | canvas | detalhe); em telas estreitas, canvas em cima e painéis em abas.
- **Canvas (Cytoscape.js):** layout `cose` calculado uma vez por resposta; com `prefers-reduced-motion`, sem animação. Cor e forma por rótulo (forma também, para não depender só de cor); tamanho fixo; arestas com rótulo da relação ao passar o mouse ou selecionar.
- **Interações:** clicar seleciona e abre o detalhe; duplo clique expande vizinhos (pede o detalhe e acrescenta os nós ao canvas); botão "Centralizar"; busca por título dentro do subgrafo carregado.
- **Alternativa acessível (obrigatória):** aba "Lista" com a tabela dos nós filtrados (rótulo, título, estado) e, para o selecionado, a lista dos vizinhos; tudo por teclado; selecionar na lista seleciona no canvas e vice-versa.
- **Detalhe:** propriedades em lista de definição (texto, nunca HTML), vizinhos agrupados por relação, histórico de auditoria sob demanda.
- **Legenda** dos rótulos com forma e cor, e contagem por rótulo.
- O cartão "Hipóteses" do painel leva a `grafo?rotulos=Hipotese`.

## 3. Impacto nos 6 eixos

Orquestrador, agentes, sandbox: nenhum. Persistência: só leitura; custo de `project_subgraph` medido no `geminiclaw_bench` (tarefa 0.1). Segurança: §4. Testes: unidade com `InMemoryGraphStore`; integração com AGE real.

## 4. Segurança

- Só leitura por papel, transação e invólucro; nenhum Cypher vindo do navegador (os filtros são parâmetros validados contra o esquema).
- Conteúdo dos nós vem, em parte, de LLM: exibido como texto; Cytoscape recebe rótulos como texto (sem `html` labels).
- Limites de nós, vizinhos e tamanho de propriedade contra exaustão de memória do navegador e do servidor.

## 5. Questões em aberto

Nenhuma (o padrão do limite vem da medição; revisão adversarial de 2026-10-24).
