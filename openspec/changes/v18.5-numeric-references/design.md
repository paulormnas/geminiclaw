# Design: Referências Numéricas Rastreáveis

## 0. Estado atual (verificado no código em 2026-09-29)

| Ponto | Local | Situação |
|---|---|---|
| Instrução do Summarizer | `agents/summarizer/agent.py:28-33` | "use as métricas de `metrics.json`, não números que você calcule" — só instrução. |
| Tabela de resultados | `agents/summarizer/agent.py:58-62` | Manda **calcular a divergência percentual** e copiar os números "exatamente". |
| Metadados de execução | `agents/summarizer/agent.py:80-86` | O LLM reescreve duração, tokens, custo e contagem de containers. |
| Bloco de métricas | `src/report/artifact_reader.py:69-84` | Tabela com `json.dumps(metrics)` injetada no prompt. |
| Montagem do prompt | `src/autonomous_loop.py:1502-1528` | `metrics_block` + estatísticas de telemetria no prompt; o que o Summarizer grava é o relatório final. |
| Gravação do relatório | `agents/summarizer/agent.py:41`, `src/orchestrator.py:463` | `relatorio_final.md` gravado pelo LLM via `write_artifact`. |
| Conversão | `src/cli.py:625-643`, `src/report/base_converter.py:25-53` | Conversores leem `relatorio_final.md` como Markdown comum. |
| HTML | `src/report/html_converter.py:65-78` | `markdown.markdown(...)` + CSS; sem pós-processamento. |
| DOCX | `src/report/docx_converter.py:21-31`, `:66-76` | Só negrito em parágrafos; células de tabela recebem texto puro. |
| LaTeX | `src/report/latex_converter.py:46-61`, `:162-172` | Ênfase e escape; preâmbulo sem `xcolor`. |
| Escrita de métricas | `src/skills/code/scientific_helpers.py:18-67` | `save_experiment_artifacts(task_name, params, metrics, ...)`; sem unidades, sem validação de nomes. |
| Execução de código | `src/skills/code/skill.py:86-95`, `:97` | `_validate_code` só procura padrões proibidos; nenhuma análise de métricas. |
| Busca técnica | `agents/researcher/tools.py:53-138`, `agents/researcher/cache.py:1-40` | Resultados só em cache em memória, perdidos ao fim do processo. |
| Unidade no grafo | `src/knowledge/schema.py:217-229` (`Resultado.unidade`), `:283-293` (`Metrica.unidade`, `sentido`) | Campos existem; ninguém os preenche a partir do `metrics.json`. |
| Insumo | `src/knowledge/schema.py:142-150` | `caminho` e `hash_conteudo`; texto extraído pelo `ContextLoader` (`src/context_loader.py:242`, PDF/DOCX em `:24`). |

## 1. Sintaxe

Três formas, reconhecidas por um único módulo (`src/numeric_refs/syntax.py`):

```
{{res:<exec_id>/<nome>}}
{{calc:<expressão>}}
{{src:<id_insumo_ou_url>#<trecho>}}
```

- `exec_id` = `exec_<uuid4>` em texto canônico minúsculo (formato de
  `v18.5-execution-provenance`).
- `nome` = chave de `metrics.json["metrics"]`, ou `param.<chave>` para um valor de
  `params.json["parameters"]` (hiperparâmetros citados no texto também precisam de origem).
  Conjunto permitido: `[A-Za-z_][A-Za-z0-9_.\-]*`. `save_experiment_artifacts` passa a
  **rejeitar** chaves fora desse conjunto, com mensagem acionável (fail-fast).
- `id_insumo_ou_url`: começa com `http://` ou `https://` → URL (sem fragmento; o primeiro `#`
  separa o trecho); caso contrário, id de nó `Insumo` (`generate_node_id`,
  `src/knowledge/ids.py:92`).
- `trecho`: texto literal da fonte, até `}}`; não pode conter `}}`.
- Dentro de `calc`, os operandos são `res:<exec_id>/<nome>` e `src:<id>#"<trecho>"` (trecho
  entre aspas duplas; `\"` escapa aspas).

