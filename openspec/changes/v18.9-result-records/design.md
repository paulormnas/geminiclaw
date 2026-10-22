# Design: v18.9-result-records

## 1. Estado atual (2026-10-21)

- **Veredito:** `src/knowledge/verdict.py` calcula o veredito (modelo v2) e `KnowledgeService.verdict_for_hypothesis` coleta as tentativas (`service.py:351`).
- **Hipóteses:** `HypothesisCycle.sync_statuses` aplica `DECISION_EVAL_MIN_VERDICT` (`hypothesis_cycle.py:426`). `_prior_support` lê `FUNCIONOU_PARA`/`FALHOU_PARA` com o veredito da descoberta (`:214`).
- **Sugestões:** `suggestions._variation_candidates` exige veredito > 0 (`suggestions.py:182`).
- **Tentativas:** `_attempt_from` trata `falha` como ambígua mesmo com valor medido.
- **Curator:** lê `verdict_breakdown` e só grava `Descoberta` funciona/não funciona com |V| ≥ 0,1.
- **Experiência relacionada:** `related_experience` (`semantic_index.py:856`) só vê atalhos derivados de descobertas.

## 2. `RegistroResultado`

Propriedades, todas gravadas pelo orquestrador (`criado_por = "orquestrador"`):

| Propriedade | Conteúdo |
|---|---|
| `chave` | `sha256(problema_id, abordagem_id, config_normalizada)`, única por projeto |
| `metrica` | Nome canônico da métrica do critério de sucesso do Problema |
| `qualificador` | `teste` ou `cv` (os registros nunca usam `treino` nem `validacao`) |
| `melhor_valor` | Melhor valor entre as tentativas válidas, no sentido da métrica |
| `delta_base` | `melhor_valor − baseline`, com `baseline` do `Resultado` do melhor valor ou, sem ele, o melhor valor medido nos experimentos de referência (`Resultado-REFERENCIA_DE->Problema`); ausente sem referência |
| `delta_pai` | `melhor_valor −` melhor valor dos registros anteriores da mesma abordagem no mesmo problema (configuração mais antiga primeiro); ausente no primeiro registro. O grafo não tem aresta `DERIVADA_DE` entre experimentos (2026-10-22: a origem da variação é a configuração anterior) |
| `n_tentativas_validas` | Tentativas válidas (§3.1) |
| `n_replicas_independentes` | Número de pares distintos (`seed`, `dataset_ids`) entre as tentativas válidas |
| `n_atingiu_alvo` / `n_abaixo_alvo` | Contagens de tentativas válidas independentes acima e abaixo do alvo |
| `atingiu_alvo` | `n_atingiu_alvo >= 1` |
| `condicoes` | `{dataset_ids, no_execucao, config_normalizada}` |
| `experimentos` | Lista de ids |
| `qualificacao` | `pendente` (padrão), `reparo`, `restricao` ou `retido`, escrita só pelo Curator (§4) |
| `limite_aplicabilidade`, `licao` | Texto do Curator, com no máximo `CURATOR_MAX_TEXT_CHARS` |

Arestas: `RegistroResultado-REGISTRA->Abordagem`, `RegistroResultado-SOBRE->Problema` e `RegistroResultado-BASEADO_EM->Resultado`.

**Recálculo:** o registro é recalculado na ingestão de cada `Resultado` do experimento (ponto atual do recálculo do veredito). É uma função pura `compute_record(tentativas, criterio) -> RecordFacts` em `src/knowledge/result_records.py`, com escrita idempotente pela `chave`.

## 3. Regra de estado

### 3.1 Tentativa válida

Um experimento que produziu `Resultado` da métrica do critério, sem qualificador ou com `teste` ou `cv` (nunca `treino` nem `validacao`), com `status_validacao` diferente de `nao_validado` (o Validator não verificou o número) e em qualquer `status` do experimento. Havendo vários, vale o melhor:

- `sucesso`;
- `falha` com `assinatura_falha = criterio_nao_atendido`;
- `divergente_documentado`.

Sem esse `Resultado`, a tentativa não é válida e não muda as contagens. Ela continua contando em `n_tentativas` da hipótese (que conta todas as tentativas, inclusive falhas e resultados não verificados) e na memória de falhas.

### 3.2 Alvo

- O alvo é `criterio_sucesso.valor` do Problema (com `delta_min` já validado por `objective_definition`), no sentido da métrica.
- O alvo é o que estava gravado no Problema quando o primeiro `Resultado` do projeto foi ingerido. Mudanças posteriores do critério pelo pesquisador valem só para tentativas novas, e o evento `alvo_alterado` é registrado.

### 3.3 Transições ao fim do ciclo

