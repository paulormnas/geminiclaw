# Proposta: Navegação do Grafo de Conhecimento do Projeto

**ID:** `v18.10-web-graph` · **Versão:** V18.10 · **Capacidade:** `web-interface`
**ADRs de origem:** [ADR 027](../../../docs/decisions/adr_027_interface_web.md) §5 (alternativa acessível), §6.4, §6.5; ADR 015 §11 (visualizar sem LLM, consultas fixas, só leitura)
**Depende de:** `v18.10-web-skeleton`. Paralela a `v18.10-web-dashboard` e `v18.10-web-artifacts`.

## Por quê

O ADR 015 §11 previa a visualização completa do grafo por um frontend. O pesquisador quer navegar o grafo do projeto (hipóteses, experimentos, resultados, abordagens, domínios e as ligações entre eles) sem a CLI.

## O que muda

- **Novo:** `src/web/routes/graph.py` e `src/web/queries/graph.py`: subgrafo do projeto com filtros, detalhe de nó, vizinhos e histórico de auditoria, tudo por `ReadOnlyGraphStore`.
- **Novo:** página Grafo com Cytoscape.js, painel de filtros, painel de detalhe e a lista acessível equivalente.
- **Fora do escopo:** edição do grafo (continua com o Curator), Cypher livre, grafo entre projetos (fica para depois do E3).

## Impacto

- **Código:** arquivos novos.
- **Schema:** nenhum; só leitura. Mudança de esquema da trilha 1 exige revisar `queries/graph.py` (lista de rótulos e relações vem de `src/knowledge/schema.py`, não de cópia).
- **Dependência nova (frontend):** `cytoscape` (e `@types/cytoscape` se faltar tipagem embutida).

## Aprovações necessárias

- **Dependência nova:** `cytoscape` no frontend.
