# Design: v18.7-exploration-metrics

## 1. Confronto com o código (2026-10-15)

| Ponto | Onde está hoje | O que muda |
|---|---|---|
| Grupos de métricas | `GROUPS` (`src/operation_metrics.py:33`), `VERSION` 1, agregação por leitor com estado `disponivel`/`indisponivel`/`erro` (`:63-100`) | Grupo `exploracao`; `VERSION = 2` |
| Contador `sem_hipotese` | `HypothesisClosureReader` (`src/operation_metrics.py:255-292`), linha do relatório (`:585-589`) | `reprovacoes_sem_hipotese` removido |
| Evento do ciclo | `hypothesis_cycle` (`src/exploration.py:398-409`) | Campos novos produzidos por `v18.7-hypothesis-linking` (design §10 dela); aqui só a agregação |
| Início de tentativa | `subtask_start` só na primeira tentativa (`src/autonomous_loop.py:1379-1390`) | Evento `subtask_attempt` em toda tentativa |
| Revisão | `subtask_review` (`src/autonomous_loop.py:2401-2425`) | Ganha `contrato_sha256` |
| Estimativa de tokens | `estimate_tokens` (`src/llm/context_compression.py:29`) | Usada para o contrato |
| Benchmark | `summarize_events` (`scripts/benchmark/interactions.py:17-44`), `render_operation` (`scripts/benchmark/report.py:177-208`) | Resumo de tentativas e tabela de exploração |

## 2. Grupo `exploracao`

```json
"exploracao": {
  "estado": "disponivel",
  "ligacao": {
    "estado": "disponivel",
    "experimentos_por_papel": {"teste": 6, "preparacao": 4, "referencia": 1},
    "testes_por_origem": {"pesquisador": 0, "researcher": 3, "curator": 1, "oportunidade": 0, "sistema": 2},
    "proporcao_testes_sistema": 0.333,
    "ligacoes_prepara_derivadas": 5,
    "hipoteses_sistema_criadas": 2,
    "hipoteses_sistema_abandonadas": 1,
    "removidas_pelo_replanejamento": 2
  },
  "parada": {
    "estado": "disponivel",
    "ciclos": 9, "intervencoes_estagnacao": 1, "saturacao_avaliada": false,
    "objetivo_atingido": true, "desfecho_objetivo": null,
    "retiradas_restricao": {"abordagem": 1, "similaridade": 2},
    "retiradas_restricao_similaridade": [{"hipotese_id": "...", "restricao_id": "...", "similaridade": 0.86}]
  },
  "contrato": {
    "estado": "disponivel",
    "tentativas": 14, "tokens_estimados_total": 23100, "tokens_estimados_medio": 1650,
    "fracao_entrada": 0.071, "divergencias": 0, "tentativas_sem_hash": 0, "tarefa_original_truncada": 1
  }
}
```

### 2.1 Fontes (métricas agregadas, não produzidas)

- **`ligacao`** (`ExplorationLinkingReader`): `experimentos_por_papel` e `testes_por_origem` contados no grafo, no fechamento, sobre os `Experimento` com `EXECUTADO_EM` a sessão (o evento por ciclo registra o planejado; o grafo registra o executado). `Experimento` sem `papel` conta como `teste` (ADR 021 §9). Origem do teste: `Hipotese.origem` do destino de `TESTA`. `ligacoes_prepara_derivadas`, `hipoteses_sistema_criadas`, `hipoteses_sistema_abandonadas` e `removidas_pelo_replanejamento`: soma dos campos do evento `hypothesis_cycle` da sessão (`ligacoes_prepara`, `hipoteses_sistema_criadas`, `hipoteses_sistema_abandonadas`, tamanho de `removidas_pelo_replanejamento`). `proporcao_testes_sistema = sistema / total de testes` (`null` com zero testes).
- **`parada`** (`ExplorationStopReader`): eventos `estagnacao_intervencao`, `saturacao_avaliada`, `objetivo_atingido`, `objetivo_desfecho`, `restricao_retirada` e `exploration_stop` de `v18.7-exploration-limits`. A lista de retiradas por similaridade é limitada a `OPERATION_METRICS_LIST_MAX_ITEMS`, com `retiradas_restricao_similaridade_omitidas` quando passa.
- **`contrato`** (`ContractReader`): eventos `subtask_attempt`, `subtask_review` e `contrato_divergente`; `fracao_entrada = tokens_estimados_total / soma de prompt_tokens das chamadas dos papéis developer e validator` da sessão (telemetria `token_usage`), `null` sem chamadas.

