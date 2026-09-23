# Spec G2 — Developer Agent: Contratos de Código Reproduzível

**Versão:** V15.2
**Status:** Proposta aprovada — aguardando implementação de V14
**Gap:** G2 — Prompts sem metodologia reproduzível
**ADRs relacionados:**
  - [ADR 007](../../docs/decisions/adr_007_reestruturacao_papeis_agentes.md) — Developer Agent separado
  - [ADR 008](../../docs/decisions/adr_008_workspace_manifest_session_scoped.md) — Workspace Manifest

---

## Objetivo

Garantir que todo código gerado pelo Developer Agent em contexto de pesquisa científica seja
**reproduzível por padrão**: documentado com hipótese e propósito científico, com parâmetros
persistidos em arquivo estruturado, com seed de aleatoriedade controlada, e com métricas
salvas em formato legível por máquina.

O objetivo não é apenas "código que funciona" — é **código que um outro pesquisador pode
reexecutar e obter os mesmos resultados**, ou compreender exatamente por que os resultados
divergem.

---

## Dependências

- **V14.4 concluído:** Developer Agent existe como entidade separada do `base_agent`
- **V14.3 / G1 implementados:** Plano gerado pelo Researcher contém campos `hypothesis` e
  `scientific_rationale` que o Developer usa para preencher as docstrings
- **V13 concluído:** WorkspaceManifest disponível para rastrear artefatos produzidos

---

## Contexto e Problema

O Developer Agent atual gera código funcional mas não rastreável:
- Sem `random_state` fixo → execuções não reproduzíveis
- Sem docstring de experimento → o código não documenta o que está testando
- Sem `params.json` → parâmetros usados são perdidos entre execuções
- Sem `metrics.json` → resultados ficam apenas no stdout do processo

Isso cria um ciclo vicioso: o Validator não tem métricas em arquivo para checar, então avalia
apenas `response_text` — que frequentemente é otimista ou impreciso.

---

## Tarefas

### Tarefa 1: Adicionar Contrato de Código Científico ao system prompt do Developer Agent

- **Módulos afetados:** `agents/developer/agent.py`
- **Complexidade estimada:** Baixa (apenas texto)
- **Critérios de aceite:**
  - [ ] System prompt inclui seção `PADRÃO DE CÓDIGO CIENTÍFICO REPRODUZÍVEL` com instruções obrigatórias
  - [ ] Instrução 1 — DOCSTRING DE EXPERIMENTO: todo script deve ter docstring no módulo com campos
        `Experimento`, `Hipótese`, `Dataset`, `Parâmetros`, `Critérios de sucesso`, `Seed`, `Referência`
  - [ ] Instrução 2 — RASTREABILIDADE: salvar `metrics.json` em `/outputs/<task_name>/metrics.json`
        e `params.json` em `/outputs/<task_name>/params.json` ao final de toda execução
  - [ ] Instrução 3 — CONTROLE DE SEED: incluir `np.random.seed(SEED)` e `random.seed(SEED)` no início
        de todo script que usa aleatoriedade; `SEED=42` como padrão salvo em `params.json`
  - [ ] Instrução 4 — HONESTIDADE DE RESULTADOS: se o resultado divergir do esperado, documentar
        em `metrics.json["divergence_note"]`; nunca ajustar dados para bater com o artigo
  - [ ] Instrução 5 — FORA DO ESCOPO: seção explícita declarando o que o Developer não faz
        (interpretação científica, decisão sobre qualidade para publicação, busca de literatura)
  - [ ] Smoke test: Developer gera script de ML → arquivo contém docstring de experimento
  - [ ] Smoke test: script usa `np.random.seed` e `params.json` é criado com campo `seed`

### Tarefa 2: Implementar helper `scientific_artifacts` no PythonSandbox

