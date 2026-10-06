# Design: Busca de Domínio com Embeddings Hierárquicos

## 1. Texto canônico hierárquico do `Dominio`

Substitui a linha `Dominio` da tabela de `v17-knowledge-semantic-index` §1
(`src/knowledge/semantic_index.py::canonical_text`). Campos nomeados e em ordem fixa, de modo que a posição na
hierarquia entra no vetor e o texto é estável (mesmo `text_hash` para o mesmo conteúdo):

```
Domínio: Conjuntos
Nível: especialidade
Caminho: Ciências Exatas e da Terra > Matemática > Álgebra > Conjuntos
Grande área: Ciências Exatas e da Terra
Área: Matemática
Subárea: Álgebra
Sinônimos: teoria dos conjuntos; set theory
```

Regras:

1. A linha `Caminho` lista todos os ancestrais, da grande área ao próprio termo, separados por ` > `.
2. As linhas `Grande área`, `Área` e `Subárea` repetem os ancestrais por nível; só entram as dos níveis que
   existem acima do termo. Para uma `grande_area` só há `Domínio`, `Nível` e `Caminho` (com ela mesma).
3. `Sinônimos` junta `sinonimos` aprovados; os `sinonimos_candidatos` **não** entram (não foram aprovados).
4. Termo candidato (`status=candidato`) sem `SUBAREA_DE` tem caminho com um só elemento e o payload
   `caminho_completo=false`. Termo com a cadeia de pais interrompida (pai inexistente) também recebe
   `caminho_completo=false` e um aviso estruturado no log; nunca falha a escrita do nó.
5. O texto é montado por uma função pura `domain_canonical_text(node, ancestors)`, que recebe os ancestrais já
   resolvidos (`list[Node]`, da raiz ao pai). Não consulta o banco.

**Por que repetir o caminho e os níveis no texto.** O modelo de embedding só enxerga o texto. Com o caminho no
texto, "Álgebra" em matemática e em outra área ficam distantes, e a consulta "inferência estatística" aproxima a
subárea e as especialidades de Probabilidade e Estatística mesmo sem o termo exato. Os rótulos por nível
("Área:", "Subárea:") dão ao modelo a estrutura, e a repetição dá peso ao contexto sem criar um segundo
vetor.

**Alternativa descartada: um vetor por nível (vetores nomeados).** Triplicaria o armazenamento e exigiria
combinar scores; o texto hierárquico único dá o mesmo ganho de contexto com um ponto por nó, que é o contrato
de `v17-knowledge-semantic-index` (ID do ponto = `id` do nó). **Alternativa descartada: embedding só do termo
mais média dos ancestrais.** Mistura vetores em uma operação que o modelo não aprendeu e não explica o resultado.

## 2. Payload do ponto

Além do payload de `v17-knowledge-semantic-index` §1:

| Campo | Conteúdo |
|---|---|
| `nivel` | `grande_area` \| `area` \| `subarea` \| `especialidade` |
| `caminho_ids` | IDs dos nós da raiz até o próprio nó (inclusive), em ordem |
| `caminho_termos` | denominações na mesma ordem |
| `caminho_completo` | `true` quando a cadeia chega a uma `grande_area`; `false` caso contrário |
| `codigo_cnpq` | código oficial, quando houver |

O filtro "dentro de" usa o campo `caminho_ids` (índice de payload do tipo `keyword`, que casa se o ID está na
lista), o que seleciona toda a subárvore de um nó com uma só condição.

## 3. Reconciliação por ancestral

`text_hash` de um domínio é calculado sobre o texto da §1; portanto muda quando o termo ou os sinônimos de um
ancestral mudam. `SemanticIndex.reconcile()` já revetoriza nós cujo `text_hash` difere do ponto; esta mudança
só acrescenta o **cálculo do hash com os ancestrais**: ao aprovar um sinônimo ou renomear um termo, os
descendentes são marcados `pendente` (`estado_vetorizacao`) na mesma operação, em lotes limitados por
`DOMAIN_REINDEX_BATCH` (padrão 200), sem bloquear a escrita.

