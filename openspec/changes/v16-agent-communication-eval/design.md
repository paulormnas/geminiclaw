# Design: Avaliação da Comunicação entre Agentes

## 1. Princípios

1. **Pós-execução.** A avaliação lê o que a sessão deixou (banco e pasta da sessão). Não há
   gancho na sessão, e rodar a avaliação nunca altera o resultado da pesquisa.
2. **Verdade antes do juiz.** O que puder ser decidido por código é decidido por código (§2). O
   juiz LLM só avalia o que não tem verdade determinística: a qualidade das perguntas (§5).
3. **Independência.** O juiz é de outro provedor que o do agente avaliado (§5.3), para não
   premiar o próprio estilo.
4. **Incerteza declarada.** Nota do juiz sem calibração suficiente sai marcada como tal; casos
   sem verdade determinística são contados como `indeterminada`, não forçados a acerto ou erro.
5. **Sem dado bruto fora do nó** (ADR 019 §3): ver §6.

## 2. Verdade determinística por subtarefa

Entrada: pasta da sessão, eventos `agent_events` da sessão, plano aprovado (`plan_json`).

```python
@dataclass(frozen=True)
class SubtaskTruth:
    task_name: str
    attempt: int
    verdict: Literal["fulfilled", "unfulfilled", "indeterminate"]
    checks: list[TruthCheck]       # um por verificação (ver tabela)

@dataclass(frozen=True)
class TruthCheck:
    kind: Literal["artifact", "metric", "exit_code"]
    subject: str                   # artefato, critério ou "sandbox"
    ok: bool
    detail: str
```

| Verificação | Como | Fonte |
|---|---|---|
| `artifact` | `resolve_artifacts(expected, session_dir, task_dir, mode="tolerant")`; `ok` = todos resolvidos | disco (`v16-pipeline-robustness` §2) |
| `metric` | `_metric_criteria` sobre `validation_criteria`; compara com o `metrics.json` da subtarefa | disco (`v16-pipeline-robustness` §3) |
| `exit_code` | último `sandbox_run` da tentativa com `exit_code == 0` e sem `timed_out` | evento `sandbox_run` |

Regras:

- `fulfilled`: todas as verificações aplicáveis `ok` **e** ao menos uma verificação `artifact`
  ou `metric` aplicável.
- `unfulfilled`: ao menos uma verificação `artifact` ou `metric` falhou.
- `indeterminate`: nenhuma verificação `artifact` ou `metric` aplicável (todos os critérios
  qualitativos e nenhum artefato esperado). `exit_code` sozinho não decide, pois um script pode
  terminar com 0 e não produzir o resultado.
- A verdade usa o comparador **tolerante**: a pergunta avaliada é "o revisor acertou
  reprovar/aprovar", não "o nome bateu".

A tentativa é a do evento `subtask_review` (`payload.attempt`, adicionado por
`v16-pipeline-robustness` §2.8). O estado do disco no fim da sessão aproxima o da tentativa;
quando uma tentativa posterior sobrescreve artefatos, a avaliação marca a tentativa como
`indeterminate` com `detail="artefatos sobrescritos"` (detectado por mtime do artefato maior que
o timestamp do evento da revisão).

## 3. Veredito do revisor contra a verdade

Para cada evento `subtask_review` (aprovado = `status` em `pass`/`divergent_but_documented`):

| Revisor \ Verdade | `fulfilled` | `unfulfilled` | `indeterminate` |
|---|---|---|---|
| aprovou | acerto | **falso aprovado** | indeterminada |
| reprovou | **falso reprovado** | acerto | indeterminada |

Métricas por sessão e por modelo do revisor (a combinação `provedor/modelo` vem de
`token_usage` do papel `reviewer`):

- `reviewer_precision_reject` = reprovações corretas / reprovações determináveis;
- `false_reject_rate` = falsos reprovados / (fulfilled determináveis);
- `false_accept_rate` = falsos aprovados / (unfulfilled determináveis);
- `indeterminate_share`.

Cada falso reprovado e falso aprovado é listado (tarefa, tentativa, `signature`, critério), para
inspeção humana; sem texto de resposta do agente.

## 4. Resolução e laços de reprovação

### 4.1 Alvos e sequências

Alvo = `("plan", sessão)` para `plan_validation` e `("subtask", task_name)` para
`subtask_review`. Cada alvo tem a sequência ordenada de seus eventos (por timestamp).

### 4.2 Taxa de resolução

- Uma **reprovação** é *resolvida* se o evento seguinte do mesmo alvo é aprovação (inclusive
  `approved_with_warnings`).
