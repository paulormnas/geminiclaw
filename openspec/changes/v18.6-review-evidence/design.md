# Design: v18.6-review-evidence

## 1. Qualificador de conjunto no nome de métrica

### 1.1 Regra

`src/knowledge/normalization.py` ganha:

```python
@dataclass(frozen=True)
class MetricName:
    base: str            # forma normalizada sem qualificador (ex.: "accuracy")
    qualifier: str       # "teste" | "cv" | "treino" | "validacao" | "" (sem qualificador)
    raw: str             # nome como escrito

def split_metric_name(name: str) -> MetricName: ...
```

1. O nome é dividido em palavras por `_`, `-`, `.` e espaço, sem acento e em minúsculas.
2. Se a **primeira** ou a **última** palavra está numa das listas abaixo, ela vira o
   qualificador e sai do nome base. Só uma palavra é removida, e só nas pontas.

| Qualificador | Palavras |
|---|---|
| `teste` | `test`, `teste`, `holdout`, `heldout` |
| `cv` | `cv`, `crossval`, `kfold` |
| `treino` | `train`, `training`, `treino` |
| `validacao` | `val`, `valid`, `validation`, `validacao` |

3. Sufixos estatísticos (`mean`, `media`, `std`, `desvio`) **não** são removidos: `cv_accuracy_mean`
   tem base `accuracymean` e qualificador `cv`. Assim, `cv_accuracy_mean` nunca vira acurácia de
   teste.
4. `normalize_metric_name` não muda (outros consumidores dependem dela). A regra nova é uma
   função a mais.

### 1.2 Uso

- **Revisor** (`_evaluate_metric_criteria`): um critério sobre a métrica `accuracy` aceita valores
  com qualificador `teste` ou vazio. Um critério que cita explicitamente um conjunto ("acurácia
  de validação cruzada >= 0,95") exige esse qualificador (a palavra é procurada no texto do
  critério com a mesma tabela).
- **Ingestão** (`IngestionService._mede`): `resolve_metric` recebe o nome base quando o
  qualificador é `teste` ou vazio, e o `Resultado` grava `qualificador`. Com qualificador `cv`,
  `treino` ou `validacao`, nenhuma aresta `MEDE` é criada para a métrica canônica do teste. Esses
  resultados continuam no grafo, mas não entram no veredito do `Problema`.
- `REVIEW_METRIC_QUALIFIERS` (padrão `true`): com `false`, nada muda em relação ao
  comportamento atual.

## 2. `metrics.json`: envelope e grupos

`metrics_of` passa a:

1. Aceitar `metricas` como sinônimo de `metrics` no envelope. Se as duas chaves existem, vale
   `metrics`.
2. Achatar **um** nível de grupo: `{"logistic_regression": {"accuracy": 0.93}}` vira
   `{"logistic_regression.accuracy": 0.93}`. Só valores numéricos, não booleanos. Níveis mais
   profundos são ignorados e registrados em `metrics_ignored_paths` (para o log).
3. Manter `NON_METRIC_KEYS` fora, também dentro de grupos.

Nova função para o revisor:

```python
def metric_candidates(metrics: dict[str, Any], base: str, qualifiers: set[str]) -> list[tuple[str, float]]:
    """(chave achatada, valor) de toda métrica cujo nome base é ``base`` e o qualificador está em ``qualifiers``."""
```

## 3. Avaliação de critérios

### 3.1 Critério com várias comparações

`_metric_criteria` passa a extrair **todas** as comparações do critério
(`_CRITERION_VALUE_PATTERN.finditer`). Um `MetricCriterion` passa a ter
`comparisons: list[Comparison]`. Regras:

- Se **toda** comparação cita uma métrica conhecida, o critério é avaliado de forma
  determinística e passa só se todas passam.
- Se alguma comparação não mapeia para uma métrica conhecida (ex.: "ganho >= 0.01",
  "artefato serializado menor"), o critério inteiro vai para o revisor LLM, com a tabela de
  métricas (§3.3). Ele nunca é reprovado por "métrica ausente".

### 3.2 Métrica em vários grupos

Para cada comparação, `metric_candidates` devolve os valores elegíveis:

| Candidatos | Grupo nomeado no critério | Decisão |
|---|---|---|
| 0 | — | reprova com "métrica ausente" (como hoje), citando as chaves existentes |
| 1 | — | avalia esse valor |
| >1 | sim (tokens do grupo aparecem no texto do critério) | avalia o valor do grupo nomeado |
| >1 | não | **indecidido**: o critério vai para o revisor LLM |

O grupo é "nomeado" quando todas as palavras do nome do grupo, normalizadas, aparecem no texto
normalizado do critério (ex.: `random_forest` em "acurácia do Random Forest >= 0,95").

### 3.3 Evidência de métricas para o LLM

Critérios indecididos chegam ao LLM com a tabela achatada de `metrics.json` (chave e valor),
origem `saida_execucao` (`metrics.json` já é agregado por `AGGREGATE_OUTPUT_NAMES`). O evento
`subtask_review` registra `undecided_criteria`.

## 4. Perfil estrutural de artefatos

### 4.1 Contrato

```python
# src/artifact_profile.py
def profile_artifact(path: Path, *, max_bytes: int, max_chars: int) -> str | None:
    """Descrição estrutural de um CSV/TSV ou JSON, sem nenhum valor de célula; None para outros tipos."""
```

