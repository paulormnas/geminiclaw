# Roadmap V13 — Persistência de Contexto no Sandbox e Continuidade de Código

**Contexto:** As etapas V12.1–V12.5 resolvem falhas de cache, resiliência do loop ReAct e desperdício de recursos. Mesmo com essas correções, persiste um problema estrutural separado: o agente de código não tem memória do que já produziu entre tool calls. Cada execução do `PythonSandbox` inicia um container novo, sem acesso aos artefatos da tool call anterior e sem saber quais tentativas já foram feitas. O resultado observado é o agente reescrevendo código do zero a cada iteração, incapaz de construir incrementalmente sobre o trabalho anterior.

**Problema central:** Tripla apatridia no pipeline de código — (1) `session_id` muda entre tool calls, colocando artefatos em diretórios distintos; (2) o container do sandbox não monta o diretório da sessão como volume; (3) o LLM não recebe o conteúdo do código anterior nem o histórico de erros antes de gerar uma nova tentativa.

**Dependências:** Este roadmap assume V10, V11 e V12 implementados. Em particular, depende da estabilidade do `session_id` como identificador de sessão (`SESSION_ID` via env var, introduzido em V10) e do canal IPC bidirecional (`src/ipc.py`) para propagação de contexto entre orquestrador e container.

**Relatório de referência:** `pipeline_failure_analysis.md` — evidências de `session_id` inconsistente (tool call 1 usou `eda_iris_001`, tool call 3 usou `"1"`), `FileNotFoundError` por artefatos em diretórios distintos, e agente gerando "Curso de Data Science" após perder contexto.

---

## Diagnóstico Consolidado

### D1 — `session_id` Inconsistente Fragmenta Artefatos (CAUSA RAIZ PRIMÁRIA)

**Problema:** O modelo pode alterar o argumento `session_id` da tool `python_interpreter` livremente entre chamadas. Na execução analisada, a tool call 1 usou `eda_iris_001` e a tool call 3 usou `"1"`, fazendo o `OutputManager` salvar artefatos em:

```
outputs/eda_iris_001/eda_iris/   ← iris_original.csv, boxplot_plots.png
outputs/1/eda_iris/              ← script.py
```

O container da tool call 3 listou `/outputs/` e encontrou apenas `script.py`, sem saber da existência dos artefatos da tool call 1.

**Impacto:** Qualquer mecanismo de persistência construído sobre `session_id` instável é ineficaz. Este é o problema que deve ser resolvido primeiro.

---

### D2 — Sandbox Sem Volume Compartilhado Isola Artefatos por Tool Call

**Problema:** O `PythonSandbox` (`src/skills/code/sandbox.py`) cria containers efêmeros sem montar o diretório de saída da sessão como volume. Cada container vê apenas o que existe em seu próprio sistema de arquivos efêmero. Artefatos gerados pela tool call 1 não são acessíveis na tool call 2, mesmo que o `session_id` seja o mesmo.

**Evidência:** Tool call 4–6 do relatório listaram `/outputs/` repetidamente sem encontrar os CSVs e PNGs que tinham sido salvos na tool call 1 — porque estavam no host, não montados no novo container.

**Impacto:** O agente não consegue construir código incremental. Cada tool call começa sem saber o que existe no diretório de trabalho.

---

### D3 — LLM Não Recebe Contexto do Código Anterior Antes de Gerar Nova Tentativa

**Problema:** O prompt enviado ao LLM para cada tool call contém apenas a instrução da subtarefa. Não contém: (a) o código gerado nas tool calls anteriores, (b) os erros específicos que ocorreram (apenas "falha na revisão" é propagado), (c) a lista de artefatos já produzidos. O resultado é que o LLM trata cada tool call como uma tarefa nova, reescrevendo código do zero — ou, quando o contexto fica fragmentado por compressão, gerando conteúdo genérico sem relação com a tarefa.

**Impacto:** O modelo não consegue corrigir bugs incrementalmente. O bug `AttributeError: 'tuple' object has no attribute 'items'` na linha 258 nunca foi endereçado porque o LLM não recebeu o erro com o código no prompt de retry.

