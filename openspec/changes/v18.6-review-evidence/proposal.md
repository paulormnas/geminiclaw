# Proposta: Evidência e Tolerância na Revisão de Subtarefas

**ID:** `v18.6-review-evidence` · **Versão:** V18.6 (correções do benchmark de 2026-10-13) ·
**Capacidade:** `pipeline-robustness` (reutilizada de `v16-pipeline-robustness`)
**ADRs de origem:** [ADR 002](../../../docs/decisions/adr_002_arquitetura_multi_agent_system.md)
(revisão como etapa do DAG), [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md)
(o assistente precisa concluir sozinho) e [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md)
§3 (o que pode sair do nó). Não há ADR novo: a mudança ajusta contratos de módulos existentes e
respeita as regras de localidade em vigor.
**Origem dos requisitos:** benchmark de 2026-10-13
([`docs/benchmarks/2026-10-13-modelos-v18-resultados.md`](../../../docs/benchmarks/2026-10-13-modelos-v18-resultados.md))
e a investigação dos eventos `subtask_review` e `plan_validation` gravados no Pi 5 (2026-10-13).
**Depende de:** — (módulos implementados: `src/agents/validator_agent.py`, `src/artifact_match.py`,
`src/metrics_file.py`, `src/knowledge/normalization.py`, `src/egress/`)
**Habilita:** `v18.6-hypothesis-closure` (a ingestão passa a ligar `test_accuracy` à métrica
canônica) e `v18.6-benchmark-harness` (placar a partir de resultados validados).

## Por quê

No benchmark de 2026-10-13, a maior parte das reprovações não foi por resultado ruim. Foi por
regras do revisor que não reconhecem resultados válidos:

| Falha observada (evento no Pi) | Causa no código |
|---|---|
| Sonnet reprovado: "eda_summary.json não pôde ser verificado: a evidência só informa que ele tem 742 bytes" | `build_artifact_evidence_fragments` (`src/agents/validator_agent.py:243`) envia o começo do conteúdo como `dado_de_pesquisa`; o filtro de localidade retém o trecho e o revisor remoto recebe só nome e tamanho |
| Luna reprovado: "757 bytes são insuficientes para 150 registros" | Mesmo caso: o revisor julga pelo tamanho em bytes, que não é evidência de conteúdo |
| Terra e Luna: "a métrica 'accuracy' não está em metrics.json" com `test_accuracy` gravado | `_METRIC_ALIASES` (`validator_agent.py:80`) só reconhece o nome inteiro; `test_`, `holdout_` e `_test` não são reconhecidos |
| Luna: "a métrica 'accuracy' não está em metrics.json" com métricas por modelo | `metrics_of` (`src/metrics_file.py:20`) só lê o primeiro nível; `{"logistic_regression": {"accuracy": ...}}` fica invisível |
| Haiku: `metrics.json` com a chave `metricas` | `metrics_of` só conhece o envelope `metrics` |
| Luna: critério "h1 aprovada se acurácia >= 0.95 **e** ganho >= 0.01" reprovado | `_CRITERION_VALUE_PATTERN` (`validator_agent.py:101`) lê só a primeira comparação do critério |
| Luna: "Artefatos esperados não encontrados: eda_iris.py" | O código executado fica em `script.py`, que `_IGNORED_NAMES` (`src/artifact_match.py:20`) descarta; nenhum `.py` esperado é resolvido |
| Luna: `dummy_baseline.joblib` esperado, `dummy_most_frequent.joblib` gravado | `.joblib` e `.pkl` não estão em `EXTENSION_TIER_SUFFIXES` (`artifact_match.py:17`) |
| Haiku: 3 de 6 reprovações de plano pela regra "subtarefa `validation` sem limiar numérico" no baseline majoritário | A regra (`validator_agent.py:426-439`) vale para toda subtarefa `validation`, inclusive as que não testam hipótese |

Os mesmos nomes (`test_accuracy`) também impedem a ingestão de ligar o `Resultado` à `Metrica`
canônica (`src/knowledge/ingestion.py:866`), o que contribui para o veredito das hipóteses
ficar sempre em 0 (tratado em `v18.6-hypothesis-closure`).

## O que muda

- **Novo:** **qualificador de conjunto** no nome de métrica. A normalização compartilhada
  (`src/knowledge/normalization.py`) separa o nome base do qualificador: `test_accuracy`,
  `accuracy_test`, `holdout_accuracy` e `acuracia_teste` têm base `accuracy` e qualificador
  `teste`. `cv_`, `train_`/`treino_` e `val_`/`validacao_` continuam distintos e nunca
  satisfazem um critério sobre o conjunto de teste. O revisor e a ingestão no grafo usam a
  mesma regra.