Regra de produtor ausente: quando a mudança produtora não está no código (sem o campo no evento, sem o evento registrado no catálogo de eventos do produtor, ou sem a propriedade no schema), o bloco é `{"estado": "indisponivel", "produtor": "<id da mudança>"}`, sem números (requisito existente "Métricas agregadas, não produzidas"). Falha de leitura de um bloco o marca `erro` e não derruba os outros. O `estado` do grupo é `disponivel` se ao menos um bloco o for.

### 2.2 Versão

`VERSION = 2`. Leitores do relatório e do benchmark tratam `versao = 1` (sessões anteriores) sem o grupo `exploracao`, exibindo `n/d`, sem erro.

## 3. Contrato por tentativa (ADR 022 §6.3, §7)

- **Início da tentativa:** imediatamente antes de `_execute_agent` em cada tentativa do Developer (`src/autonomous_loop.py:1373-1393`), o laço emite `subtask_attempt` com `task_name`, `attempt` (1-indexado), `contrato_sha256` (de `SubtaskContract.sha256()`, `v18.7-subtask-contract`), `contrato_chars` (tamanho do bloco renderizado), `contrato_tokens_estimados` (`estimate_tokens` do bloco renderizado, a mesma estimativa usada na compressão de contexto), `tarefa_original_truncada` e `recorte_sha256` (hash do recorte do regimento usado na tentativa, lido de `AgentContext.recorte_sha256`, de `v18.7-agent-system-prompts`; `null` enquanto aquela mudança não existir). Assim o registro por tentativa do ADR 022 §4.4 e §7 (hash do contrato e do recorte) fica todo neste evento, e o registro por sessão (`regimento_sessao`) fica com `v18.7-agent-system-prompts`. Sem contrato (subtarefa do Researcher, ou produtor ausente), o evento sai com `contrato_sha256 = null` e conta em `tentativas_sem_hash`. O evento é emitido uma vez por tentativa, nunca por volta do laço de ferramentas (o contrato entra uma vez por tentativa, ADR 022 §1).
- **Revisão:** `subtask_review` ganha `contrato_sha256 = ReviewResult.contract_sha256`.
- **Divergência:** ao registrar a revisão, o laço compara com o hash do `subtask_attempt` do mesmo `(task_name, attempt)`; diferentes, emite `contrato_divergente` (`task_name`, `attempt`, os dois hashes) e segue: a subtarefa não é reprovada por isso (ADR 022 §7). Revisão sem `subtask_attempt` correspondente não é divergência; é contada como `tentativas_sem_hash`.
- O hash é só hexadecimal (64 caracteres); o evento não leva o texto do contrato (que pode conter dado do Researcher marcado como contaminado, ADR 022 §6.1).

## 4. Relatório da sessão

Na seção determinística "Métricas de operação" (`render_operation_metrics_section`), linha "Exploração":

- experimentos por papel; testes por origem com a proporção do sistema; `PREPARA` derivadas; hipóteses do sistema criadas e abandonadas;
- ciclos, intervenções por estagnação, objetivo atingido ou desfecho;
- retiradas por restrição por critério e a lista das por similaridade (hipótese, restrição, similaridade), para auditar a regra (ADR 021 §5.5);
- tokens estimados do contrato (total, médio por tentativa, fração da entrada) e divergências de hash.

Sai a linha "subtarefas reprovadas por limiar sem hipótese (sem_hipotese)".

## 5. Benchmark

