# Proposta: Memória de falhas apresentada ao Developer

**ID:** `v18.9-failure-memory` · **Versão:** V18.9

**Capacidades:** `agent-prompts`

**ADRs de origem:** [ADR 026](../../../docs/decisions/adr_026_memoria_por_registros_de_resultado.md) §5.

**Depende de:** nada (lê `Experimento.causa_falha` e `assinatura_falha`, que já existem). Pode ser implementada em paralelo a `v18.9-result-records`.

## Por quê

O sistema já classifica cada falha de forma determinística (`failure_cause.classify_failure`), mas o Developer não recebe essas falhas. Assim, repete os mesmos erros de pacote, de memória ou de formato do `metrics.json`. Um registro global de falhas compartilhado entre os ramos da busca levou as execuções válidas de 81% para 100% e as falhas repetidas de 46% para 7,8% em 9 tarefas tabulares ("Recovering Wasted Compute", COLM 2026).

## O que muda

### Novo
- Módulo `src/knowledge/failure_memory.py`, que monta a memória de falhas do projeto a partir dos `Experimento` com causa `abordagem` ou `infraestrutura` e assinatura conhecida. A memória tem duas partes:
  - **ambiente:** assinaturas ligadas a ambiente, pacotes, dados e recursos;
  - **por abordagem.**
- Bloco `memoria_de_falhas` no prompt do Developer, em texto "NÃO / USE", via `wrap_data`, com teto `FAILURE_MEMORY_MAX_CHARS` (padrão 1500).
- Evento `memoria_falhas_aplicada` com o número de itens e de caracteres.

### Fora do escopo
- `Restricao` (decisão do pesquisador, ADR 021 §5.5), que não muda.
- Memória entre projetos, que é de `v18.9-cross-project-context`.

## Impacto
- **Código:** `src/knowledge/failure_memory.py` (novo) e montagem do prompt do Developer (`src/agents/developer/agent.py` ou o ponto que monta a instrução da subtarefa).
- **Schema e custo:** nenhuma mudança de schema. O prompt cresce até 1500 caracteres.

## Aprovações necessárias
Nenhuma (sem schema, Dockerfile ou exclusão).
