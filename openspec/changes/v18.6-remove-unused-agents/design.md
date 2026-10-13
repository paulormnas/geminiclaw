# Design: v18.6-remove-unused-agents

## 1. Papéis depois da mudança

| Papel | Executa subtarefa do plano | Uso interno | Modelo no catálogo |
|---|---|---|---|
| `developer` | sim | — | sim |
| `researcher` | sim | planejamento, consulta | sim |
| `validator` | não | validação do plano, revisão de subtarefa, verificação de afirmações | sim |
| `summarizer` | não | síntese final, revisão de afirmações | sim |
| `base` | não | promoção de memória, extração de padrões de código | sim |
| `curator` | não | curadoria do grafo | sim (opcional) |
| ~~`reviewer`~~ | — | — | removido |

`AGENT_IDS` (`src/orchestrator.py:74`) passa a ser `("developer", "researcher")`: é a lista de papéis
que uma subtarefa do plano pode pedir. `AGENT_DEFINITIONS` (`src/agent_runtime/definitions.py`)
mantém `base`, `summarizer` e `curator`, que o runtime em processo executa por chamada interna.

## 2. Plano com papel fora de `AGENT_IDS`

`src/plan_normalizer.py` resolve `agent_id` antes da validação:

| `agent_id` no plano | Resultado |
|---|---|
| `developer`, `researcher` e sinônimos atuais | mantido |
| `base` | reparado para `developer` (`normalize_agent_id`); antes era redirecionado no despacho |
| `reviewer`, `revisor`, `summarizer`, `sumarizador` | não recuperável: "papel de subtarefa inválido: use `developer` ou `researcher`" |

Com isso o ramo `base` de `_dispatch_subtask` (`src/autonomous_loop.py:722`) sai. O ramo de
palavras-chave para `agent_id` desconhecido continua, porque cobre subtarefas criadas fora do
normalizador (replanejamento).

## 3. Catálogo

`REQUIRED_ROLES` passa a `("researcher", "developer", "summarizer", "validator", "base")`. A seção
`reviewer` sai de `catalog.yaml`. Um `catalog.local.yaml` com `papeis.reviewer` falha na validação
estrita com a mensagem "papel `reviewer` removido em V18.6 (v18.6-remove-unused-agents)".

## 4. Telemetria e benchmark

- `review_result` grava `record_llm_call(..., "validator", funcao="revisao_subtarefa")` e o evento
  `subtask_review` com `agent_id = "validator"`.
- `scripts/benchmark/communication.py` lê `subtask_review` com `agent_id` em
  `{"validator", "reviewer"}`, para que as sessões gravadas antes da mudança continuem legíveis, e
  publica a chave `revisao_subtarefa`.
- `comm_judge.POOL_ROLES` passa a `("validator", "summarizer", "base")`.

## 5. Questões em aberto (decisão do pesquisador)

1. **`base` como papel interno.** Proposto: manter `base` só para promoção de memória e extração de
   padrões. Alternativa: executar esses dois trabalhos com o `summarizer` e remover o papel `base`
   do catálogo (o módulo `agents/base/` continua como biblioteca). A alternativa elimina mais um
   papel e um pin (`BASE_MODEL`), mas dá ao `summarizer` a ferramenta de memória.
2. **Os 3 `sandbox_run` do `base` em 2026-10-12** (`analisar_sessao`, `iris_session_review`,
   `ler_script`) não têm origem identificada no código atual. Proposto: tratá-los como execução
   manual de diagnóstico; se o pesquisador reconhecer outro uso, a remoção de `base` de
   `AGENT_IDS` é revista.

## 6. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador e loop | `AGENT_IDS` menor; atalho `agent_tasks` removido; ramo `base` do despacho removido |
| Agentes e prompts | `agents/reviewer/` removido; nenhum prompt ativo muda |
| Sandbox | Nenhum |
| Persistência | Nenhum schema; rótulo novo em eventos futuros |
| Segurança | Superfície menor (um agente com skills a menos) |
| Testes e telemetria | Testes do `reviewer` removidos ou ajustados; relatório de comunicação lê os dois rótulos |
