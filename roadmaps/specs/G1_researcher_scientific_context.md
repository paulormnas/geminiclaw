# Spec G1 — Researcher Agent: Contexto Científico e Decomposição de Tarefas Experimentais

**Versão:** V15.1
**Status:** Proposta aprovada — aguardando implementação de V14
**Gap:** G1 — Researcher Agent sem contexto científico
**ADRs relacionados:**
  - [ADR 001](../../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md) — Propósito como harness de execução
  - [ADR 007](../../docs/decisions/adr_007_reestruturacao_papeis_agentes.md) — Reestruturação de papéis

---

## Objetivo

Dotar o Researcher Agent de vocabulário e raciocínio sobre metodologia científica experimental,
habilitando-o a operacionalizar corretamente contexto de artigos e dados fornecidos pelo pesquisador
humano, em vez de decompor tarefas de forma genérica como um agente de propósito geral.

O Researcher Agent deve entender *tipos de experimento científico*, *dependências metodológicas*
entre etapas, e a distinção entre análise exploratória, análise confirmatória e reprodução de
resultados publicados.

---

## Dependências

- **V14 concluído:** O Researcher Agent deve existir como entidade separada com container próprio (V14.3)
- **V14.1 concluído:** Model Router operacional — Researcher usa modelo remoto capaz (ex: Gemini 2.5 Flash)
- **G9 implementado:** `input_context/` pipeline disponível para que o Researcher receba contexto estruturado

---

## Contexto e Problema

O Planner/Researcher atual decompõe tarefas como um agente de software genérico. Quando recebe:

> "Reproduza a análise de classificação da Seção 3 do artigo usando Random Forest"

Ele gera planos como: `[pesquisar → analisar → codificar → relatar]` — sem considerar que uma
tarefa de reprodução científica requer: validar os dados de entrada, implementar exatamente os
hiperparâmetros descritos, confrontar métricas com os valores da tabela de resultados, e documentar
qualquer divergência com hipótese de causa.

**Impacto observado:** Planner precisou de 7 tentativas porque o modelo local não tinha
capacidade de decomposição adequada *e* não sabia o que era esperado de uma reprodução experimental.

---

## Tarefas

### Tarefa 1: Reescrever system prompt do Researcher Agent com epistemologia científica

- **Módulos afetados:** `agents/researcher/agent.py`
- **Complexidade estimada:** Baixa (apenas texto — nenhuma linha de código Python)
- **Critérios de aceite:**
  - [ ] System prompt inclui seção `MODO DE OPERAÇÃO` declarando que o agente recebe contexto
        pré-curado e nunca busca literatura de forma autônoma (conforme ADR 001)
  - [ ] System prompt inclui seção `TIPOS DE TAREFA` com os 5 tipos experimentais:
        `REPRODUÇÃO`, `EDA`, `IMPLEMENTAÇÃO DE MODELO`, `VALIDAÇÃO`, `SÍNTESE`
  - [ ] System prompt inclui seção `ESTRUTURA DO PLANO` com os campos obrigatórios de cada
        subtarefa (incluindo `hypothesis`, `scientific_rationale`, `validation_criteria`)
  - [ ] System prompt inclui seção `REGRA DE DÚVIDA`: antes de gerar o plano, se o contexto
        tiver ambiguidade bloqueante → usar `ask_researcher`; se tiver padrão claro na
        literatura → usar o padrão e documentar; nunca inventar
  - [ ] Teste manual: dada uma tarefa de reprodução com artigo em `input_context/`, o plano
        gerado contém campo `hypothesis` em todas as subtarefas
  - [ ] Teste manual: dada uma tarefa de EDA sem critérios explícitos, o plano gera subtarefas
        cobrindo distribuição, outliers, correlações e visualizações — sem consultar pesquisador

### Tarefa 2: Adicionar tipagem dos tipos de experimento ao schema do plano

- **Módulos afetados:** `src/autonomous_loop.py`, `src/schemas.py` (ou equivalente)
- **Complexidade estimada:** Baixa-Média
- **Critérios de aceite:**
  - [ ] `SubTask` tem campo opcional `task_type: Literal["reproduction", "eda", "model_impl", "validation", "synthesis"]`
  - [ ] `SubTask` tem campo obrigatório `hypothesis: str` — descrição do que a subtarefa testa ou produz
  - [ ] `SubTask` tem campo obrigatório `scientific_rationale: str` — por que esta etapa é necessária
  - [ ] Validator Agent (V14.2) valida que `hypothesis` e `scientific_rationale` não são strings vazias
  - [ ] Schema retrocompatível: subtarefas sem esses campos (do Researcher atual) recebem valores
        default para não quebrar execuções durante transição

### Tarefa 3: Enriquecer o prompt de replanejamento com raciocínio científico

- **Módulos afetados:** `agents/researcher/agent.py` (método `replan`)
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] Prompt de `replan` instrui o agente a identificar se a falha é: (a) problema de dados,
        (b) problema de implementação, (c) resultado legítimo divergente do artigo
  - [ ] Quando tipo (c): `replan` não tenta "forçar" o resultado — gera plano de documentação
        da divergência com `task_type: "validation"`
  - [ ] Subtarefas já concluídas com sucesso não são redefinidas no novo plano
  - [ ] Teste: subtarefa de treino falha 3x → replan identifica como divergência e gera
        subtarefa de documentação em vez de nova tentativa de treino

### Tarefa 4: Testes unitários do schema enriquecido

- **Módulos afetados:** `tests/unit/test_schemas.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] Teste: subtarefa com `hypothesis` vazia → `ValidationResult.approved = False`
  - [ ] Teste: subtarefa sem `scientific_rationale` → aceita (campo opcional retrocompatível)
  - [ ] Teste: subtarefa `task_type="reproduction"` → Validator verifica que `validation_criteria`
        contém ao menos 1 critério quantitativo (métrica com threshold numérico)
  - [ ] Teste: subtarefa `task_type="eda"` → Validator aceita `validation_criteria` qualitativo

---

## Validação da Etapa

- [ ] `uv run pytest -m "unit" -v` — todos os testes unitários passam
- [ ] Execução de smoke test com tarefa de reprodução: plano contém `hypothesis` em todas as subtarefas
- [ ] Execução de smoke test com tarefa de EDA: plano cobre as 4 categorias de análise sem consultar pesquisador
- [ ] ADR 007 referenciado corretamente no system prompt do Researcher Agent
- [ ] PR merged em `dev`

---

## Arquivos

| Arquivo | Ação | Descrição |
|---|---|---|
| `agents/researcher/agent.py` | MODIFY | Reescrever system prompt com epistemologia científica |
| `src/schemas.py` | MODIFY | Adicionar campos `hypothesis`, `scientific_rationale`, `task_type` ao `SubTask` |
| `src/autonomous_loop.py` | MODIFY | Usar novos campos no dispatch e na geração de contexto |
| `tests/unit/test_schemas.py` | MODIFY | Adicionar testes dos novos campos |
