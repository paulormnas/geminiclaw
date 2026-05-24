# Roadmap V14 — Reestruturação de Agentes, Model Router e Ciclo de Vida de Containers

**Contexto:** As etapas V12 e V13 resolvem falhas de cache, resiliência do loop ReAct e persistência de contexto no sandbox. Mesmo com essas correções, o sistema tem um problema arquitetural mais profundo: os papéis dos agentes estão mal distribuídos. O `base_agent` acumula routing e execução de código. O Planner, Validator e Reviewer são chamadas LLM avulsas embutidas no `autonomous_loop.py`, sem identidade própria, sem consistência garantida e gerando containers desnecessários. O `researcher_agent` tem skills de busca web que não estão sendo acionadas corretamente. Todos os agentes usam o mesmo modelo, independentemente do tipo de tarefa.

**Objetivo:** Consolidar o sistema em quatro papéis claros alinhados ao propósito de assistente de pesquisa científica — Orchestrator, Researcher Agent, Validator Agent e Developer Agent — com seleção de modelo estática por papel e ciclo de vida de containers atrelado à sessão do usuário.

**Dependências:** V10 (sandbox DinD, sessões), V11 (telemetria), V12 (cache, resiliência, circuit breaker), V13 (manifest, volume compartilhado, session_id consistente). O Model Router (V14.1) é pré-requisito para todas as demais etapas deste roadmap.

**Relatório de referência:** `pipeline_failure_analysis.md` e `execution_analysis_report.md` — evidências de 7 tentativas do Planner, Validator inconsistente, base_agent gerando "Curso de Data Science" após perda de foco, e researcher_agent com web skills não utilizadas.

---

## Diagnóstico Consolidado

### D1 — Todos os Agentes Usam o Mesmo Modelo (CAUSA RAIZ DE CUSTO E QUALIDADE)

**Problema:** Uma única variável `DEFAULT_MODEL` é consumida por Planner, Validator, Reviewer, base_agent e researcher_agent. Isso força um tradeoff impossível: um modelo local pequeno (qwen3.5:4b) é insuficiente para planejamento e geração de código; um modelo remoto pesado para checklist de validação é desperdício de API.

**Impacto:** O Planner precisou de 7 tentativas porque o modelo local não tinha capacidade de decomposição adequada. O base_agent perdeu o foco e gerou conteúdo genérico porque o modelo não tinha janela de contexto suficiente para tarefas de código complexas.

---

### D2 — Planner, Validator e Reviewer São Funções Disfarçadas de Agentes

**Problema:** Planner, Validator e Reviewer são chamadas LLM com prompts específicos embutidas no `autonomous_loop.py`, não agentes com identidade, ciclo de vida e responsabilidades definidas. Cada chamada gera um container Docker separado apesar de não executarem código arbitrário — apenas fazem chamadas ao LLM e manipulam JSON. Na execução analisada, isso gerou ~15 containers só na fase de planejamento e validação.

**Impacto:** Overhead de container desnecessário no Raspberry Pi. Validator inconsistente (sem identidade de agente, o comportamento varia entre chamadas). Impossibilidade de executar Planner e Validator concorrentemente com outras tarefas administrativas do orquestrador.

---

### D3 — base_agent Acumula Responsabilidades Incompatíveis

**Problema:** O `agents/base/agent.py` realiza simultaneamente: (a) recebimento e interpretação da subtarefa via IPC, (b) decisão sobre qual ferramenta invocar (routing), e (c) execução de código via `python_interpreter`. Essas responsabilidades têm perfis completamente diferentes de modelo, contexto e ciclo de vida. O resultado é um agente que tenta ser tudo e consequentemente falha em todas as frentes quando a tarefa é complexa.

**Impacto:** Impossível otimizar modelo por responsabilidade. O agente que deveria ter sessão longa (código) e o que deveria ser leve (routing) têm o mesmo ciclo de vida e o mesmo modelo.

---

### D4 — researcher_agent com Web Skills Não Utilizadas Corretamente

**Problema:** O `researcher_agent` possui skills de busca web disponíveis, mas o agente não as aciona de forma eficaz — ou porque o system prompt não instrui a estratégia correta de uso (search-first, não URL-first), ou porque o papel do pesquisador não está integrado ao pipeline principal de planejamento. A lógica de decomposição de tarefas (Planner) e a de pesquisa científica (researcher) estão separadas quando deveriam ser o mesmo agente.

**Impacto:** O Planner gera planos sem contexto científico do domínio. O researcher_agent não é chamado para informar o planejamento. Web search é subutilizado.

---

### D5 — Container Criado e Destruído a Cada Subtarefa ou Retry

**Problema:** O `base_agent` é instanciado como container novo a cada subtarefa e destruído ao terminar. Isso descarta o histórico de execução em memória, força reconstrução de contexto a cada chamada, e gera overhead de startup recorrente. O container do agente de código deveria persistir durante toda a sessão do usuário, recebendo novas subtarefas via IPC.