- **Módulos afetados:** `src/skills/code/sandbox.py`, `src/skills/code/scientific_helpers.py` (novo)
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `scientific_helpers.py` criado com função `save_experiment_artifacts(task_name, params, metrics, output_dir)`
  - [ ] `save_experiment_artifacts` salva `params.json` e `metrics.json` com schema padronizado:
        ```json
        {
          "task_name": "...",
          "session_id": "...",
          "timestamp": "ISO-8601",
          "seed": 42,
          "parameters": { ... },
          "metrics": { ... },
          "divergence_note": null
        }
        ```
  - [ ] `scientific_helpers.py` é injetado automaticamente no contexto do sandbox antes de executar
        scripts de ML/data science (detectado por imports de `numpy`, `pandas`, `sklearn`)
  - [ ] O LLM recebe instrução no prompt: "Use `save_experiment_artifacts()` ao final do script"
  - [ ] Testes unitários verificam que o JSON gerado tem todos os campos obrigatórios

### Tarefa 3: Atualizar o Validator Agent para validação científica de resultados

- **Módulos afetados:** `src/agents/validator_agent.py`
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `review_result()` verifica existência de `metrics.json` e `params.json` em disco antes
        de avaliar `response_text`
  - [ ] Se `metrics.json` existe: avalia `validation_criteria` contra valores reais do arquivo,
        não contra o texto da resposta
  - [ ] Se `validation_criteria` contém threshold numérico (ex: `"acurácia > 0.85"`): parse do
        threshold e comparação automática com `metrics.json["metrics"]["accuracy"]`
  - [ ] Se `metrics.json` tem `divergence_note` preenchido: resultado marcado como
        `ReviewResult.status = "divergent_but_documented"` — não como falha
  - [ ] Testes: subtarefa com `metrics.json` mostrando acurácia 0.87 e critério `> 0.85`
        → `ReviewResult.approved = True`
  - [ ] Testes: subtarefa sem `metrics.json` → `ReviewResult.approved = False` com issue
        `"metrics.json não encontrado em /outputs/<task_name>/"`

### Tarefa 4: Adicionar campos científicos ao WorkspaceManifest

- **Módulos afetados:** `src/workspace_manifest.py` (ou equivalente)
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] Manifest inclui por subtarefa: `params_path`, `metrics_path`, `seed_used`, `divergence_detected`
  - [ ] `divergence_detected: bool` é `True` quando `metrics.json["divergence_note"]` não é nulo
  - [ ] Manifest retrocompatível — subtarefas sem esses campos recebem `null`

### Tarefa 5: Testes de integração

- **Módulos afetados:** `tests/integration/agents/test_developer_agent.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] Cenário: Developer gera script de classificação → `params.json` e `metrics.json`
        encontrados em `/outputs/<task_name>/`
  - [ ] Cenário: `metrics.json["metrics"]["accuracy"]` é `float` (não string) e corresponde
        ao valor impresso no stdout do script
  - [ ] Cenário: Developer recebe subtarefa com `hypothesis` preenchido → docstring do script
        contém o texto da hipótese
  - [ ] Cenário: resultado diverge do `validation_criteria` → `divergence_note` preenchido,
        resultado não é suprimido

---

## Validação da Etapa

- [ ] `uv run pytest -m "unit or integration" -v` — todos os testes passam
- [ ] Pipeline Iris completo: `params.json` e `metrics.json` gerados para todas as subtarefas
- [ ] Validator aprova resultados lendo `metrics.json` (não apenas `response_text`)
- [ ] Relatório final inclui tabela de métricas lida do `metrics.json` (integração com G8)
- [ ] PR merged em `dev`

---

## Arquivos

| Arquivo | Ação | Descrição |
|---|---|---|
| `agents/developer/agent.py` | MODIFY | Adicionar contrato de código científico reproduzível ao system prompt |
| `src/skills/code/scientific_helpers.py` | NEW | Função `save_experiment_artifacts()` injetada no sandbox |
| `src/skills/code/sandbox.py` | MODIFY | Injetar `scientific_helpers.py` automaticamente para scripts científicos |
| `src/agents/validator_agent.py` | MODIFY | Validação contra `metrics.json`; reconhecer status `divergent_but_documented` |
| `src/workspace_manifest.py` | MODIFY | Adicionar campos `params_path`, `metrics_path`, `seed_used`, `divergence_detected` |
| `tests/unit/test_scientific_helpers.py` | NEW | Testes unitários de `save_experiment_artifacts()` |
| `tests/integration/agents/test_developer_agent.py` | MODIFY | Adicionar cenários de reprodutibilidade |
