# Design: Prompts Alinhados ao Assistente Digital de Pesquisa

## Nome do produto

```python
# src/config.py
APP_NAME = get_env("APP_NAME", default="GeminiClaw")
```

- Prompts usam `{app_name}` e são renderizados por uma função única
  (`src/prompts.py::render_instruction(template, **extra)`), que injeta `APP_NAME`.
- `AGENT_NAME = "geminiclaw_researcher"` e similares passam a ser o papel (`"researcher"`);
  quem precisar de um identificador legível usa `f"{APP_NAME}:{role}"` em tempo de execução.
- **Fora do escopo** (registrado para a renomeação futura): nome do pacote no
  `pyproject.toml`, comando `geminiclaw`, coleções Qdrant e tabelas existentes. A renomeação
  destes exigirá migração própria.

## Mudanças de conteúdo por agente

| Agente | Arquivo | Mudança |
|---|---|---|
| Researcher | `agents/researcher/agent.py` | Abertura: "assistente de pesquisa científica que conduz experimentos, formula hipóteses, valida suposições e relata resultados (ADR 010)". Nova diretriz: hipóteses podem ser formuladas a partir dos insumos em `input_context/` e dos resultados de subtarefas anteriores, sempre com `scientific_rationale`. Mantém: proibição de busca bibliográfica (agora citando ADR 010), uso de `quick_search` só para dúvidas técnicas, tipos de tarefa, formato do plano, regras de `ask_researcher` e de replanejamento. |
| Developer | `agents/developer/agent.py` | Remove "executando em um container Docker isolado". Acrescenta: "todo código roda exclusivamente pela ferramenta de execução de código, em sandbox isolado; nunca proponha executar comandos no computador principal; dependências vão no parâmetro `packages`". |
| Base | `agents/base/agent.py` | Remove a instrução de `subprocess`/`pip` (já tratado em `v16-in-process-agents`; aqui só o texto de propósito). |
| Validator | `agents/validator/agent.py`, `src/agents/validator_agent.py` | Atualiza propósito; sem mudanças nos critérios de validação. |
| Summarizer | `agents/summarizer/agent.py` | Atualiza propósito; mantém estrutura do relatório G8. |
| Reviewer / Planner | `agents/reviewer/agent.py`, `agents/planner/agent.py` | Atualiza propósito e nome. |

A diretriz de formulação de hipóteses nesta versão é **textual**: o Researcher pode propor
hipóteses no campo `hypothesis` já existente. A governança por `SessionMode` (aprovação no
modo `assisted`) e o registro no grafo chegam em `v18-hypothesis-loop`.

## Teste de regressão de prompts

`tests/unit/test_prompt_policy.py` percorre todas as instruções renderizadas e verifica:

1. não contêm o valor literal `"GeminiClaw"` nos templates (apenas via `APP_NAME`);
2. não citam "ADR 001" nem "Google ADK";
3. não contêm `subprocess` nem `pip install`;
4. a instrução do Researcher contém a proibição de busca bibliográfica.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum. |
| Agentes & Prompts | Todas as instruções de sistema. |
| Sandboxes & Containers | Nenhum. |
| Persistência | Nenhum. |
| Segurança | Reforço textual de que nada executa no host. |
| Testes & Telemetria | Novo teste de política de prompts; sessões de referência para comparar comportamento. |
