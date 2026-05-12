# Roadmap V10 — Estabilidade, Planejamento Incremental e Observabilidade de Execução

**Contexto:** A validação do pipeline de classificação Iris (benchmark principal) revelou três categorias críticas de falha que impedem o uso do sistema em produção:

1. **Sandbox de código quebrado** — O `python_interpreter` falha 100% das vezes quando invocado por agentes em containers Docker, devido a mapeamento incorreto de volumes no Docker-in-Docker (DinD).
2. **Planejamento destrutivo** — O ciclo Planner → Validator descartava planos inteiros a cada iteração, gerando centenas de tentativas sem progresso (184 subdiretórios em uma única execução). O mesmo ocorre no loop de execução: se uma subtarefa falha, todo o plano é descartado.
3. **Outputs e logs ilegíveis** — A estrutura atual cria subdiretórios aninhados opacos por sessão (UUID) e tarefa, tornando impossível acompanhar o estado de uma execução ou depurar falhas.

> **Escopo:** Este roadmap é focado em estabilização estrutural profunda (soluções definitivas) e melhoria incremental. Não introduz novas funcionalidades de IA, apenas resolve gargalos da infraestrutura MAS.

---

## Diagnóstico e Soluções Definitivas

### D1 — Sandbox DinD: `python: can't open file '/outputs/script.py'`

**Causa raiz:** O `PythonSandbox.run()` tenta montar o volume `/outputs` no container do sandbox usando caminhos absolutos do *host*. Porém, quando o orquestrador roda dentro de um container Docker (DinD), o daemon Docker local recebe um path que só existe dentro do container do agente, falhando silenciosamente e criando um volume vazio.

**Solução proposta original (Frágil):** Tentar descobrir o caminho original do host injetando variáveis de ambiente (`HOST_PROJECT_PATH`).
**Solução DEFINITIVA (Robusta):** **Eliminar bind mounts do Sandbox.** Como a comunicação com o daemon via socket Docker funciona perfeitamente, o `PythonSandbox` deve iniciar o container sem volumes montados e usar as APIs nativas `put_archive` e `get_archive` do Docker SDK para transferir o `script.py` para dentro e os artefatos para fora. Isso é 100% imune a problemas de caminhos DinD, redes de overlay ou SO base.

### D2 — Loop de Planejamento Destrutivo

**Problema:** O Planner é "stateless" (sem estado). Cada rejeição do Validator resulta em um prompt do zero. Além disso, no `autonomous_loop.py`, se a execução do plano falhar na tarefa 3 de 5, o orquestrador descarta o plano todo e recomeça da tarefa 1.

**Solução DEFINITIVA (Stateful Planning):** 
1. **No Planner/Validator:** O Validator não deve retornar texto livre, mas um array estruturado de issues (`[{"task_name": "x", "issue": "y"}]`). O Planner recebe o plano anterior + os issues específicos, e atua como "Editor", fazendo patches no plano em vez de reescrevê-lo.
2. **No Loop de Execução:** Se a execução falhar, o orquestrador passa as tarefas que tiveram sucesso, as que falharam e os logs de erro para o Planner. O Planner gera um plano de *recuperação* (mantendo os artefatos já gerados), evitando refazer trabalho.

### D3 — Estrutura de Logs e Outputs Ilegível

**Problema atual:** IDs opacos (ex: `cc2faf212845...`) com subdiretórios para cada agente e cada tarefa, ocultando os arquivos finais.
**Solução DEFINITIVA (Sessões Legíveis & Estrutura Plana):**
1. O UUID da sessão será substituído no momento da criação da solicitação por um slug legível com timestamp: `YYYYMMDD_HHMMSS_classificacao_iris`. Toda a estrutura de pastas herda essa legibilidade nativamente.
2. Mudar a estrutura para:
   ```
   outputs/20260512_103015_classificacao_iris/
   ├── plan.json                 ← O plano final consolidado
   ├── artifacts/                ← Pasta PLANA compartilhada onde todos os agentes gravam arquivos
   │   ├── dataset.csv
   │   └── model.pkl
   └── logs/                     ← Logs isolados por agente (evita concorrência de escrita)
       ├── orchestrator.log
       ├── planner.log
       └── reviewer.log
   ```

---

## Etapas de Implementação

### Etapa V10.1 — Sandbox Resiliente (No-Mount DinD)

**Objetivo:** Refatorar `PythonSandbox.run()` para usar transferência de arquivos por stream (tar archive) via Docker API, eliminando dependência de caminhos absolutos do host.

#### Tarefas:
- [x] Criar métodos auxiliares em `PythonSandbox` para empacotar texto/arquivos num buffer `.tar` em memória.
- [x] Alterar `run()` para iniciar o container do sandbox *sem* o parâmetro `volumes`.
- [x] Usar `container.put_archive("/outputs", tar_buffer)` para injetar o `script.py` antes de rodar o comando principal.
- [x] Após a execução, usar `container.get_archive("/outputs")` para extrair os artefatos gerados, descompactá-los na memória e salvá-los no `output_dir` local do agente.
- [x] Remover tentativas antigas de `chmod` e cálculos complexos de `pathlib`.
- [x] Criar testes unitários em `tests/unit/skills/test_sandbox_archive.py`.