**Impacto:** Perda de contexto entre subtarefas (problema parcialmente endereçado pelo manifest no V13, mas a raiz é o ciclo de vida efêmero). Latência adicionada por startup de container a cada subtarefa.

---

## Nova Arquitetura de Agentes

```
CLI (sessão do usuário)
│
│  inicia/encerra via comando explícito
│
└── ORCHESTRATOR (src/autonomous_loop.py — processo Python, sem LLM)
    │  Coordenação pura: routing, IPC, retry, circuit breaker,
    │  session management, ciclo de vida de containers.
    │  Planner/Validator/Reviewer viram corrotinas async aqui.
    │
    ├── RESEARCHER AGENT (container por sessão — modelo remoto)
    │   Absorve: Planner atual + researcher_agent atual
    │   Responsabilidades:
    │   • Decomposição da tarefa em subtarefas (DAG)
    │   • Busca em literatura e web para informar o plano
    │   • Síntese de fontes científicas
    │   • Replanejamento baseado em resultados parciais
    │   Modelo: Remoto pesado (Gemini Flash ou similar)
    │
    ├── VALIDATOR AGENT (corrotina async no processo — modelo local)
    │   Absorve: Validator atual + Reviewer atual
    │   Responsabilidades:
    │   • Validação do plano contra schema (antes da execução)
    │   • Avaliação dos resultados de cada subtarefa (após execução)
    │   • Verificação de artefatos em disco, não apenas response.text
    │   Modelo: Local leve (qwen3:8b) — julgamento estruturado,
    │            output curto, sem criatividade necessária
    │
    └── DEVELOPER AGENT (container por sessão — modelo remoto)
        Absorve: base_agent (parte de execução de código)
        Responsabilidades:
        • Geração e correção incremental de código
        • Integração com PythonSandbox e manifest (V13)
        • Manutenção do histórico de código em memória entre subtarefas
        Modelo: Remoto pesado (Gemini Flash ou similar)
```

**O que desaparece:**
- `agents/base/agent.py` — substituído pelo Developer Agent
- Planner como entidade interna do loop — absorvido pelo Researcher Agent
- Reviewer como chamada avulsa — absorvido pelo Validator Agent
- Containers para Validator — passa a ser corrotina no processo principal

---

## Etapas de Implementação

### Etapa V14.1 — Model Router: Seleção Estática de Modelo por Papel (Prioridade: CRÍTICA)

**Objetivo:** Introduzir uma camada de configuração que mapeia papel de agente para modelo específico, substituindo a variável `DEFAULT_MODEL` global. Pré-requisito para todas as demais etapas.

#### Tarefas:

- [ ] **V14.1.1 — Definir schema de configuração de modelos por papel.**
  Criar o arquivo `src/model_config.py` (ou seção dedicada em `src/config.py`) com o mapeamento estático de papel para provider e modelo.
  - **Arquivo:** `src/model_config.py` (novo arquivo).
  - **Schema proposto:**
    ```python
    MODEL_CONFIG: dict[str, dict] = {
        "researcher": {
            "provider": os.getenv("RESEARCHER_PROVIDER", "gemini"),
            "model":    os.getenv("RESEARCHER_MODEL", "gemini-2.0-flash"),
        },
        "validator": {
            "provider": os.getenv("VALIDATOR_PROVIDER", "ollama"),
            "model":    os.getenv("VALIDATOR_MODEL", "qwen3:8b"),
        },
        "developer": {
            "provider": os.getenv("DEVELOPER_PROVIDER", "gemini"),
            "model":    os.getenv("DEVELOPER_MODEL", "gemini-2.0-flash"),
        },
    }

    def get_model_config(role: str) -> dict:
        if role not in MODEL_CONFIG:
            raise ValueError(f"Papel desconhecido: '{role}'. Papéis válidos: {list(MODEL_CONFIG)}")
        return MODEL_CONFIG[role]
    ```
  - **Variáveis de ambiente correspondentes em `.env`:**
    ```
    RESEARCHER_PROVIDER=gemini
    RESEARCHER_MODEL=gemini-2.0-flash
    VALIDATOR_PROVIDER=ollama
    VALIDATOR_MODEL=qwen3:8b
    DEVELOPER_PROVIDER=gemini
    DEVELOPER_MODEL=gemini-2.0-flash
    # Fallback global mantido para compatibilidade retroativa
    DEFAULT_MODEL=qwen3:8b
    DEFAULT_PROVIDER=ollama
    ```

