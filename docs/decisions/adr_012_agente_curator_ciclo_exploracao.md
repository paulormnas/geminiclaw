# ADR 012 — Agente Curator e Ciclo de Exploração Contínua

**Status:** Aceito — implementado (Curator, ciclo de hipóteses, continuidade, limites de uso); validação em AGE real pendente (aprovado em 2026-10-01 pelo pesquisador responsável; atualizado em 2026-10-08)
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw)
**ADRs relacionados:** ADR 007 (papéis), ADR 009 (conhecimento experimental), ADR 010 (propósito), ADR 014 (agentes em processo)


## Estado da implementação (2026-10-08)

| Mudança OpenSpec | Estado | PR |
|---|---|---|
| [`v17-curator-agent`](../../openspec/changes/v17-curator-agent/proposal.md) | Implementada, com pendências | #106 |
| [`v18-researcher-consult`](../../openspec/changes/v18-researcher-consult/proposal.md) | Implementada, com pendências | #97 |
| [`v18-research-continuity`](../../openspec/changes/v18-research-continuity/proposal.md) | Implementada, com pendências | #108 |
| [`v18-hypothesis-loop`](../../openspec/changes/v18-hypothesis-loop/proposal.md) | Implementada, com pendências | #109, #115 |
| [`v18-usage-limits`](../../openspec/changes/v18-usage-limits/proposal.md) | Implementada, com pendências | #68 |

---

## Contexto

O ADR 009 decidiu que os agentes constroem ativamente um grafo de conhecimento experimental.
Faltava decidir **quem** faz esse registro e **como** ele alimenta a continuidade da
pesquisa.

Hoje:

- O Validator avalia resultados; o Researcher planeja e replaneja; o Developer executa.
  Nenhum papel tem a responsabilidade de consolidar o que foi aprendido.
- As decisões de caminho no DAG (por que uma abordagem foi escolhida e não outra) não são
  registradas em lugar nenhum.
- O loop autônomo termina após um número fixo de tentativas de replanejamento
  (`MAX_PLAN_RETRIES`) e circuit breakers, não por decisão de exploração.
- A comunicação entre agentes é sempre mediada pelo orquestrador, em ciclos
  request/response (ADR 004). A exceção é o `ask_researcher` (Spec G5), que já envia
  mensagens no meio de uma execução.

---

## Decisão

### 1. Novo papel: Curator

Criar um agente **Curator** com um papel claro e contido: **explorar os resultados da
pesquisa e registrar as descobertas como memória experimental** (ADR 009). Um papel dedicado
é mais fácil de controlar, testar e auditar do que distribuir essa responsabilidade entre os
agentes existentes.

O Curator registra, entre outros:

- **O que funcionou bem** e em quais condições.
- **O que não funcionou**, com o mesmo rigor.
- **Oportunidades a explorar** — caminhos promissores ainda não testados.
- **Resultados da exploração do DAG** — por que um caminho foi seguido e outro não.

Para o último item, o Researcher Agent passa a **registrar a justificativa de cada decisão
de caminho** ao planejar e replanejar, para que o Curator possa consolidá-la.

Antes de criar qualquer nó, o Curator revisa minuciosamente o que já existe, evitando
duplicações e criando apenas nós significativos — que apontem novos caminhos de pesquisa ou
documentem caminhos explorados, inclusive os que ficaram sem conclusão. As diretrizes
detalhadas estão no ADR 015 §10.

### 2. Qualquer agente pode sinalizar ao Curator

Researcher, Developer e Validator podem **indicar ao Curator** algo novo e importante que
identificarem durante o trabalho. O Curator decide o que registrar — a responsabilidade pelo
conteúdo do grafo permanece concentrada nele.

### 3. O Curator orienta o Researcher

O Curator pode **indicar novos caminhos ao Researcher Agent**, com base no que observou nos
resultados e no conhecimento acumulado. O Researcher decide se e como incorporá-los ao plano.

### 4. Comunicação ativa e contínua

Curator e Researcher trabalham em **ciclo ativo**: exploram, registram, sugerem e replanejam
continuamente, até que:

- **uma solução seja encontrada**, ou
- **um limite de uso definido pelo pesquisador responsável seja atingido**.