Expressões regulares (normativas):

```
RES  = r"\{\{res:(exec_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})/([A-Za-z_][A-Za-z0-9_.\-]*)\}\}"
CALC = r"\{\{calc:(.+?)\}\}"
SRC  = r"\{\{src:([^#{}\s]+)#(.+?)\}\}"
```

Qualquer `{{` seguido de `res:`, `calc:` ou `src:` que não case com a forma completa é
**referência malformada** (erro de sintaxe com posição). API pública:

```python
@dataclass(frozen=True)
class NumericRef:
    kind: Literal["res", "calc", "src"]
    raw: str
    span: tuple[int, int]          # posição no texto canônico
    payload: ResTarget | CalcExpr | SrcTarget

def find_references(text: str) -> list[NumericRef]          # usado também pelo EgressGate
def find_malformed(text: str) -> list[SyntaxIssue]
```

## 2. Resolução

`src/numeric_refs/resolver.py`:

```python
@dataclass(frozen=True)
class ResolvedValue:
    valor: float | int
    unidade: str | None            # None = não informada
    origem: Literal["res", "calc", "src"]
    detalhe: dict                  # exec_id, subtarefa, arquivo+sha256 | expressão+operandos | fonte+trecho
    ok: bool
    motivo: str | None             # código do motivo quando ok=False

class ReferenceResolver:
    def __init__(self, project_id: str, session_id: str, records: ExecutionRecordReader, graph: GraphStore): ...
    def resolve(self, ref: NumericRef) -> ResolvedValue
```

### 2.1 `res`

1. Busca o registro de término de `exec_id` (`v18.5-execution-provenance`). Sem registro de
   término (órfão), ou com código de saída ≠ 0 → `ok=False`, `motivo="execucao_sem_termino"`
   ou `"execucao_falhou"`.
2. Localiza `metrics.json` (ou `params.json` para `param.`) entre as saídas do registro e
   **confere o sha256** com o do registro. Divergência → `motivo="artefato_alterado"`.
3. Lê o valor; ausente ou não numérico (`bool` não conta como número) → `"metrica_ausente"`.
4. Unidade: `metrics.json["unidades"][nome]` (novo, opcional); senão `Metrica.unidade` da
   métrica canônica (`src/knowledge/schema.py:289`) quando o nome já está mapeado no
   vocabulário; senão `None`.

### 2.2 `src`

- **Insumo:** lê o nó; confere `hash_conteudo` com o arquivo em `caminho` (divergência →
  `"insumo_alterado"`); extrai o texto com o mesmo extrator do `ContextLoader`
  (`src/context_loader.py:242-335`), com cache por hash. A leitura é local e o texto não vai a
  prompt (ADR 019 §3.6).
- **URL:** procura a URL em `fontes_busca.jsonl` das sessões do projeto (§2.4). URL que o
  sistema não consultou → `"fonte_nao_consultada"`.
- **Casamento do trecho:** normalização NFC, espaços colapsados, hifenização de fim de linha
  desfeita, comparação sem distinção de maiúsculas. Não encontrado → `"trecho_nao_encontrado"`.
- **Valor:** o trecho deve conter **exatamente um** número (mesmo reconhecedor do §5); zero →
  `"trecho_sem_numero"`, mais de um → `"trecho_ambiguo"` (a mensagem pede um trecho menor).
  Unidade: o token imediatamente após o número, se estiver em `UNIDADES_CONHECIDAS`
  (`src/numeric_refs/units.py`, lista fechada: `%`, SI e derivadas comuns, `pp`) ou for o
  nome/sinônimo de unidade de uma `Metrica`.

### 2.3 Registro da origem

Cada referência resolvida gera uma linha em `outputs/<sessão>/proveniencia_numerica.json`
(§8). A "referência do `Insumo` ao trecho de origem" pedida no ADR 019 (tabela de impacto) é
atendida por esse arquivo, sem nova propriedade no grafo. Se o pesquisador preferir a aresta
no grafo, é uma mudança de schema separada (pergunta em aberto).

