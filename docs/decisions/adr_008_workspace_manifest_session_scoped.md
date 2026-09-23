# ADR 008 — Workspace Manifest e Session-Scoped Volumes (V13)

**Status:** Aceito
**Data:** 2026-09-22
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V13.md`

---

## Contexto

Antes do V13, o sistema sofria de "tripla apatridia" no pipeline de código:

1. **`session_id` instável:** O LLM podia alterar o argumento `session_id` da tool `python_interpreter` entre tool calls, causando artefatos espalhados em diretórios distintos (`outputs/eda_001/` e `outputs/1/` na mesma sessão).

2. **Sandbox sem volume compartilhado:** Cada `PythonSandbox` criava um container efêmero sem acesso aos artefatos da tool call anterior — o agente "reescrevia do zero" a cada tentativa.

3. **LLM sem contexto de código anterior:** O prompt enviado ao LLM para cada tool call não incluía: código gerado nas tentativas anteriores, erros específicos, lista de artefatos já produzidos. O resultado foi o agente gerando conteúdo genérico após perder o contexto.

**Evidência documentada:** Arquivo `pipeline_failure_analysis.md` mostra `AttributeError: 'tuple' object has no attribute 'items'` na linha 258 nunca sendo endereçado porque o LLM não recebeu o erro com o código no prompt de retry.

---

## Decisão

Três mecanismos complementares resolvem a apatridia em camadas:

### Camada 1: `session_id` Canônico e Imutável (V13.1)

O `session_id` é gerado uma única vez pelo orquestrador e injetado como variável de ambiente no container do agente:

```python
# src/runner.py
environment = {
    "SESSION_ID": session_id,   # canônico — agente não pode alterar
    "TASK_NAME": task.name,
    "OUTPUT_DIR": "/outputs",
}
```

O `agent_loop.py` intercepta chamadas à tool `python_interpreter` e sobrescreve o argumento `session_id` com o valor canônico, independentemente do que o LLM gerar:

```python
# src/llm/agent_loop.py
if tool_call.name == "python_interpreter":
    tool_call.args["session_id"] = canonical_session_id  # override imutável
```

### Camada 2: Volume Compartilhado por Sessão (V13.2)

O diretório de output da sessão (`outputs/<session_id>/artifacts/`) é montado como volume em **todos** os containers de agente da sessão:

```python
volumes={
    str(session_artifacts_dir): {"bind": "/outputs", "mode": "rw"},
}
```

Todas as tool calls de `python_interpreter` na mesma sessão compartilham o mesmo `/outputs`. Artefatos da tool call 1 são visíveis na tool call 2 sem necessidade de transferência explícita.

### Camada 3: WorkspaceManifest — Fonte de Verdade do Estado (V13.3)

Um arquivo `manifest.json` é mantido no diretório da sessão e atualizado após cada tool call:

```json
{
  "session_id": "20260512_143000_analise_iris",
  "artifacts": [
    {"name": "dataset.csv", "size_bytes": 4096, "created_at": "...", "tool_call": 1},
    {"name": "model.pkl",   "size_bytes": 8192, "created_at": "...", "tool_call": 3}
  ],
  "execution_history": [
    {"tool_call": 1, "status": "success", "artifacts_produced": ["dataset.csv"]},
    {"tool_call": 2, "status": "error",   "error": "AttributeError: ..."},
    {"tool_call": 3, "status": "success", "artifacts_produced": ["model.pkl"]}
  ]
}
```

O manifest é a **única fonte de verdade** sobre o estado atual do workspace — o que existe, o que foi executado, o que falhou.

### Camada 4: Injeção de Contexto no Retry (V13.4 e V13.5)

Antes de cada retry de subtarefa, o orquestrador injeta na `ShortTermMemory` do agente:
- Conteúdo do `manifest.json` (artefatos existentes)
- Código gerado na tentativa anterior (via `get_archive` do sandbox)
- Erro específico que causou a falha (stack trace completo)

O `agent_loop.py` lê a `ShortTermMemory` e inclui esse contexto no prompt enviado ao LLM.

### Camada 5: Memória Semântica de Padrões de Código (V13.6)

Ao final de cada subtarefa bem-sucedida, o orquestrador extrai padrões do código produzido e os salva na memória de longo prazo (Qdrant) para reutilização em sessões futuras.

---

## Princípio de Separação de Responsabilidades

```
Filesystem   → Estado objetivo: o que existe, o que foi executado, o que falhou
ShortTerm    → Raciocínio acumulado sobre esse estado na sessão atual
LongTerm     → Aprendizados reutilizáveis entre sessões (Qdrant)
```

---

## Consequências

### Positivas

- **Continuidade garantida:** O agente pode construir código incrementalmente sobre o trabalho anterior, sem amnésia entre tool calls.
- **Debug facilitado:** O `manifest.json` registra toda a sequência de tentativas com artefatos e erros — permite diagnóstico humano pós-execução.
- **Eliminação de ambiguidade:** O `session_id` canônico elimina a classe inteira de bugs de fragmentação de artefatos.

### Negativas / Trade-offs

- **Overhead de I/O:** Atualizar o `manifest.json` após cada tool call introduz latência de escrita em disco.
- **Complexidade do `agent_loop.py`:** A interceptação e override de argumentos de tool call adiciona lógica não trivial ao loop.
- **Volume persistente:** O diretório de sessão cresce durante a execução — o `OutputManager.cleanup_session()` deve ser chamado após sessões de desenvolvimento/teste.

---

## Revisão

Este ADR deve ser revisado quando:
- V14 for implementado (containers por sessão tornam algumas dessas proteções mais simples)
- O formato do `manifest.json` precisar de campos adicionais
- A estratégia de injeção de contexto mudar