- `resolution_rate` = reprovações resolvidas / reprovações com ao menos um evento seguinte.
- `attempts_to_resolve` = média e máximo de reprovações consecutivas antes da aprovação.
- Reprovação sem evento seguinte é `unresolved_tail` (a sessão acabou ou o alvo foi abandonado)
  e é reportada à parte, não entra no denominador.

### 4.3 Laços

Um **laço** é uma sequência de `LOOP_MIN_LENGTH` (padrão 3) ou mais reprovações consecutivas do
mesmo alvo com a mesma `signature` (campo definido por `v16-pipeline-robustness`). O relatório
traz, por sessão: número de laços, comprimento máximo, e a razão entre eventos de reprovação em
laço e o total de reprovações. Laços do Validator LLM e do revisor são separados.

### 4.4 Reparos do planejador

`plan_normalized` contado por sessão e por modelo do Researcher: taxa de planos com reparo e
tipos mais frequentes. Mede o quanto o framework compensa o planejador.

## 5. Juiz LLM das perguntas de `ask_researcher`

### 5.1 Eventos avaliados

Todo evento `ask_researcher` da sessão (`question`, `context`, `why_cant_proceed`, `options`,
`mode`; e, a partir de `v18-researcher-consult`, a resposta registrada em
`researcher_interactions` com `respondido_por`, `confianca`, `fontes`).

### 5.2 Rubrica

Cada critério em escala 1 a 3, com âncoras fixas no prompt do juiz e nesta spec:

| Critério | 1 | 2 | 3 |
|---|---|---|---|
| `necessidade` | o contexto da própria pergunta já permitia decidir | decisão razoável sem ajuda, mas com risco | só o pesquisador (ou fonte externa) poderia decidir |
| `clareza` | pergunta ambígua ou sem contexto suficiente | compreensível, falta detalhe | objetiva, com contexto e opções |
| `resposta` (só se houver resposta) | não responde ou contradiz o contexto | responde parcialmente | responde e é utilizável |
| `efeito` (só se houver resposta e evento seguinte do agente) | o agente ignorou a resposta | uso parcial | o agente passou a agir conforme a resposta |

`efeito` é decidido **deterministicamente** quando possível (a opção escolhida aparece no
prompt da próxima tentativa ou no `scientific_rationale`); o juiz só desempata os casos que o
código não resolve. A saída do juiz é JSON validado
(`{"necessidade": int, "clareza": int, "justificativa": str}` e demais campos aplicáveis);
resposta inválida tem uma nova tentativa e, falhando, o evento é marcado `judge_error`
(nunca nota inventada).

### 5.3 Independência do juiz

`COMM_EVAL_JUDGE_PROVIDER` e `COMM_EVAL_JUDGE_MODEL` (sem padrão: ausentes, o juiz é
recusado com erro explícito, não substituído por outro modelo). Antes de avaliar, o juiz
verifica o provedor do agente que perguntou (`token_usage.provider` da execução do evento) e
**recusa** o evento se for igual ao do juiz, registrando `judge_skipped: same_provider`. O
juiz é instanciado pela fábrica de provedores existente (`src/llm/registry.py`); quando
`v16-model-catalog-router` existir, o papel `comm_judge` do catálogo o substitui sem mudar o
contrato desta spec.

### 5.4 Calibração humana

- **Amostra:** `COMM_EVAL_CALIBRATION_SIZE` eventos (padrão 20), escolhidos por um gerador
  determinístico (semente fixa em arquivo) estratificado por papel que perguntou e por sessão;
  o comando `calibration-sheet` grava a planilha em branco com os campos do evento e as colunas
  da rubrica.
- **Rótulos:** o pesquisador (ou quem ele indicar) preenche `necessidade` e `clareza` (1 a 3)
  por evento; arquivo `docs/benchmarks/calibracao/ask_researcher.jsonl`, uma linha por evento
  (`event_ref`, `rotulador`, notas, `rotulado_em`).
- **Concordância:** kappa de Cohen ponderado (pesos quadráticos, escala ordinal) entre juiz e
  humano, por critério, calculado em `calibrate` sobre os eventos que ambos avaliaram.
- **Limiar:** `COMM_EVAL_MIN_KAPPA` (padrão 0,6). Abaixo do limiar, ou com menos de
  `COMM_EVAL_CALIBRATION_SIZE` eventos rotulados, toda nota do juiz no relatório recebe o
  selo `não calibrado` e o relatório mostra o kappa obtido. Nenhuma média de notas do juiz é
  apresentada sem o selo ou o kappa ao lado.
- **Reprodutibilidade:** o arquivo de calibração registra o modelo e a versão da rubrica usados
  em cada rodada do juiz; mudar o modelo ou a rubrica invalida a calibração anterior (nova
  rodada exigida).

### 5.5 Orçamento

