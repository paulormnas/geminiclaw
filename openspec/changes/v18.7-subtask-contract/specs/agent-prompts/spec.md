# Delta: agent-prompts

Os testes desta capacidade usam um provedor LLM falso que grava, em cada `generate`, a lista `messages` e o `system` recebidos e devolve respostas roteirizadas (chamadas de ferramenta e texto final). Nenhum cenário chama provedor pago.

## ADDED Requirements

### Requirement: Contexto montado por um construtor por papel
O sistema SHALL montar o contexto de cada papel por um único construtor em `src/subtask_contract.py` (ADR 022 §1): Researcher (plano), Developer (contrato da subtarefa), Validator (plano) e Validator (revisão de subtarefa). O contexto do Validator do plano MUST conter a tarefa original, o critério do `Problema` (quando há projeto) e o plano. Nenhum outro módulo SHALL montar esses contextos.

#### Scenario: Validação do plano com o critério do Problema
- **GIVEN** um projeto cujo `Problema` tem `criterio_sucesso` com métrica `acuracia`, alvo `0.9` e `baseline_descricao` "classe majoritária"
- **WHEN** `validate_plan` é chamado com um provedor falso
- **THEN** a mensagem enviada contém um fragmento de fonte `contrato:objetivo` com `acuracia`, `0.9` e "classe majoritária"
- **AND** contém a tarefa original e o JSON do plano

#### Scenario: Ponto único de montagem
- **WHEN** o teste de arquitetura procura, fora de `src/subtask_contract.py`, a montagem do texto "CONTRATO DA SUBTAREFA"
- **THEN** nenhuma ocorrência é encontrada

### Requirement: Contrato da subtarefa enviado ao Developer
Toda tentativa de subtarefa do Developer SHALL levar o bloco "CONTRATO DA SUBTAREFA (versão 1)" com os itens 1 a 9 do ADR 022 §2, nesta ordem: `task_name`, `task_type` e papel do experimento; critérios de aceite numerados `c1…cn`; artefatos esperados com os nomes exatos; a linha da hipótese; a tarefa original; o objetivo do `Problema` (métrica, sentido, alvo, referência, tipo); as chaves de métrica exigidas; os artefatos consumidos por subtarefas posteriores; e a proibição de ajuste no conjunto de teste. Item sem conteúdo SHALL aparecer com "não se aplica".

#### Scenario: Itens do contrato
- **GIVEN** a subtarefa `treinar_modelo_a` (`model_impl`, hipótese "o modelo A melhora a acurácia em relação à referência"), critérios "acurácia no teste >= 0.90" e "matriz de confusão salva", artefatos `metrics.json` e `matriz_confusao.png`, e a subtarefa `comparar_modelos` que depende dela e cita `metrics.json`
- **WHEN** a primeira tentativa é executada com o provedor falso
- **THEN** a primeira mensagem `user` da primeira chamada contém, em ordem, os rótulos "1. Subtarefa", "2. Critérios de aceite", "3. Artefatos esperados", "4. Hipótese testada", "5. Tarefa original", "6. Objetivo do Problema", "7. Chaves de métrica exigidas", "8. Artefatos que subtarefas posteriores consomem" e "9. Integridade"
- **AND** contém `c1: acurácia no teste >= 0.90`, `matriz_confusao.png`, a chave `acuracia (critério c1)` e a linha `metrics.json: comparar_modelos`

#### Scenario: Preparação sem hipótese própria
- **GIVEN** a subtarefa `dividir_dados` com papel `preparacao`, da qual dependem testes das hipóteses `h1` e `h2`
- **WHEN** o contrato é montado
- **THEN** o item 4 é "preparação: serve às hipóteses h1, h2"
- **AND** o item 7 é "não se aplica" quando nenhum critério cita métrica com limiar