---

### D4 — Orquestrador Não Injeta Contexto Acumulado no Retry

**Problema:** Quando o `autonomous_loop.py` dispara um retry após reprovação do Reviewer, o `enriched_task.prompt` é idêntico ao da tentativa anterior (problema de cache já tratado em V12.1, mas que tem uma segunda face: mesmo sem cache, o LLM não sabe *o que foi produzido* na tentativa anterior). O Reviewer avalia apenas `response.text` e não lista os artefatos parciais existentes em disco, impossibilitando o agente de saber que a tool call 1 gerou resultados válidos.

**Impacto:** O agente de retry parte do mesmo ponto zero, descartando trabalho parcial válido.

---

### D5 — Ausência de Registro Estruturado do Histórico de Execução por Subtarefa

**Problema:** Não existe um artefato persistente e estruturado que descreva a sequência de tentativas de uma subtarefa: o que foi executado, o que produziu, o que falhou e por quê. O `SessionManager` guarda histórico de mensagens, mas em formato de conversação — não em formato de estado de execução consultável pelo agente. A `MemorySkill` é populada apenas se o agente executa `memorize` explicitamente, o que não ocorre em cenários de falha.

**Impacto:** Ausência de continuidade estruturada. Cada reinicialização é uma amnésia total sobre o trabalho anterior.

---

## Arquitetura da Solução

A solução é organizada em três camadas complementares, cada uma resolvendo um aspecto distinto da apatridia:

```
┌─────────────────────────────────────────────────────────────┐
│  Camada 3 — Memória Semântica (MemorySkill)                 │
│  Aprendizados cross-sessão: padrões que funcionam,          │
│  armadilhas conhecidas, datasets com comportamentos         │
│  específicos. Populada pelo orquestrador pós-conclusão.     │
├─────────────────────────────────────────────────────────────┤
│  Camada 2 — Injeção de Contexto (agent_loop + loop retry)   │
│  Manifest + código anterior + erros específicos injetados   │
│  no prompt antes de cada chamada ao LLM. O orquestrador     │
│  popula a memória de curto prazo antes de cada retry.       │
├─────────────────────────────────────────────────────────────┤
│  Camada 1 — Estado Objetivo (Workspace Manifest + Volume)   │
│  session_id consistente + diretório da sessão montado       │
│  como volume + manifest.json atualizado a cada tool call.   │
│  Sobrevive a falhas de container. Fonte de verdade.         │
└─────────────────────────────────────────────────────────────┘
```

**Princípio de separação de responsabilidades:**
- O **filesystem** guarda o estado objetivo: o que existe, o que foi executado, o que falhou.
- A **memória de curto prazo** guarda o raciocínio acumulado sobre esse estado dentro da sessão atual.
- A **memória de longo prazo** guarda aprendizados reutilizáveis entre sessões.

---

## Etapas de Implementação

### Etapa V13.1 — `session_id` Consistente no Agent Loop (Prioridade: CRÍTICA)

**Objetivo:** Garantir que o `session_id` passado pelo modelo para a tool `python_interpreter` seja sempre o valor canônico da sessão, independentemente do que o LLM gerar como argumento.

#### Tarefas:

- [x] **V13.1.1 — Forçar `session_id` a partir de variável de ambiente.**
  No `agent_loop.py`, ao processar os argumentos de qualquer tool call para `python_interpreter`, sobrescrever o campo `session_id` com o valor de `os.environ.get("SESSION_ID")` antes de executar a tool. O modelo ainda pode gerar o campo (para manter o formato de chamada), mas o valor é ignorado.
  - **Arquivo:** `src/llm/agent_loop.py` — bloco de execução de ferramentas (L157-247).
  - **Lógica:**
    ```python
    if tool_call.function.name == "python_interpreter":
        args = json.loads(tool_call.function.arguments)
        args["session_id"] = os.environ.get("SESSION_ID", args.get("session_id"))
        tool_call.function.arguments = json.dumps(args)
    ```
  - **Efeito:** Todos os artefatos de uma sessão vão para o mesmo diretório raiz no host, independentemente de quantas tool calls ocorrem ou do que o LLM gerou.

