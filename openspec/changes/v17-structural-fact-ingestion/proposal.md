# Proposta: Ingestão Determinística de Fatos Estruturais

**ID:** `v17-structural-fact-ingestion` · **Versão:** V17 · **Capacidade:** `knowledge-ingestion`
**ADRs de origem:** [ADR 009](../../../docs/decisions/adr_009_camada_conhecimento_experimental.md) §2,
[ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §1, §2, §5, §9.3

## Por quê

O ADR 015 separa **fatos** (o que aconteceu) de **conhecimento** (o que se aprendeu). Os fatos
— sessões, insumos, experimentos, resultados, abordagens aplicadas — já existem em disco
(`input_snapshot/`, `params.json`, `metrics.json`, resultado do Validator) e devem ir para o
grafo **pelo orquestrador, de forma determinística**, sem custo de tokens e sem risco de
alucinação. São as evidências que o Curator e o veredito usam.

## O que muda

- **Novo:** `src/knowledge/ingestion.py`, chamado pelo orquestrador em pontos fixos do ciclo:
  início de sessão, snapshot de insumos e conclusão (revisada) de cada subtarefa.
- **Modificado:** contrato de artefatos da Spec G2 — `save_experiment_artifacts` ganha os
  parâmetros opcionais `datasets` e `baselines`, e o plano do Researcher ganha o campo
  opcional `approach` por subtarefa.
- **Novo:** classificação determinística da **causa** de falhas (`infraestrutura`,
  `abordagem`, `ambigua`) e assinatura da falha — insumo do tratamento de inconclusivos (§9.3).
- **Novo:** fila local de reenvio quando o grafo está indisponível (a sessão nunca para por
  falha do grafo) e comando `geminiclaw knowledge sync`.
- **Fora do escopo:** `Hipotese` formal, `Decisao`, `Descoberta`, arestas
  `SUSTENTA`/`REFUTA` (Curator e ciclo de hipóteses).

## Impacto

- **Código:** `src/knowledge/ingestion.py` (novo), `src/orchestrator.py`,
  `src/autonomous_loop.py`, `src/skills/code/scientific_helpers.py`,
  `src/skills/code/sandbox.py` (códigos de saída/erros), `agents/researcher/agent.py` (campo
  `approach` no formato do plano), `agents/developer/agent.py` (instrução de `datasets`/
  `baselines`), `src/orchestrator.py::AgentTask` (campo `approach`), `src/cli.py`.
- **Contratos:** acréscimos opcionais e retrocompatíveis em `params.json`/`metrics.json` e no
  JSON do plano.

## Aprovações necessárias

Nenhuma alteração de schema relacional (a fila local é arquivo no diretório da sessão).
