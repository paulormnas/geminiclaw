# Design: Armazenamento do Grafo de Conhecimento

## 1. Infraestrutura

- `containers/Dockerfile.postgres`: base PostgreSQL 16 (Debian) + Apache AGE compilado para a
  versão compatível com PG16 (`release/PG16/*`). **Tarefa 1.1 verifica** se existe imagem
  oficial ARM64 (`apache/age`) na versão compatível; se existir, usá-la em vez de compilar.
- `docker-compose.yml`: serviço `postgres` passa a usar a nova imagem; volume
  `postgres_data` preservado (mesma versão major do PostgreSQL → dados existentes continuam
  válidos).
- Nome do grafo em `config.KNOWLEDGE_GRAPH_NAME` (default `knowledge` — sem o nome do
  produto, ADR 011).

## 2. Migração (`scripts/migrations/v17_001_knowledge_graph.sql`, idempotente)

```sql
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
-- create_graph só se não existir (verificar ag_catalog.ag_graph)
-- create_vlabel / create_elabel para cada rótulo do schema (verificar ag_catalog.ag_label)
-- índice por propriedade "id" em cada rótulo de nó
-- papel somente-leitura:
--   CREATE ROLE knowledge_reader LOGIN PASSWORD <de .env>;
--   GRANT USAGE ON SCHEMA <grafo>, ag_catalog; GRANT SELECT ON ALL TABLES IN SCHEMA <grafo>;
--   ALTER ROLE knowledge_reader SET statement_timeout = '<KNOWLEDGE_READ_TIMEOUT_MS>';
```

Um script Python (`scripts/migrate_v17_knowledge.py`) aplica o SQL lendo nomes e senha de
`config`, gerando os rótulos a partir de `src/knowledge/schema.py` (fonte única da verdade).

`src/db.py`: o pool de conexões configura cada conexão com `LOAD 'age'` e o `search_path`
(callback `configure` do `psycopg_pool`). Um segundo pool, com `KNOWLEDGE_READER_DATABASE_URL`,
atende as consultas somente-leitura.

## 3. Schema declarativo (`src/knowledge/schema.py`)

### Propriedades comuns (todo nó) — obrigatórias, preenchidas pelo `GraphStore`

`id` (UUIDv7, texto), `criado_em`, `atualizado_em` (ISO-8601 UTC), `criado_por` (ex.:
`orquestrador`, `pesquisador`, `curator/<modelo>`), `projeto_id`, `sessao_id`,
`visibilidade` (`privado` | `compartilhavel`, default `privado`), `origem_no` (default
`local`), `versao_schema` (inteiro; começa em 1).

Nós criados por agentes (`criado_por` diferente de `orquestrador`/`pesquisador`) exigem ainda
`justificativa_criacao` (texto não vazio) e `nos_consultados` (lista de IDs, pode ser vazia).

### Nós (rótulo → propriedades específicas; `*` = obrigatória)