- [x] **V13.1.2 — Propagar `SESSION_ID` como variável de ambiente no container do agente.**
  O `ContainerRunner` já passa variáveis de ambiente para o container do agente. Verificar que `SESSION_ID` está incluído e é derivado do `master_session_id` da subtarefa atual.
  - **Arquivo:** `src/runner.py` — bloco de construção de `environment` no spawn do container.
  - **Lógica:** `environment["SESSION_ID"] = f"{master_session_id}_{task_name}"` — combinação do ID da sessão mestra com o nome da subtarefa, garantindo unicidade mas também rastreabilidade.

- [x] **V13.1.3 — Testes unitários para consistência de `session_id`.**
  - **Arquivo:** `tests/unit/llm/test_session_id_consistency.py`
  - Cenário 1: Tool call com `session_id="1"` é sobrescrito para o valor do env var.
  - Cenário 2: Tool call sem campo `session_id` recebe o valor do env var.
  - Cenário 3: Tool call para ferramenta diferente de `python_interpreter` não é afetada.

---

### Etapa V13.2 — Volume Compartilhado da Sessão no PythonSandbox (Prioridade: CRÍTICA)

**Objetivo:** Garantir que todas as tool calls de uma mesma sessão de agente enxerguem o mesmo diretório de trabalho, com acesso de leitura e escrita aos artefatos produzidos em tool calls anteriores.

#### Tarefas:

- [x] **V13.2.1 — Montar `outputs/<session_id>/` como volume no container do sandbox.**
  No `PythonSandbox.execute()`, antes de criar o container efêmero, calcular o caminho absoluto do diretório da sessão no host e montá-lo em `/outputs/` dentro do container.
  - **Arquivo:** `src/skills/code/sandbox.py` — método de criação do container (L110-121).
  - **Lógica:**
    ```python
    session_output_dir = Path(settings.OUTPUT_DIR) / session_id
    session_output_dir.mkdir(parents=True, exist_ok=True)
    volumes = {
        str(session_output_dir.resolve()): {
            "bind": "/outputs",
            "mode": "rw"
        }
    }
    ```
  - **Contrato com o agente:** O código gerado pelo LLM deve salvar artefatos em `/outputs/`. O system prompt do agente base deve documentar isso explicitamente (ver V13.4.2).
  - **Efeito:** Arquivos criados pela tool call 1 em `/outputs/` são visíveis na tool call 2 no mesmo caminho, porque ambos os containers efêmeros montam o mesmo diretório do host.

- [x] **V13.2.2 — Garantir que o diretório existe antes do spawn.**
  Criar o diretório `outputs/<session_id>/` no host antes de qualquer tool call, não apenas quando o primeiro artefato é salvo. Isso evita race conditions quando o manifest (V13.3) tenta abrir o arquivo antes da primeira execução de código.
  - **Arquivo:** `src/skills/code/skill.py` — método `execute()` da `CodeSkill`, antes de chamar `PythonSandbox`.

- [x] **V13.2.3 — Testes de integração para acesso cross-tool-call.**
  - **Arquivo:** `tests/integration/test_sandbox_volume.py`
  - Cenário 1: Arquivo criado na tool call 1 é listado por `os.listdir('/outputs/')` na tool call 2 com o mesmo `session_id`.
  - Cenário 2: Tool calls com `session_id` diferentes não compartilham diretório.
  - Cenário 3: Container do sandbox encerra mas arquivo persiste no host.

---

### Etapa V13.3 — Workspace Manifest por Sessão (Prioridade: ALTA)

**Objetivo:** Criar e manter um arquivo `manifest.json` dentro de cada diretório de sessão, atualizado automaticamente após cada tool call, que registra o histórico estruturado de execução. Este arquivo é a fonte de verdade para o agente sobre o que já foi feito, o que produziu e o que falhou.

#### Schema do manifest:

