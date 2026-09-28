# Proposta: Armazenamento do Grafo de Conhecimento (Apache AGE)

**ID:** `v17-graph-store` · **Versão:** V17 · **Capacidade:** `knowledge-graph`
**ADRs de origem:** [ADR 009](../../../docs/decisions/adr_009_camada_conhecimento_experimental.md) §4,
[ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §2–§5, §11

## Por quê

O ADR 009 escolheu Apache AGE (extensão do PostgreSQL 16) para o grafo de conhecimento, e o
ADR 015 definiu os tipos de nós, relações e propriedades. Não existe banco de grafo no
projeto. Esta mudança cria o armazenamento e a **única porta de acesso** a ele — todas as
mudanças seguintes da V17 (ingestão, vocabulário, índice semântico, Curator, CLI) escrevem e
leem o grafo por esta camada.

## O que muda

- **Novo:** imagem PostgreSQL 16 com a extensão Apache AGE (ARM64), substituindo
  `postgres:16-alpine` no `docker-compose.yml`.
- **Novo:** migração idempotente que cria a extensão, o grafo e os rótulos.
- **Novo:** pacote `src/knowledge/` com:
  - `schema.py` — definição declarativa dos 13 tipos de nó, suas propriedades e das relações
    permitidas (par origem → tipo → destino), fiel ao ADR 015;
  - `graph_store.py` — interface `GraphStore` com **operações tipadas** de escrita e leitura,
    e a implementação `AgeGraphStore`;
  - `ids.py` — geração de IDs estáveis (UUIDv7).
- **Novo:** papel de banco **somente-leitura** para consultas livres (usado pelo Curator e
  pela CLI), com timeout de consulta.
- **Fora do escopo:** quem escreve cada nó (mudanças seguintes), embeddings, confiança.

## Impacto

- **Infra:** `docker-compose.yml` (serviço `postgres`), novo `containers/Dockerfile.postgres`.
- **Banco:** nova extensão, novo grafo e novo papel de banco.
- **Código:** `src/knowledge/` (novo), `src/db.py` (configuração de sessão AGE no pool),
  `src/config.py`, `scripts/`.
- **Pi 5:** AGE roda dentro do PostgreSQL existente — nenhum serviço novo.

## Aprovações necessárias

1. **Alteração de `docker-compose.yml` e novo Dockerfile de infraestrutura** — aprovação
   explícita.
2. **Alteração de schema** (extensão, grafo, papel somente-leitura) — aprovação explícita.
3. **Avaliação do Analista de Segurança** sobre o papel somente-leitura e a proteção contra
   injeção de Cypher.
