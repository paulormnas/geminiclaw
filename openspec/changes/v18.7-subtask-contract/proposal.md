# Proposta: Contrato da Subtarefa e Contexto por Papel

**ID:** `v18.7-subtask-contract` · **Versão:** V18.7 · **Capacidade:** `agent-prompts`, `pipeline-robustness`, `data-egress`
**ADRs de origem:** [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) §1 (contrato de contexto por papel), §2 (contrato da subtarefa, itens 1 a 9), §3 (critérios de aceite e regras de integridade), §6 (egresso, contaminação e tamanho) e §8 (artefatos repetidos entre subtarefas); [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §2 (papel do experimento) e §3.3 (hipótese do sistema), que alimentam os itens 1 e 4; ADR 019 §3 (contaminação e regra de nomes); ADR 015 §8 (vocabulário de métricas); ADR 020 (revisão pelo Validator).
**Depende de:** `v18.7-hypothesis-linking` (papel do experimento e hipótese derivada, usados nos itens 1 e 4 do contrato); `v18.7-exploration-limits` só como dependência opcional (tipo do objetivo do Problema, usado no item 6; recomenda-se mergeá-la antes, na mesma onda; se não existir, o item 6 sai com os campos atuais de `criterio_sucesso` e tipo `limiar`, e a mudança não bloqueia). O hash do contrato é calculado por tentativa (o contrato é reconstruído em cada tentativa) e exposto em `SubtaskContract.sha256()` e `ReviewResult.contract_sha256`; o registro por tentativa (`subtask_attempt`) é de `v18.7-exploration-metrics`. Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.
**Habilita:** `v18.7-agent-system-prompts` (preenche o recorte do regimento nos construtores de contexto e passa a lista de regras de integridade para o regimento) e `v18.7-exploration-metrics` (registra `(tentativa, hash do contrato)` e os tokens do contrato por execução, ADR 022 §6.3 e §7).

## Por quê

Na bateria V18.6 (2026-10-15), o Developer recebeu em todas as 41 chamadas da `gemini-dev-sonnet-juiz` r1 o prompt do papel, o enunciado da subtarefa e o contexto do workspace, e nunca recebeu os critérios de aceite, os nomes de arquivo esperados, a hipótese, a tarefa original, o objetivo do Problema nem quem consome os artefatos dele (ADR 022, Contexto). As reprovações mais caras vieram daí: artefato com outro nome, métrica gravada com outra chave, duas subtarefas gravando o mesmo arquivo.

O código confirma a lacuna:

| Onde | O que acontece hoje |
|---|---|
| `src/autonomous_loop.py:1328-1331` | O prompt da tentativa é só o prefixo das dependências (`_build_context_prefix`, `:666`) mais `task.prompt`. Nenhum campo do plano além do enunciado chega ao modelo. |
| `src/autonomous_loop.py:720-754` (`_dispatch_subtask`) | Recria a `AgentTask` sem `task_type`, `approach`, `hypothesis`, `hypothesis_ref`, `hypothesis_id` nem `prompt_tainted` (`src/orchestrator.py:100-110`): mesmo que o contrato fosse montado depois desse ponto, os campos já teriam sido perdidos. |
| `agents/developer/agent.py:74` | O prompt manda preencher a docstring `Hipótese` com o campo `hypothesis`, que nunca é enviado. |
| `src/llm/agent_loop.py:288-293` e `src/llm/context_compression.py:133-163` | A compressão usa `OLLAMA_NUM_CTX` (padrão 4096, `src/config.py:86`) para qualquer provedor e, ao truncar, descarta primeiro os blocos mais antigos. A primeira mensagem do usuário, onde o contrato precisa ficar, é a primeira a sair num laço longo. |
| `src/autonomous_loop.py:1505-1519` | A retentativa concatena artefatos parciais e o erro anterior ao prompt já enriquecido; nada é reconstruído a partir do plano. |
| `src/agents/validator_agent.py:989-1012` | A instrução da revisão de subtarefa só fala em critérios de aceite; não há regras de integridade, e qualquer coisa que o revisor ache errada pode reprovar. Quando todos os critérios são métricas e passam (`:980-984`), não há revisão de integridade nenhuma. |
| `src/agents/validator_agent.py:912` e spec `pipeline-robustness` ("Critérios com várias comparações…") | Métrica em vários grupos sem grupo nomeado vai ao revisor LLM, que escolhe entre chaves qualificadas. O ADR 022 §2.7 proíbe essa escolha. |
| `src/agents/validator_agent.py:741-760` e `src/orchestrator.py:2238-2242` | A validação do plano recebe a tarefa original e o plano, mas não o critério do `Problema`, e não confere colisão de `expected_artifacts` entre subtarefas. |

## O que muda

- **Novo:** construtores de contexto por papel (ADR 022 §1) num módulo único, `src/agents/subtask_contract.py`: Researcher (plano), Developer (contrato da subtarefa), Validator (plano) e Validator (revisão de subtarefa). Cada um devolve fragmentos rotulados por origem e contaminação; nenhum outro ponto do código monta esses contextos.
- **Novo:** contrato da subtarefa do Developer com os itens 1 a 9 do ADR 022 §2, renderizado num bloco de layout fixo (design §3), entregue uma vez por tentativa no início da conversa, antes do contexto do workspace, e reconstruído a partir do plano vigente em cada nova tentativa.
- **Novo:** mensagens fixadas no laço do agente: a compressão de contexto nunca descarta, trunca ou resume o bloco do contrato.
- **Novo:** chaves de métrica exigidas (item 7): nome canônico do vocabulário para cada métrica citada pelos critérios, com a regra da chave sem qualificador para o modelo escolhido na validação e chaves qualificadas `<modelo>.<metrica>` como informação.
- **Novo:** desfecho de revisão `criterio_ambiguo`: métrica medida em dois ou mais grupos, sem chave sem qualificador e sem grupo citado pelo critério. O resultado fica não validado, a tentativa é devolvida ao contador e o caso volta ao Researcher como observação.
- **Novo:** verificação de colisão de artefatos na validação do plano (ADR 022 §8): mesmo arquivo em `expected_artifacts` de duas subtarefas sem dependência entre elas é problema corrigível (`colisao_artefato`); com dependência, é aviso `artefato_atualizado`.
- **Novo:** fonte de egresso `contrato:<item>` para os itens escritos pelo Researcher, delimitada como dado pelo `EgressGate` com origem própria `planejador` (nunca `instrucao`) e marcada com `tainted = role_tainted("researcher")` (ADR 022 §6.1); o script executado enviado ao revisor passa pelo `EgressGate` com a política do destino do Validator (design §8.1).
- **Modificado:** revisão de subtarefa (ADR 022 §3). O Validator recebe o contrato completo (itens 1 a 9), as regras de integridade e a evidência; o parecer passa a ter problemas tipados (`aceite`, `integridade`) e `observacoes`. Problema de aceite só reprova se citar um critério do contrato enviado; problema de integridade só reprova se citar uma regra da lista; o resto vira observação ao Researcher e não reprova.
- **Modificado:** a revisão de integridade passa a rodar também quando todos os critérios são métricas e passaram (`REVIEW_INTEGRITY_ALWAYS`), com o script executado da subtarefa como evidência de código e os achados de métrica literal (`src/numeric_refs/literal_metrics.py`) como reprovação determinística por integridade.
- **Modificado:** "Critérios com várias comparações e métricas em vários grupos" (`pipeline-robustness`): o caso de grupo não nomeado deixa de ir ao revisor LLM e segue a tabela do item 7.
- **Modificado:** "Propagação dos nomes reais entre subtarefas" e "Revisão de critérios quantitativos por métrica nomeada" (`pipeline-robustness`) passam a usar o contrato como fonte dos critérios, artefatos e chaves (ADR 022, tabela de mudanças).
- **Modificado:** validação do plano: o contexto passa a incluir o critério do `Problema`; o Validator do plano é instruído a apontar critério com limiar sem chave indicada em subtarefa que mede vários modelos; campos do plano que entram no contrato têm teto de tamanho e padrão de nome de artefato.
- **Modificado:** `_dispatch_subtask` preserva todos os campos da `AgentTask` (usa `dataclasses.replace`).
- **Removido:** nada da verdade atual além do comportamento de "grupo não nomeado vai ao LLM", substituído acima.
- **Fora do escopo:**
  - Regimento da pesquisa, recorte por tipo de objetivo e modo, ferramenta de leitura e revisão dos prompts de sistema de cada papel: [`v18.7-agent-system-prompts`](../v18.7-agent-system-prompts/proposal.md). Esta mudança deixa nos construtores o espaço do recorte, vazio até lá, e uma lista provisória de regras de integridade em código, que aquela mudança move para a parte estruturada do regimento.
  - Registro de `(tentativa, hash do contrato)`, anomalia de hash divergente e tokens do contrato por execução: [`v18.7-exploration-metrics`](../v18.7-exploration-metrics/proposal.md). Esta mudança só calcula o hash e o expõe.
  - Papel do experimento, hipótese do sistema e retorno de retiradas ao Researcher: [`v18.7-hypothesis-linking`](../archive/v18.7-hypothesis-linking/proposal.md).
  - O bloco de contexto do workspace, que hoje é acrescentado a cada volta do laço (`src/llm/agent_loop.py:218-247`) e cresce com o número de voltas, não muda aqui; o achado vai para [`v18.7-benchmark-fixes`](../archive/v18.7-benchmark-fixes/proposal.md).
  - Qualquer chamada a provedor pago nos testes.

## Impacto

- **Código:** `src/agents/subtask_contract.py` (novo, caminho corrigido no design §13: dados do contrato, construtores, renderização, hash); `src/orchestrator.py` (`AgentTask.contract`, construtor do contexto do plano e da validação do plano); `src/autonomous_loop.py` (montagem do contrato por tentativa, `_dispatch_subtask`, desfecho `criterio_ambiguo`, observações ao Researcher); `src/agent_runtime/runtime.py` e `src/llm/agent_loop.py` (prefixo fixado); `src/llm/context_compression.py` (mensagens fixadas); `src/agents/validator_agent.py` (revisão com contrato, parecer tipado, integridade, chaves de métrica, colisão de artefatos, critério do Problema na validação do plano); `src/egress/fragments.py` e `src/egress/gate.py` (fonte `contrato:`); `src/usage.py` (devolução de tentativa); `src/plan_normalizer.py` (teto de campos e padrão de nome de artefato); `src/config.py`; `.env.example`.
- **Contratos:** `AgentTask` ganha `contract: SubtaskContract | None`. `ReviewResult` ganha `typed_issues`, `observations`, `contract_sha256` e o valor `criterio_ambiguo` em `outcome`. O evento `subtask_review` ganha `contrato_sha256`, `observacoes` e `criterio_ambiguo`. `ValidationResult.warnings` ganha `artefato_atualizado`; os problemas do plano ganham o código `colisao_artefato`. O JSON do parecer de revisão muda de `issues: [str]` para `issues: [{tipo, item|regra, texto}]` mais `observacoes: [str]`, com leitura tolerante do formato antigo (design §6.3).
- **Schema de banco:** nenhuma tabela, coluna ou propriedade de nó nova.
- **Localidade (ADR 019):** os itens 1 a 4 e 8 seguem como texto do Researcher (contaminado se o modelo dele aceita dados brutos) e delimitados como dado; nomes de artefato seguem a regra de nomes. Nenhum dado de pesquisa novo sai do nó.
- **Custo:** de 1 a 3 mil tokens de entrada por tentativa de subtarefa do Developer (não por chamada, porque o contrato entra uma vez e o histórico o reenvia); cerca de 1 mil tokens a mais por revisão LLM; uma revisão LLM a mais por subtarefa cujos critérios eram todos métricas aprovadas, com `REVIEW_INTEGRITY_ALWAYS=true`. Em troca, menos reprovações por nome de artefato, chave de métrica e colisão, cada uma custando uma tentativa inteira.
- **Hardware (Pi 5):** só montagem de texto e hash; sem dependência nova.
- **Compatibilidade:** `SUBTASK_CONTRACT_ENABLED=false` volta ao prompt atual do Developer e à revisão atual, para comparação na bateria.

## Achado novo (2026-10-18)

O contrato não entrega ao consumidor os artefatos das dependências (design §14). Fora do escopo até decisão do pesquisador.

## Aprovações necessárias

- Nenhuma alteração de schema relacional, Dockerfile, `docker-compose.yml`, exclusão de arquivos ou `AGENTS.md`.
- **Parecer do Analista de Segurança** sobre injeção de prompt por campos do contrato e sobre a nova fonte de egresso (design §8).
- **Decisão do pesquisador** sobre as questões em aberto do design §11, em especial o mascaramento do limiar quando o Researcher aceita dados brutos e o Developer não (§11.1) e o custo da revisão de integridade sempre ativa (§11.2).