### 2.4 Fontes da busca técnica

`agents/researcher/tools.py::search` (`:53`) passa a acrescentar, para cada resultado
devolvido ao Researcher, uma linha em `outputs/<sessão>/fontes_busca.jsonl`:
`{"url", "titulo", "trecho", "consulta", "obtido_em", "sha256_trecho"}`. Só o texto que o
sistema de fato recebeu conta como fonte. O cache em memória continua como está.

## 3. Avaliador de expressões (`calc`)

`src/numeric_refs/calc.py`. **Nunca** usa `eval`, `exec`, `compile` para código executável ou
`numexpr`.

1. **Pré-processamento:** cada operando `res:…`/`src:…"…"` é trocado por um identificador
   `_o0`, `_o1`, …; um operando malformado é erro de sintaxe.
2. **Parse:** `ast.parse(expr, mode="eval")` apenas para obter a árvore; um visitante com
   **lista de permissão** percorre os nós. Qualquer nó fora da lista → `CalcError("nó não
   permitido: <tipo>")`.
3. **Avaliação:** o próprio visitante calcula, em `float` (IEEE 754), com unidades.

| Permitido | Detalhe |
|---|---|
| `Expression`, `BinOp` | operadores `+`, `-`, `*`, `/`, `**` |
| `UnaryOp` | `+`, `-` |
| `Constant` | `int` ou `float` (não `bool`, não `complex`, não `str`) |
| `Name` | somente `_o<n>` criados no pré-processamento |
| `Call` | `func` é `Name` da lista abaixo; sem `keywords`, sem `*args` |

| Função | Semântica | Unidade do resultado |
|---|---|---|
| `abs(x)` | valor absoluto | a de `x` |
| `min(a, b, …)`, `max(a, b, …)` | mínimo/máximo | exige unidades iguais |
| `media(a, b, …)` | média aritmética (`math.fsum`) | exige unidades iguais |
| `sqrt(x)` | raiz quadrada; `x < 0` é erro | `√(u)` ou adimensional |
| `round(x, n)` | arredonda meio para cima (`Decimal.quantize`, `ROUND_HALF_UP`), `n` inteiro constante em [0, 10] | a de `x`; define as casas exibidas |
| `pct(x)` | `x · 100` | `%`; exige `x` adimensional |

**Limites** (`src/config.py`): `NUMREF_CALC_MAX_CHARS` (400), `NUMREF_CALC_MAX_NODES` (64),
profundidade ≤ 16, expoente de `**` só constante inteira com |e| ≤ `NUMREF_CALC_MAX_POW` (4).
Divisão por zero, resultado `NaN`/`inf` e estouro → `CalcError`.

**Regras de validade:**

- Pelo menos **um operando** `res:` ou `src:`. `{{calc:0.95}}` é erro
  (`"calculo_sem_referencia"`): impede que um literal seja disfarçado de cálculo.
- Constantes literais são permitidas (ex.: `100`, `2`, `0.05`) e **listadas** no apêndice ao
  lado da expressão.
- **Unidades:** `+`, `-`, `min`, `max`, `media` exigem operandos com a mesma unidade
  (constantes só com operandos adimensionais ou de unidade não informada); `*` e `/` compõem
  (`a·b`, `a/b`), e `u/u` vira adimensional; constante multiplicando mantém a unidade. Unidade
  não informada se propaga como não informada. Incompatibilidade → `"unidades_incompativeis"`.
- Exibição padrão com `NUMREF_CALC_SIG_DIGITS` (4) algarismos significativos, salvo `round`.

Exemplo — divergência percentual do valor medido em relação ao do artigo:
`{{calc:round(pct((res:exec_…/rmse - src:<insumo>#"RMSE de 0,42 mm") / src:<insumo>#"RMSE de 0,42 mm"), 1)}}`
→ `7,1 % [C1]`.

## 4. Renderização

`src/numeric_refs/render.py`.

