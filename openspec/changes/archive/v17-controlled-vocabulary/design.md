# Design: Vocabulário Controlado

## 1. Carga inicial

### Domínios (`data/vocabulary/cnpq_areas.csv`)

Colunas: `codigo_cnpq`, `termo`, `nivel` (`grande_area` | `area` | `subarea` |
`especialidade`), `codigo_pai`. Arquivo obtido da tabela oficial do CNPq, com a versão/data da
fonte registrada em `data/vocabulary/README.md`.

Script `scripts/seed_vocabulary.py` (idempotente, chave = `codigo_cnpq`):

1. cria cada `Dominio` com `status=aprovado`, `criado_por=orquestrador`;
2. cria `SUBAREA_DE` de cada termo para o pai;
3. em reexecução, não duplica; termos já existentes só têm `sinonimos` ampliados.

Nós de vocabulário usam `projeto_id="__global__"` e `visibilidade=compartilhavel` — são
comuns a todos os projetos.

### Métricas (`data/vocabulary/metrics.yaml`)

Catálogo inicial (ampliável pelo mesmo processo de candidatos):

| nome | sinônimos | sentido | faixa | família |
|---|---|---|---|---|
| `acuracia` | accuracy, acc | maior_melhor | 0–1 | classificacao |
| `f1` | f1_score, f1-score, f_measure | maior_melhor | 0–1 | classificacao |
| `precisao` | precision | maior_melhor | 0–1 | classificacao |
| `revocacao` | recall, sensitivity, sensibilidade | maior_melhor | 0–1 | classificacao |
| `auc_roc` | roc_auc, auc | maior_melhor | 0–1 | classificacao |
| `log_loss` | cross_entropy, logloss | menor_melhor | ≥0 | classificacao |
| `rmse` | root_mean_squared_error | menor_melhor | ≥0 | erro_regressao |
| `mae` | mean_absolute_error | menor_melhor | ≥0 | erro_regressao |
| `mape` | mean_absolute_percentage_error | menor_melhor | ≥0 | erro_regressao |
| `r2` | r_squared, r², coeficiente_determinacao | maior_melhor | ≤1 | ajuste_regressao |
| `rendimento` | yield, rendimento_percentual | maior_melhor | 0–100 | sintese |
| `pureza` | purity | maior_melhor | 0–100 | sintese |
| `tempo_execucao` | runtime, execution_time | menor_melhor | ≥0 | desempenho_computacional |

Métricas da mesma família são ligadas por `RELACIONADA_A`.

## 2. Resolução de termos (`src/knowledge/vocabulary.py`)

```python
@dataclass
class Resolution:
    node_id: str | None       # termo canônico encontrado ou candidato criado
    status: str               # "exato" | "sinonimo" | "semantico" | "candidato_criado"
    alternativas: list[tuple[str, float]]   # (node_id, similaridade) para revisão

def resolve_domain(term: str, *, actor: Actor, sessao_id: str) -> Resolution
def resolve_metric(name: str, *, actor: Actor, sessao_id: str) -> Resolution
```

Ordem de resolução:

1. **Exato:** termo normalizado (minúsculas, sem acentos, espaços/hífens → `_`; para métricas,
   a mesma normalização de `validator_agent._normalize_metric_name`) igual a `termo`/`nome`.
2. **Sinônimo:** igual a um item de `sinonimos`.
3. **Semântico:** busca no índice semântico (mudança `v17-knowledge-semantic-index`) entre nós
   do mesmo rótulo; similaridade ≥ `VOCAB_MATCH_THRESHOLD` (default 0,90, a faixa de
   duplicata) → usa o termo existente e **adiciona o termo livre como sinônimo candidato**
   (registrado para o pesquisador ver em `vocab pending`).
4. **Candidato:** nada encontrado → cria `Dominio`/`Metrica` com `status=candidato`; para
   `Metrica`, `sentido` é obrigatório e deve vir do chamador (o Curator infere; se não
   souber, o candidato fica sem uso no veredito até a aprovação).

Enquanto o índice semântico não existir, o passo 3 é pulado (a resolução continua correta,
apenas menos tolerante a variações).

Termos candidatos **podem ser usados** imediatamente (ADR 015 §8), marcados como candidatos.

## 3. Decisão do pesquisador (CLI determinística)

```
geminiclaw vocab pending                      # lista candidatos e sinônimos candidatos
geminiclaw vocab approve <id>                 # candidato → aprovado
geminiclaw vocab reject <id> [--motivo TEXTO] # candidato → rejeitado*
geminiclaw vocab map <id> --para <id_canonico># funde: arestas do candidato passam ao canônico;
                                              # termo vira sinônimo do canônico
```

\* Para permitir rejeição sem apagar (ADR 015 §7), a enumeração `status` de `Dominio` e
`Metrica` ganha o valor `rejeitado` nesta mudança (ajuste em `schema.py`).

Estes comandos são **operações tipadas e determinísticas** do `GraphStore` com
`Actor(kind="pesquisador")`, sem LLM. São a exceção prevista à regra "alterações pelo
Curator" (ADR 015 §11), por serem decisões fechadas (aprovar/rejeitar/mapear), não edições
livres do grafo.

`map` não apaga o candidato: marca-o `rejeitado` com `motivo_decisao="mapeado para <id>"` e
recria as arestas `NO_DOMINIO`/`MEDE` apontando para o canônico.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum direto (a ingestão usa `resolve_metric`). |
| Agentes & Prompts | Curator e Researcher usarão a resolução (mudanças seguintes). |
| Sandboxes & Containers | Nenhum. |
| Persistência | Carga de nós `Dominio`/`Metrica`; valor `rejeitado` na enumeração. |
| Segurança | CLI com operações tipadas; nenhum Cypher livre. |
| Testes & Telemetria | Testes de normalização, precedência e comandos da CLI. |