## 4. `DomainSearch`

```python
@dataclass(frozen=True)
class DomainHit:
    node_id: str
    termo: str
    nivel: str
    caminho: list[str]          # denominações, da grande área ao termo
    caminho_ids: list[str]
    score: float
    status: str                 # "aprovado" | "candidato"
    sinonimos: list[str]

class DomainSearch:
    def search(self, text: str, *, context: str | None = None, within: str | None = None,
               max_level: str | None = None, include_candidates: bool = False,
               limit: int | None = None) -> list[DomainHit]
```

Algoritmo:

1. Valida e normaliza a entrada: texto de 2 a `DOMAIN_SEARCH_MAX_QUERY_CHARS` (300) caracteres; mais longo
   é truncado e registrado; vazio levanta `ValueError`. `context` (opcional, por exemplo o título do problema) é
   truncado do mesmo modo e concatenado à consulta com o rótulo `Contexto:`.
2. Formata a consulta no mesmo molde do texto canônico (`Domínio: <texto>`) para ficar no mesmo espaço
   semântico dos pontos.
3. Busca no Qdrant com filtros: `tipo_no == "Dominio"`, `status` em `aprovado` (e `candidato` se
   `include_candidates`), `nivel` em níveis até `max_level`, `caminho_ids` contendo `within`; pede
   `limit * 3` pontos (mínimo 15) para permitir o desempate por especificidade.
4. **Preferência pelo mais específico:** entre os resultados com `score ≥ score_topo − DOMAIN_SPECIFICITY_MARGIN`
   (padrão 0,03), ordena por nível mais profundo primeiro e depois por score; os demais seguem por score.
   Assim "estatística" devolve a subárea ou a especialidade quando a pontuação é equivalente à da área, e a
   área continua aparecendo como alternativa mais ampla.
5. Descarta `score < DOMAIN_SEARCH_MIN_SCORE` (padrão 0,35; depende do modelo, ver §8) e devolve até `limit`
   (padrão `DOMAIN_SEARCH_LIMIT` = 5, máximo 10).

Retorno vazio significa "sem correspondência", e quem chama decide criar candidato (`resolve_domain`). A
busca nunca escreve.

## 5. Integração com `resolve_domain`

`vocabulary.resolve_domain` mantém os passos 1 (exato) e 2 (sinônimo). O passo 3 (semântico) passa a chamar
`DomainSearch.search(term, context=problem_text)`:

- melhor score ≥ `VOCAB_MATCH_THRESHOLD` (mesma variável de `v17-controlled-vocabulary`): status `semantico` com
  o nó e as demais como `alternativas` (`(node_id, score)`);
- abaixo do limiar: segue para criar candidato, e as três melhores viram `alternativas` para revisão humana.

O parâmetro `semantic_search` injetável de `resolve_domain` é preservado; `DomainSearch.search` é o valor
padrão quando o índice existe.

## 6. Ferramenta `buscar_dominio` (skill `vocabulary`)

`src/skills/vocabulary/skill.py`, registrada para os papéis `researcher` e `curator` (não para `developer`,
que não escreve no grafo). Parâmetros: `texto` (obrigatório), `contexto`, `dentro_de` (código CNPq ou ID),
`nivel_maximo`, `incluir_candidatos`. Saída em texto curto e estável:

```
1. Ciência da Computação > Inteligência Artificial  (subárea, score 0,71, id=...)
2. ...
```

mais `sem_correspondencia: true` quando vazio. Regras:

- **Somente leitura:** nenhuma escrita no grafo, em arquivo ou em rede; o texto da consulta nunca é executado nem
  interpolado em Cypher (a busca é vetorial e os filtros são parâmetros).