- **Formato numérico pt-BR:** vírgula decimal; sem separador de milhar abaixo de 10 000;
  acima, espaço fino inseparável (U+202F); notação científica `1,2 × 10⁻³` abaixo de 10⁻³ ou
  acima de 10⁶.
- **`res`:** exibido com até `NUMREF_DISPLAY_MAX_SIG_DIGITS` (6) significativos; inteiros como
  inteiros. O valor **exato** fica no apêndice.
- **Forma inline:** `<valor>[ <unidade>] [<código>]`, com código `R<n>` (execução), `C<n>`
  (cálculo) ou `S<n>` (fonte citada), numerado na ordem de aparição. Ex.: `0,8735 [R1]`,
  `12,4 mm [R2]`, `7,1 % [C1]`.
- **Marca de métrica literal:** `0,95 [R3] [literal no código]` quando a métrica foi apontada
  pela verificação estática (§6).
- **Referência que não resolve:** o texto original da referência vai em código inline, seguido
  de `[não verificado]`, e o motivo aparece no apêndice. Nada é apagado.
- **Apêndice** (seção do orquestrador, delimitada por
  `<!-- numeric-provenance:begin -->` … `<!-- numeric-provenance:end -->`), título
  "Origem dos números", com tabelas:
  - Códigos: `Código | Valor exato | Unidade | Origem | Detalhe` (R: `exec_id`, subtarefa,
    métrica, `metrics.json` + sha256 abreviado; C: expressão com os códigos dos operandos e as
    constantes; S: título do insumo ou URL, trecho entre aspas, data de obtenção).
  - Números não verificados: seção, trecho ao redor e motivo.
  - Métricas gravadas como literais no código: `exec_id`, métrica, linha.

Descobertas do grafo guardam o **texto canônico** (com referências). A CLI do grafo
(`v17-graph-cli`) e o relatório exibem a forma renderizada, usando o mesmo módulo.

## 5. Verificador de números

`src/numeric_refs/verifier.py`. Entrada: texto renderizado **e** a lista de trechos que o
renderizador produziu (spans com origem). Saída: lista de `UnverifiedNumber(span, texto,
motivo)` e o texto com as marcas inseridas.

### 5.1 O que é número

- **Algarismos:** inteiros, decimais com vírgula ou ponto, sinais (`−`, `-`, `+`, `±`),
  milhares, percentuais (`%`, "por cento"), pontos percentuais ("p.p.", "pontos percentuais"),
  notação científica (`1e-3`, `1,2 × 10^-3`, `10⁻³`), faixas (`10–20`, "entre 3 e 5" → dois
  números).
- **Por extenso (pt-BR):** cardinais de "zero" a "novecentos e noventa e nove" e compostos com
  "mil", "milhão/milhões", "bilhão/bilhões"; decimais por extenso ("dois vírgula cinco");
  frações ("metade", "um terço", "dois terços", "um quarto").
- **Multiplicadores:** "N vezes", `Nx`, `N×`, "o dobro", "o triplo", "o quádruplo", "N vezes
  mais/menos", "uma ordem de grandeza", "N ordens de grandeza".

### 5.2 Exclusões estruturais (regra explícita, lista fechada)