| Rótulo | Propriedades | Enumerações |
|---|---|---|
| `Projeto` | `titulo*`, `objetivo*`, `status*` | status: `ativo`, `pausado`, `concluido` |
| `Sessao` | `modo*`, `inicio*`, `fim`, `motivo_parada`, `consumo` (mapa), `no_execucao*` | modo: `assisted`, `semi`, `auto`; motivo_parada: `solucao_encontrada`, `limite_tokens`, `limite_tempo`, `limite_retentativas`, `limite_conexao`, `erro`, `interrompida` |
| `Insumo` | `tipo*`, `titulo*`, `hash_conteudo*`, `caminho*` | tipo: `artigo`, `dataset`, `protocolo`, `outro` |
| `Problema` | `titulo*`, `resumo*`, `classe`, `caracteristicas_dados` (mapa), `criterio_sucesso` (mapa: `metrica_id`, `alvo`, `delta_min`), `status*` | status: `rascunho`, `confirmado` |
| `Hipotese` | `enunciado*`, `justificativa*`, `status*`, `origem*`, `suporte`, `certeza`, `veredito`, `n_tentativas` | status: `proposta`, `em_teste`, `validada`, `refutada`, `inconclusiva`, `abandonada`; origem: `pesquisador`, `researcher`, `curator`, `oportunidade` |
| `Abordagem` | `nome*`, `tipo*`, `descricao*`, `versao`, `config_normalizada` (mapa) | tipo: `arquitetura`, `algoritmo`, `teste_estatistico`, `pipeline`, `protocolo`, `instrumento`, `biblioteca`, `configuracao`, `outro` |
| `Experimento` | `subtarefa_id*`, `status*`, `causa_falha`, `assinatura_falha`, `hash_params`, `seed`, `hash_codigo`, `ambiente` (mapa), `caminho_artefatos*`, `no_execucao*`, `dataset_ids` (lista) | status: `sucesso`, `falha`, `divergente_documentado`; causa_falha (só com status `falha`): `infraestrutura`, `abordagem`, `ambigua` |
| `Resultado` | `nome_original*`, `valor*`, `unidade`, `baseline`, `status_validacao*`, `caminho_metrics*` | status_validacao: `validado`, `divergente_documentado`, `nao_validado` |
| `Decisao` | `contexto*`, `justificativa*`, `criterio`, `resultado_posterior` | — |
| `Descoberta` | `tipo*`, `enunciado*`, `condicoes`, `veredito`, `confianca`, `n_evidencias*`, `status*`, `ponto_de_parada`, `motivo`, `proximo_passo_sugerido` | tipo: `funciona`, `nao_funciona`, `condicional`, `licao_de_caminho`, `caminho_sem_conclusao`; status: `ativa`, `contestada`, `substituida` |
| `Oportunidade` | `enunciado*`, `justificativa*`, `status*`, `decidido_por`, `decidido_em`, `motivo_decisao` | status: `documentada`, `aprovada`, `rejeitada`, `em_investigacao`, `concluida` |
| `Dominio` | `termo*`, `nivel*`, `sinonimos` (lista), `codigo_cnpq`, `status*` | nivel: `grande_area`, `area`, `subarea`, `especialidade`; status: `candidato`, `aprovado` |
| `Metrica` | `nome*`, `sinonimos` (lista), `sentido*`, `unidade`, `faixa`, `familia`, `status*` | sentido: `maior_melhor`, `menor_melhor`; status: `candidato`, `aprovado` |

`Sessao.no_execucao` e `Experimento.no_execucao` guardam o identificador do computador
(`config.NODE_ID`, gerado uma vez e persistido) — insumo do fator de independência (§9 do
ADR 015).

### Relações permitidas (origem, tipo, destino)

```
Sessao-PERTENCE_A->Projeto            Sessao-CONTINUA->Sessao
Projeto-INVESTIGA->Problema           Projeto-RECEBEU->Insumo
Experimento-EXECUTADO_EM->Sessao      Experimento-APLICOU->Abordagem   {config, hash_params}
Experimento-USOU->Insumo              Experimento-PRODUZIU->Resultado
Resultado-MEDE->Metrica
Hipotese-SOBRE->Problema              Hipotese-PROPOE->Abordagem
Hipotese-DERIVADA_DE->{Insumo|Descoberta|Oportunidade}
Experimento-TESTA->Hipotese
Decisao-TOMADA_EM->Sessao
Decisao-ESCOLHEU->{Abordagem|Hipotese}  Decisao-DESCARTOU->{Abordagem|Hipotese} {motivo}
Decisao-INFORMADA_POR->Descoberta
Resultado-SUSTENTA->Hipotese {peso}   Resultado-REFUTA->Hipotese {peso}
Descoberta-BASEADA_EM->{Resultado|Experimento|Decisao}
Descoberta-SOBRE->{Abordagem|Problema|Hipotese}
Descoberta-CONTRADIZ->Descoberta      Descoberta-SUBSTITUI->Descoberta
Abordagem-FUNCIONOU_PARA->Problema {metrica, melhor_valor, config, n_exp, descoberta_id}
Abordagem-FALHOU_PARA->Problema {motivo, n_exp, descoberta_id}
Abordagem-VARIANTE_DE->Abordagem      Abordagem-COMPONENTE_DE->Abordagem
Oportunidade-ORIGINADA_DE->Descoberta Oportunidade-SUGERE->{Abordagem|Hipotese}
Oportunidade-PARA->Problema           Oportunidade-GEROU->Hipotese
{Projeto|Problema}-NO_DOMINIO->Dominio
Dominio-SUBAREA_DE->Dominio           Metrica-RELACIONADA_A->Metrica
{Projeto|Problema|Abordagem|Descoberta|Oportunidade}-SEMELHANTE_A->(mesmo rótulo) {score, modelo, versao}
Descoberta-SEMELHANTE_A->Problema     {score, modelo, versao}
```