- [ ] **V14.1.2 — Criar `ModelRouter` para resolução de provider por papel.**
  Implementar a classe responsável por instanciar o provider LLM correto dado um papel. Deve suportar os providers já existentes no projeto (Ollama, Gemini, Anthropic) e ser extensível para novos.
  - **Arquivo:** `src/model_router.py` (novo arquivo).
  - **Interface pública:**
    ```python
    class ModelRouter:
        def get_provider(self, role: str) -> BaseLLMProvider:
            """Retorna provider instanciado para o papel dado."""
            config = get_model_config(role)
            return self._build_provider(config["provider"], config["model"])

        def _build_provider(self, provider_name: str, model: str) -> BaseLLMProvider:
            """Factory de providers. Adicionar novo provider aqui."""
            ...
    ```
  - **Singleton:** O `ModelRouter` deve ser instanciado uma vez no `autonomous_loop.py` e passado por injeção de dependência para os agentes que precisam dele. Não usar importação global.

- [ ] **V14.1.3 — Substituir referências a `DEFAULT_MODEL` nos agentes existentes.**
  Atualizar `agents/base/agent.py` e `agents/researcher/agent.py` para receber o provider via injeção em vez de ler `DEFAULT_MODEL` diretamente. Manter compatibilidade: se nenhum papel for especificado, usar o fallback global.
  - **Arquivos:** `agents/base/agent.py`, `agents/researcher/agent.py`, `src/orchestrator.py`.

- [ ] **V14.1.4 — Testes unitários para o Model Router.**
  - **Arquivo:** `tests/unit/test_model_router.py`
  - Cenário 1: `get_provider("researcher")` retorna provider Gemini com modelo correto.
  - Cenário 2: `get_provider("validator")` retorna provider Ollama com modelo correto.
  - Cenário 3: `get_provider("papel_inexistente")` levanta `ValueError` com mensagem clara.
  - Cenário 4: Variável de ambiente `RESEARCHER_MODEL` sobrescreve o default corretamente.

---

### Etapa V14.2 — Orchestrator: Validator como Corrotina Async (Prioridade: ALTA)

**Objetivo:** Extrair as chamadas LLM de Validator e Reviewer do interior dos containers para corrotinas assíncronas no processo principal do Orchestrator, eliminando containers desnecessários para papéis que não executam código arbitrário.

**Nota:** O Planner é extraído junto com o Researcher Agent na V14.3, pois os dois são consolidados. Esta etapa foca exclusivamente no Validator e no Reviewer.

#### Tarefas:

- [ ] **V14.2.1 — Identificar e isolar o código de Validator e Reviewer no `autonomous_loop.py`.**
  Mapear todos os pontos onde o `autonomous_loop.py` faz chamadas LLM para validação de plano e revisão de resultados. Extrair para métodos privados claramente delimitados como preparação para a refatoração.
  - **Arquivo:** `src/autonomous_loop.py`.
  - **Entregável:** Docstring em cada método extraído descrevendo: input esperado, output esperado, e qual provider LLM usa atualmente.

- [ ] **V14.2.2 — Criar `ValidatorAgent` como classe async no processo principal.**
  Implementar `src/agents/validator_agent.py` com a lógica de validação de plano e revisão de resultados como métodos assíncronos, sem container Docker.
  - **Arquivo:** `src/agents/validator_agent.py` (novo arquivo).
  - **Interface pública:**
    ```python
    class ValidatorAgent:
        def __init__(self, model_router: ModelRouter): ...

        async def validate_plan(self, plan: dict) -> ValidationResult:
            """
            Valida o plano JSON do Researcher contra o schema esperado.
            Retorna: ValidationResult(status, issues, approved_plan)
            """
            ...

        async def review_result(
            self,
            task: SubTask,
            response_text: str,
            artifacts_on_disk: list[str]
        ) -> ReviewResult:
            """
            Avalia o resultado de uma subtarefa.
            Considera tanto response_text quanto artefatos em disco.
            Retorna: ReviewResult(status, issues, partial_artifacts_valid)
            """
            ...
    ```
  - **Uso do Model Router:** `self.provider = model_router.get_provider("validator")`.
  - **Determinismo:** O system prompt do ValidatorAgent deve incluir o schema JSON exato esperado para aprovação, eliminando a inconsistência observada no Validator atual.

- [ ] **V14.2.3 — Atualizar `autonomous_loop.py` para usar `ValidatorAgent`.**
  Substituir as chamadas LLM avulsas de validação e revisão pelas chamadas ao `ValidatorAgent`. O loop principal passa a `await validator.validate_plan(plan)` e `await validator.review_result(task, response, artifacts)`.
  - **Arquivo:** `src/autonomous_loop.py`.
  - **Ganho de concorrência:** Como o ValidatorAgent é uma corrotina, o Orchestrator pode executar outras tarefas administrativas (atualizar estado da sessão, preparar contexto do próximo agente) enquanto aguarda a resposta do LLM local.