| # | Exclusão | Regra de reconhecimento |
|---|---|---|
| X1 | Spans renderizados | Todo trecho produzido por `res`/`calc`/`src`, inclusive a unidade e o código `[R1]`. |
| X2 | Seções do orquestrador | Blocos `<!-- <nome>:begin -->` … `<!-- <nome>:end -->` com `<nome>` registrado no pipeline (§7): `numeric-provenance`, `claims`, `operation-metrics`, `allocation-profile`, `provenance-chain`, `execution-metadata`. |
| X3 | Código | Blocos cercados por ` ``` `, código inline, URLs, alvos de links, comentários HTML, DOIs. |
| X4 | Numeração | Numeração de títulos (`## 3.2`), marcadores de lista (`1.`), marcadores de citação `[1]`, códigos `[R1]`/`[C1]`/`[S1]`/`[A1]`. |
| X5 | Identificadores | Número colado a letras sem espaço (`F1`, `R²`, `L2`, `qwen3:8b`, `exec_…`), versões (`v1.2.3`, `Python 3.11`), nomes de arquivo, hashes. |
| X6 | Datas e horas | ISO-8601, `dd/mm/aaaa`, `hh:mm`, mês por extenso com dia/ano. |
| X7 | Anos | Inteiro de 4 dígitos em [`NUMREF_YEAR_MIN`, `NUMREF_YEAR_MAX`] (1900–2100) **somente** junto a "em", "de", "desde", "até", "ano(s)", nome de mês, ou dentro de citação "(Autor, 2020)". Fora desses contextos é contado. |
| X8 | Contagens do orquestrador | Inteiro (algarismos ou extenso) seguido, em até duas palavras, de um substantivo da lista fechada — subtarefa, hipótese, experimento, execução, tentativa, sessão, afirmação, insumo, artigo de referência, abordagem, ciclo de planejamento — **e igual** à contagem que o orquestrador tem para a sessão. Se o valor difere, ou o orquestrador não tem a contagem, o número é marcado. |
| X9 | Artigos indefinidos e ordinais | "um"/"uma" como artigo e ordinais ("primeiro", "segundo"…) — exceto quando seguidos de unidade ou em forma de multiplicador ("uma vez e meia"). |

Qualquer outro número fora de X1–X9 recebe `[não verificado]` logo depois do número (ou do
multiplicador), é listado no apêndice e contado. **O texto do número não é apagado nem
alterado.** A lista X1–X9 é normativa: ampliar exige alterar esta spec.

### 5.3 Onde roda

- No relatório final, depois da renderização e antes da conversão.
- No texto de `Descoberta` (`enunciado`, `condicoes`), `Oportunidade` e caminhos sem conclusão
  gravados pelas ferramentas do Curator (§7.2).

## 6. Verificação estática de métricas literais

`src/numeric_refs/literal_metrics.py`, chamada por `CodeSkill.run`
(`src/skills/code/skill.py:97`) sobre o código **exatamente como executado** (o mesmo cujo hash
vai ao registro de execução), sem o código auxiliar injetado
(`_load_scientific_helpers_source`, `src/skills/code/skill.py:25`).

Padrões (AST, sem executar nada):

| # | Padrão | Sinaliza |
|---|---|---|
| P1 | `save_experiment_artifacts(..., metrics={...})` (keyword ou 3º posicional) com valor `Constant` numérico ou `-Constant` | cada chave com valor literal |
| P2 | `metrics` é um `Name`: no mesmo escopo, a última atribuição antes da chamada é `{k: Constant}`, `dict(k=Constant)`, `name[k] = Constant`, `name.update({k: Constant})`, ou `name[k] = var` com `var = Constant` (um nível) | idem |
| P3 | `json.dump(obj, f)` / `Path(...).write_text(json.dumps(obj))` / `open(...)` com destino literal terminando em `metrics.json`, e `obj` como em P1/P2 (também aninhado em `{"metrics": {...}}`) | idem |

Resultado por execução: `outputs/<sessão>/<subtarefa>/metricas_literais.json` =
`{"exec_id", "hash_codigo", "achados": [{"metrica", "linha", "padrao"}]}`. **Nunca bloqueia**
a execução; alimenta a marca `[literal no código]`, o apêndice e a contagem. Limite declarado:
é heurística — um literal passado por várias variáveis ou funções não é detectado.

## 7. Pipeline do relatório e contratos de escrita

### 7.1 Summarizer

Mudanças em `agents/summarizer/agent.py`:

- **Linhas 28-33:** "Não escreva números medidos, calculados nem citados. Escreva
  referências `{{res:…}}`, expressões `{{calc:…}}` e citações `{{src:…#…}}` a partir do
  CATÁLOGO DE REFERÊNCIAS. Números sem referência serão marcados como não verificados."
- **Linhas 58-62:** a tabela de resultados usa `{{res}}` por célula; a coluna "Valor Esperado"
  usa `{{src}}`; a divergência é `{{calc:round(pct((res:… − src:…)/src:…), 1)}}`. A instrução
  "calcule a divergência percentual" é removida.
