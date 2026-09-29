# Proposta: Verificação das Conclusões por Afirmações

**ID:** `v18.5-claim-verification` · **Versão:** V18.5 · **Capacidade:** `claim-verification`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §6
(exceto o campo de catálogo), §8 (contagens), §9 (evidência como dado);
[ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §7, §9.3;
[ADR 009](../../../docs/decisions/adr_009_camada_conhecimento_experimental.md) (resultados negativos são conhecimento);
[ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §5 (orçamento)
**Depende de:** `v18.5-numeric-references`, `v18.5-model-catalog-locality`

## Por quê

O Validator hoje revisa **planos** (`src/agents/validator_agent.py:181`) e o **resultado de
cada subtarefa** contra os critérios de aceite (`src/agents/validator_agent.py:310-420`), mas
ninguém confere as **conclusões** que o sistema entrega: os parágrafos do relatório final
(escritos pelo Summarizer) e os enunciados de `Descoberta` (escritos pelo Curator). Uma
conclusão pode afirmar que "a abordagem A supera B" quando os valores registrados dizem o
contrário, e isso chega ao pesquisador sem aviso.

O ADR 019 §6 decide que cada conclusão é decomposta em afirmações atômicas, conferidas contra
a evidência registrada, e que cada afirmação recebe um `status_afirmacao`, com efeitos fixos
e sem alterar o `validation` do ADR 015 nem a direção da evidência por julgamento de LLM.

## O que muda

- **Novo:** `src/claims/` — decomposição das conclusões em afirmações atômicas, conferência
  **determinística primeiro** para afirmações que só comparam referências numéricas,
  verificação **em lote por conclusão** pelo Validator para as demais, e armazenamento em
  `outputs/<sessão>/afirmacoes.json`.
- **Novo:** atributo `status_afirmacao` = `suportada` | `parcial` | `refutada_deterministica`
  | `contestada` | `nao_verificavel` | `pendente`, com os efeitos do ADR 019 §6. O status
  **nunca** é entrada de `compute_verdict` nem filtro de admissão de `Resultado` no grafo.
- **Novo:** método `ValidatorAgent.verify_claims` (modo de verificação de conclusões), com
  evidência delimitada como dado e passando pelo `EgressGate`.
- **Novo:** seção do orquestrador "Verificação das afirmações" no relatório, com **todas** as
  afirmações e seus status, e marcas inline para as não suportadas.
- **Novo:** nó de grafo `Afirmacao` para as afirmações extraídas de `Descoberta`s, com
  relações para a descoberta e para a evidência conferida.
- **Novo:** revisão humana das afirmações `contestada`:
  `geminiclaw claims list` e `geminiclaw claims resolve`.
- **Novo:** afirmações `pendente` (orçamento esgotado) gravadas no `checkpoint.json` e
  verificadas na retomada (`v18-research-continuity`).
- **Novo:** até `CLAIM_REVISION_MAX_CYCLES` ciclos de correção do Summarizer para conclusões
  com afirmação `refutada_deterministica` ou `parcial`, com histórico preservado.
- **Modificado:** chamadas de verificação contam no orçamento da V18 (`v18-usage-limits`);
  esgotar o orçamento não bloqueia a sessão.

## Impacto

- **Código:** `src/claims/` (novo: `model.py`, `decompose.py`, `deterministic.py`,
  `service.py`, `store.py`, `report_section.py`), `src/agents/validator_agent.py`,
  `src/report/pipeline.py` (estágio e seção registrados), `src/report/base_converter.py`
  (marcas), `src/autonomous_loop.py` (fechamento e checkpoint do Curator),
  `src/continuity.py` (retomada, criado por `v18-research-continuity`), `src/knowledge/schema.py`, `src/cli.py`, `src/config.py`.
- **Custo:** chamadas LLM do Validator por conclusão não resolvida deterministicamente.
- **Comportamento:** o relatório passa a exibir o status de cada afirmação; nenhum texto de
  conclusão é apagado.

## Dependências e acordos

| Mudança | Relação |
|---|---|
| `v18.5-numeric-references` | Usa o parser, os valores resolvidos e o pipeline do relatório (estágio após a resolução, antes da renderização). |
| `v18.5-model-catalog-locality` | Dona de `familia_modelo` e do desempate no roteador. Esta mudança consome `current_allocation("validator")` e as famílias dos autores. `familias_autor` inclui `summarizer` e `curator` (acordado na consolidação; ver design §6). |
| `v18.5-egress-gate` | Todo envio ao Validator passa pelo `EgressGate` com origem por trecho. |
| `v18-usage-limits`, `v18-research-continuity` | Contabilização e retomada (delta declarado aqui; as specs originais não são alteradas). |
| `v18.5-operation-metrics` | Fornece o leitor do grupo `verificacao`. |

## Aprovações necessárias

- **Mudança de schema do grafo** (`src/knowledge/schema.py`): novo nó `Afirmacao` com a
  propriedade `status_afirmacao` e as relações `Afirmacao-EXTRAIDA_DE->Descoberta` e
  `Afirmacao-CONFERIDA_CONTRA->(Resultado | Experimento | Insumo)` — aprovação explícita do
  pesquisador (AGENTS.md). Nenhuma tabela nova no PostgreSQL; os valores de `validation` /
  `status_validacao` **não** mudam.
- Nenhuma alteração de Dockerfile ou compose; nenhum arquivo apagado.
