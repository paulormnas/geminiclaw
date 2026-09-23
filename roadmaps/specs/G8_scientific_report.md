# Spec G8 — Relatório Científico Estruturado com Conversão de Formatos

**Versão:** V15.4
**Status:** Proposta aprovada — aguardando implementação de V14
**Gap:** G8 — Relatório do Summarizer sem estrutura acadêmica
**ADRs relacionados:**
  - [ADR 001](../../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md) — Propósito como harness
  - [ADR 008](../../docs/decisions/adr_008_workspace_manifest_session_scoped.md) — Workspace Manifest

---

## Objetivo

Garantir que toda sessão produza obrigatoriamente um **relatório científico estruturado em Markdown**
com rastreabilidade completa: hipóteses, metodologia, resultados, divergências investigadas,
decisões do pesquisador e metadados de execução. Adicionar arquitetura de conversão de formatos
(LaTeX, DOCX, HTML) como comandos sob demanda, com templates e interfaces já preparadas.

---

## Dependências

- **V14 concluído:** Summarizer Agent ou equivalente disponível
- **G2 implementado:** `metrics.json` e `params.json` produzidos pelo Developer Agent
- **G5 implementado:** `researcher_interactions` persistidos no `SessionManager`
- **G9 implementado:** `input_snapshot/` disponível para referência no relatório

---

## Contexto e Problema

O Summarizer atual produz Markdown livre sem seções fixas. O resultado é:
- Sem resumo executivo — pesquisador não tem visão rápida dos resultados
- Sem tabela de métricas — comparação com artigo de referência é manual
- Sem registro de decisões — por que Z-score foi usado em vez de min-max não fica documentado
- Sem limitações identificadas — divergências não explicadas ficam enterradas no log
- Sem metadados de execução — custo, tempo e tokens são perdidos após a sessão

---

## Tarefas

### Tarefa 1: Reescrever system prompt do Summarizer com template obrigatório

- **Módulos afetados:** `agents/summarizer/agent.py` (ou `src/agents/summarizer_agent.py`)
- **Complexidade estimada:** Baixa (principalmente prompt engineering)
- **Critérios de aceite:**
  - [ ] System prompt inclui template de seções obrigatórias:
        `Resumo Executivo`, `Contexto e Objetivo`, `Metodologia`, `Resultados`,
        `Análise das Divergências`, `Decisões do Pesquisador`, `Limitações Identificadas`,
        `Próximos Passos Sugeridos`, `Metadados de Execução`
  - [ ] Seção `Resultados` inclui instrução: "leia `metrics.json` de cada subtarefa e
        construa tabela comparativa; se artigo de referência forneceu valores esperados,
        inclua coluna 'Valor Esperado' e calcule divergência percentual"
  - [ ] Seção `Decisões do Pesquisador` instrui: "leia `researcher_interactions` do
        `session_metadata.json` e popule a tabela — não reconstrua de memória"
  - [ ] Seção `Próximos Passos` instrui: "sugira extensões baseadas nos resultados obtidos;
        se houver divergências não resolvidas, sugira experimentos para investigá-las"
  - [ ] Teste: sessão com 2 subtarefas → relatório tem seções obrigatórias presentes
  - [ ] Teste: sessão com divergência documentada → relatório tem seção `Análise das Divergências`
        preenchida (não vazia)

### Tarefa 2: Implementar leitura de artefatos para população do relatório

- **Módulos afetados:** `agents/summarizer/agent.py`, `src/report/artifact_reader.py` (novo)
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `ArtifactReader` lê `metrics.json` e `params.json` de cada subtarefa antes de
        iniciar a sumarização; injeta os dados no contexto do Summarizer
  - [ ] `ArtifactReader` lê `session_metadata.json` para popular `Decisões do Pesquisador`
        e `Metadados de Execução`
  - [ ] `ArtifactReader` lê `input_snapshot/` para identificar artigos e dados de referência
        usados (para a seção `Contexto e Objetivo`)
  - [ ] Tabela de métricas no relatório é construída de dados reais de `metrics.json`,
        **não** de texto gerado pelo LLM
  - [ ] Testes: `ArtifactReader` com 3 subtarefas → retorna dict com métricas de cada uma

### Tarefa 3: Salvar relatório final como artefato da sessão