- [ ] **V14.2.4 — Schema de validação explícito no ValidatorAgent.**
  O ValidatorAgent deve ter o schema de plano válido embutido no system prompt, não apenas instruções em linguagem natural. Isso resolve a inconsistência identificada no relatório (Validator aprovou plano sem `validation_criteria` na segunda revisão).
  - **Arquivo:** `src/agents/validator_agent.py`.
  - **Schema embutido no prompt:**
    ```
    Um plano válido DEVE conter exatamente estes campos em cada subtarefa:
    - task_name (string, único no plano)
    - agent_id (string, um de: researcher, developer)
    - prompt (string, não vazio)
    - depends_on (lista, pode ser vazia)
    - expected_artifacts (lista com ao menos 1 item)
    - validation_criteria (lista com ao menos 1 critério mensurável)

    Se QUALQUER subtarefa violar um desses requisitos, o plano é REJEITADO.
    Responda APENAS com JSON: {"approved": true/false, "issues": [...]}
    ```

- [ ] **V14.2.5 — Testes unitários e de integração para `ValidatorAgent`.**
  - **Arquivo:** `tests/unit/agents/test_validator_agent.py`
  - Cenário 1: Plano com todas as chaves obrigatórias → `approved: true`.
  - Cenário 2: Plano sem `validation_criteria` em uma subtarefa → `approved: false` com issue descritivo.
  - Cenário 3: `review_result` com artefatos esperados em disco mas `response_text` vazio → aprovação parcial com `partial_artifacts_valid: true`.
  - Cenário 4: `review_result` sem artefatos e response_text genérico → reprovação com issues.

---

### Etapa V14.3 — Researcher Agent: Absorção do Planner e Correção de Web Skills (Prioridade: ALTA)

**Objetivo:** Consolidar o `researcher_agent` existente com a lógica de planejamento (Planner atual), tornando o Researcher o agente responsável por decompor tarefas em subtarefas E por buscar contexto científico para informar essa decomposição. Corrigir a integração com as web skills existentes.

#### Tarefas:

- [ ] **V14.3.1 — Migrar lógica de geração de plano do `autonomous_loop.py` para o Researcher Agent.**
  O Planner atual é uma chamada LLM com prompt específico dentro do loop. Esse prompt e a lógica de construção do DAG devem ser movidos para o `agents/researcher/agent.py`, que passa a ser o único responsável por produzir o plano de execução.
  - **Arquivo:** `agents/researcher/agent.py` — adicionar método `async def plan(self, task: str, context: dict) -> ExecutionPlan`.
  - **Arquivo:** `src/autonomous_loop.py` — substituir chamada direta ao Planner por `await researcher.plan(task, context)` via IPC.
  - **Contrato do método `plan`:**
    ```python
    async def plan(self, task: str, context: dict) -> ExecutionPlan:
        """
        Recebe a tarefa original e contexto (histórico de sessão, memória de longo prazo).
        Opcionalmente busca literatura/web para informar o plano antes de decompor.
        Retorna ExecutionPlan com lista de SubTask e grafo de dependências.
        """
    ```

- [ ] **V14.3.2 — Integrar busca web ao fluxo de planejamento.**
  O Researcher deve, antes de gerar o plano, usar as web skills para contextualizar a tarefa quando o domínio for científico ou técnico. A decisão de buscar ou não deve ser do próprio agente, instruída pelo system prompt.
  - **Arquivo:** `agents/researcher/agent.py` — system prompt.
  - **Instrução adicionada ao system prompt:**
    ```
    FLUXO DE PLANEJAMENTO:
    1. Analise a tarefa recebida e identifique o domínio científico/técnico.
    2. Se o domínio requer contexto especializado (metodologias, datasets, métricas),
       use a ferramenta 'web_search' para buscar referências relevantes ANTES de planejar.
       Consulte ao menos 2 fontes para tarefas de domínio não familiar.
    3. Use as informações coletadas para informar a decomposição em subtarefas.
    4. Gere o plano em formato JSON seguindo o schema fornecido.

    REGRAS DE BUSCA:
    - Use 'web_search' com termos técnicos específicos, nunca URLs inventadas.
    - Use 'web_reader' apenas para URLs retornadas pelo 'web_search'.
    - Nunca invente referências ou assuma conhecimento sem verificar.
    ```

- [ ] **V14.3.3 — Corrigir integração das web skills no researcher_agent.**
  Diagnosticar por que as web skills não estão sendo acionadas corretamente pelo `researcher_agent` atual. Verificar: (a) se as ferramentas estão registradas no `openai_tools` do agente, (b) se o system prompt instrui quando e como usá-las, (c) se há conflito com a estratégia URL-first identificada no V12.4.
  - **Arquivo:** `agents/researcher/agent.py` — verificar registro de tools e system prompt.
  - **Arquivo:** `src/skills/web_reader/skill.py` — garantir que as correções de V12.4 (schema validation, robots.txt 404) estejam aplicadas.
  - **Entregável:** Teste de smoke com tarefa de domínio técnico verificando que `web_search` é chamado antes de `web_reader`.

