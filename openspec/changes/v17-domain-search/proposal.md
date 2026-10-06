# Proposta: Busca de Domínio com Embeddings Hierárquicos

**ID:** `v17-domain-search` · **Versão:** V17 · **Capacidade:** `domain-search`
**ADRs de origem:** [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §4 e §8
(domínios do vocabulário controlado e o passo semântico da resolução de termos);
[ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) (embeddings locais, versionados);
[ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) (o Curator registra o conhecimento)
**Origem:** pedido do pesquisador em 2026-10-06, depois de carregar a Tabela de Áreas do Conhecimento do CNPq
no vocabulário: o agente precisa consultar os domínios ao criar registros no grafo, e os embeddings devem
contemplar o caminho do nível mais alto ao mais baixo da hierarquia.
**Depende de:** [`v17-controlled-vocabulary`](../v17-controlled-vocabulary/proposal.md) (nós `Dominio` e
`SUBAREA_DE`; `resolve_domain`) e [`v17-knowledge-semantic-index`](../v17-knowledge-semantic-index/proposal.md)
(coleção `knowledge_nodes`, `SemanticIndex`, `canonical_text`)
**Modifica:** `v17-knowledge-semantic-index` (texto canônico e payload do rótulo `Dominio`)

## Por quê

A tabela do CNPq tem 1335 termos em quatro níveis (grande área, área, subárea e especialidade). O agente não
pode lê-la no prompt, e o casamento por nome normalizado e sinônimo do `resolve_domain` falha quando o texto
do agente não coincide com a denominação oficial ("aprendizado de máquina" não é um termo do CNPq). Hoje o
texto vetorizado de um `Dominio` é só `termo` e `sinonimos` (`v17-knowledge-semantic-index` §1): "Álgebra" fica
igual em qualquer ramo, e uma especialidade perde o contexto da área a que pertence. A busca semântica precisa
enxergar o caminho completo para distinguir termos homônimos, aproximar consultas de áreas vizinhas e devolver
ao agente a posição do termo na hierarquia.

## O que muda

- **Modificado:** o texto canônico do `Dominio` passa a ser **estruturado e hierárquico**: termo, nível, caminho
  completo da grande área até o termo (cada ancestral nomeado por nível) e sinônimos. O payload do ponto no
  Qdrant ganha `nivel`, `caminho_ids` (da raiz até o nó) e `caminho_termos`, permitindo filtrar por subárvore.
- **Novo:** `DomainSearch` (`src/knowledge/domain_search.py`): busca semântica de domínios que devolve candidatos
  com score, nível e caminho completo, preferindo o nível mais específico quando a pontuação empata dentro de
  uma margem, com filtros por subárvore e por nível máximo.
- **Novo:** ferramenta somente leitura `buscar_dominio` (skill `vocabulary`) oferecida ao Researcher e ao
  Curator, para o agente escolher entre candidatos antes de registrar a ligação `NO_DOMINIO`.
- **Modificado:** o passo semântico de `resolve_domain` (`v17-controlled-vocabulary` §2, passo 3) usa
  `DomainSearch`, de modo que o Curator e a ferramenta compartilham a mesma busca.
- **Novo:** reconciliação por ancestral: mudança de termo ou sinônimo de um ancestral revetoriza os
  descendentes (o `text_hash` deles muda).
- **Novo:** conjunto rotulado de consultas e comando de avaliação (acerto no topo e nos 3 primeiros) para
  escolher e validar o modelo de embedding, já que o padrão atual (`all-MiniLM-L6-v2`) é centrado em inglês e a
  tabela está em português.
- **Fora do escopo:** criação de termos novos (continua em `resolve_domain` e no processo de candidatos);
  vocabulário de métricas; busca de nós que não sejam `Dominio`; troca do modelo de embedding (decisão do
  pesquisador depois da avaliação, §8 do design).

## Impacto

- **Código:** `src/knowledge/semantic_index.py` (texto canônico e payload do `Dominio`),
  `src/knowledge/domain_search.py` (novo), `src/knowledge/vocabulary.py` (passo semântico),
  `src/skills/vocabulary/` (novo), registro da ferramenta nos papéis, `src/config.py`, `.env.example`,
  `scripts/eval_domain_search.py` (avaliação), `tests/fixtures/domain_queries.jsonl`.
- **Qdrant:** os pontos `Dominio` existentes precisam ser reindexados (texto e payload novos); nenhuma coleção
  nova. A reindexação é a reconciliação normal do índice (`geminiclaw knowledge reindex`).
- **Schema de banco e do grafo:** nenhum.
- **Custo:** nenhuma chamada LLM; embeddings locais. Indexação inicial de cerca de 1335 pontos.
- **Hardware (Pi 5):** a busca é uma consulta ao Qdrant local com um embedding da consulta.

## Aprovações necessárias

- Nenhuma alteração de schema, Dockerfile, compose, exclusão de arquivos ou `AGENTS.md`.
- **Decisão do pesquisador (design §10):** modelo de embedding multilíngue, se a avaliação mostrar que o padrão
  não atende; isso muda `EMBEDDING_MODEL` e exige reindexação completa.
