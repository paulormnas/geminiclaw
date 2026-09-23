# ADR 007 — Reestruturação de Papéis de Agentes: 3 Papéis Claros (V14)

**Status:** Aceito (implementado na V14)
**Data:** 2026-09-22 (atualizado em 2026-09-23)
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V14.md`

---

## Contexto

A análise de logs de execução revelou falhas sistêmicas decorrentes da distribuição inadequada de responsabilidades entre os agentes:

1. **Planner, Validator e Reviewer** são chamadas LLM embutidas no `autonomous_loop.py`, não agentes com identidade própria. Cada chamada gera um container Docker desnecessário, resultando em ~15 containers só na fase de planejamento.

2. **`base_agent`** acumula simultaneamente: recebimento de tarefa via IPC, decisão sobre qual ferramenta invocar (routing), e execução de código via `python_interpreter`. Responsabilidades com perfis completamente diferentes de modelo, contexto e ciclo de vida.

3. **`researcher_agent`** possui skills de busca web mas não integradas ao pipeline de planejamento — o Planner gera planos sem contexto de domínio.

4. **Todos os agentes usam o mesmo `DEFAULT_MODEL`** — um único modelo local (qwen3.5:4b) é insuficiente para planejamento e geração de código; um modelo remoto para validação estruturada é desperdício.

**Evidência:** Em execução real, o Planner precisou de 7 tentativas porque o modelo local não tinha capacidade de decomposição adequada. O base_agent gerou "Curso de Data Science" após perder o foco da tarefa original.

---

## Decisão

Consolidar os 6+ agentes atuais em **3 papéis claros**, com responsabilidades bem definidas e modelos selecionados por papel:

### Papel 1: Researcher Agent (container por sessão — modelo remoto)

**Absorve:** Planner atual + researcher_agent atual

**Responsabilidades:**
- Decomposição da tarefa em subtarefas (DAG) com contexto de domínio científico
- Interpretação do contexto de artigos/dados fornecido pelo pesquisador
- Busca web para suporte técnico (não bibliográfico — ver ADR 001)
- Síntese de fontes e contexto para enriquecer o plano
- Replanejamento baseado em resultados parciais das subtarefas

**Modelo:** Remoto pesado (ex: `gemini-2.0-flash` ou superior)
**Ciclo de vida:** Container único por sessão — não efêmero por subtarefa

### Papel 2: Validator Agent (corrotina async no processo principal — modelo local)

**Absorve:** Validator atual + Reviewer atual

**Responsabilidades:**
- Validação do plano contra schema JSON antes da execução
- Avaliação dos resultados de cada subtarefa após execução
- Verificação de artefatos em disco (via manifest) — não apenas `response.text`
- Checklist estruturado: JSON bem formado, dependências satisfeitas, artefatos presentes

**Modelo:** Local leve (ex: `qwen3:8b`) — julgamento estruturado, output curto, sem criatividade necessária
**Ciclo de vida:** Corrotina assíncrona no processo principal do orquestrador — **sem container Docker**

**Motivação para eliminação do container:** O Validator não executa código arbitrário. Criar um container para fazer chamadas LLM e retornar JSON é overhead puro. Como corrotina no processo principal, o Validator pode acessar o filesystem da sessão diretamente para verificar artefatos.

### Papel 3: Developer Agent (container por sessão — modelo remoto)

**Absorve:** base_agent (parte de execução de código)

**Responsabilidades:**
- Recebimento de subtarefas de código via IPC
- Geração e correção incremental de código Python
- Integração com PythonSandbox e WorkspaceManifest (V13)
- Manutenção do histórico de código em memória entre subtarefas da mesma sessão
- Produção de artefatos em `/outputs/<session_id>/artifacts/`

**Modelo:** Remoto pesado (ex: `gemini-2.0-flash` ou superior)
**Ciclo de vida:** Container único por sessão — persiste durante toda a sessão, recebe múltiplas subtarefas via IPC

---

## O que desaparece

| Agente/Componente atual | Destino |
|---|---|
| `agents/base/agent.py` | Substituído pelo Developer Agent |
| Planner como entidade no loop | Absorvido pelo Researcher Agent |
| Reviewer como chamada avulsa | Absorvido pelo Validator Agent |
| Containers para Validator/Reviewer | Eliminados — Validator vira corrotina |
| `DEFAULT_MODEL` global único | Substituído pelo Model Router (V14.1) |

---

## Model Router (V14.1 — Pré-requisito)

O Model Router (`src/model_router.py`) mapeia papel → provider + modelo:

```python
MODEL_CONFIG = {
    "researcher": {"provider": "google", "model": "gemini-2.0-flash"},
    "validator":  {"provider": "ollama", "model": "qwen3:8b"},
    "developer":  {"provider": "google", "model": "gemini-2.0-flash"},
}
```

Configurável via variáveis de ambiente, com fallback para `DEFAULT_MODEL` por compatibilidade.

---

## Alternativas Consideradas

### Alternativa A: Manter 6 agentes, apenas melhorar prompts

Manter a estrutura atual mas reescrever as instruções dos agentes para corrigir o comportamento.

**Descartado porque:**
- O problema de criar 15 containers para planejamento é estrutural — não resolve com melhor prompt
- `base_agent` com responsabilidades incompatíveis não pode ser resolvido por instrução
- Modelo único para todos os papéis continuaria inadequado

### Alternativa B: Eliminar containers completamente (tudo como corrotinas)

Mover todos os agentes para corrotinas assíncronas no processo principal, sem Docker.

**Descartado porque:**
- O Developer Agent precisa de isolamento para execução de código arbitrário (PythonSandbox)
- O Researcher Agent com sessão longa se beneficia do isolamento de memória do container
- Sem containers, o footprint de memória do processo principal seria incontrolável

---

## Consequências

### Positivas

- **Overhead de containers ~70% menor:** De ~15 containers na fase de planejamento para 2 containers por sessão (Researcher + Developer) + 1 Validator como corrotina.
- **Modelo adequado por papel:** Researcher e Developer usam modelo capaz; Validator usa modelo leve e rápido.
- **Contexto persistente:** Containers por sessão mantêm histórico em memória entre subtarefas — sem amnésia entre tool calls.
- **Researcher com contexto científico:** Absorver o Planner permite que o Researcher use o contexto de domínio para decompor tarefas adequadamente.

### Negativas / Trade-offs

- **Refatoração significativa:** `autonomous_loop.py` precisará de cirurgia para extrair e redirecionar chamadas de Planner/Validator.
- **Novos Dockerfiles:** Researcher e Developer precisam de imagens dedicadas.
- **Transição de ciclo de vida:** Containers por sessão requerem gerenciamento explícito de início/fim da sessão.

---

## Dependências de Implementação

```
V14.1 (Model Router) → pré-requisito de tudo
V14.2 (Validator como corrotina) → depende de V14.1
V14.3 (Researcher absorve Planner) → depende de V14.1
V14.4 (Developer Agent) → depende de V14.1, V14.3
V14.5 (Containers por sessão) → depende de V14.2, V14.3, V14.4
```

---

## Revisão

Este ADR foi formalmente aceito e implementado na V14 através das 6 entregas:
- **V14.1 (Model Router):** Suporte a roteamento granular de provedor e modelo por papel (`researcher`, `validator`, `developer`).
- **V14.2 (Validator como corrotina):** `ValidatorAgent` assíncrono executado no processo host sem containers, com validação de schema e checagem de artefatos em disco.
- **V14.3 (Researcher absorve Planner):** `ResearcherAgent` unificado com geração de DAG, replanejamento técnico e busca web contextual.
- **V14.4 (Developer Agent):** `DeveloperAgent` focado exclusivamente em execução de código e manipulação de arquivos com imagem Docker dedicada (`geminiclaw-developer`) e manifest awareness. `base_agent` marcado como depreciado.
- **V14.5 (Session Container Lifecycle):** `SessionContainerRunner` com containers persistentes por sessão, health check de 30s, auto-recuperação (circuit breaker de 2 retentativas) e encerramento gracioso via IPC (`shutdown`/`shutdown_ack`).
- **V14.6 (Comandos CLI e SIGINT):** Comandos `geminiclaw sessions` e `geminiclaw stop [--session <id>]`, além de handler SIGINT para encerramento gracioso de containers de sessão.
