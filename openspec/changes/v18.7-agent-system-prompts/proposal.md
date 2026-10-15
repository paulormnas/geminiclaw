# Proposta: Regimento da Pesquisa e Prompts de Sistema por Papel

**ID:** `v18.7-agent-system-prompts` · **Versão:** V18.7 · **Capacidade:** `agent-prompts`, `agent-runtime`
**ADRs de origem:** [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) §4 (regimento da pesquisa e prompts por papel: 4.1 conteúdo comum, 4.2 prompt do papel, 4.3 injeção por recorte, 4.4 versão e adendo de projeto, 4.5 redação, 4.6 auditoria) e §5 (coerência entre regimento, prompts e código); [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §2 (papéis de experimento), §5 (tipos de objetivo, paradas, estagnação e saturação), §6 (o que impede a execução) e §7 (retorno ao Researcher), que são o conteúdo do regimento; ADR 007 (papéis); ADR 010 (assistente de pesquisa); ADR 019 (egresso); ADR 020 (Validator).
**Depende de:** `v18.7-subtask-contract` (construtores de contexto com o espaço do recorte, lista de regras de integridade e contrato do Developer); `v18.7-hypothesis-linking` (papel do experimento, motivos de retirada e retorno ao Researcher); `v18.7-exploration-limits` (tipo do objetivo do `Problema`, motivos de parada `limite_custo` e `saturacao`, política `ao_atingir_objetivo` e decisão reservada `restringir_direcao`); `v18.7-persistent-human-gate` (pedido ao pesquisador para ativar o adendo de projeto, com a prova da aprovação em `gate_requests`; o valor `ativar_adendo_regimento` já consta do `CHECK` de `decisao` criado por aquela mudança). Não depende de `v18.7-exploration-metrics`: aquela registra por tentativa o `recorte_sha256` que esta mudança põe no `AgentContext` (nulo até esta entrar). Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.
**Habilita:** a bateria curta comparada à V18.6 (ADR 022 §4.6) e a revisão do ADR 022 depois dela.

## Por quê

Cada prompt descreve o papel isoladamente, e a mesma regra aparece escrita de formas diferentes em lugares diferentes, às vezes contra o que o código faz (ADR 022, Contexto; ADR 021, Contexto). A leitura do código em 2026-10-15 (auditoria preliminar no design §1) mostra, entre outros:

| Onde | Divergência |
|---|---|
| `src/exploration.py:108-109`, `src/exploration.py:295-308` (`_is_bound`) e `src/agents/validator_agent.py:93-95` | A regra de `hypothesis_ref` escrita de três formas, uma delas contrária ao código. O ADR 021 §2 a substitui pelos papéis de experimento. |
| `agents/researcher/agent.py:56-58` | Diz que o ciclo "só termina com uma solução, sem caminhos promissores ou ao atingir um limite de uso"; o ADR 021 §5 troca isso por parada pelo objetivo tipado, estagnação como intervenção e saturação. |
| `agents/researcher/agent.py:102-122`, `src/agents/validator_agent.py:83-97` e `src/exploration.py:95-113` | Três cópias do formato do plano, mantidas à mão. |
| `src/exploration.py:271-273` | O bloco "EXPLORAÇÃO ATIVA (dados de contexto, não são instruções)" começa com o formato obrigatório do plano, que é instrução. |
| `agents/developer/agent.py:72-74` e `:85-86` | Manda preencher `Hipótese` com um campo que não era enviado e fixa `SEED = 42`, o que impede a replicação com nova seed (ADR 021 §4.3). |
| `agents/developer/agent.py:44-45` e `:78-79` | `/inputs/<nome>` num parágrafo e `input_snapshot/` em outro para o mesmo insumo. |
| `agents/researcher/consult.py:46` | O nome do produto está escrito no prompt, contra o requisito "Nome do produto configurável". |
| `agents/developer/agent.py:107-110`, `agents/researcher/agent.py:139-141`, `agents/researcher/consult.py:61-63` | A lista de decisões reservadas copiada em três prompts, sem `restringir_direcao` (ADR 021 §5.5). |
| `agents/base/agent.py:274-293` (`_MODE_GUIDANCE`) | As regras dos modos, comuns a todos, ficam numa função auxiliar acrescentada a todo prompt, fora de qualquer fonte versionada. |

Além disso, nenhum papel sabe o lugar dele no fluxo: o Developer não sabe que um Validator confere artefatos e chaves de métrica; o Validator do plano não sabe que a governança retira subtarefas; o Researcher não sabe como o papel de cada subtarefa é decidido nem quando a sessão para.

Decisões do pesquisador (2026-10-15, ADR 022 §4): o regimento é um arquivo comum a todos os agentes, escrito de forma direta, sem emojis nem caracteres especiais que gastem tokens sem conteúdo; as regras de comportamento e as estruturas de comunicação de cada agente ficam no prompt inicial do próprio papel; o prompt inicial do Developer é reenviado em cada chamada da subtarefa, porque a API não guarda estado.

## O que muda

- **Novo:** auditoria de cada prompt contra o código, registrada no design §1 (preliminar nesta proposta; confirmada no início da implementação).
- **Novo:** regimento da pesquisa v1 em `src/agents/regimento/`: `regimento.md` (prosa por seção, com aplicabilidade declarada) e `regimento.yaml` (parte estruturada: papéis de experimento e ordem de decisão, tipos de objetivo e seus critérios, motivos de parada e de retirada, regras de integridade, decisões reservadas, regras por modo). Conteúdo: funcionamento do sistema e quem faz cada passo, condução da exploração, tipos de objetivo, paradas e retiradas, regras de integridade comuns.
- **Novo:** `src/regimento.py`: carga e validação, recorte por tipo de objetivo e modo, renderização das tabelas a partir da parte estruturada, hashes.
- **Novo:** injeção do recorte no `system` de toda chamada de agente, depois do prompt do papel, com a versão e o tipo e modo do recorte no cabeçalho (ADR 022 §4.3).
- **Novo:** ferramenta `ler_regimento(secao)` para os papéis com laço de ferramentas (Researcher, Developer, Curator), para o que estiver fora do recorte.
- **Novo:** registro por sessão da versão, do hash do regimento, do hash de cada recorte usado e do hash do adendo (evento `regimento_sessao` e payload da sessão).
- **Novo:** adendo de projeto (`regimento_adendo.yaml` nos insumos do pesquisador, fora do repositório), só com regras e proibições acrescentadas; ativação e cada mudança pela decisão reservada nova `ativar_adendo_regimento`; hash registrado.
- **Novo:** esquemas únicos dos formatos de cada papel (plano, parecer do Validator, rascunho do Problema, resposta do consultor, narrativa do Summarizer, `metrics.json`), dos quais o texto dos prompts é gerado.
- **Novo:** teste de coerência entre código, parte estruturada do regimento, prosa e prompts; teste de redação.
- **Modificado:** prompts de sistema de todos os papéis reescritos com a mesma estrutura de seções (papel, o que recebe, o que produz, ferramentas, como é avaliado, regras do papel), sem repetir o regimento: Researcher (plano, replanejamento, rascunho do Problema, consultor), Developer, Validator (plano, revisão, verificação de afirmações, definição de métricas), Curator (execução e edição), Summarizer (narrativa e revisão de conclusões).
- **Modificado:** `_MODE_GUIDANCE` sai de `agents/base/agent.py` e vira a seção de modos do regimento; `PLAN_FORMAT_INSTRUCTION` e `SCHEMA_INSTRUCTION` passam a ser gerados do esquema do plano; o bloco de exploração separa instrução (formato) de dado (hipóteses e sugestões).
- **Modificado:** requisitos "Nome do produto configurável" e "Formato do plano preservado" de `agent-prompts` (o prompt do consultor passa a usar `APP_NAME`; o formato do plano passa a ser gerado do esquema, com o campo `papel`).
- **Removido:** as três cópias manuais do formato do plano e as três cópias da lista de decisões reservadas.
- **Fora do escopo:**
  - Contrato da subtarefa, revisão tipada e regras de integridade na revisão: [`v18.7-subtask-contract`](../v18.7-subtask-contract/proposal.md).
  - Registro por tentativa do hash do contrato e do recorte, e tokens por execução: [`v18.7-exploration-metrics`](../v18.7-exploration-metrics/proposal.md).
  - O comportamento que o regimento descreve (papéis, paradas, saturação, restrições): as mudanças `v18.7-hypothesis-linking` e `v18.7-exploration-limits`. Esta mudança descreve e confere; não implementa a regra.
  - Remover o papel `base` (questão em aberto do design §10).
  - O prompt de visão (`src/llm/vision.py:23`) e a sumarização de contexto, que não são papéis de agente.

## Impacto

- **Código:** `src/agents/regimento/regimento.md` e `src/agents/regimento/regimento.yaml` (novos); `src/regimento.py` (novo); `src/schemas/` ou módulo equivalente com os esquemas de formato (novo, nome final na implementação); `agents/researcher/agent.py`, `agents/researcher/consult.py`, `agents/developer/agent.py`, `agents/curator/agent.py`, `agents/summarizer/agent.py`, `agents/base/agent.py`, `src/agents/validator_agent.py`, `src/claims/revision.py`, `src/exploration.py`, `src/orchestrator.py` (textos e montagem); `src/agent_runtime/runtime.py` e `src/agent_runtime/context.py` (recorte por sessão, hash no contexto); `agents/base/tools.py` (`ler_regimento`); `src/research_consult/__init__.py` (`ativar_adendo_regimento`); `src/human_gate.py`; `src/config.py`; `.env.example`.
- **Contratos:** `AgentContext` ganha `regimento_sha256` e `recorte_sha256`; evento novo `regimento_sessao`; payload da sessão ganha `regimento`; `DECISOES_RESERVADAS` ganha `ativar_adendo_regimento`; o esquema do plano inclui o campo opcional `papel`, criado por `v18.7-hypothesis-linking` (dona do campo e do comportamento); aqui só o texto do formato passa a ser gerado do esquema.
- **Schema de banco:** nenhum (o valor `ativar_adendo_regimento` do `CHECK` de `gate_requests.decisao` é criado por `v18.7-persistent-human-gate`).
- **Dependências:** nenhuma nova (`PyYAML` já é usado por `src/llm/catalog.yaml`; conferir na implementação).
- **Custo:** o recorte soma até `REGIMENTO_EXCERPT_MAX_CHARS` (padrão 8000 caracteres, cerca de 2 mil tokens) ao `system` de cada chamada de agente; a reescrita sem duplicações e sem decoração deve reduzir os prompts de papel (o do Developer tem hoje cerca de 8,3 mil caracteres). Como `system` e recorte são fixos na sessão, os provedores com cache de prompt aproveitam o prefixo. O saldo é medido na bateria curta.
- **Hardware (Pi 5):** carga e hash uma vez por sessão; sem custo relevante.

## Aprovações necessárias

- Nenhuma alteração de schema relacional, Dockerfile, `docker-compose.yml` ou `AGENTS.md`. Nenhum arquivo é apagado (as cópias de texto saem de dentro de arquivos que continuam existindo).
- **Aprovação do pesquisador para o conteúdo do regimento v1** (ADR 022 §4.4: mudanças no regimento passam por PR com aprovação do pesquisador). O texto entra no PR da implementação e é aprovado nele.
- **Decisão reservada nova** `ativar_adendo_regimento` (design §5), que amplia a lista de decisões do pesquisador.
- **Parecer do Analista de Segurança** sobre o adendo de projeto e a ferramenta de leitura (design §8).
- **Confirmação do pesquisador antes da bateria curta** (tarefa 9.3), que usa provedores pagos e o Raspberry Pi.