- **Modificado:** `metrics_of` aceita o envelope `metricas` e achata métricas aninhadas por
  grupo (ex.: `logistic_regression.accuracy`), sem mudar o contrato de escrita.
- **Modificado:** avaliação de critério quantitativo. O critério com mais de uma comparação é
  avaliado por comparação. Quando a métrica aparece em mais de um grupo e o critério não nomeia
  o grupo, a avaliação determinística não escolhe sozinha: o critério segue para o revisor LLM,
  com a tabela achatada de `metrics.json` como evidência.
- **Novo:** **perfil estrutural** dos artefatos de dados (`src/artifact_profile.py`), calculado
  no nó e enviado como `esquema_agregado`: linhas, colunas, nomes de colunas e nulos por coluna
  de um CSV; caminhos de chaves, tipos e tamanhos de listas de um JSON. Nenhum valor de célula
  sai do nó.
- **Modificado:** instrução do revisor: tamanho em bytes não é evidência de conteúdo; reprovar
  só quando o perfil, `metrics.json` ou o texto contradizem um critério.
- **Modificado:** comparador de artefatos: um `.py` esperado da subtarefa resolve para o
  `script.py` executado nela (camada `script`); `.joblib` e `.pkl` entram na camada `extension`.
- **Modificado:** a regra "subtarefa `validation` exige limiar numérico" passa a valer só para
  subtarefas `validation` com `hypothesis_ref` e para `reproduction`. Baseline e diagnóstico sem
  hipótese passam pela checagem estrutural sem limiar.
- **Fora do escopo:**
  - Tratar resultado negativo como progresso e fechar hipóteses:
    [`v18.6-hypothesis-closure`](../v18.6-hypothesis-closure/proposal.md).
  - Validator de família diferente do Developer:
    [`v18.6-validator-independence`](../v18.6-validator-independence/proposal.md).
  - Mudar o filtro de localidade ou o `LOCALITY_MIN_GROUP_SIZE`: o perfil estrutural é
    construído para passar pelo filtro atual sem afrouxá-lo.
  - Qualquer chamada nova a provedor pago.

## Impacto

- **Código:** `src/knowledge/normalization.py` (qualificador), `src/metrics_file.py`
  (envelope e achatamento), `src/agents/validator_agent.py` (critérios compostos, grupos, regra
  do limiar, evidência, instrução), `src/artifact_profile.py` (novo), `src/artifact_match.py`
  (camada `script`, extensões), `src/knowledge/ingestion.py` (`_mede` com o nome base),
  `src/config.py`, `.env.example`.
- **Contratos:** `ReviewResult` ganha `undecided_criteria` (critérios que a avaliação
  determinística não decidiu e foram ao LLM); o evento `subtask_review` ganha
  `metric_qualifiers` e `undecided_criteria`. `ArtifactResolution.tier` ganha o valor `script`.
  `Resultado` ganha a propriedade opcional `qualificador` (propriedade nova de nó do grafo, sem
  migração: o AGE guarda propriedades em `agtype`).
- **Schema de banco:** nenhuma tabela ou coluna nova.
- **Localidade (ADR 019):** o perfil estrutural sai como `esquema_agregado`; nomes de colunas já
  são tratados como esquema hoje. A revisão de segurança confirma que contagens de nulos por
  coluna não expõem grupos menores que `LOCALITY_MIN_GROUP_SIZE` (design §4).
- **Compatibilidade:** `REVIEW_METRIC_QUALIFIERS=false` desliga o qualificador e
  `REVIEW_ARTIFACT_PROFILE=false` volta à evidência atual, para comparar nas avaliações.
- **Custo:** reduz chamadas (menos reprovações e retentativas). O perfil soma até
  `REVIEW_PROFILE_MAX_CHARS` caracteres por artefato no prompt do revisor.
- **Hardware (Pi 5):** leitura de CSV limitada a `REVIEW_PROFILE_MAX_BYTES`; sem dependência nova
  (módulos `csv` e `json` da biblioteca padrão).

## Aprovações necessárias

- Nenhuma alteração de schema relacional, Dockerfile, `docker-compose.yml`, exclusão de arquivos
  ou `AGENTS.md`.
- **Decisão do pesquisador** sobre as questões em aberto do `design.md` §8, em especial o
  escopo da regra do limiar (§8.1, altera a decisão de 2026-10-05 de `v16-pipeline-robustness`
  §1.3) e se `val_` conta como teste (§8.2).
- **Parecer do Analista de Segurança** sobre o perfil estrutural (design §4).
