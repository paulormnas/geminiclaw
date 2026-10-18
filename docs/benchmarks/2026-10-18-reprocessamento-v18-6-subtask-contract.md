# Reprocessamento da bateria V18.6 com as regras de `v18.7-subtask-contract` (2026-10-18)

Tarefa 7.2 de `openspec/changes/v18.7-subtask-contract/tasks.md`. Sem LLM e sem provedor: as regras novas (`plan_contract_issues`, tabela de chaves de métrica) foram aplicadas, offline, aos planos e aos `metrics.json` que a bateria V18.6 (2026-10-15) deixou no Raspberry Pi (`~/bench/bateria_v18_6.json.d/*/*/sessao.tar.gz`), e os pareceres originais (`eventos.json`, evento `subtask_review`) foram classificados. `dev` em `d11f3cd`.

## Material disponível

11 execuções com `sessao.tar.gz` (`r1` a `r3` de 4 combinações; `controle-gemini-todos/r1` não tem sessão arquivada). Os pareceres de `gemini-dev-sonnet-juiz/r3-falha-cota-google` e `haiku-dev-sol-juiz/r1-falha-sequence-item` entram só na classificação das reprovações. O reprocessamento dos planos usou 18 arquivos `plans/plano_N.txt` (normalizados por `normalize_plan`) e 33 `metrics.json`; só 5 execuções têm critério de métrica casável com um `metrics.json` do plano (as demais fecharam sem treinar modelos, ver o relatório da V18.6).

## O que os pareceres da V18.6 reprovaram

Das 58 revisões de subtarefa registradas, 26 reprovaram (sem contar resultado negativo):

| Causa (classificação por texto do parecer) | Reprovações |
|---|---|
| Artefato esperado ausente no disco | 10 |
| Chave de métrica ausente ou `metrics.json` ausente | 11 |
| Outras (critério qualitativo, evidência) | 5 |

Foi a esse custo que o ADR 022 se referiu: cada reprovação gasta uma tentativa inteira do Developer.

## O que as regras novas teriam feito

| Regra | Resultado no material da V18.6 |
|---|---|
| `colisao_artefato` | **0** planos com colisão real (mesmo arquivo em duas subtarefas sem dependência). O defeito apontado no ADR não aparece nestes 18 planos. |
| `artefato_atualizado` (aviso) | 2 planos, ambos de `controle-gemini-todos/r3` (arquivo repetido com dependência entre as subtarefas). |
| `campo_do_contrato_longo` | 0 (nenhum campo acima de `CONTRACT_FIELD_MAX_CHARS=1500`). |
| `nome_de_artefato_invalido` | 0. |
| Critério de métrica sobre `metrics.json` (17 critérios, 5 execuções) | 10 que a V18.6 deixava **indecididos** (`None`, encaminhados ao revisor LLM) passam a ser decididos pela chave sem qualificador (6 em `controle-gemini-todos/r2`, 3 em `gemini-dev-sonnet-juiz/r1`, 1 em `controle-gemini-todos/r3`); os outros 7 já eram decididos (4 atendidos, 3 reprovados) e não mudam de resultado. |
| `criterio_ambiguo` | **0** casos nos 17 critérios. |

## Leitura honesta

- As 21 reprovações por **artefato ausente** (10) e **chave de métrica ausente** (11) são o alvo do contrato (itens 3 e 7 entregam ao Developer os nomes e as chaves exigidas). Este reprocessamento **não prova** que elas seriam evitadas: isso depende do Developer obedecer ao contrato e só a bateria real mede. O que se confirma offline é que as regras determinísticas novas estão consistentes com o material real e não geram falso positivo nos 18 planos (0 colisões, 0 campos longos, 0 nomes inválidos).
- O ganho verificável sem LLM é de custo e de determinismo: 10 dos 17 critérios antes encaminhados ao revisor LLM passam a ser decididos por regra (e a revisão LLM de integridade, ligada por padrão, roda uma vez por subtarefa).
- A colisão de artefatos, que o ADR 022 §8 cita como causa de reprovação, não ocorre neste conjunto; a regra fica como proteção.
- Os 28 `Resultado` sem `MEDE` da bateria de 2026-10-18 (`haiku-dev-sol-juiz`) e a falha por artefatos de dependências ausentes no sandbox não estão neste material (V18.6) e seguem pendentes de bateria real: o primeiro é tratado pelo item 7 do contrato; o segundo **não é coberto** pela mudança (design §14, `v18.7-dependency-artifacts`).

## Como reproduzir

Extrair os `sessao.tar.gz` em um diretório fora do repositório (`<combinação>/<repetição>/<sessão>/`) e rodar, no checkout do Pi, um script que, por sessão, normalize cada `plans/plano_N.txt`, chame `plan_contract_issues` e avalie `_evaluate_metric_criteria(criterios, metrics, contract_keys=False)` contra `contract_keys=True` para cada `metrics.json` com o critério do plano. Os números acima vêm dessa execução em 2026-10-18.
