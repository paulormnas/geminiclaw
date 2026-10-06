# Design: Índice Semântico do Grafo e Fila de Similaridade

## 1. Coleção e texto canônico

Coleção `config.KNOWLEDGE_COLLECTION` (default `knowledge_nodes`), distância cosseno,
dimensão do provedor local. **ID do ponto = `id` do nó** (UUID).

Rótulos vetorizados e texto canônico (`src/knowledge/semantic_index.py::canonical_text`):

| Rótulo | Texto canônico (campos concatenados com rótulos, na ordem) |
|---|---|
| `Projeto` | titulo, objetivo |
| `Problema` | titulo, resumo, classe, caracteristicas_dados, criterio_sucesso (métrica e alvo) |
| `Hipotese` | enunciado, justificativa |
| `Abordagem` | nome, tipo, descricao |
| `Descoberta` | tipo, enunciado, condicoes |
| `Decisao` | contexto, justificativa |
| `Oportunidade` | enunciado, justificativa |
| `Dominio` | termo, sinonimos |
| `Metrica` | nome, sinonimos, familia |

`Sessao`, `Insumo`, `Experimento` e `Resultado` não são vetorizados.

Payload: `tipo_no`, `projeto_id`, `dominios` (IDs em nível `area`, ver §4), `status`,
`visibilidade`, `veredito` (quando houver), `criado_em`, e `embedding_payload(texto)`
(`embedding_model`, `embedding_version`, `embedding_dim`, `text_hash`).

## 2. Fluxo de escrita e reconciliação

`schema.py` ganha a propriedade de sistema `estado_vetorizacao` (`pendente` | `ok`) nos
rótulos vetorizados.

Implementação: o gancho é o decorator `IndexedGraphStore` (`src/knowledge/indexed_store.py`), que
envolve o `GraphStore` sem alterá-lo; `factory.open_graph_store()` devolve o store indexado
(`KNOWLEDGE_SEMANTIC_INDEX_ENABLED`, padrão ligado), de modo que toda escrita de produção —
inclusive as do vocabulário controlado — passa pelo gancho. `estado_vetorizacao` é de sistema:
o chamador não pode gravá-lo. `reconcile` varre o grafo em páginas por cursor de `id`
(`GraphStore.list_nodes`, `SIM_RECONCILE_BATCH_SIZE`), também atualiza o payload (`status`,
`visibilidade`, `projeto_id`) quando diverge do nó, e só recria a coleção (mudança de dimensão) com
confirmação explícita e se ela for `KNOWLEDGE_COLLECTION` e só tiver pontos de nós do grafo.

1. `GraphStore.create_node`/`update_node` grava o nó com `estado_vetorizacao="pendente"`
   quando o texto canônico mudou (comparando `text_hash`).
2. Gancho pós-escrita chama `SemanticIndex.upsert(node)` → embedding local → upsert no Qdrant
   → `estado_vetorizacao="ok"`.
3. Falha no passo 2 não desfaz o nó; ele fica `pendente`.
4. `SemanticIndex.reconcile()` (no início de cada sessão e por
   `geminiclaw knowledge reindex`): revetoriza nós `pendente`, nós cujo `text_hash` difere do
   ponto, e pontos de modelo/versão diferentes do atual.

## 3. Busca

```python
def similar(self, *, text: str | None = None, node_id: str | None = None,
            labels: list[str], filters: dict | None = None,
            min_score: float = 0.0, limit: int = 20) -> list[Hit]    # Hit(node_id, label, score)

def related_experience(self, problema_id: str, limit: int = 10, *,
                       restrict_to_visible: bool = False) -> list[ExperienceItem]
```

`similar` e `related_experience` **nunca** devolvem nós com `status` `substituida`, `rejeitado` ou
`rejeitada`. `similar(projeto_id=...)` e `related_experience(restrict_to_visible=True)` restringem a
nós do próprio projeto ou `compartilhavel` (nada de outro projeto privado — usado por consumidores
que não são o pesquisador local, ex.: registros remotos, ADR 013); o padrão é a visão local, em
que todos os projetos são do mesmo pesquisador. `filters` só aceita chaves do payload.

`related_experience` — consulta híbrida para a pergunta "o que já funcionou ou falhou em
problemas parecidos?":

1. `similar(node_id=problema_id, labels=["Problema"], min_score=SIM_RELATED_MIN_CROSS)`.
2. Para cada problema similar, no grafo: `Abordagem-FUNCIONOU_PARA|FALHOU_PARA->Problema`,
   `Descoberta-SOBRE->Problema` (status `ativa`) e `Decisao` ligadas às sessões do projeto.
3. `rank = similaridade × max(confianca, CONFIDENCE_FLOOR) × recencia`, com
   `recencia = 0,5 ^ (idade_dias / RECENCY_HALF_LIFE_DAYS)` e `CONFIDENCE_FLOOR = 0,05` (para
   itens sem veredito não zerarem).

## 4. Domínio de um nó e "entre domínios"

- `Projeto`/`Problema`: domínios pelas arestas `NO_DOMINIO`.
- Demais rótulos: domínios do `Problema` do seu projeto.
- Cada domínio é levado ao seu ancestral de nível `area` (ou mantido, se já for
  `grande_area`/`area`) — assim "Química Orgânica" e "Química Inorgânica" contam como o
  mesmo domínio `Química`.
- **Par entre domínios** = conjuntos de domínios (nível `area`) disjuntos. Se um dos lados **não tem
  domínio atribuído**, o par **não** é "entre domínios" (conservador). Como o domínio costuma ser
  atribuído depois da criação do nó, criar `NO_DOMINIO` reavalia os pares do nó e atualiza
  `entre_dominios`/`prioridade` dos pares ainda pendentes.