- [ ] **V14.3.4 — Adicionar capacidade de replanejamento baseado em resultados.**
  O Researcher deve ser capaz de receber, via IPC, um sinal do Orchestrator indicando que uma subtarefa falhou e o motivo, e produzir um plano revisado que incorpora esse aprendizado.
  - **Arquivo:** `agents/researcher/agent.py` — adicionar método `async def replan(self, original_plan: ExecutionPlan, failed_tasks: list[FailedTask], artifacts_available: list[str]) -> ExecutionPlan`.
  - **Diferença para o `plan` original:** O `replan` recebe o histórico de falhas e os artefatos já produzidos. O prompt de replanejamento instrui o agente a não redefinir subtarefas já concluídas com sucesso e a focar na causa da falha.
  - **Integração:** O `autonomous_loop.py` chama `replan` em vez de `plan` quando o circuit breaker detecta falha sem progresso, substituindo o re-planejamento genérico atual.

- [ ] **V14.3.5 — Atualizar `ContainerRunner` para o ciclo de vida do Researcher.**
  O Researcher Agent passa a ter container por sessão (não por chamada de planejamento). O container sobe uma vez no início do pipeline e recebe chamadas de `plan` e `replan` via IPC ao longo da sessão.
  - **Arquivo:** `src/runner.py` — adicionar suporte a container com ciclo de vida de sessão para o Researcher.
  - **Detalhes:** Ver V14.5 (Developer Agent) para a implementação completa do padrão de container por sessão, que é compartilhado.

- [ ] **V14.3.6 — Testes de integração para o Researcher Agent.**
  - **Arquivo:** `tests/integration/agents/test_researcher_agent.py`
  - Cenário 1: Tarefa de ML → agente chama `web_search` antes de gerar plano.
  - Cenário 2: Plano gerado contém `validation_criteria` em todas as subtarefas.
  - Cenário 3: `replan` com 1 subtarefa falha → novo plano não redefine subtarefas já concluídas.
  - Cenário 4: URL retornada por `web_search` é lida corretamente por `web_reader`.

---

### Etapa V14.4 — Developer Agent: Separação do base_agent (Prioridade: ALTA)

**Objetivo:** Criar o `developer_agent` como entidade separada do `base_agent`, com responsabilidade exclusiva de geração e correção incremental de código. O `base_agent` é descontinuado; sua lógica de routing é absorvida pelo Orchestrator.

#### Tarefas:

- [ ] **V14.4.1 — Criar `agents/developer/agent.py` a partir do base_agent.**
  O Developer Agent é construído sobre o `agent_loop.py` existente (ReAct loop com tool calls), mas com system prompt focado exclusivamente em geração de código, integração com o manifest do V13, e sem lógica de routing ou coordenação.
  - **Arquivo:** `agents/developer/agent.py` (novo arquivo).
  - **System prompt central:**
    ```
    Você é um desenvolvedor especializado em implementar soluções de código para
    pesquisa científica. Sua única responsabilidade é escrever, executar e corrigir
    código Python de forma incremental.

    PRINCÍPIOS:
    - Sempre leia o [CONTEXTO DO WORKSPACE] antes de escrever qualquer código.
    - Nunca reescreva código que já funciona. Corrija apenas o que falhou.
    - Salve todos os artefatos em /outputs/ (já montado).
    - Documente cada função com docstring descrevendo input, output e propósito científico.
    - Se um erro ocorrer 3 vezes com a mesma abordagem, mude completamente de estratégia.

    FERRAMENTAS DISPONÍVEIS: python_interpreter, web_search (para documentação técnica).
    NÃO use web_search para busca científica — isso é responsabilidade do Researcher.
    ```
  - **Injeção de contexto do manifest:** O Developer Agent recebe o bloco de contexto do manifest (V13.4) automaticamente antes de cada chamada ao LLM, via `agent_loop.py`.

- [ ] **V14.4.2 — Remover lógica de routing do base_agent e absorver no Orchestrator.**
  Identificar todo o código do `base_agent` que decide qual agente ou ferramenta invocar para uma subtarefa e movê-lo para o `autonomous_loop.py`. O Orchestrator passa a ser o único responsável por mapear `agent_id` da subtarefa para o container/corrotina correto.
  - **Arquivo:** `agents/base/agent.py` — identificar e extrair lógica de routing.
  - **Arquivo:** `src/autonomous_loop.py` — adicionar método `_dispatch_subtask(task: SubTask) -> AgentResult` que redireciona para `developer_agent`, `researcher_agent` ou `validator_agent` com base em `task.agent_id`.
  - **Mapping proposto:**
    ```python
    AGENT_DISPATCH = {
        "developer": self._ipc_send(developer_container, task),
        "researcher": self._ipc_send(researcher_container, task),
        # Validator não recebe subtarefas — só valida plano e resultados
    }
    ```