- No máximo 10 resultados e 300 caracteres por entrada; resposta com no máximo 2 000 caracteres.
- `dentro_de` aceita o `codigo_cnpq` ou o `id` do nó; valor desconhecido devolve erro explícito, não busca global.
- Evento de telemetria `domain_search` (`resultados`, `melhor_score`, `nivel_do_melhor`, `candidatos_incluidos`)
  **sem o texto da consulta**, pois ela pode conter conteúdo de pesquisa (ADR 019 §3).

## 7. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `DOMAIN_SEARCH_LIMIT` | `5` | resultados devolvidos (máximo 10) |
| `DOMAIN_SEARCH_MIN_SCORE` | `0.35` | escore mínimo (por modelo de embedding) |
| `DOMAIN_SPECIFICITY_MARGIN` | `0.03` | margem para preferir o nível mais específico |
| `DOMAIN_SEARCH_MAX_QUERY_CHARS` | `300` | tamanho máximo da consulta |
| `DOMAIN_REINDEX_BATCH` | `200` | lote de descendentes marcados `pendente` por operação |
| `VOCAB_MATCH_THRESHOLD` | (existente) | limiar do passo semântico em `resolve_domain` |

## 8. Avaliação do modelo de embedding

O padrão atual, `sentence-transformers/all-MiniLM-L6-v2`, é centrado em inglês, e os termos do CNPq estão em
português. Esta mudança não troca o modelo; ela entrega o **instrumento para decidir**:

- `tests/fixtures/domain_queries.jsonl`: consultas em português e em inglês, escritas pelo pesquisador ou por
  quem ele indicar, com o código CNPq esperado em qualquer nível aceito (uma linha por consulta:
  `consulta`, `esperados` (lista de códigos aceitos), `idioma`). Tamanho inicial sugerido: 40 consultas. O
  arquivo **não** vem de um caso de estudo: usa exemplos genéricos de várias áreas.
- `scripts/eval_domain_search.py`: carrega a tabela em um índice em memória com o modelo configurado e calcula
  acerto no topo (`hit@1`), `hit@3` e a posição média do primeiro acerto, por idioma. Roda no Pi 5 e
  localmente; não é executado no CI (precisa baixar o modelo).
- O relatório da avaliação acompanha o PR de implementação e embasa a decisão do pesquisador sobre
  `EMBEDDING_MODEL` e sobre `DOMAIN_SEARCH_MIN_SCORE`.

## 9. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum. |
| Agentes & Prompts | Nova ferramenta para Researcher e Curator; instrução curta de quando usá-la (antes de ligar `NO_DOMINIO`). |
| Sandboxes & Containers | Nenhum. |
| Persistência | Payload novo nos pontos `Dominio` da coleção existente; reindexação dos 1335 pontos; sem schema relacional ou de grafo. |
| Segurança | Entrada limitada e tratada como dado; busca vetorial com filtros parametrizados; telemetria sem o texto; ferramenta sem escrita. |
| Testes & Telemetria | Embeddings simulados nos testes (vetores determinísticos por texto); avaliação com modelo real fora do CI; evento `domain_search`. |

## 10. Riscos e questões em aberto

- **Modelo em inglês sobre termos em português:** pode errar consultas coloquiais. Mitigação: a avaliação da §8
  antes de adotar limiares; `EMBEDDING_MODEL` é configurável e o índice é versionado.
- **Escore mínimo e margem dependem do modelo:** valores padrão são iniciais e devem ser ajustados pela avaliação.
- **Hierarquia incompleta em candidatos:** mitigada por `caminho_completo=false` e pela exclusão dos candidatos da
  busca padrão.
- **Questão em aberto (pesquisador):** trocar `EMBEDDING_MODEL` por um modelo multilíngue, caso `hit@3` fique
  abaixo do esperado (o PR de implementação traz a medição; sugiro tratar como meta `hit@3` ≥ 0,85).
