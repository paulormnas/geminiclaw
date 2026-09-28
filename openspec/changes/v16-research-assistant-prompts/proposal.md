# Proposta: Prompts Alinhados ao Assistente Digital de Pesquisa

**ID:** `v16-research-assistant-prompts` · **Versão:** V16 · **Capacidade:** `agent-prompts`
**ADRs de origem:** [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md),
[ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) (nome do projeto),
[ADR 014](../../../docs/decisions/adr_014_agentes_em_processo_sandbox_codigo.md)

## Por quê

As instruções de sistema ainda descrevem o sistema do ADR 001. O Researcher se apresenta como
"um harness de execução de pesquisa científica (ADR 001)"; o Developer, como "executando em um
container Docker isolado" (falso após o ADR 014); todos os prompts repetem o nome
"GeminiClaw", que será trocado (ADR 011). Os prompts precisam refletir o novo propósito antes
que o grafo (V17) e o ciclo de hipóteses (V18) sejam construídos sobre eles.

## O que muda

- **Modificado:** instrução do Researcher — passa a se apresentar como assistente de pesquisa
  que **formula hipóteses** a partir dos insumos do pesquisador e dos resultados obtidos; a
  proibição de busca bibliográfica permanece; referências ao ADR 001 passam ao ADR 010.
- **Modificado:** instrução do Developer — sem menção a container próprio; deixa claro que o
  código roda **somente** pela skill de código (sandbox).
- **Modificado:** Validator, Summarizer, Reviewer e agente base — referências ao ADR 001 e ao
  Google ADK removidas; propósito atualizado.
- **Novo:** nome do produto centralizado em `config.APP_NAME` (default `GeminiClaw`) e
  inserido nos prompts por template; identificadores internos de agente derivados do papel
  (`researcher`, `developer`...) sem prefixo do nome do produto.
- **Novo:** teste de regressão que impede o nome literal do produto e referências ao ADR 001
  nos prompts.
- **Fora do escopo:** comportamento do ciclo de hipóteses (V18); instruções do Curator (V17).

## Impacto

- **Código:** `agents/*/agent.py` (instruções e `AGENT_NAME`), `src/agents/validator_agent.py`,
  `src/config.py`, `src/cli.py` (banner, se usar o nome).
- **Contratos:** o formato JSON do plano **não** muda nesta mudança.
- **Risco:** mudanças de prompt alteram o comportamento do LLM — validar com sessões de
  referência (tarefa 4).

## Aprovações necessárias

Nenhuma alteração de schema ou infraestrutura.