Para cada hipótese não abandonada, sobre as tentativas dela (`Experimento-TESTA->Hipotese`, as mesmas que alimentam os registros), com `n_atingiu_alvo` e `n_abaixo_alvo` gravados na `Hipotese` por `recompute_hypothesis` (a independência vale sobre o conjunto, não por configuração):

| Condição | Estado |
|---|---|
| `n_atingiu_alvo >= HYPOTHESIS_MIN_REPLICAS` | `validada` |
| `n_abaixo_alvo >= HYPOTHESIS_MIN_REFUTATIONS` e `n_atingiu_alvo == 0` | `refutada` |
| Hipótese concluída que deixa de cumprir a própria condição | Volta a `em_teste` (mesmos efeitos de reabertura de hoje) |
| Demais casos | Sem mudança |

O evento `hipotese_transicao` passa a ter `regra` (`replicas_atingiram_alvo`, `replicas_abaixo_alvo` ou `reabertura`), `n_atingiu_alvo` e `n_abaixo_alvo`.

As variáveis usam `_bounded_number`:

| Variável | Padrão | Restrição |
|---|---|---|
| `HYPOTHESIS_MIN_REPLICAS` | 2 | Inteiro ≥ 1 |
| `HYPOTHESIS_MIN_REFUTATIONS` | 2 | Inteiro ≥ 1 |

## 4. Curator

- **`result_records(problema_id, limit)`:** lista os registros com os fatos e a qualificação.
- **`qualify_record(registro_id, qualificacao, limite_aplicabilidade, evidencia_ids, licao)`:** recusa quando `evidencia_ids` não cita ao menos um `Resultado` do registro. Também recusa `reparo` quando `atingiu_alvo` é falso e `delta_pai` não é positivo, e `restricao` quando não existe tentativa abaixo do alvo nem falha atribuída à abordagem.
- **`Descoberta`:** continua para `licao_de_caminho`/`caminho_sem_conclusao`. `funciona`/`nao_funciona` (e `condicional` com filtro) exigem que as tentativas do escopo cumpram a regra e passam a ser `BASEADA_EM` os registros do escopo que as sustentam (ligados pela própria ferramenta, no máximo cinco).
- **Prompts:** perdem a menção ao veredito.

## 5. Atalhos

O orquestrador mantém `Abordagem-FUNCIONOU_PARA->Problema` quando algum registro do par tem `n_atingiu_alvo >= HYPOTHESIS_MIN_REPLICAS`, e `FALHOU_PARA` quando nenhum registro do par atinge o alvo e algum tem `n_abaixo_alvo >= HYPOTHESIS_MIN_REFUTATIONS` (uma configuração que falha não refuta a abordagem inteira). Cada atalho guarda o `registro_id`. Quando a condição deixa de valer, o atalho passa a `contestada`, como hoje.

## 6. Migração

O script `scripts/migrate_v18_9_result_records.py` faz quatro coisas:

1. Recalcula os registros de cada projeto a partir dos `Resultado` existentes.
2. Remove as propriedades de veredito.
3. Marca como `contestada` os atalhos antigos sem `registro_id`.
4. Remove `peso` das arestas `SUSTENTA`/`REFUTA` e `descoberta_id` dos atalhos (Cypher `REMOVE`, só no Apache AGE).

Ele é idempotente, só simula por padrão e, com `--aplicar`, faz `pg_dump` em `--backup-dir` antes de gravar. Os status das hipóteses são reconciliados pela regra no fim do próximo ciclo.

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Domínio | O estado da hipótese passa a ser auditável por contagem |
| Camadas | Só `knowledge`, `agents/curator` e `cli`, sem nova dependência entre pacotes |
| Dados | Mudança de schema com migração |
| Segurança | O Curator perde uma ferramenta e ganha uma escrita restrita a qualificação. Fatos continuam fora do alcance dos agentes |
| Desempenho | Menos consultas por subtarefa (não há mais coleta de tentativas para o veredito) |
| Testes | Removem os do veredito e acrescentam os da regra e dos registros |

## 8. Segurança

- `limite_aplicabilidade` e `licao` são texto de LLM. Entram em prompts futuros só pelo `wrap_data` (dado não confiável) e com teto de caracteres.
- `qualify_record` não altera campos factuais. A porta do grafo recusa `criado_por != orquestrador` para eles.

## 9. Riscos

- **Validação casual com duas réplicas em ruído:** medida no regime N do gerador (E2). Se a falsa validação passar de 5%, o padrão de `HYPOTHESIS_MIN_REPLICAS` sobe para 3.
- **Métrica sem sentido declarado:** o registro recusa calcular `melhor_valor`. Isso conta como `metrica_indisponivel`, o mesmo comportamento de hoje.

## 10. Questões em aberto

1. Valores iniciais de `HYPOTHESIS_MIN_REPLICAS` e `HYPOTHESIS_MIN_REFUTATIONS` (proposta: 2 e 2).