```json
{
  "session_id": "20260514_173741_eda_iris_001",
  "task_name": "eda_iris",
  "created_at": "2026-05-14T17:37:41Z",
  "last_updated": "2026-05-14T17:41:03Z",
  "steps": [
    {
      "step": 1,
      "status": "success",
      "timestamp": "2026-05-14T17:38:12Z",
      "artifacts_created": ["iris_original.csv", "boxplot_plots.png", "correlation_heatmap.png"],
      "summary": "Dataset Iris carregado (150 linhas, 4 features, sem nulos). Gráficos exploratórios gerados.",
      "code_file": "step_01.py"
    },
    {
      "step": 2,
      "status": "failed",
      "timestamp": "2026-05-14T17:39:44Z",
      "artifacts_created": ["step_02.py"],
      "error_type": "AttributeError",
      "error_message": "'tuple' object has no attribute 'items'",
      "error_location": "step_02.py, linha 258",
      "summary": "Script EDA completo gerado mas falhou. O retorno de value_counts() é tuple, não dict.",
      "code_file": "step_02.py"
    }
  ],
  "artifacts_available": ["iris_original.csv", "boxplot_plots.png", "correlation_heatmap.png", "step_01.py", "step_02.py"],
  "next_step_hint": "Corrigir step_02.py linha 258: substituir .items() por enumerate() ou converter para dict antes."
}
```

#### Tarefas:

- [x] **V13.3.1 — Criar `WorkspaceManifest` como classe utilitária.**
  Implementar em `src/skills/code/manifest.py` a classe responsável por criar, atualizar e ler o `manifest.json` da sessão.
  - **Arquivo:** `src/skills/code/manifest.py` (novo arquivo).
  - **Interface pública:**
    ```python
    class WorkspaceManifest:
        def __init__(self, session_dir: Path, session_id: str, task_name: str): ...
        def record_step(self, step: int, status: str, artifacts: list[str],
                        summary: str, error: dict | None = None,
                        code_file: str | None = None) -> None: ...
        def update_next_hint(self, hint: str) -> None: ...
        def read(self) -> dict: ...
        def get_artifacts_available(self) -> list[str]: ...
        def get_last_error(self) -> dict | None: ...
        def get_step_count(self) -> int: ...
    ```
  - **Atomicidade:** Usar `write` in arquivo temporário + rename para evitar manifest corrompido em caso de crash durante escrita.

- [x] **V13.3.2 — Atualizar o manifest após cada tool call no `CodeSkill`.**
  Após cada execução do `PythonSandbox`, independentemente de sucesso ou falha, chamar `manifest.record_step()` com o resultado. O manifest é atualizado no host, não dentro do container — o `CodeSkill` tem acesso ao resultado e ao `session_dir`.
  - **Arquivo:** `src/skills/code/skill.py` — após `sandbox.execute()`.
  - **Em caso de sucesso:** listar arquivos novos em `/outputs/<session_id>/` comparando com o manifest anterior para identificar `artifacts_created`.
  - **Em caso de falha:** extrair `error_type`, `error_message` e `error_location` do `stderr` ou da `exception` retornada pelo sandbox. Usar regex simples para capturar o padrão `ErrorType: message` e `File "...", line N`.

- [x] **V13.3.3 — Salvar snapshot do código executado por step.**
  Antes de executar o código no sandbox, salvá-lo como `step_NN.py` no diretório da sessão (no host, antes do spawn do container). Isso garante que o código está disponível para referência futura mesmo que o container falhe antes de salvar qualquer coisa.
  - **Arquivo:** `src/skills/code/skill.py` — antes de chamar `sandbox.execute()`.
  - **Convenção de nome:** `step_{step_number:02d}.py`, onde `step_number` é `manifest.get_step_count() + 1`.

- [x] **V13.3.4 — Testes unitários para `WorkspaceManifest`.**
  - **Arquivo:** `tests/unit/skills/test_workspace_manifest.py`
  - Cenário 1: Criação de manifest em diretório novo.
  - Cenário 2: `record_step` com sucesso atualiza `artifacts_available` e `steps`.
  - Cenário 3: `record_step` com falha registra `error_type` e `error_message`.
  - Cenário 4: Crash durante escrita não corrompe o manifest anterior (atomicidade).
  - Cenário 5: `get_last_error()` retorna o erro do step mais recente com status `"failed"`.