#### Scenario: Métrica fora do vocabulário
- **GIVEN** o critério "f_beta_2 >= 0.7", um `InMemoryGraphStore` com vocabulário semeado sem termo nem sinônimo para `f_beta_2`, e a busca semântica simulada sem resultado
- **WHEN** o contrato é montado
- **THEN** o item 7 lista `f_beta_2` como chave exigida, com `MetricKey.new_term = True`
- **AND** `resolve_metric` devolve `Resolution` com `status = "candidato_criado"`, existe um nó `Metrica` com `nome = "f_beta_2"` e `status = "candidato"`, e `list_pending(store)` traz um item `{"label": "Metrica", "termo": "f_beta_2", "tipo": "termo"}`
- **AND** a subtarefa aparece em `CycleOutcome.tasks` e é despachada, sem retirada nem pedido ao gate

### Requirement: Contrato uma vez por tentativa e fixado no histórico
O bloco do contrato SHALL entrar uma única vez, como primeira mensagem `user` da conversa da tentativa, antes do enunciado e do contexto do workspace, e o laço de ferramentas MUST NOT acrescentá-lo de novo. A compressão de contexto MUST NOT descartar, truncar nem resumir a mensagem do contrato. Cada nova tentativa SHALL reconstruir o contrato a partir do plano vigente. O prompt de sistema do papel SHALL ir em toda chamada ao provedor.

#### Scenario: Laço com várias voltas
- **GIVEN** um provedor falso que pede `python_interpreter` em 4 voltas e responde texto final na 5ª
- **WHEN** a tentativa é executada
- **THEN** a 5ª chamada tem exatamente uma mensagem que contém "CONTRATO DA SUBTAREFA"
- **AND** essa mensagem é a primeira `user` da lista
- **AND** as 5 chamadas recebem `system` igual à instrução do Developer

#### Scenario: Compressão não remove o contrato
- **GIVEN** `OLLAMA_NUM_CTX=1024` e resultados de ferramenta de 3000 caracteres em 6 voltas
- **WHEN** a 7ª chamada é montada
- **THEN** a mensagem do contrato está presente e inalterada

#### Scenario: Nova tentativa depois de replanejamento
- **GIVEN** a tentativa 1 de `treinar_modelo_a` com o critério "acurácia no teste >= 0.90" e o plano vigente alterado para "acurácia no teste >= 0.85" antes da tentativa 2
- **WHEN** a tentativa 2 começa
- **THEN** o contrato da tentativa 2 contém `>= 0.85` e não contém `>= 0.90`
- **AND** `SubtaskContract.sha256()` das duas tentativas é diferente

### Requirement: Campos da subtarefa preservados até o runtime
O despacho da subtarefa SHALL preservar todos os campos de `AgentTask`, inclusive `task_type`, `approach`, `hypothesis`, `hypothesis_ref`, `hypothesis_id`, `prompt_tainted` e `contract`.

#### Scenario: Despacho
- **GIVEN** uma `AgentTask` com `task_type="model_impl"`, `hypothesis_ref="h1"` e `prompt_tainted=True`
- **WHEN** `_dispatch_subtask` a processa
- **THEN** a tarefa devolvida tem os mesmos três valores

### Requirement: Contrato desligável
Com `SUBTASK_CONTRACT_ENABLED=false` (padrão `true`, em `src/config.py`), o sistema SHALL montar o prompt do Developer e a revisão como antes desta mudança.

#### Scenario: Contrato desligado
- **GIVEN** `SUBTASK_CONTRACT_ENABLED=false`
- **WHEN** uma tentativa é executada com o provedor falso
- **THEN** nenhuma mensagem contém "CONTRATO DA SUBTAREFA" e a primeira mensagem `user` é o prefixo das dependências seguido do enunciado

### Requirement: Validator do plano aponta critério sem chave
A instrução do Validator do plano SHALL dizer que um critério com limiar, sem chave qualificada, numa subtarefa que compara vários modelos, é problema corrigível com o código `criterio_sem_chave` (ADR 022 §2.7).

#### Scenario: Instrução renderizada
- **WHEN** `validate_plan` chama o provedor falso
- **THEN** o `system` contém `criterio_sem_chave`
- **AND** um parecer roteirizado com o problema `criterio_sem_chave: comparar_modelos.c1` resulta em `revision_needed` com esse texto em `issues`