- **Módulos afetados:** `src/output_manager.py`, `src/session_manager.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] `relatorio_final.md` salvo em `/outputs/<session_id>/relatorio_final.md` ao final de toda sessão
  - [ ] `session_metadata.json` salvo em `/outputs/<session_id>/session_metadata.json` com schema:
        ```json
        {
          "session_id": "...",
          "task": "...",
          "mode": "assisted|semi|auto",
          "started_at": "ISO-8601",
          "ended_at": "ISO-8601",
          "duration_seconds": 1112,
          "subtasks": [...],
          "researcher_interactions": [...],
          "token_usage": {...},
          "cost_usd": 2.34,
          "containers_used": 12,
          "report_path": "relatorio_final.md"
        }
        ```
  - [ ] `relatorio_final.md` registrado no `WorkspaceManifest` como artefato da sessão
  - [ ] Testes: ao final da sessão, ambos os arquivos existem em `/outputs/<session_id>/`

### Tarefa 4: Implementar arquitetura de conversão de formatos

- **Módulos afetados:** `src/report/__init__.py` (novo), `src/report/base_converter.py` (novo),
  `src/report/latex_converter.py` (novo), `src/report/html_converter.py` (novo),
  `src/report/docx_converter.py` (novo)
- **Complexidade estimada:** Alta
- **Critérios de aceite:**

  **Interface base:**
  - [ ] `ReportConverter(ABC)` com método abstrato `convert(markdown_path: Path, output_path: Path) -> None`
  - [ ] Factory: `ReportConverterFactory.create(format: str) -> ReportConverter`

  **LaTeXConverter:**
  - [ ] Converte Markdown → LaTeX usando template `article` class com `\documentclass{article}`
  - [ ] Tabelas Markdown → `tabular` LaTeX com `booktabs`
  - [ ] Código → `lstlisting` com highlighting
  - [ ] Seções → `\section{}` / `\subsection{}`
  - [ ] Implementação via `pandoc` (se disponível) ou `markdown-it` + templates Jinja2

  **HTMLConverter:**
  - [ ] Converte Markdown → HTML estático com CSS acadêmico embutido
  - [ ] Responsivo, legível para impressão (media query `@print`)

  **DOCXConverter:**
  - [ ] Converte Markdown → DOCX via `python-docx` com template acadêmico
  - [ ] Preserva estrutura de seções, tabelas e listas

  **Todos os conversores:**
  - [ ] Conversão invocável por `geminiclaw convert --session <id> --format <fmt>`
  - [ ] Arquivo gerado salvo ao lado do `relatorio_final.md`
  - [ ] Testes unitários: cada conversor produz arquivo não-vazio a partir de Markdown de teste

### Tarefa 5: Adicionar comando `convert` ao CLI

- **Módulos afetados:** `src/cli.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] `geminiclaw convert --session <id> --format latex|html|docx` funciona
  - [ ] Se sessão não encontrada → erro descritivo: "Sessão '<id>' não encontrada em /outputs/"
  - [ ] Se formato não suportado → erro descritivo com lista de formatos disponíveis
  - [ ] `geminiclaw convert --help` exibe exemplos de uso

---

## Validação da Etapa

- [ ] `uv run pytest -m "unit or integration" -v` — todos os testes passam
- [ ] Pipeline Iris completo → `relatorio_final.md` com todas as 9 seções presentes
- [ ] Tabela de métricas no relatório construída a partir de `metrics.json` reais (verificável por diff)
- [ ] `geminiclaw convert --format latex` produz arquivo `.tex` válido compilável com `pdflatex`
- [ ] `session_metadata.json` presente com `token_usage` e `cost_usd` preenchidos
- [ ] PR merged em `dev`

---

## Arquivos

| Arquivo | Ação | Descrição |
|---|---|---|
| `agents/summarizer/agent.py` | MODIFY | System prompt com template obrigatório e instrução de leitura de artefatos |
| `src/report/__init__.py` | NEW | Package de report |
| `src/report/artifact_reader.py` | NEW | `ArtifactReader` — lê métricas, params, interações de disco |
| `src/report/base_converter.py` | NEW | `ReportConverter` abstrato + `ReportConverterFactory` |
| `src/report/latex_converter.py` | NEW | `LaTeXConverter` |
| `src/report/html_converter.py` | NEW | `HTMLConverter` |
| `src/report/docx_converter.py` | NEW | `DOCXConverter` via `python-docx` |
| `src/output_manager.py` | MODIFY | Salvar `relatorio_final.md` e `session_metadata.json` ao final da sessão |
| `src/session_manager.py` | MODIFY | Incluir `researcher_interactions` no `session_metadata.json` |
| `src/cli.py` | MODIFY | Adicionar comando `convert` |
| `tests/unit/test_report_converters.py` | NEW | Testes unitários dos conversores |
| `tests/integration/test_summarizer_agent.py` | MODIFY | Verificar seções obrigatórias e dados reais |