---

### Etapa V13.4 — Injeção de Contexto no Prompt Antes de Cada LLM Call (Prioridade: ALTA)

**Objetivo:** Garantir que o LLM receba, antes de gerar código, o conteúdo do manifest atual, o código do step anterior (quando relevante) e os erros específicos que ocorreram. O LLM não deve "descobrir" o que existe consultando o filesystem durante a execução — deve receber esse contexto no prompt.

#### Tarefas:

- [x] **V13.4.1 — Injetar bloco de contexto do workspace no prompt do agente base.**
  No `agent_loop.py`, antes de cada chamada ao LLM (não apenas na primeira da sessão), ler o manifest e construir um bloco de contexto estruturado a ser inserido como mensagem de sistema com role `"tool"` ou como prefixo no `user` message.
  - **Arquivo:** `src/llm/agent_loop.py` — antes da chamada ao LLM no loop (L100-155).
  - **Bloco de contexto injetado:**
    ```
    [CONTEXTO DO WORKSPACE]
    Sessão: {session_id} | Tarefa: {task_name} | Steps concluídos: {N}
    
    Artefatos disponíveis em /outputs/:
    {lista de artifacts_available do manifest}
    
    Último step ({status}):
    {summary do último step}
    {se falhou: "Erro: {error_type}: {error_message} em {error_location}"}
    
    Próximo passo sugerido:
    {next_step_hint, se existir}
    
    IMPORTANTE: NÃO recriar artefatos já listados acima. Construa sobre o que já existe.
    ```
  - **Leitura do manifest:** O bloco é construído pelo host (no `CodeSkill` ou `agent_loop.py`), lendo o arquivo `manifest.json` do diretório da sessão antes de chamar o LLM. O código de leitura roda no host, não dentro do container.

- [x] **V13.4.2 — Injetar código do step anterior quando o último step falhou.**
  Se `manifest.get_last_error()` retornar um erro (último step com status `"failed"`), ler o arquivo `step_NN.py` correspondente e incluí-lo no bloco de contexto com uma instrução explícita de correção. Limitar a injeção às últimas 150 linhas do código para não extrapolar a context window em modelos menores.
  - **Arquivo:** `src/llm/agent_loop.py` — extensão do bloco de contexto do V13.4.1.
  - **Bloco adicional injetado:**
    ```
    Código do step anterior (que falhou):
    ```python
    {conteúdo de step_NN.py, últimas 150 linhas}
    ```
    O erro ocorreu na linha {error_location}. Corrija especificamente esse ponto.
    NÃO reescreva o código inteiro — corrija apenas a parte problemática.
    ```
  - **Limite de linhas:** Configurável via `MAX_CODE_CONTEXT_LINES` in `config.py`, default 150. Para `qwen3:8b` com 8192 tokens, 150 linhas de Python cabem confortavelmente com espaço para o restante do prompt.

- [x] **V13.4.3 — Documentar o contrato de paths no system prompt do agente base.**
  Atualizar o system prompt do agente base para incluir as convenções de path que o agente deve seguir ao gerar código. Sem isso, o modelo pode continuar inventando paths como `/datasets/iris.csv`.
  - **Arquivo:** `agents/base/agent.py` — system prompt.
  - **Instrução adicionada:**
    ```
    CONVENÇÕES DE PATHS:
    - Seus artefatos de saída DEVEM ser salvos em /outputs/ (este diretório já está montado).
    - Para ler arquivos de iterações anteriores, leia de /outputs/ — eles já estão lá.
    - NUNCA use paths como /datasets/, /data/, /tmp/ para artefatos persistentes.
    - Antes de criar um arquivo, verifique os artefatos já disponíveis no [CONTEXTO DO WORKSPACE].
    - Para instalar dependências Python, use: import subprocess; subprocess.run(['pip', 'install', 'pacote', '--quiet'])
    ```