`COMM_EVAL_MAX_USD` (padrão `0`: nenhum juiz externo roda sem teto explícito). O custo vem de
`record_llm_call`/tabela de preços existente; ao estourar, a avaliação para, relata o que
avaliou e marca o restante como `judge_skipped: budget`.

## 6. Dados que saem do nó

O juiz externo recebe somente `question`, `why_cant_proceed` e `options`, mais `context`
truncado em `COMM_EVAL_JUDGE_CONTEXT_CHARS` (padrão 400), após a **redação**:

- números com casas decimais e sequências de 6 ou mais dígitos viram `<num>`;
- nomes de arquivos de `input_snapshot/`, `input_context/` e dos artefatos da sessão viram
  `<arquivo>`;
- URLs e e-mails viram `<url>` e `<email>`.

Habilitação explícita: `COMM_EVAL_ALLOW_EXTERNAL_JUDGE=false` por padrão; falso, só juiz
configurado para provedor `ollama` (no nó) ou para endpoint declarado local é aceito. A redação é
uma função pura (`redact_for_judge`), testada à parte. Quando `v18.5-egress-gate` existir, o
juiz passa a usá-lo; até lá, esta redação mínima vale (mesma política que
`v18-researcher-consult` adota para consultas à web).

O que o pesquisador já decidiu para o benchmark (tarefa pública, sem dado sensível) fica em
configuração da execução, não no código: nenhum valor específico de estudo de caso entra nos
padrões.

## 7. Saída

`communication.py` produz `communication_eval.json` por sessão (e o resume em `results.json` do
benchmark):

```json
{
  "session_id": "...",
  "reviewer": {"model": "...", "confusion": {"hit": 0, "false_reject": 0, "false_accept": 0, "indeterminate": 0},
               "false_reject_rate": null, "false_accept_rate": null, "mismatches": []},
  "resolution": {"plan": {...}, "subtask": {...}, "loops": {...}},
  "planner_repairs": {"plans": 0, "with_repair": 0, "by_kind": {}},
  "ask_researcher": {"events": 0, "judged": 0, "skipped": {}, "scores": {}, "calibration": {"kappa": null, "n": 0, "calibrated": false}}
}
```

Campos de taxa são `null` (não zero) quando o denominador é 0. `report.py` renderiza uma tabela
por combinação com as taxas, o comprimento do maior laço e o selo de calibração.

## 8. Análise de impacto nos 6 eixos

| Eixo | Avaliação |
|---|---|
| Segurança | Principal risco é o texto enviado ao juiz externo (§6): desligado por padrão, redação testada, teto de custo. A leitura de disco usa `resolve_artifacts` (sem travessia de caminho). |
| Desempenho | Pós-execução, no host que roda o benchmark ou no Pi; leitura de disco e consultas ao banco por sessão; sem carga durante a pesquisa. |
| Persistência | Sem schema novo; arquivo de calibração versionado e `results.json`. |
| Compatibilidade | `summarize_events` e a tabela atual do relatório continuam; bloco novo é aditivo. |
| Observabilidade | Esta mudança **é** a observabilidade da comunicação; depende dos eventos de `v16-pipeline-robustness`. |
| Testabilidade | Verdade e laços são funções puras sobre eventos e `tmp_path`; juiz com provedor simulado; nenhum teste chama provedor pago (a fixture de `tests/conftest.py` falha DNS dos provedores). |

## 9. Decisões do pesquisador e questões em aberto

**Decidido em 2026-10-05:** as questões 1 a 4 abaixo foram aceitas como descritas: a spec não
fixa modelo do juiz nem teto de gasto (padrões `COMM_EVAL_MAX_USD=0`, juiz sem configuração é
recusado); provedor, modelo e teto são definidos na execução da avaliação, e a rotulagem de
calibração é combinada quando houver eventos suficientes.

1. **Provedor e modelo do juiz**, e `COMM_EVAL_MAX_USD` para a primeira rodada. A spec não fixa
   modelo: o juiz tem de ser de provedor diferente do agente que pergunta (o benchmark usou
   Gemini, GPT e Claude como agentes; o juiz muda conforme o caso).
2. **Quem rotula** os cerca de 20 eventos de calibração, e se um segundo rotulador deve rotular
   uma parte para medir a concordância humano-humano (teto prático do kappa).
3. **Fonte dos eventos de calibração:** hoje só há `ask_researcher` do GPT-6 Luna (10 chamadas
   no benchmark de 2026-10-01) e, talvez, de outras combinações. Se faltarem eventos, a
   calibração espera as sessões com `v18-researcher-consult` ativo ou aceita menos de 20 com o
   selo `não calibrado`.
4. **`LOOP_MIN_LENGTH=3`** e `COMM_EVAL_MIN_KAPPA=0.6`: valores iniciais.