- [ ] **V14.4.3 — Criar Dockerfile para o Developer Agent.**
  O Developer Agent tem dependências diferentes do base_agent: precisa de um ambiente Python científico completo (numpy, pandas, scikit-learn, matplotlib) pré-instalado no container, evitando `pip install` em runtime a cada execução.
  - **Arquivo:** `containers/developer/Dockerfile` (novo arquivo).
  - **Base image:** Python 3.12-slim com dependências científicas comuns pré-instaladas.
  - **Packages pré-instalados:** `numpy`, `pandas`, `scikit-learn`, `matplotlib`, `seaborn`, `scipy`, `jupyter` (para geração de notebooks se necessário).
  - **Nota:** O PythonSandbox (V13) continua sendo o ambiente de execução de código — o Developer Agent apenas gera e corrige o código. As dependências científicas devem estar tanto no container do Developer quanto no container do Sandbox.

- [ ] **V14.4.4 — Deprecar `agents/base/agent.py`.**
  Após V14.4.1 e V14.4.2 validados por testes, marcar `base_agent` como deprecated e remover na próxima versão. Manter temporariamente para compatibilidade retroativa com testes existentes.
  - **Arquivo:** `agents/base/agent.py` — adicionar docstring `# DEPRECATED: use developer_agent. Será removido na V15.`

- [ ] **V14.4.5 — Testes de integração para o Developer Agent.**
  - **Arquivo:** `tests/integration/agents/test_developer_agent.py`
  - Cenário 1: Subtarefa de código recebida via IPC → agente lê manifest antes de gerar código.
  - Cenário 2: Erro na tool call anterior presente no manifest → agente corrige especificamente o erro sem reescrever o script inteiro.
  - Cenário 3: Subtarefa de pesquisa recebida via IPC → erro claro ("use o researcher_agent para pesquisa").
  - Cenário 4: 3 erros consecutivos do mesmo tipo → agente muda de estratégia (V12.2.1).

---

### Etapa V14.5 — Ciclo de Vida de Container por Sessão (Prioridade: MÉDIA)

**Objetivo:** Implementar o padrão de container por sessão para Researcher Agent e Developer Agent: um único container por papel sobe no início do pipeline e permanece ativo recebendo subtarefas via IPC até que o usuário encerre a sessão pelo CLI.

#### Tarefas:

- [ ] **V14.5.1 — Implementar `SessionContainerRunner` no `src/runner.py`.**
  Criar uma classe que gerencia containers de longa duração, diferente do `ContainerRunner` atual que cria containers efêmeros. O `SessionContainerRunner` sobe o container, verifica saúde via health check, e mantém a referência ativa durante toda a sessão.
  - **Arquivo:** `src/runner.py` — adicionar classe `SessionContainerRunner`.
  - **Interface pública:**
    ```python
    class SessionContainerRunner:
        async def start(self, role: str, session_id: str, env: dict) -> ContainerHandle:
            """Sobe o container do agente e aguarda estar pronto via health check."""

        async def send(self, handle: ContainerHandle, message: IPCMessage) -> IPCMessage:
            """Envia mensagem via IPC e aguarda resposta."""

        async def stop(self, handle: ContainerHandle, graceful_timeout: int = 10) -> None:
            """Envia shutdown via IPC, aguarda encerramento limpo, força stop após timeout."""

        async def is_alive(self, handle: ContainerHandle) -> bool:
            """Verifica saúde do container. Usado pelo health monitor."""
    ```

- [ ] **V14.5.2 — Implementar health check e recuperação de container morto.**
  O Orchestrator deve detectar quando um container de sessão morreu (OOM no Raspberry Pi, por exemplo) e reiniciá-lo com contexto reconstituído do manifest e da memória de curto prazo.
  - **Arquivo:** `src/autonomous_loop.py` — adicionar `_health_monitor` como task asyncio periódica.
  - **Frequência:** Verificação a cada 30 segundos via `is_alive()`.
  - **Recuperação:** Se container morto detectado durante execução de subtarefa:
    1. Registrar evento na sessão com timestamp e motivo (OOM, crash).
    2. Subir novo container via `SessionContainerRunner.start()`.
    3. Injetar contexto do manifest + histórico de erros no primeiro IPC.
    4. Reenviar a subtarefa que estava em execução.
  - **Limite de recuperações:** Máximo 2 recuperações automáticas por subtarefa. Se exceder, marcar subtarefa como falha com diagnóstico e acionar circuit breaker.

- [ ] **V14.5.3 — Protocolo de shutdown graceful via IPC.**
  O container de sessão não deve ser derrubado com `docker stop` diretamente enquanto processa uma subtarefa. Implementar handshake de shutdown: Orchestrator envia `{"type": "shutdown"}` via IPC, container confirma com `{"type": "shutdown_ack", "current_task_status": "completed"|"aborted"}` e encerra o processo Python limpo.
  - **Arquivo:** `agents/researcher/agent.py` e `agents/developer/agent.py` — handler para mensagem de tipo `"shutdown"`.
  - **Arquivo:** `src/runner.py` — `stop()` aguarda `shutdown_ack` por `graceful_timeout` segundos antes de forçar `docker stop`.