- [x] **V13.4.4 — Testes de integração para injeção de contexto.**
  - **Arquivo:** `tests/integration/test_context_injection.py`
  - Cenário 1: Com manifest de 1 step bem-sucedido, o prompt contém os artefatos listados.
  - Cenário 2: Com manifest de 1 step falho, o prompt contém o código anterior e o erro.
  - Cenário 3: Manifest ausente (primeira execução) → bloco de contexto indica "nenhum step anterior".
  - Cenário 4: Código anterior com 300 linhas → injetadas apenas as últimas 150.

---

### Etapa V13.5 — Enriquecimento de Contexto no Retry pelo Orquestrador (Prioridade: MÉDIA)

**Objetivo:** Garantir que quando o `autonomous_loop.py` dispara um retry após reprovação do Reviewer, o agente da próxima tentativa encontra na memória de curto prazo o contexto completo do que foi tentado — incluindo artefatos parciais válidos que o Reviewer não considerou.

#### Tarefas:

- [x] **V13.5.1 — Orquestrador lista artefatos reais antes de cada retry.**
  Em `autonomous_loop.py`, antes de disparar o retry de uma subtarefa, chamar `output_manager.list_artifacts(session_id)` e incluir a lista no `enriched_task.prompt` de retry, explicitando que esses artefatos são válidos e não devem ser recriados.
  - **Arquivo:** `src/autonomous_loop.py` — bloco de retry em `_execute_task_in_dag` (L405-459).
  - **Lógica:**
    ```python
    artifacts_on_disk = self.orchestrator.output_manager.list_artifacts(
        f"{master_session_id}_{task.task_name}"
    )
    artifact_context = ""
    if artifacts_on_disk:
        artifact_context = (
            f"\n[ARTEFATOS PARCIAIS EXISTENTES EM DISCO]\n"
            + "\n".join(f"  - {a}" for a in artifacts_on_disk)
            + "\nEsses artefatos são válidos. Não os recrie. Continue a partir deles.\n"
        )
    enriched_prompt = task.prompt + artifact_context + error_context  # error_context já existe via V12.1.1
    ```

- [x] **V13.5.2 — Orquestrador popula memória de curto prazo antes do retry.**
  Usar a `MemorySkill` com `remember()` para registrar, na sessão do agente que irá executar o retry, o contexto de falha — não apenas via prompt, mas também via memória, de forma que o agente possa consultar em qualquer ponto da sua execução.
  - **Arquivo:** `src/autonomous_loop.py` — antes do dispatch do container de retry.
  - **Lógica:**
    ```python
    memory_context = {
        "type": "retry_context",
        "task": task.task_name,
        "attempt": attempt,
        "previous_error": result.error,
        "artifacts_available": artifacts_on_disk,
        "manifest_path": f"outputs/{session_id}/manifest.json"
    }
    await self.memory_skill.remember(
        session_id=session_id,
        key=f"retry_context_{task.task_name}_{attempt}",
        value=json.dumps(memory_context)
    )
    ```

- [x] **V13.5.3 — Reviewer inclui lista de artefatos na avaliação.**
  Atualizar o prompt do Reviewer para incluir os artefatos em disco, de forma que ele possa distinguir entre "tarefa completamente falha" e "tarefa parcialmente executada com artefatos válidos". Isso evita que o Reviewer reprove uma subtarefa cujos artefatos principais foram gerados, mesmo que o `response.text` esteja incompleto.
  - **Arquivo:** `src/autonomous_loop.py` — método `_review_subtask` (L745-752).
  - **Adição ao prompt do Reviewer:**
    ```
    ARTEFATOS EXISTENTES NO DISCO (considerar como parte do resultado):
    {lista de artifacts_on_disk}
    
    Avalie se os artefatos esperados ({expected_artifacts}) estão presentes em disco,
    não apenas se o response.text os menciona.
    ```

