# Design: Cálculo do Veredito de Evidência

## Entradas

```python
@dataclass(frozen=True)
class Criterion:
    sentido: Literal["maior_melhor", "menor_melhor"]   # da Metrica canônica
    delta_min: float | None                            # δ do Problema (definido antes dos experimentos)
    alvo: float | None                                 # usado quando não há baseline

@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    timestamp: str                     # ordena as tentativas
    node_id: str                       # NODE_ID do computador
    session_id: str
    seed: int | None
    dataset_ids: tuple[str, ...]
    config_hash: str                   # hash da config_normalizada
    outcome_kind: Literal["resultado", "falha"]
    # quando outcome_kind == "resultado":
    value: float | None = None
    baseline: float | None = None
    validation: Literal["validado", "divergente_documentado", "nao_validado"] | None = None
    contract_complete: bool = False    # params.json + seed + metrics.json presentes
    # quando outcome_kind == "falha":
    failure_cause: Literal["infraestrutura", "abordagem", "ambigua"] | None = None
    failure_signature: str | None = None   # ex.: tipo de erro normalizado

def compute_verdict(attempts: list[Attempt], criterion: Criterion,
                    params: VerdictParams | None = None) -> VerdictResult
```

## Algoritmo

Tentativas ordenadas por `timestamp` (resultado determinístico).

### 1. Classificação de cada tentativa

- **Resultado com `validation="nao_validado"`** → `q = 0` (não é evidência; conta em
  `n_tentativas`).
- **Resultado** → direção `o`:
  - `Δ = (value − baseline)` se `sentido == maior_melhor`, senão `(baseline − value)`;
  - com baseline e `delta_min`: `o = +1` se `Δ ≥ δ`, senão `o = −1`;
  - sem baseline: `o = +1` se o valor atinge `alvo` no sentido da métrica, senão `−1`;
  - sem baseline e sem alvo: tentativa **ambígua**.
- **Falha `infraestrutura`** → excluída do veredito; conta em `n_tentativas`.
- **Falha `abordagem`** → se existem ≥ `approach_failure_min_repeats` (2) falhas `abordagem`
  com a mesma `failure_signature` em tentativas **independentes** (sessão, semente ou nó
  diferentes), cada uma vira evidência **negativa** com `q = approach_failure_q` (0,3) e
  `m = 1`; senão, é tratada como **ambígua**.
- **Falha `ambigua`** → ambígua.

### 2. Pesos (`w = q · m · d · b`)

| Fator | Regra |
|---|---|
| `q` | `validado` + `contract_complete` → 1,0 · `validado` sem contrato completo → 0,7 · `divergente_documentado` → 0,3 · falha de abordagem reproduzida → 0,3 |
| `m` positivo | `min(1, Δ / (2δ))` |
| `m` negativo | `min(1, (δ − Δ) / δ)`; `Δ ≤ 0` → 1,0 |
| `m` sem baseline | 0,5 |
| `d` | percorrendo em ordem: 1,0 se o `node_id` **ou** algum `dataset_id` ainda não apareceu; senão 0,5 se a `session_id` é nova; senão 0,2 (nova semente na mesma sessão) |
| `b` | só para `o = +1`: se o `config_hash` da tentativa aparece em outra tentativa positiva de **outra sessão ou outro nó**, `b = 1`; senão `b = 1 / (1 + γ · ln(n_config))`, com `n_config` = nº de `config_hash` distintos entre as tentativas |

### 3. Agregação

```
α = α0 + Σ w (o = +1)          β = β0 + Σ w (o = −1)        (α0 = β0 = 1)
suporte  = α / (α + β)
certeza  = (α + β − 2) / (α + β)
f        = 1 − λ · n_ambiguas / n_validas      (n_validas = tentativas − infraestrutura; f = 1 se n_validas = 0)
veredito = f · certeza · (2 · suporte − 1)
confianca = |veredito|
```

### 4. Leitura

| `veredito` | `leitura` | `tipo_descoberta` sugerido |
|---|---|---|
| ≥ 0,5 | `funciona_forte` | `funciona` |
| [0,3; 0,5) | `funciona_moderada` | `funciona` |
| [0,1; 0,3) | `funciona_fraca` | `funciona` |
| (−0,1; 0,1) | `insuficiente` | nenhum |
| (−0,3; −0,1] | `nao_funciona_fraca` | `nao_funciona` |
| (−0,5; −0,3] | `nao_funciona_moderada` | `nao_funciona` |
| ≤ −0,5 | `nao_funciona_forte` | `nao_funciona` |

## Saída

```python
@dataclass(frozen=True)
class EvidenceBreakdown:
    attempt_id: str
    classificacao: str         # "positiva" | "negativa" | "ambigua" | "infraestrutura" | "nao_evidencia"
    q: float; m: float; d: float; b: float; w: float

@dataclass(frozen=True)
class VerdictResult:
    alpha: float; beta: float
    suporte: float; certeza: float; f: float
    veredito: float; confianca: float
    leitura: str; tipo_descoberta: str | None
    n_tentativas: int; n_evidencias: int; n_ambiguas: int; n_infraestrutura: int
    detalhes: tuple[EvidenceBreakdown, ...]
```

O detalhamento é o que o Curator registra e a CLI exibe — o pesquisador vê **por que** o
veredito tem aquele valor.

## Parâmetros (`VerdictParams`, lidos de `src/config.py`)

| Variável | Default |
|---|---|
| `VERDICT_Q_VALIDATED_COMPLETE` | 1.0 |
| `VERDICT_Q_VALIDATED_INCOMPLETE` | 0.7 |
| `VERDICT_Q_DIVERGENT` | 0.3 |
| `VERDICT_D_NEW_NODE_OR_DATASET` | 1.0 |
| `VERDICT_D_NEW_SESSION` | 0.5 |
| `VERDICT_D_NEW_SEED` | 0.2 |
| `VERDICT_GAMMA` | 0.5 |
| `VERDICT_LAMBDA_AMBIGUOUS` | 0.5 |
| `VERDICT_APPROACH_FAILURE_Q` | 0.3 |
| `VERDICT_APPROACH_FAILURE_MIN_REPEATS` | 2 |
| `VERDICT_PRIOR` | 1.0 |
| `VERDICT_THRESHOLDS` | `0.1,0.3,0.5` |

## Testes-ouro (do ADR 015 §9.6 e §9.7)

Exemplo completo (δ = 0,05; baseline R² = 0,70; E1–E6 conforme o ADR):
`α = 3,225`, `β = 1,8`, `suporte ≈ 0,642`, `certeza ≈ 0,602`, `veredito ≈ 0,171` (tolerância
0,005), leitura `funciona_fraca`. Pesos por evidência: 1,000 / 0,160 / 0,315 / 0,600 / 0,800 /
0,150.

Só E1, com 4 configurações e sem réplica: `b ≈ 0,591`, `veredito ≈ 0,052`, `insuficiente`.

Tabela de referência (q = m = 1): 1 positivo → 0,11; 5 sementes na mesma sessão → 0,22;
3 nós → 0,36; 5 nós → 0,51; 6 positivos + 1 negativo independentes → 0,43; 4 negativos
independentes → −0,44; 1 positivo entre 20 configurações sem réplica → 0,03.

## Análise de impacto (6 eixos)

Somente "Testes & Telemetria" e "Persistência" (indiretamente, pelos consumidores). Módulo
puro, sem efeitos colaterais.