- [ ] **V14.5.4 — Integrar `SessionContainerRunner` ao `autonomous_loop.py`.**
  O Orchestrator deve subir os containers de Researcher e Developer no início do pipeline (antes de enviar a primeira tarefa) e mantê-los referenciados durante toda a sessão.
  - **Arquivo:** `src/autonomous_loop.py` — método `_initialize_session_containers(session_id)` chamado no início de `_run_complex_path`.
  - **Estado mantido:**
    ```python
    self._session_containers: dict[str, ContainerHandle] = {
        "researcher": researcher_handle,
        "developer": developer_handle,
    }
    ```

- [ ] **V14.5.5 — Testes de integração para o ciclo de vida por sessão.**
  - **Arquivo:** `tests/integration/test_session_container_lifecycle.py`
  - Cenário 1: Container sobe no início do pipeline e permanece ativo entre 3 subtarefas consecutivas.
  - Cenário 2: Shutdown graceful via IPC — container confirma `shutdown_ack` e encerra limpo.
  - Cenário 3: Simulação de morte de container (SIGKILL) → Orchestrator detecta via health check e reinicia com contexto do manifest.
  - Cenário 4: 3 mortes consecutivas do mesmo container → circuit breaker ativado com diagnóstico.

---

### Etapa V14.6 — Comando CLI para Gerenciamento de Containers de Sessão (Prioridade: MÉDIA)

**Objetivo:** Adicionar ao CLI um comando para listar containers ativos do projeto e encerrá-los. O usuário tem controle explícito sobre o ciclo de vida — containers não são destruídos automaticamente entre tarefas, mas são encerrados quando o usuário decide finalizar a sessão.

#### Tarefas:

- [ ] **V14.6.1 — Implementar comando `sessions` no CLI.**
  Adicionar subcomando que lista sessões ativas com seus containers correspondentes.
  - **Arquivo:** `src/cli.py` (ou equivalente).
  - **Output esperado:**
    ```
    $ geminiclaw sessions

    Sessões ativas:
    ┌─────────────────────────────────┬────────────┬──────────────┬────────┐
    │ Session ID                      │ Tarefa     │ Containers   │ Status │
    ├─────────────────────────────────┼────────────┼──────────────┼────────┤
    │ 20260514_173741_iris_pipeline   │ Iris ML    │ researcher   │ idle   │
    │                                 │            │ developer    │ idle   │
    └─────────────────────────────────┴────────────┴──────────────┴────────┘
    ```

- [ ] **V14.6.2 — Implementar comando `stop` no CLI.**
  Adicionar subcomando para encerrar todos os containers de uma sessão ou de todas as sessões ativas, com shutdown graceful.
  - **Arquivo:** `src/cli.py`.
  - **Uso:**
    ```
    $ geminiclaw stop                          # encerra todos os containers ativos
    $ geminiclaw stop --session <session_id>   # encerra containers de uma sessão específica
    ```
  - **Comportamento:** Chama `SessionContainerRunner.stop()` para cada container ativo da sessão, com timeout de 10 segundos. Se o container não responder ao shutdown graceful, força `docker stop`.

- [ ] **V14.6.3 — Encerramento automático ao finalizar o processo CLI.**
  Registrar handler de `SIGINT`/`SIGTERM` no processo CLI que chama `stop` para todas as sessões ativas antes de encerrar. Isso garante que Ctrl+C no CLI derruba os containers corretamente sem deixar processos órfãos.
  - **Arquivo:** `src/cli.py` — `signal.signal(signal.SIGINT, _shutdown_handler)`.
  - **Nota:** O handler deve ser não-bloqueante (máximo 15 segundos para encerrar tudo) para não travar o terminal do usuário.

- [ ] **V14.6.4 — Testes de integração para os comandos CLI.**
  - **Arquivo:** `tests/integration/test_cli_session_management.py`
  - Cenário 1: `sessions` com 2 sessões ativas lista corretamente os containers.
  - Cenário 2: `stop` encerra todos os containers via shutdown graceful.
  - Cenário 3: Ctrl+C durante execução encerra containers sem deixar órfãos.

---

## Ordem de Execução Recomendada

```
V14.1 (Model Router)
    │
    ├──► V14.2 (Validator como corrotina)
    │
    ├──► V14.3 (Researcher Agent + web skills)
    │         │
    │         └──► V14.5 (ciclo de vida por sessão)
    │                   │
    ├──► V14.4 (Developer Agent)    │
              │                    │
              └────────────────────┘
                                   │
                              V14.6 (CLI stop/sessions)
```

**V14.1 é pré-requisito absoluto.** Nenhum agente deve ser criado ou refatorado sem o Model Router estar operacional — caso contrário, todos ainda usarão o `DEFAULT_MODEL`.