- [x] **V13.5.4 — Testes de integração para contexto de retry.**
  - **Arquivo:** `tests/integration/test_retry_context_enrichment.py`
  - Cenário 1: Retry contém lista de artefatos parciais no prompt.
  - Cenário 2: Memória de curto prazo contém `retry_context` antes do dispatch do container.
  - Cenário 3: Reviewer aprova subtarefa quando artefatos esperados estão em disco, mesmo com `response.text` incompleto.

---

### Etapa V13.6 — Memória de Longo Prazo para Padrões de Código (Prioridade: BAIXA)

**Objetivo:** Após a conclusão bem-sucedida de uma subtarefa de código, extrair aprendizados reutilizáveis e salvá-los na `MemorySkill` de longo prazo. Isso cria uma base de conhecimento incremental sobre padrões que funcionam e armadilhas conhecidas para o domínio do projeto.

**Nota:** Esta etapa só deve ser implementada depois que V13.1–V13.5 estiverem estáveis. Memória de longo prazo construída sobre contexto instável é ruído, não sinal.

#### Tarefas:

- [x] **V13.6.1 — Extrair padrões de código pós-conclusão.**
  Após `result.status == "success"` em `_execute_task_in_dag`, disparar uma chamada leve ao LLM (pode usar o modelo local menor, pois é uma tarefa simples de extração) para gerar um resumo estruturado das lições aprendidas durante a execução.
  - **Arquivo:** `src/autonomous_loop.py` — após confirmação de sucesso da subtarefa.
  - **Prompt de extração:**
    ```
    Dado o histórico de execução desta subtarefa, extraia lições reutilizáveis no formato JSON:
    {
      "domain": "nome do domínio (ex: sklearn, pandas, matplotlib)",
      "pattern": "descrição do padrão que funcionou",
      "pitfall": "descrição da armadilha encontrada (se houver)",
      "fix": "como foi resolvida"
    }
    Histórico: {manifest_steps}
    ```

- [x] **V13.6.2 — Persistir lições na `MemorySkill` de longo prazo.**
  Salvar as lições extraídas com chave composta `code_pattern:{domain}:{hash_curto}` para permitir recuperação por domínio.
  - **Arquivo:** `src/autonomous_loop.py` — após extração em V13.6.1.
  - **Integração:** Usar `memory_skill.memorize(key, value)` existente.

- [x] **V13.6.3 — Injetar lições relevantes no contexto inicial da subtarefa.**
  Antes de iniciar uma nova subtarefa de código, consultar a memória de longo prazo por padrões no mesmo domínio e incluir no prompt inicial.
  - **Arquivo:** `src/autonomous_loop.py` — em `_enrich_task_prompt()` ou equivalente.
  - **Query:** `memory_skill.retrieve(query=f"code_pattern:{inferred_domain}")`.

- [x] **V13.6.4 — Testes unitários para extração e recuperação de padrões.**
  - **Arquivo:** `tests/unit/test_code_pattern_memory.py`
  - Cenário 1: Extração gera JSON válido a partir de histórico de manifest.
  - Cenário 2: Lição salva é recuperada por domínio na sessão seguinte.
  - Cenário 3: Lição de `pandas` não é injetada em subtarefa de domínio `matplotlib`.

---

## Ordem de Execução Recomendada

```
V13.1 (session_id)  ──►  V13.2 (volume)  ──►  V13.3 (manifest)
                                                      │
                                                      ▼
                              V13.4 (injeção de contexto no LLM)
                                                      │
                                                      ▼
                              V13.5 (enriquecimento de retry)
                                                      │
                                                      ▼
                              V13.6 (memória de longo prazo)  [opcional, pós-estabilização]
```

**V13.1 e V13.2 são pré-requisitos bloqueantes.** Sem `session_id` consistente e sem volume montado, o manifest (V13.3) seria escrito em diretórios errados e a injeção de contexto (V13.4) leria arquivos desatualizados. Não implementar V13.3+ antes de V13.1 e V13.2 estarem validados por testes.

**V13.3 é pré-requisito para V13.4.** O bloco de contexto injetado no prompt é derivado do manifest. Sem manifest, V13.4 não tem fonte de dados confiável.