A comunicação continua **mediada pelo orquestrador**, que registra todas as mensagens. Com
os agentes rodando como processo no host (ADR 014), essas trocas são baratas. O padrão de
mensagens no meio da execução, já usado pelo `ask_researcher` (Spec G5), é o precedente para
as novas mensagens (sinalizações ao Curator e sugestões ao Researcher).

### 5. Limites de uso definidos pelo pesquisador responsável

O ciclo de exploração é sempre limitado por orçamento configurável pelo pesquisador
responsável, incluindo no mínimo:

- **Tokens** consumidos.
- **Tempo** de sessão.
- **Retentativas da mesma tarefa.**
- **Retentativas de conexão** (com provedores, sandbox ou serviços).

Os limites operacionais da Spec G5 (tokens, custo, duração, containers) hoje apenas **avisam**
o pesquisador. Aqui eles passam a ser também **condições de parada** do ciclo. A unificação
entre avisos e limites de parada será definida na spec.

Atingir um limite **interrompe a execução, não a pesquisa**: todo o avanço — incluindo as
descobertas do Curator e as sugestões ainda não exploradas — é registrado para que a próxima
execução continue de onde parou (ADR 010, "Continuidade entre execuções").

### 6. Fora do escopo deste ADR

Ficam para as specs: o formato das mensagens entre agentes, o momento exato em que o Curator
atua no ciclo, qual modelo usa, e
os critérios para considerar que "uma solução foi encontrada". O modelo de dados do grafo
continua fora do escopo, conforme o ADR 009.

### 7. O Curator decide quando registrar

O Curator é quem decide **quando** registrar no grafo e **o quê**, aplicando as diretrizes do
ADR 015 §10. Fatos estruturais continuam sendo gravados pelo orquestrador de forma
determinística (ADR 015 §1); o Curator entra no fluxo da sessão em pontos definidos na spec
(fim de experimento, checkpoint e fechamento).

### 8. Consulta ao Researcher nos modos autônomos

Nos modos `semi` e `auto`, quando um agente chama `ask_researcher`, o **Researcher responde no
lugar do pesquisador humano**, podendo fazer consultas simples na internet para enriquecer o
contexto e decidir (documentação, definições, valores usuais; não buscas de artigos). A pergunta,
o motivo, a resposta e as fontes são registrados como mensagem mediada pelo orquestrador, para
avaliar depois se a consulta foi relevante e se mudou a decisão do agente. Em `assisted`, a
pergunta continua indo ao pesquisador humano. Valem o limite de uso do §5 e o ADR 019 §3 (sem
dados brutos de pesquisa nas consultas). *(Decisão do pesquisador responsável, 2026-10-01.)*

---

## Alternativas Consideradas

### Alternativa A: O Validator registra os resultados validados

**Descartado porque:** misturaria julgar resultados com modelar conhecimento, e o Validator
não observa as decisões de caminho do Researcher.

### Alternativa B: O Researcher lê e escreve o grafo

**Descartado porque:** o Researcher já é o papel mais carregado (planejamento, replanejamento,
pesquisa técnica). Concentrar também a curadoria dificultaria controlar a qualidade do grafo.

### Alternativa C: Comunicação direta entre agentes, sem mediação

**Descartado porque:** perderia a rastreabilidade centralizada do orquestrador e o controle
dos limites de uso.

---

## Consequências

### Positivas

- Responsabilidade clara pelo conteúdo do grafo — mais fácil de auditar e corrigir.
- Decisões de caminho passam a ser memória reaproveitável, não apenas logs.
- A pesquisa continua enquanto houver caminhos promissores, e não por um número fixo de
  replanejamentos.
- O pesquisador responsável controla o custo por meio de limites explícitos.

### Negativas / Trade-offs

- **Mais um papel** para manter, com prompt e testes próprios.
- **Mais chamadas LLM por sessão:** o Curator consome orçamento; os limites de uso precisam
  contabilizá-lo.
- **Risco de loop improdutivo:** Curator e Researcher podem se realimentar sem progresso. Os
  limites de uso e o circuit breaker de progresso zero (V12.5.1) continuam necessários.
- **Novos tipos de mensagem entre agentes**, com validação estrita.

---

## Revisão

Este ADR deve ser revisado quando:
- O modelo de dados do grafo for definido.
- A spec do ciclo de hipóteses (V18) detalhar a interação Curator ↔ Researcher.
- A federação (ADR 013) exigir que o Curator publique conhecimento para outros nós.