- **Linhas 80-86:** o bloco "Metadados de Execução" sai do LLM; o orquestrador acrescenta a
  seção `execution-metadata` (duração, tokens, custo, sandboxes) com os dados da telemetria. O
  "nível de confiança consolidado" continua como julgamento qualitativo (alto/médio/baixo) na
  seção de Limitações.
- **Linha 41:** grava `relatorio_final.fonte.md`.
- Contagens podem ser escritas por extenso ou em algarismos (X8), desde que corretas.

Contexto (`src/autonomous_loop.py:1502-1521`): `ArtifactReader.build_metrics_context_block`
(`src/report/artifact_reader.py:69`) é substituído por `ReferenceCatalog.build(session)`
(`src/numeric_refs/catalog.py`), que lista, por subtarefa: `res:<exec_id>/<nome>` = valor
exato, unidade, hipótese, status de validação, `divergence_note`; e as fontes disponíveis
(`Insumo`: id e título; URLs de `fontes_busca.jsonl`). O catálogo é enviado pelo `EgressGate`
com origem `saida_execucao`/`documento` (`v18.5-egress-gate`). O bloco antigo continua
disponível para `--metrics`.

### 7.2 Curator

- Instrução (`v17-curator-agent`, design §5): cita valores por referência em `enunciado`,
  `condicoes` e `justificativa`; não escreve veredito nem confiança no texto (são propriedades
  calculadas pelo `KnowledgeService`).
- Ferramentas de escrita (`create_discovery`, `reinforce_discovery`, `create_opportunity`,
  `register_open_path`): referência **malformada ou que não resolve** → erro da ferramenta com
  a lista e o motivo, para o Curator corrigir (o grafo só guarda referências resolvíveis).
  Número sem referência → a escrita é aceita, a ferramenta devolve aviso com os números que
  serão exibidos como `[não verificado]`, e a contagem é registrada.

### 7.3 Developer

Instrução (delta sobre `v16-research-assistant-prompts`): calcular métricas a partir dos
dados, nunca escrever valores literais; informar `unidades` em `save_experiment_artifacts`;
nomes de métrica no conjunto do §1.

### 7.4 Pipeline

`src/report/pipeline.py`, chamado ao fim de `_synthesize_results`
(`src/autonomous_loop.py:1459`):

```
relatorio_final.fonte.md (Summarizer)
  → find_malformed / find_references
  → ReferenceResolver.resolve (todas)
  → [extensão: ClaimVerification sobre o texto canônico + valores]   (v18.5-claim-verification)
  → render (spans com origem)
  → NumberVerifier (marca [não verificado])
  → seções do orquestrador registradas, em ordem
  → relatorio_final.md (gravação atômica) + proveniencia_numerica.json
```

```python
class ReportPipeline:
    def register_stage(self, name: str, fn: Callable[[ReportState], ReportState], after: str) -> None
    def register_section(self, name: str, fn: Callable[[ReportState], str]) -> None   # nome = delimitador X2
    def build(self, session_id: str) -> Path
```

Se só existir `relatorio_final.md` escrito pelo LLM (instrução antiga), ele é **renomeado**
para `relatorio_final.fonte.md` antes do pipeline. Falha do pipeline é erro explícito; o
arquivo fonte permanece.

## 8. Saída para métricas de operação

`proveniencia_numerica.json`:

```json
{
  "versao": 1, "session_id": "…",
  "codigos": [{"codigo": "R1", "tipo": "res", "valor_exato": 0.87345, "unidade": null,
               "detalhe": {"exec_id": "exec_…", "subtarefa": "…", "arquivo": "…/metrics.json",
                           "sha256": "…"}, "ocorrencias": 2}],
  "nao_verificados": [{"local": "relatorio:Resultados", "texto": "três vezes", "motivo": "sem_origem"}],
  "metricas_literais": [{"exec_id": "exec_…", "metrica": "acc", "linha": 42, "padrao": "P1"}],
  "contagens": {"res": 0, "calc": 0, "src": 0, "nao_verificados": 0, "metricas_literais": 0}
}
```

