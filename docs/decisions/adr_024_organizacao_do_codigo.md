# ADR 024 — Organização do Código por Responsabilidade e Regra de Camadas

**Status:** Aprovado (2026-10-15)
**Data:** 2026-10-15
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.7.md`
**ADRs relacionados:** ADR 011 (troca do nome do projeto), ADR 014 (agentes em processo), ADR 019 (filtro de egresso), ADR 021, ADR 022 e ADR 023 (mudanças da V18.7 que tocam os módulos reorganizados)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 022 §4.1 | O regimento da pesquisa fica em `src/agents/regimento/`, não em `agents/regimento/`, porque o pacote `agents/` passa para dentro de `src/` (§2). |
| 021, 022, 023 | Referências a arquivo e linha nesses ADRs descrevem o código antes da reorganização; valem pela tabela de caminhos do §2, sem reescrever os ADRs. |

---

## Contexto

### Decisão do pesquisador (2026-10-15)

A raiz de `src/` tem muitos arquivos `.py` soltos; o projeto precisa ser reorganizado e reestruturado. O pesquisador concordou com a proposta do Arquiteto: reorganizar em etapas, a primeira só movendo código e a seguinte dividindo os módulos grandes dentro das mudanças da V18.7 que já mexem neles, com uma regra automática de camadas.

### Estado atual (medido em 2026-10-15)

- **Raiz de `src/` com 44 módulos e cerca de 23 mil linhas**, de seis assuntos: interface de linha de comando (`cli` e cinco `cli_*`), orquestração da pesquisa, ciclo de vida da sessão, artefatos das subtarefas, observabilidade e infraestrutura. Módulos da camada de LLM (`model_router`, `model_config`, `llm_cache`, `rate_limiter`) também estão na raiz, fora de `src/llm/`.
- **Três módulos concentram responsabilidades:** `src/autonomous_loop.py` (2.893 linhas), `src/orchestrator.py` (2.329) e `src/cli.py` (1.770), os mais alterados pela V18.7.
- **Agentes em dois lugares:** Researcher, Developer, Curator, Summarizer e a base em `agents/`, na raiz do repositório; o Validator em `src/agents/validator_agent.py`.
- **Ciclos de dependência entre pacotes.** Medindo as importações (inclusive as feitas dentro de funções) com os módulos já agrupados pela estrutura alvo, há 16 pares de pacotes que se importam mutuamente. Os principais, com a causa:

| Ciclo | Causa |
|---|---|
| `agent_runtime` ↔ `agents`, `llm`, `orchestration`; `egress`, `skills` → `agent_runtime` | O contexto da execução (`agent_runtime/context.py`, uma variável de contexto sem dependências) mora no runtime, e todos o leem; `runtime.py` usa um tipo de `orchestrator` |
| `knowledge` ↔ `orchestration` | `knowledge/hypotheses.py` e `opportunities.py` usam `human_gate`, que só depende de `logger` e `research_consult` |
| `knowledge` ↔ `session` | `knowledge/resume_context.py` usa constantes de estado de subtarefa de `continuity` e a classe `Checkpoint`, esta só em anotações |
| `knowledge` ↔ `agents` | `knowledge/ingestion.py` usa o núcleo de avaliação de critérios de métrica do Validator (`_METRIC_ALIASES`, `evaluated_metric_names`, `_metric_criteria` e o que eles usam) |
| `knowledge` ↔ `artifacts`, `skills`, `agents` | `knowledge/normalization.py` (normalização de termos, sem dependências) é usada por todos |
| `knowledge`, `embeddings`, `numeric_refs` ↔ `skills` | o processamento de documentos (`skills/document_processor`) é usado como biblioteca, não só como ferramenta de agente; ele próprio usa funções de `knowledge/ingestion*` (`insumo_tipo`, `sha256_file`), e `knowledge` usa o cliente do Qdrant de `embeddings/reindex.py` |
| `llm` ↔ `skills` | `llm/context_injection.py` usa o manifesto do espaço de trabalho (`skills/code/manifest.py`, sem dependências) |
| `egress` ↔ `llm`, `research_data` | `egress/fragments.py` (tipos dos fragmentos) é usado por todos; o gate de egresso usa a sessão e a alocação de modelos do `llm`, e o `llm` chama o gate |
| `config` ↔ `knowledge` | `config.py` importa `knowledge/ids.py` para gerar o identificador do nó |
| `cli` ↔ `orchestration`, `host` | `utils/terminal.py` é usado pela orquestração e pela verificação de infraestrutura |
| `observability` → `provenance`, `claims`, `numeric_refs` | `operation_metrics` agrega métricas desses pacotes, enquanto `telemetry` é usada por quase todos; `claims/report.py` usa `report` |

- **Caminhos calculados a partir do arquivo:** `src/cli.py:21` (`sys.path`), `src/platform_images.py:29` (raiz do projeto, usada por `scripts/setup_pi.sh`), `src/knowledge/vocabulary.py:40` (`data/vocabulary`); mover esses módulos muda o resultado sem erro de importação.
- Testes com 155 alvos de `patch`/`monkeypatch` escritos como texto apontando para módulos da raiz, e testes que afirmam caminhos de arquivo como dados (por exemplo, listas de arquivos permitidos).

### Por que agora

As 11 mudanças da V18.7 criam módulos novos (eventos de progresso, gate persistente, presença do terminal, monitor de recursos, contrato da subtarefa, regimento) e mexem nos três módulos grandes. Implementá-las sobre a estrutura atual aumenta a raiz e os ciclos; reorganizar depois custaria mais.

---

## Decisão

### 1. Etapas

1. **Etapa 1, antes de implementar a V18.7:** mover módulos inteiros e mover definições (funções, classes, constantes) de um módulo para outro **sem alterar o corpo**, ajustando importações, num PR próprio, sem mudança de comportamento. A Etapa 1 é mergeada antes de abrir a primeira worktree de código da V18.7, sem nenhuma outra branch com código Python em andamento.
2. **Etapa 2, logo depois:** resolver os ciclos que exigem mudança de lógica (§4), com testes, numa mudança própria.
3. **Etapa 3, dentro da V18.7:** cada mudança que já altera um dos módulos grandes divide-o na parte que toca (§5).

Critério de pronto da Etapa 1: a suíte `unit` e `integration` inteira passa; nos testes, só mudam caminhos de importação, alvos de `patch`/`monkeypatch` e caminhos de arquivo citados como dados, cada um conferido na revisão.

### 2. Estrutura alvo

Pacotes por responsabilidade dentro de `src/`. Ficam na raiz só os três módulos transversais, cuja mudança geraria trabalho mecânico sem ganho: `config.py` (importado por 135 arquivos), `logger.py` (144) e `db.py` (29).

| Pacote | Responsabilidade | Recebe |
|---|---|---|
| `src/cli/` | Interface de linha de comando e REPL | `cli.py` (vira `src/cli/main.py`), `cli_graph`, `cli_claims`, `cli_project`, `cli_opportunities`, `cli_provenance` (sem o prefixo `cli_`), `project_session`, `infrastructure` (verificação da infraestrutura na partida, usada só pela CLI) |
| `src/orchestration/` | Planejamento, execução e laço de pesquisa | `orchestrator`, `autonomous_loop`, `exploration`, `triage`, `plan_normalizer`, `task_scheduler`, `usage`, `unlimited_mode`, `pipeline_errors` (vira `errors.py`) |
| `src/session/` | Ciclo de vida da sessão | `session`, `resume`, `continuity`, `heartbeat`, `history` |
| `src/gate/` | Decisões reservadas ao pesquisador | `human_gate` (que o ADR 023 torna persistente) |
| `src/artifacts/` | Arquivos produzidos pelas subtarefas | `artifact_profile`, `artifact_match`, `subtask_output`, `output_manager`, `metrics_file`, `reserved_files` |
| `src/documents/` | Processamento de documentos como biblioteca | o núcleo de `skills/document_processor` (extratores, enriquecimento, indexação) e `embeddings/reindex.py`; a ferramenta de agente (`skill.py`) fica em `skills/` |
| `src/observability/` | Telemetria | `telemetry` |
| `src/report/` (existente) | Relatórios e agregações | recebe `operation_metrics` e `claims/report.py` |
| `src/host/` | Máquina | `health`, `platform_info`, `platform_images` |
| `src/llm/` (existente) | Provedores, roteamento e cache | recebe `model_router`, `model_config`, `llm_cache`, `rate_limiter` |
| `src/agents/` (existente) | Agentes e seus prompts | recebe todo o pacote `agents/` da raiz (`base`, `researcher`, `developer`, `curator`, `summarizer`); `validator_agent.py` vira `src/agents/validator/`; `prompts.py` entra aqui |
| `src/research_data/` (existente) | Insumos da pesquisa | recebe `context_loader` |
| `src/utils/` (existente) | Utilitários sem dependências do projeto | recebe o contexto da execução (`agent_runtime/context.py`), a normalização de termos (`knowledge/normalization.py`), os tipos de fragmento do egresso (`egress/fragments.py`), o manifesto do espaço de trabalho (`skills/code/manifest.py`; ajustado na spec em 2026-10-15: em `artifacts` formaria um ciclo com `llm` e `egress`), a geração do identificador do nó (de `knowledge/ids.py`) e o cliente do Qdrant de `embeddings/reindex.py` (em `utils/qdrant.py`); `terminal.py` continua aqui |

Definições movidas sem alterar o corpo, para desfazer ciclos: as constantes de estado de subtarefa de `continuity` vão para `knowledge`; o núcleo de avaliação de critérios de métrica sai de `validator_agent` para `knowledge` (junto de `metric_definition.py`); `insumo_tipo`, `sha256_file` e `MAX_HASH_BYTES` saem de `knowledge/ingestion*` para `documents`; o tipo de `orchestrator` usado por `agent_runtime/runtime.py` (`AgentResult`) vai para um módulo de tipos abaixo do runtime. Importações usadas só em anotações passam para `TYPE_CHECKING` (caso de `Checkpoint` em `knowledge/resume_context.py`). A lista exata de definições é gerada na spec por uma simulação do grafo depois das movimentações; o que a simulação mostrar que ainda forma ciclo e não se resolve assim vai para a Etapa 2 (§4).

`src/knowledge/` continua um pacote só nesta etapa: dividi-lo em subpacotes multiplica os alvos de `patch` sem que nenhuma mudança da V18.7 precise disso. A divisão é reavaliada ao fim da V18.7, já com a regra de camadas ativa. Os demais pacotes (`agent_runtime`, `egress`, `provenance`, `claims`, `numeric_refs`, `research_consult`, `embeddings`, `skills`) mudam só no que a tabela indica. O nome `host` evita confundir um subpacote `platform` com o módulo `platform` da biblioteca padrão.

A tabela completa "caminho antigo → caminho novo", arquivo por arquivo e definição por definição, fica na spec da mudança e é copiada para o roadmap da V18.7, para que as mudanças OpenSpec escritas antes da reorganização sejam lidas com os caminhos novos.

### 3. Regra de camadas, verificada automaticamente

1. **Sem ciclos entre pacotes.** Nenhum par de pacotes de `src/` se importa mutuamente, direta ou indiretamente; importações dentro de funções contam, e as feitas só para verificação de tipos (`TYPE_CHECKING`) não contam.
2. **Ordem fixa nas pontas.** De cima para baixo: `cli`; `orchestration`; `agent_runtime`; `agents`; os pacotes de domínio e serviço; e, na base, `utils`, `host`, `config`, `logger` e `db`. Nenhuma camada importa uma de cima.
3. **Ordem do meio pela medição.** A ordem entre os pacotes de domínio e serviço (`session`, `gate`, `knowledge`, `artifacts`, `documents`, `egress`, `provenance`, `claims`, `numeric_refs`, `report`, `research_data`, `research_consult`, `skills`, `llm`, `embeddings`, `observability`) é a que a medição das importações mostrar depois da Etapa 1, sem ciclos, e fica escrita no contrato da ferramenta pela spec.
4. **Verificação.** Uma ferramenta de contratos de importação (por exemplo, `import-linter`, dependência de desenvolvimento adicionada com `uv add --dev`) roda junto com o `ruff` e os testes antes de cada commit. Uma importação que viola o contrato quebra a verificação.
5. **Exceções.** Os ciclos que só se resolvem com mudança de lógica entram, com caminho e motivo, numa lista de exceções do contrato, cada um atribuído à Etapa 2. A lista fica vazia ao fim da Etapa 2.

### 4. Etapa 2: ciclos que exigem mudança de lógica

O ciclo conhecido é entre o gate de egresso e a camada de LLM: o gate usa a sessão e a alocação de modelos do `llm`, e o `llm` (`agent_loop`, `vision`, `model_router`) chama o gate. A solução (por exemplo, o `llm` recebe o gate por injeção em vez de importá-lo) é decidida na spec, com testes de que nenhum envio ao provedor deixa de passar pelo filtro (ADR 019). Outros ciclos que a medição exata da Etapa 1 revelar entram na mesma mudança.

### 5. Etapa 3: divisão dos módulos grandes dentro da V18.7

Cada divisão acontece na mudança da V18.7 que já altera aquele trecho, com o critério de um módulo por responsabilidade (não um limite de linhas). A tarefa de divisão vem antes das tarefas de comportamento novo, no `tasks.md` da própria mudança:

| Módulo | Mudança que divide | O que sai |
|---|---|---|
| `orchestration/autonomous_loop.py` | `v18.7-exploration-limits` | critérios de parada, objetivo tipado e política ao atingir o objetivo, estagnação e saturação |
| `orchestration/orchestrator.py` | `v18.7-subtask-contract` | construtores de contexto por papel e contrato da subtarefa |
| `orchestration/exploration.py` e `autonomous_loop.py` | `v18.7-hypothesis-linking` | papel do experimento e ligação a hipóteses |
| `cli/main.py` | `v18.7-background-sessions` e `v18.7-session-events-terminal` | lançamento do processo da sessão, laço do REPL, comandos de acompanhamento, exibição de eventos |
| `gate/human_gate.py` | `v18.7-persistent-human-gate` | gate persistente e pedidos ao pesquisador |

### 6. Sem caminhos antigos

Nenhum módulo de compatibilidade que reexporte o caminho antigo: as importações antigas deixam de existir no mesmo PR (sem débito técnico). O ponto de entrada passa a ser `geminiclaw = "src.cli.main:main"` em `pyproject.toml`. ADRs, specs e mudanças arquivadas não são reescritos: descrevem o código da época, e a tabela de caminhos permite lê-los.

### 7. O que é atualizado junto na Etapa 1

- importações em `src/`, `scripts/` e `tests/`; alvos de `patch`/`monkeypatch` escritos como texto, conferidos por busca textual dos caminhos antigos (não só por erro de importação);
- caminhos calculados a partir de `__file__` nos módulos movidos (`cli`, `platform_images`, e qualquer outro encontrado), com teste de que os arquivos de dados que eles apontam existem;
- `pyproject.toml` (ponto de entrada) e a reinstalação do comando com `uv sync` no Mac e no Raspberry Pi; `scripts/setup_pi.sh` e `scripts/platform_images.py`, que dependem da raiz do projeto;
- a seção de estrutura do `AGENTS.md` (§7) e do `README.md`, e os caminhos citados nas regras e workflows de `.agents/`;
- `openspec/project.md` e `openspec/specs/` (verdade atual) onde citam caminhos de módulo;
- o roadmap da V18.7, com a tabela de caminhos.

### 8. Aprovações necessárias

- **Alteração do `AGENTS.md`** (seção de estrutura do projeto), que exige aprovação explícita (AGENTS.md §8).
- **Remoção do pacote `agents/` da raiz** e dos módulos movidos (movidos com `git mv`, preservando o histórico, mas os caminhos antigos deixam de existir).
- **Nova dependência de desenvolvimento** para a regra de camadas.

Não há alteração de schema de banco, Dockerfile ou `docker-compose.yml`: o sandbox não copia `src/` nem `agents/`.

---

## Consideradas e Rejeitadas

### A. Reorganizar e dividir tudo de uma vez
**Rejeitada:** mistura mudança de lugar com mudança de lógica; um defeito na divisão fica escondido no volume de movimentações.

### B. Manter a estrutura atual
**Rejeitada:** a V18.7 acrescenta módulos e responsabilidades exatamente onde a estrutura já está confusa, e os ciclos continuariam crescendo.

### C. Reorganizar depois da V18.7
**Rejeitada:** reorganiza mais código, com mais conflito, e a V18.7 seria escrita sobre a raiz atual.

### D. Módulos de compatibilidade nos caminhos antigos
**Rejeitada:** viram débito técnico permanente e escondem quem ainda usa o caminho antigo; um alvo de `patch` que continua válido por reexportação vira um mock silencioso.

### E. Mover também `config`, `logger` e `db`
**Rejeitada:** são transversais, estão na camada base e já têm lugar claro; mover só gera alteração em mais de 150 arquivos.

### F. Trazer o Validator para `agents/` na raiz, em vez de levar `agents/` para `src/`
**Rejeitada:** manteria dois pacotes de código Python de primeiro nível com importações nos dois sentidos.

### G. Trocar o nome do pacote junto (ADR 011)
**Não adotada agora:** o novo nome do projeto ainda não foi escolhido; fica para quando for decidido.

### H. Limite de linhas por módulo
**Rejeitada:** um número fixo divide arquivos coesos e não impede módulos com várias responsabilidades abaixo dele.

### I. Ordem completa das camadas fixada neste ADR
Seis camadas com todos os pacotes posicionados. **Rejeitada na revisão:** a medição mostrou que a ordem proposta seria violada em cerca de 40 importações no primeiro dia; a ordem do meio sai da medição depois das movimentações (§3.3).

### J. Dividir `src/knowledge/` em subpacotes na Etapa 1
**Adiada na revisão:** multiplica os alvos de `patch` sem necessidade da V18.7; reavaliada ao fim da etapa.

---

## Consequências

### Positivas
- Cada assunto tem um lugar; um módulo novo da V18.7 entra no pacote do seu assunto.
- Os ciclos entre pacotes desaparecem, e a regra de camadas impede que voltem.
- Os agentes ficam num só pacote, e o regimento da pesquisa (ADR 022) fica junto deles.
- Os módulos grandes diminuem onde já seriam alterados, com testes.

### Negativas / Trade-offs
- Um PR grande de movimentação, que exige não haver outra branch de código aberta.
- Referências a arquivo e linha em ADRs, specs e mudanças arquivadas passam a apontar para caminhos antigos; a tabela de caminhos compensa.
- O histórico de um arquivo movido exige `git log --follow`.
- Quem tiver o comando `geminiclaw` instalado precisa rodar `uv sync` depois da Etapa 1.

---

## Casos de verificação

| # | Caso | Como verificar |
|---|---|---|
| 1 | Etapa 1 não muda comportamento | Suíte `unit` e `integration` inteira verde; o diff dos testes só altera caminhos de importação, alvos de `patch` e caminhos citados como dados |
| 2 | Nenhum caminho antigo sobrevive | Busca textual pelos caminhos antigos (`src.<módulo antigo>`, `agents.`) em `src/`, `scripts/`, `tests/` e `.agents/` não encontra nada; a raiz de `src/` só tem `__init__.py`, `config.py`, `logger.py` e `db.py` |
| 3 | Arquivos de dados continuam acessíveis | Testes conferem que os caminhos calculados a partir de `__file__` (vocabulário, manifesto de imagens, catálogo) apontam para arquivos existentes |
| 4 | Regra de camadas ativa | A verificação passa; uma importação proibida de teste (por exemplo, `knowledge` importando `orchestration`) faz a verificação falhar |
| 5 | Ponto de entrada | `uv run geminiclaw --help` funciona no Mac e no Raspberry Pi depois de `uv sync`; `scripts/setup_pi.sh` encontra `containers/images.yaml` |
| 6 | Exceções esvaziam | Ao fim da Etapa 2, a lista de exceções do contrato está vazia, e o filtro de egresso continua cobrindo todo envio ao provedor |

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.7-source-layout` | `project-structure` (nova) | §1 (Etapa 1), §2, §3, §6–§8: movimentações, tabela de caminhos, regra de camadas e sua verificação, lista inicial de exceções, atualização de `pyproject.toml`, `AGENTS.md`, `README.md`, `.agents/`, `openspec/` e scripts do Pi |
| `v18.7-layer-cycles` | `project-structure`, `data-egress`, `llm-providers` | §4 (Etapa 2): ciclos que exigem mudança de lógica, a começar pelo gate de egresso e o `llm` |
| `v18.7-exploration-limits`, `v18.7-subtask-contract`, `v18.7-hypothesis-linking`, `v18.7-background-sessions`, `v18.7-session-events-terminal`, `v18.7-persistent-human-gate` | (as próprias) | §5 (Etapa 3): tarefa de divisão do módulo grande antes do comportamento novo |

---

## Revisão

Revisar ao fim da V18.7: a lista de exceções está vazia, os módulos novos entraram nos pacotes certos, nenhum módulo voltou a acumular responsabilidades, e se `src/knowledge/` precisa ser dividido.