Propriedades comuns de toda aresta: `criado_em`, `criado_por`, `origem`
(`fato` | `afirmado` | `derivado`), `evidencias` (lista de IDs), `status`
(`confirmada` | `contestada`).

## 4. Interface `GraphStore`

```python
class GraphStore(ABC):
    # escrita — somente por operações tipadas
    def create_node(self, label: str, props: dict, *, actor: Actor) -> str
    def update_node(self, node_id: str, changes: dict, *, actor: Actor) -> None
    def create_edge(self, src_id: str, rel: str, dst_id: str, props: dict, *, actor: Actor) -> None
    def set_edge_status(self, src_id: str, rel: str, dst_id: str, status: str, *, actor: Actor) -> None
    # leitura
    def get_node(self, node_id: str) -> Node | None
    def find_nodes(self, label: str, filters: dict, limit: int = 50) -> list[Node]
    def neighbors(self, node_id: str, rels: list[str] | None, direction: str = "both",
                  depth: int = 1) -> Subgraph
    def project_subgraph(self, projeto_id: str, labels: list[str] | None = None) -> Subgraph
    # consulta livre — conexão somente-leitura, com timeout
    def read_query(self, cypher: str, params: dict) -> list[dict]
```

`Actor` = `(kind: "orquestrador" | "pesquisador" | "agente", role: str | None, model: str | None)`;
o `GraphStore` deriva `criado_por` do `Actor` — nunca do conteúdo enviado pelo chamador.

Regras aplicadas pela implementação:

1. **Validação contra o schema:** rótulo conhecido; propriedades desconhecidas recusadas;
   obrigatórias presentes; enumerações válidas; relação permitida para o par de rótulos.
2. **Sem injeção:** rótulos e tipos de relação vêm apenas do schema (whitelist); todos os
   valores vão como parâmetros `agtype` do `cypher()` — nunca interpolados no texto.
3. **Nada é apagado:** não há operação de remoção de nó ou aresta. Correções são mudança de
   `status` ou novos nós (`SUBSTITUI`). `update_node` não altera `id`, `criado_em`,
   `criado_por`, `projeto_id`.
4. **Atualização registra histórico:** cada `update_node` grava em tabela relacional
   `knowledge_audit` (`node_id`, `actor`, `timestamp`, `changes` JSONB) — permite auditar
   correções do pesquisador e do Curator.
5. **`read_query` somente-leitura:** executa com o papel `knowledge_reader`, em transação
   `READ ONLY`, com `statement_timeout`; rejeita o texto se contiver `CREATE`, `MERGE`,
   `SET`, `DELETE`, `REMOVE` fora de literais (defesa em profundidade — a garantia real é o
   papel do banco).

`InMemoryGraphStore` (mesma interface, para testes unitários) valida com o mesmo `schema.py`.

## 5. Configuração nova

| Variável | Default |
|---|---|
| `KNOWLEDGE_GRAPH_NAME` | `knowledge` |
| `KNOWLEDGE_READER_DATABASE_URL` | (obrigatória em produção; `.env`) |
| `KNOWLEDGE_READ_TIMEOUT_MS` | `5000` |
| `NODE_ID` | gerado na primeira execução e persistido em `~/.config/<app>/node_id` |

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum nesta mudança (ingestão vem depois). |
| Agentes & Prompts | Nenhum. |
| Sandboxes & Containers | Nova imagem de infraestrutura do PostgreSQL. |
| Persistência | Extensão AGE, grafo, rótulos, índices, papel somente-leitura, tabela `knowledge_audit`. |
| Segurança | Whitelist de rótulos/relações; parâmetros; papel somente-leitura; timeout; sem remoção. |
| Testes & Telemetria | Testes unitários com `InMemoryGraphStore`; integração com AGE real (marcador `integration`). |

## Riscos

- **AGE indisponível para PG16/ARM64 em imagem pronta** — plano B: compilar no Dockerfile.
- **Desempenho de consultas de múltiplos saltos no Pi 5** — medir com 10 mil nós sintéticos
  (tarefa 5.2) antes de liberar para o Curator.