### Etapa V10.2 — Identificadores de Sessão Legíveis e Estrutura Plana

**Objetivo:** Alterar a fundação da criação de sessões para usar slugs temporais e unificar os diretórios de saída.

#### Tarefas:
- [x] Criar função `generate_session_slug(prompt: str) -> str` (ex: `20260512_143000_crie_um_script_python`).
- [x] Atualizar o CLI (`src/cli.py`) e a API/Entrypoints para gerar o `session_id` usando essa função em vez de `uuid.uuid4().hex`.
- [x] Refatorar `OutputManager`:
  - [x] Garantir que `/outputs/<session_id>/artifacts` seja o único caminho de saída repassado aos agentes.
  - [x] O volume `/outputs` no `ContainerRunner` deve apontar sempre para a raiz de `artifacts` da sessão.
- [x] Refatorar Logger:
  - [x] O `setup_file_logging()` dos agentes em container deve salvar em `/logs/<agent_id>.log`.
  - [x] O `ContainerRunner` mapeia o volume `/logs` para `outputs/<session_id>/logs`.
- [x] Opcional: Adicionar comando CLI `uv run adk log <session_id>` para agregar os JSON-lines de `/logs/*.log` e exibi-los em ordem cronológica.

### Etapa V10.3 — Planejamento Incremental Estruturado

**Objetivo:** Converter o ciclo Planner/Validator de "destrutivo" para "patching", e permitir que o loop de execução recupere planos falhos de forma inteligente.

#### Tarefas:
- [x] **Instrução do Validator:** Alterar `agents/validator/agent.py` para não tentar corrigir o plano (`corrected_plan`), mas sim retornar uma lista rigorosa: `{"status": "revision_needed", "issues": [{"task_name": "x", "issue": "y"}]}`.
- [x] **Loop de Planejamento (`src/orchestrator.py`):**
  - Armazenar o `last_plan` (JSON object).
  - Na iteração de retry, compor o prompt: *"Este é o plano atual: {json}. O Validator apontou estes problemas: {issues}. Corrija apenas as tarefas com problemas. Retorne o plano completo atualizado."*
- [x] **Loop de Execução (`src/autonomous_loop.py`):**
  - Ao invés de abortar no final do DAG se houver `failed_tasks`, injetar o status da execução num prompt de replanejamento: *"O plano original era {plano}. As tarefas {X, Y} completaram com sucesso. A tarefa {Z} falhou com o erro: {erro}. Crie um novo plano focando apenas na recuperação e continuação a partir de {Z}, sem refazer {X, Y}."*
  - Substituir `max_plan_retries` global por um ciclo de `max_execution_recoveries = 3`. (Nota: Reaproveitado MAX_PLAN_RETRIES para este fim conforme alinhado com o usuário).

---

## Ordem de Execução Recomendada

1. **V10.1 (Sandbox)** — O mais isolado e crítico para o Code Skill voltar a funcionar imediatamente.
2. **V10.2 (Sessões Legíveis)** — Fundamental para a DX (Developer Experience). Sem isso, depurar os próximos passos será doloroso.
3. **V10.3 (Planejamento Stateful)** — O mais complexo, envolve prompts e lógica de DAG.
4. **Benchmark** — Executar o pipeline Iris para validar a resiliência completa do sistema.

---

## Resumo de Impacto

### Arquivos Modificados
- `src/skills/code/sandbox.py` — Remoção de `volumes` e adoção de `put_archive`/`get_archive`.
- `src/orchestrator.py` — Lógica stateful do planner e parser de issues do validator.
- `src/autonomous_loop.py` — Lógica de stateful recovery após falha de execução.
- `src/output_manager.py` — Criação do novo esquema de diretórios planos e slugs legíveis.
- `src/cli.py` (e points de entrada) — Geração antecipada de slugs de sessão.
- `src/runner.py` — Ajuste de volumes mapeados (pasta plana `artifacts`).
- `agents/validator/agent.py` — Instrução de output estruturado com issues.

### Arquivos Criados
- `tests/unit/skills/test_sandbox_archive.py`

---

## Critérios de Aceite Globais

1. O pipeline Iris executa do início ao fim sem falhas de sandbox no Pi 5, mesmo em arquitetura Docker-in-Docker.
2. Em caso de falha de validação ou de execução de um agente, o Planner não rescreve tarefas que já foram aprovadas ou executadas com sucesso.
3. A pasta `outputs/` contém apenas diretórios com nomes legíveis (ex: `20260512_143000_crie_um_script_python`).
4. Os artefatos finais do script Python, dados e logs estão todos disponíveis dentro dessa pasta, garantindo rastreabilidade perfeita.