**CSV/TSV** (delimitador detectado com `csv.Sniffer`; leitura até `max_bytes`):

```
perfil: csv, 150 linhas de dados, 5 colunas
colunas: sepal_length (numérica, 0 nulos), sepal_width (numérica, 0 nulos), ..., species (texto, 0 nulos)
```

Se o arquivo passa de `max_bytes`, a contagem vira "≥ N linhas (lidas até o limite)".

**JSON:**

```
perfil: json, objeto com 4 chaves
n_amostras: número
classes: lista[3] de texto
estatisticas: objeto com 4 chaves
estatisticas.sepal_length: objeto com 8 chaves
```

Profundidade máxima 3. Listas mostram tamanho e tipo dos itens. Valores numéricos e textos
nunca entram.

### 4.2 Localidade

- O perfil é rotulado `ContentOrigin.ESQUEMA_AGREGADO`, como os nomes de artefato hoje.
- Contagem de nulos por coluna e contagem de linhas são agregados do arquivo inteiro. A
  contagem de nulos é omitida ("nulos: omitido") quando está entre 1 e
  `LOCALITY_MIN_GROUP_SIZE - 1`, pela mesma regra de grupo pequeno do filtro (ADR 019 §3).
- O começo do conteúdo continua sendo enviado só para texto e logs (`saida_execucao`), como hoje.
  Para `dado_de_pesquisa`, o perfil substitui o trecho que o filtro retinha.
- `REVIEW_ARTIFACT_PROFILE=false` volta ao comportamento atual.

### 4.3 Instrução do revisor

A regra "Não reprove por não ver o conteúdo completo" é mantida, e entram duas regras:

- "O tamanho em bytes não é evidência de conteúdo. Não estime linhas ou colunas pelo tamanho."
- "Quando houver PERFIL, use-o para conferir linhas, colunas e chaves. Reprove só se o perfil
  contradiz o critério."

## 5. Comparador de artefatos

- **Camada `script`** (depois de `normalized`, antes de `extension`): se a subtarefa espera
  exatamente **um** `.py` que não foi resolvido e a pasta dela tem `script.py`, esse arquivo
  resolve o esperado. Com dois ou mais `.py` esperados e não resolvidos, nenhum é resolvido por
  esta camada (não há como saber qual código é qual). `name_mismatch` vale `true` para `script`.
- `script.py` continua fora da camada `extension` e do contexto propagado entre subtarefas.
- `EXTENSION_TIER_SUFFIXES` ganha `.joblib` e `.pkl`. O pareamento por sobreposição de palavras
  (`_pair_by_overlap`) já existente decide qual arquivo resolve qual esperado.

## 6. Regra do limiar numérico no plano

`_QUANTITATIVE_REQUIRED_TASK_TYPES` passa a ser aplicado assim:

| `task_type` | `hypothesis_ref` | Exige limiar numérico? |
|---|---|---|
| `reproduction` | qualquer | sim |
| `validation` | preenchido | sim |
| `validation` | vazio | não (registra `plan_warning` `validation_sem_hipotese`) |
| demais | qualquer | não |

O normalizador de plano não inventa limiar (regra de `v16-pipeline-robustness`).

## 7. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador e loop | Menos reprovações falsas: o disjuntor de zero progresso dispara menos por erro do revisor |
| Agentes e prompts | Instrução do revisor muda (§4.3); o Researcher recebe menos reprovações de plano por baseline |
| Sandbox | Nenhum: o perfil é lido no host, sobre arquivos já gravados em `outputs/` |
| Persistência | Propriedade `qualificador` em `Resultado`; mais arestas `MEDE` (uma por resultado de teste) |
| Segurança | Perfil sai como `esquema_agregado`; ver §4.2 e o parecer do Analista de Segurança |
| Testes e telemetria | `subtask_review` com `undecided_criteria` e `metric_qualifiers`; testes unitários puros |

## 8. Questões em aberto

1. **Escopo da regra do limiar (§6).** A decisão de 2026-10-05 (`v16-pipeline-robustness` §1.3)
   manteve a regra para todo `validation`. Proposta: exigir só com `hypothesis_ref`. Alternativa:
   manter a regra e ensinar o Researcher a usar `task_type` `eda` no baseline (o feedback já
   sugere, e a Haiku não seguiu).
2. **`val_` como teste.** Algumas bibliotecas chamam de `val` o conjunto separado do fim. A
   proposta trata `val_` como `validacao` (distinto de teste), que é o uso mais comum.
3. **Profundidade do achatamento (§2).** Um nível cobre os casos vistos. Níveis mais profundos
   ficam registrados no log e fora da avaliação.

## 9. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Qualificador mal reconhecido torna `cv_accuracy` em acurácia de teste | Lista fechada de palavras; sufixos estatísticos não são removidos; teste para `cv_accuracy_mean` |
| Perfil de CSV grande consome memória no Pi | Leitura em fluxo até `REVIEW_PROFILE_MAX_BYTES` (padrão 5 MB) |
| Perfil expõe grupo pequeno via nulos | Regra de omissão (§4.2) e parecer de segurança |
| Camada `script` aprova subtarefa que não gravou o script pedido | Só com um `.py` esperado; `name_mismatch` gera aviso no relatório |