**V13.5 é independente de V13.3/V13.4** no sentido de que pode ser implementado em paralelo, mas seu valor é multiplicado quando o manifest já existe — o Reviewer pode verificar artefatos com mais precisão.

---

## Resumo de Arquivos

### Arquivos Modificados

| Arquivo | Etapas | Natureza da Mudança |
|---|---|---|
| `src/llm/agent_loop.py` | V13.1.1, V13.4.1, V13.4.2 | Forçar `session_id`, injetar bloco de contexto do workspace antes de cada LLM call |
| `src/runner.py` | V13.1.2 | Incluir `SESSION_ID` nas variáveis de ambiente do container do agente |
| `src/skills/code/sandbox.py` | V13.2.1 | Montar `outputs/<session_id>/` como volume rw no container efêmero |
| `src/skills/code/skill.py` | V13.2.2, V13.3.2, V13.3.3 | Criar diretório pré-spawn, atualizar manifest pós-execução, salvar snapshot do código |
| `src/config.py` | V13.4.2 | Nova variável `MAX_CODE_CONTEXT_LINES` (default: 150) |
| `src/autonomous_loop.py` | V13.5.1, V13.5.2, V13.5.3, V13.6.1, V13.6.2, V13.6.3 | Enriquecer retry com artefatos e memória, atualizar Reviewer, extrair e injetar padrões |
| `agents/base/agent.py` | V13.4.3 | System prompt com convenções de paths e instrução de não recriar artefatos |

### Arquivos Criados

| Arquivo | Etapa | Descrição |
|---|---|---|
| `src/skills/code/manifest.py` | V13.3.1 | Classe `WorkspaceManifest` — criação, atualização e leitura do `manifest.json` |
| `tests/unit/llm/test_session_id_consistency.py` | V13.1.3 | Testes de consistência do `session_id` |
| `tests/integration/test_sandbox_volume.py` | V13.2.3 | Testes de acesso cross-tool-call via volume compartilhado |
| `tests/unit/skills/test_workspace_manifest.py` | V13.3.4 | Testes unitários para `WorkspaceManifest` |
| `tests/integration/test_context_injection.py` | V13.4.4 | Testes de injeção de contexto no prompt do LLM |
| `tests/integration/test_retry_context_enrichment.py` | V13.5.4 | Testes de enriquecimento do prompt e memória no retry |
| `tests/unit/test_code_pattern_memory.py` | V13.6.4 | Testes de extração e recuperação de padrões de código |

---

## Critérios de Aceite Globais

1. **`session_id` estável:** Em uma execução com 5 tool calls para `python_interpreter`, todos os artefatos estão no mesmo diretório `outputs/<session_id>/` no host. Nenhum arquivo está em diretório derivado de `session_id` gerado pelo modelo.

2. **Continuidade cross-tool-call:** Um arquivo `iris.csv` criado na tool call 1 está acessível em `/outputs/iris.csv` dentro do container da tool call 2 do mesmo agente, sem nenhuma cópia ou transferência manual.

3. **Manifest atualizado a cada step:** Após 3 tool calls (1 sucesso, 1 falha, 1 sucesso), o `manifest.json` contém 3 entradas em `steps`, com `artifacts_available` refletindo apenas os artefatos reais em disco.

4. **LLM não reescreve código do zero:** Em uma simulação onde o manifest registra 1 step falho com `AttributeError` na linha 258, o código gerado pela LLM call seguinte contém a correção na linha 258, não uma reescrita completa do script.

5. **Retry com contexto completo:** O prompt de retry contém a lista de artefatos em disco e o erro específico da tentativa anterior. O Reviewer não reprova uma subtarefa cujos artefatos esperados existem em disco.

6. **Benchmark Iris com V13:** O pipeline completo de classificação Iris (EDA → Pré-processamento → Treino → Avaliação) executa com `qwen3:8b`, gerando artefatos reais em todas as etapas, sem nenhuma tool call reescrevendo do zero código que já existia no manifest como bem-sucedido.