- **Par entre projetos** = `projeto_id` diferentes.

## 5. Geração de candidatos

Após `upsert` de nó de rótulo elegível, buscar vizinhos (sem limite de quantidade, até
`SIM_CANDIDATE_SCAN_LIMIT` = 200 por varredura, paginando se necessário):

| Par | Condição de entrada na fila |
|---|---|
| Mesmo rótulo ∈ {`Projeto`, `Problema`, `Abordagem`, `Descoberta`, `Oportunidade`} | `score ≥ 0,90` → tipo `duplicata`; `0,70 ≤ score < 0,90` → `relacionado`; `0,60 ≤ score < 0,70` → `relacionado` **somente se** o par é entre domínios |
| `Descoberta` → `Problema` de **outro projeto** | `score ≥ 0,60` (mesmas regras de domínio) **e** `|veredito| ≥ 0,3` na descoberta |

`Descoberta`↔`Problema` com score ≥ 0,90 é `relacionado` (`duplicata` só vale para o mesmo rótulo).

Pares envolvendo nós com `status` `substituida`, `rejeitado` ou `rejeitada` são ignorados.

Limiares em configuração, por modelo de embedding:

| Variável | Default |
|---|---|
| `SIM_DUPLICATE_MIN` | 0.90 |
| `SIM_RELATED_MIN_SAME_DOMAIN` | 0.70 |
| `SIM_RELATED_MIN_CROSS` | 0.60 |
| `SIM_CROSS_PROJECT_MIN_CONFIDENCE` | 0.30 |
| `SIM_CROSS_DOMAIN_BOOST` | 1.5 |
| `RECENCY_HALF_LIFE_DAYS` | 365 |

## 6. Tabela `similarity_queue`

```sql
CREATE TABLE IF NOT EXISTS similarity_queue (
    id              BIGSERIAL PRIMARY KEY,
    node_a          TEXT NOT NULL,        -- menor ID do par (par não ordenado)
    node_b          TEXT NOT NULL,
    label_a         TEXT NOT NULL,
    label_b         TEXT NOT NULL,
    tipo            TEXT NOT NULL,        -- 'duplicata' | 'relacionado'
    score           REAL NOT NULL,
    entre_dominios  BOOLEAN NOT NULL,
    entre_projetos  BOOLEAN NOT NULL,
    prioridade      REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pendente',  -- 'pendente' | 'confirmado' | 'descartado'
    text_hash_a     TEXT NOT NULL,
    text_hash_b     TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    revisado_em     TIMESTAMPTZ,
    revisado_por    TEXT,
    motivo          TEXT,
    UNIQUE (node_a, node_b, embedding_model, embedding_version, text_hash_a, text_hash_b)
);
CREATE INDEX IF NOT EXISTS idx_simq_pendente ON similarity_queue (status, prioridade DESC);
```

- **Prioridade** = `score × peso_evidencia × (SIM_CROSS_DOMAIN_BOOST se entre_dominios)`, com
  `peso_evidencia` = maior `confianca` entre os dois nós, ou 0,5 se nenhum tem veredito.
- **Par já avaliado** (`confirmado`/`descartado`) não volta à fila enquanto `text_hash_a` e
  `text_hash_b` forem os mesmos; se um texto mudar, o par pode ser reinserido como novo
  registro (o antigo permanece como histórico; por isso os hashes de texto fazem parte da chave
  única). Ao inserir o registro novo, os registros **pendentes** antigos do mesmo par/modelo viram
  `descartado` com `revisado_por="sistema"` e motivo "texto alterado": o Curator nunca revisa par
  obsoleto, e essas revisões automáticas não entram na taxa de confirmação.
- API (`src/knowledge/similarity_queue.py`): `enqueue`, `next_batch(limit)` (ordenado por
  prioridade), `mark_confirmed(id, by, motivo)`, `mark_discarded(id, by, motivo)`,
  `confirmation_rate(window_days)`.
- **Somente pares confirmados viram aresta** `SEMELHANTE_A` (feito pelo Curator via
  `GraphStore.create_edge`, com `score`, `modelo`, `versao`).

## 7. Calibração pelo uso

Só há sugestão com ao menos `SIM_CALIBRATION_MIN_SAMPLES` (10) pares revisados na faixa.

`geminiclaw knowledge stats` mostra a taxa de confirmação dos últimos
`SIM_CALIBRATION_WINDOW_DAYS` (30) dias por tipo e faixa, e **sugere** ajuste: taxa < 10% na
faixa baixa → subir o limite inferior; taxa > 60% → descer. O ajuste em si é uma mudança de
configuração feita pelo pesquisador — o sistema não muda limiares sozinho.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Reconciliação no início da sessão (rápida quando não há pendências). |
| Agentes & Prompts | Nenhum direto; Curator e Researcher consomem a API. |
| Sandboxes & Containers | Nenhum. |
| Persistência | Coleção `knowledge_nodes`; tabela `similarity_queue`; propriedade `estado_vetorizacao`. |
| Segurança | Embeddings locais; nenhum vetor ou texto sai do computador. |
| Testes & Telemetria | Tamanho da fila, taxa de confirmação e tempo de varredura na telemetria. |

## Riscos

- **Crescimento da fila** em projetos grandes — mitigação: prioridade e revisão por orçamento
  (nada é descartado por falta de tempo; apenas espera).
- **Custo da varredura** no Pi 5 — mitigação: varredura por nó alterado, não do índice todo.
