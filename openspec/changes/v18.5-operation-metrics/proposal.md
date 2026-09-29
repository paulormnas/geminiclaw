# Proposta: Métricas de Operação por Sessão e Modo Sem Limite

**ID:** `v18.5-operation-metrics` · **Versão:** V18.5 · **Capacidade:** `operation-metrics`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md)
§8 e §11; [ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §5;
[ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md)
("Continuidade entre execuções")

## Por quê

O ADR 019 cria duas garantias (o que saiu do nó e de onde veio cada número) e várias mudanças
V18.5 produzem os dados que as sustentam: registro de egresso, cadeia de execuções,
referências numéricas e status das afirmações. Falta um lugar único onde o pesquisador veja,
por sessão, **quanto saiu, para onde, quanto custou, quanto foi verificado e quanto ele
interveio** (§8). Sem isso, o custo real de cada configuração de provedores e a taxa de
retenção do filtro de saída ficam invisíveis, e a revisão do ADR 019 não tem base.

Além disso, os limites de uso da V18 (`v18-usage-limits`, já implementada) são sempre
condições de parada, e `UsageBudget` exige todos os limites positivos
(`src/usage.py:64-71`). O pesquisador decidiu (§11) que pode optar, de forma **explícita**, por
um **modo sem limite**, para que a pesquisa continue até encontrar um resultado, mantendo os
limites que protegem contra laços de falha e as regras de localidade.

Hoje também:

- O relatório final recebe as estatísticas de telemetria como texto para o Summarizer
  reescrever (`src/autonomous_loop.py:1478`, `src/telemetry.py:1075-1108`), o que contraria o
  §2 do ADR 019 (o LLM não escreve números medidos).
- Ctrl+C encerra o processo sem checkpoint (`src/cli.py:1102-1130`); interromper a sessão
  perde o avanço registrado desde o último ponto de gravação.
- Os avisos da Spec G5 leem `SESSION_MAX_TOKENS`/`SESSION_MAX_MINUTES` de `config` e não do
  orçamento efetivo da sessão (`src/autonomous_loop.py:267-290`), ignorando overrides da CLI.

## O que muda

- **Novo:** módulo `src/operation_metrics.py`, que **agrega** as métricas do §8 por sessão a
  partir dos produtores (outras mudanças V18.5 e a telemetria existente) e as grava em
  `agent_sessions.payload["operation_metrics"]` e em `session_metadata.json`.
- **Novo:** seção **"Métricas de operação"** no `relatorio_final.md`, renderizada pelo
  orquestrador (código determinístico), não pelo Summarizer.
- **Novo:** grupo indisponível é marcado como tal (mudança produtora ainda não implementada),
  nunca preenchido com zero.
- **Modificado:** `UsageBudget` aceita `unlimited=True`: sem limite de tokens, tempo, custo e
  volume de egresso; retentativas da mesma tarefa e de conexão mantêm limite.
- **Novo:** flag `--unlimited` na CLI (também em `resume`/`continue`) e marcação por projeto,
  sempre com confirmação no início da execução. Nunca por padrão, por variável de ambiente ou
  por agente.
- **Novo:** avisos periódicos de consumo no modo sem limite, com cadência configurável
  (`UNLIMITED_NOTICE_INTERVAL_MINUTES`, `UNLIMITED_NOTICE_TOKEN_STEP`).
- **Novo:** limite de volume de egresso integrado ao `UsageTracker` como condição de parada
  (`motivo_parada="limite_egresso"`) fora do modo sem limite.
- **Novo:** interrupção pelo pesquisador (primeiro Ctrl+C) executa o fechamento gracioso com
  checkpoint (`motivo_parada="interrompida_pesquisador"`), em qualquer modo.
- **Corrigido:** avisos G5 passam a ler o orçamento efetivo da sessão.

## Dependências

| Mudança | O que esta mudança consome |
|---|---|
| V18 (`v18-usage-limits`, `v18-research-continuity`, `v18-hypothesis-loop`) | `UsageBudget`/`UsageTracker`, fechamento, `checkpoint.json`, critérios de parada `solucao_encontrada` e `sem_caminhos_promissores` |
| `v18.5-egress-gate` | `egress_log` (volume por provedor, `trust`, `localidade`, `ContentOrigin`; intervenções do filtro; buscas e visão), `EGRESS_SESSION_MAX_BYTES` |
| `v18.5-model-catalog-locality` (via egress-gate) | `allocation_profile` para rotular provedor, `trust` e `localidade` |
| `v18.5-execution-provenance` | resultado de `provenance verify` e ponta da cadeia |
| `v18.5-numeric-references` (via claim-verification) | contagem de números por origem, `[não verificado]` e métricas literais |
| `v18.5-claim-verification` | afirmações por `status_afirmacao` e ciclos de correção |
| Spec G5 (implementada) | `researcher_interactions`, `divergence_reports`, suspensão |

Esta mudança **só agrega e apresenta**: não calcula egresso, não verifica cadeia, não conta
números nem classifica afirmações. Cada produtor expõe uma função de leitura por sessão
(design §3).

## Impacto

- **Código:** `src/operation_metrics.py` (novo), `src/usage.py`, `src/autonomous_loop.py`,
  `src/orchestrator.py`, `src/cli.py`, `src/telemetry.py`, `src/config.py`, `.env.example`,
  `src/knowledge/schema.py` (valores de `motivo_parada`).
- **Comportamento:** Ctrl+C passa a fechar com checkpoint (segundo Ctrl+C mantém o
  encerramento imediato atual). As estatísticas deixam de ser enviadas ao Summarizer.

## Aprovações necessárias

- **Nenhuma alteração de schema do PostgreSQL:** `operation_metrics` e os campos do modo sem
  limite ficam no payload JSONB de `agent_sessions`. As tabelas `egress_log` e
  `execution_records` pertencem a `v18.5-egress-gate` e `v18.5-execution-provenance`, que
  trazem as próprias aprovações.
- **Modelo do grafo (confirmar):** novos valores `limite_egresso` e
  `interrompida_pesquisador` no enum `Sessao.motivo_parada` (`src/knowledge/schema.py:127-136`),
  caso ainda não tenham sido acrescentados por outra mudança. Não altera tabela, mas altera o
  modelo de dados validado do ADR 015; pedir confirmação ao pesquisador na implementação.
- Nenhum Dockerfile, compose ou arquivo apagado.