Contagem por **ocorrência** no relatório final e nos textos do grafo escritos na sessão.
`NumericProvenanceReader` (grupo `proveniencia`, produtor `v18.5-numeric-references`) devolve
`numeros_por_origem`, `numeros_nao_verificados` e `metricas_literais` para
`v18.5-operation-metrics`.

## 9. Conversores

Marcas reconhecidas por um registro comum em `src/report/base_converter.py`:

```python
MARKS: list[MarkRule]   # (regex, estilo) — extensível por outras mudanças
ORIGIN_CODE = r"\[(R|C|S)\d+\]"; UNVERIFIED = r"\[não verificado\]"; LITERAL = r"\[literal no código\]"
```

| Formato | Código de origem | `[não verificado]` / `[literal no código]` |
|---|---|---|
| HTML (`html_converter.py:65-78`) | pós-processa o HTML fora de `<code>`/`<pre>`: `<sup class="origem"><a href="#origem-R1">R1</a></sup>`; células do apêndice recebem `id="origem-R1"` | `<mark class="nao-verificado">não verificado</mark>`; cores em tokens CSS com variante escura e de impressão |
| DOCX (`docx_converter.py:21-31`, `:66-76`) | run sobrescrito; células de tabela passam a usar runs (não `cell.text`) | run em negrito com realce amarelo (`WD_COLOR_INDEX.YELLOW`) |
| LaTeX (`latex_converter.py:46-61`, `:162-172`) | `\textsuperscript{\hyperlink{origem-R1}{R1}}`; `\hypertarget` no apêndice | `\colorbox{yellow}{\textbf{não verificado}}`; `\usepackage{xcolor}` no preâmbulo |

A marca continua legível no Markdown puro.

## 10. Configuração (`src/config.py`, `.env.example`)

| Variável | Default |
|---|---|
| `NUMREF_DISPLAY_MAX_SIG_DIGITS` | 6 |
| `NUMREF_CALC_SIG_DIGITS` | 4 |
| `NUMREF_CALC_MAX_CHARS` | 400 |
| `NUMREF_CALC_MAX_NODES` | 64 |
| `NUMREF_CALC_MAX_POW` | 4 |
| `NUMREF_YEAR_MIN` / `NUMREF_YEAR_MAX` | 1900 / 2100 |
| `NUMREF_STATIC_CHECK_ENABLED` | true |

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | `_synthesize_results` passa a chamar o pipeline do relatório; catálogo de referências substitui o bloco de métricas. |
| Agentes & Prompts | Summarizer e Curator escrevem referências; Developer informa unidades. Mudança de contrato do LLM, validada por sessões de referência. |
| Sandboxes & Containers | Nenhuma mudança de imagem; análise estática no host sobre o texto do código (sem executá-lo). |
| Persistência | Arquivos novos em `outputs/<sessão>/`; `metrics.json` ganha `unidades` (opcional). Sem schema. |
| Segurança | Avaliador sem `eval` com lista de permissão e limites; leitura local de insumos sem ir a prompt; referência malformada não é interpretada. |
| Testes & Telemetria | Contagens por origem, não verificados e literais para `v18.5-operation-metrics`. |

## Riscos

- **Modelos pequenos erram a sintaxe.** Mitigação: catálogo com referências prontas para
  copiar; erro de ferramenta acionável para o Curator; números não resolvidos marcados, não
  perdidos. A taxa aparece nas métricas (gatilho de revisão do ADR 019).
- **Falsos positivos do verificador** (ex.: número estrutural fora da lista). Mitigação: lista
  X1–X9 normativa e testada; o excesso fica visível nas métricas.
- **Falsos negativos da verificação estática.** Limite declarado no ADR 019 §2; o relatório
  diz que a verificação é heurística.
- **Texto canônico no grafo com referências a execuções de outro nó** (federação, V20): fora do
  escopo; a resolução é local ao projeto.