- `summarize_events` ganha `subtask_attempts` (`total`, `com_hash`, `tokens_contrato_total`) e `contrato_divergente` (contagem); `subtask_reviews.motivos` continua genérico (passa a mostrar `hipotese_do_sistema`, `direcao_restrita` etc. quando existirem).
- Cada resultado guarda `exploracao` (cópia do grupo das métricas de operação).
- `report.py` ganha `render_exploration`: por combinação, média por execução de testes, preparações e referências, proporção de testes do sistema, `PREPARA` derivadas, hipóteses do sistema abandonadas, tokens do contrato por execução e fração da entrada, paradas `hipoteses_nao_testadas`; mais o número de modelos treinados (testes aprovados), que a "Revisão" do ADR 021 pede.
- `contrato_divergente` vira aviso de placar (como `versao_desconhecida`), não anomalia de parada: não interrompe o runner com `--fail-fast` (decisão: é registro de integridade, não falha de infraestrutura; ver Questões em aberto).

## 6. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `OPERATION_METRICS_LIST_MAX_ITEMS` | `50` | máximo de itens de listas nas métricas e no relatório (retiradas por similaridade); inteiro ≥ 1 |

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Baixo | Um evento por tentativa e uma comparação de hash na revisão |
| Agentes & Prompts | Nenhum | Nada muda no que os agentes recebem |
| Sandboxes & Containers | Nenhum | — |
| Persistência de Estado | Baixo | Grupo novo no `payload["operation_metrics"]` e em `session_metadata.json`; eventos na tabela existente |
| Segurança & Hardening | Baixo | Eventos só com hashes, contagens, IDs e códigos; sem texto do contrato nem enunciados |
| Testes & Telemetria | Médio | Leitores novos com telemetria e grafo simulados; tabelas novas no benchmark |

## 8. Segurança

- Os eventos novos não carregam texto vindo de LLM nem de dados de pesquisa: hashes, contagens, IDs de nó, nomes de subtarefa e códigos. A lista de retiradas por similaridade leva IDs e o valor da similaridade, não o texto da hipótese nem o da restrição.
- O hash divergente é sinal de integridade (contrato alterado entre execução e julgamento, possivelmente por injeção); fica registrado e visível no relatório e no benchmark, sem decidir nada sozinho.
- O relatório continua gerado por código, nunca reescrito pelo Summarizer (requisito existente).

Parecer do Analista de Segurança (2026-10-15): **Aprovado.** Um achado **Baixo**: os nomes de subtarefa são texto de LLM. No `relatorio_final.md` e nas tabelas do benchmark, eles passam por escape de Markdown e por `sanitize_text`, para que um link ou uma imagem remota no nome não envie dados a terceiros quando alguém abrir o relatório. Um teste usa um nome com `![](http://...)`. Os eventos levam o hash só em hexadecimal e nenhum texto do contrato, o que está adequado.

## 9. Riscos e mitigações

| Risco | Severidade | Mitigação |
|---|---|---|
| Estimativa de tokens diferente do cobrado | Média | Nome explícito `tokens_estimados`; a fração da entrada usa os `prompt_tokens` reais como denominador |
| Bloco lido antes de o produtor existir dá zeros enganosos | Média | Bloco `indisponivel` com o nome da mudança produtora, nunca zero |
| Contagem planejada × executada divergente | Baixa | `ligacao` conta do grafo (executado); os eventos do ciclo ficam para o planejado |
| Leitores do relatório quebram com `versao = 1` | Baixa | Teste com payload antigo |

## 10. Questões em aberto

1. **`contrato_divergente` no benchmark:** proposto como aviso de placar. Se o pesquisador preferir tratá-lo como anomalia que interrompe a bateria (é defeito de código, não do modelo), muda uma linha de `anomalies()`.
2. **Tokenizador:** a estimativa usa `estimate_tokens` (caracteres/4 aproximado). Contagem por tokenizador do provedor exigiria dependência ou chamada extra; proposto não fazer.
3. **Calibração do veredito e `SOLUTION_MIN_VERDICT`:** fora desta mudança; decisão do pesquisador para a Etapa 2 (ver `v18.7-exploration-limits`, design §17).