**V14.2 pode ser implementado em paralelo com V14.3 e V14.4** após V14.1, pois são entidades independentes (Validator não depende de Researcher ou Developer).

**V14.5 depende de V14.3 e V14.4** estarem implementados, pois o ciclo de vida por sessão pressupõe que os agentes têm identidade e contrato IPC definidos.

**V14.6 depende de V14.5** — os comandos CLI gerenciam os containers de sessão introduzidos nessa etapa.

---

## Resumo de Arquivos

### Arquivos Criados

| Arquivo | Etapa | Descrição |
|---|---|---|
| `src/model_config.py` | V14.1.1 | Mapeamento estático de papel para provider/modelo |
| `src/model_router.py` | V14.1.2 | Factory de providers LLM por papel |
| `src/agents/validator_agent.py` | V14.2.2 | ValidatorAgent como corrotina async (sem container) |
| `agents/developer/agent.py` | V14.4.1 | Developer Agent — geração de código exclusivamente |
| `containers/developer/Dockerfile` | V14.4.3 | Imagem com deps científicas pré-instaladas |
| `tests/unit/test_model_router.py` | V14.1.4 | Testes do Model Router |
| `tests/unit/agents/test_validator_agent.py` | V14.2.5 | Testes do ValidatorAgent |
| `tests/integration/agents/test_researcher_agent.py` | V14.3.6 | Testes de integração do Researcher |
| `tests/integration/agents/test_developer_agent.py` | V14.4.5 | Testes de integração do Developer |
| `tests/integration/test_session_container_lifecycle.py` | V14.5.5 | Testes do ciclo de vida por sessão |
| `tests/integration/test_cli_session_management.py` | V14.6.4 | Testes dos comandos CLI |

### Arquivos Modificados

| Arquivo | Etapas | Natureza da Mudança |
|---|---|---|
| `src/autonomous_loop.py` | V14.2.3, V14.3.1, V14.4.2, V14.5.4 | Usar ValidatorAgent, dispatch por agent_id, inicializar containers de sessão |
| `src/runner.py` | V14.5.1, V14.5.2, V14.5.3 | Adicionar `SessionContainerRunner` com health check e shutdown graceful |
| `agents/researcher/agent.py` | V14.3.1, V14.3.2, V14.3.3, V14.3.4, V14.5.3 | Absorver Planner, corrigir web skills, adicionar replan, handler de shutdown |
| `agents/base/agent.py` | V14.4.2, V14.4.4 | Remover routing (para Orchestrator), marcar como deprecated |
| `src/config.py` ou `.env` | V14.1.1 | Novas variáveis de modelo por papel |
| `src/orchestrator.py` | V14.1.3 | Substituir DEFAULT_MODEL por ModelRouter |
| `src/cli.py` | V14.6.1, V14.6.2, V14.6.3 | Comandos `sessions`, `stop`, handler SIGINT |

### Arquivos Removidos (na V15, após estabilização)

| Arquivo | Substituto |
|---|---|
| `agents/base/agent.py` | `agents/developer/agent.py` + routing no `autonomous_loop.py` |
| Planner interno ao `autonomous_loop.py` | `agents/researcher/agent.py` — método `plan()` |
| Reviewer interno ao `autonomous_loop.py` | `src/agents/validator_agent.py` — método `review_result()` |

---

## Critérios de Aceite Globais

1. **Model Router funcional:** `researcher` e `developer` usam provider remoto; `validator` usa Ollama local. Verificável nos logs de cada agente (`provider: gemini` vs `provider: ollama`).

2. **Zero containers para validação:** Uma execução completa do pipeline não cria nenhum container para Validator ou Reviewer. O número total de containers é 2 (researcher + developer) durante toda a sessão, mais containers efêmeros do PythonSandbox.

3. **Validator determinístico:** Plano sem `validation_criteria` em qualquer subtarefa → sempre rejeitado, em 10/10 execuções do mesmo plano.

4. **Researcher planeja com contexto:** Para tarefa de domínio técnico (ex: "comparar Random Forest e SVM no dataset Iris"), o log do Researcher contém ao menos 1 chamada `web_search` antes da geração do plano.

5. **Developer não reescreve do zero:** Com manifest registrando 1 step bem-sucedido, o código gerado no step 2 referencia ou importa artefatos do step 1, não os recria.

6. **Container por sessão:** Um único container de Developer permanece ativo durante execução de 3 subtarefas consecutivas. Verificável por `docker ps` — o container ID não muda entre subtarefas.

7. **CLI stop funcional:** `geminiclaw stop` encerra todos os containers ativos em menos de 15 segundos. `docker ps` após o comando não lista nenhum container do projeto.

8. **Benchmark Iris com V14:** Pipeline completo executa com 2 containers de sessão + containers efêmeros do sandbox. O Researcher faz busca web antes de planejar. O Validator aprova o plano na primeira ou segunda tentativa (não 7). O Developer constrói código incrementalmente usando o manifest.