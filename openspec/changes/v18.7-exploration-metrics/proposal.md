# Proposta: Métricas da exploração rastreável e do contrato da subtarefa

**ID:** `v18.7-exploration-metrics` · **Versão:** V18.7

**Capacidades:** `operation-metrics`, `benchmark`

**ADRs de origem:** [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §8.4 (contadores por papel, por origem da hipótese, ligações `PREPARA` derivadas, hipóteses do sistema abandonadas; substituição de `reprovacoes_sem_hipotese`; `fechada_por_hipoteses_nao_testadas` continua), §5.5 (retiradas por similaridade de restrição contadas e listadas no relatório) e "Revisão" (o que comparar na primeira bateria); [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) §6.3 (custo do contrato medido por execução) e §7 (hash do contrato por tentativa e na revisão; divergência registrada como anomalia, sem reprovar).

**Depende de:** `v18.7-hypothesis-linking` (produz os campos novos do evento `hypothesis_cycle` e os eventos `hipotese_sistema_abandonada` e `hipotese_derivada`); `v18.7-subtask-contract` (produz o contrato, `SubtaskContract.sha256()` e `ReviewResult.contract_sha256`). Lê, quando existirem, os eventos de `v18.7-exploration-limits` (estagnação, objetivo, saturação, restrições); sem eles, o bloco correspondente fica `indisponivel`, sem bloquear esta mudança. Compatível com `v18.7-benchmark-fixes`, que também acrescenta chaves a `operation-metrics` e colunas ao relatório do benchmark (sem requisito em comum). Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.

**Nota de data:** escrita em 2026-10-15, a partir dos ADRs 021 e 022 aprovados nessa data. **Atualização 2026-10-18:** `v18.7-subtask-contract` já emite, por tentativa do Developer, o evento `subtask_contract` (`tentativa`, `contrato_sha256`, `tarefa_original_truncada_de`, `limiar_mascarado`) e já grava `contrato_sha256` no `subtask_review`. Esta mudança cria o `subtask_attempt` a partir desses campos (acrescenta `contrato_chars`, `contrato_tokens_estimados` e `recorte_sha256`, e passa a ser o único evento por tentativa, removendo `subtask_contract`) e só acrescenta ao `subtask_review` o que ainda falta; o evento `contrato_divergente` continua desta mudança. Com `v18.7-dependency-artifacts`, o contrato passa à versão 2 (item 10).

## Por quê

O ADR 021 troca o bloqueio por registro: a qualidade do plano deixa de ser cobrada pela retirada de subtarefas e passa a ser medida. Sem contadores, não há como saber se o Researcher declara hipóteses ou deixa o sistema derivá-las, quantas preparações foram ligadas por inferência, nem quantas hipóteses do sistema morreram sem teste; a "Revisão" do ADR 021 pede exatamente essas comparações por combinação de modelos. O contador `reprovacoes_sem_hipotese` (`src/operation_metrics.py:276-292`) mede um motivo que deixa de existir (ADR 021 §8.1).

O ADR 022 estima de 1 a 3 mil tokens de entrada a mais por tentativa de subtarefa com o contrato e pede que o benchmark meça esse custo por execução; e exige o registro do hash do contrato no início de cada tentativa e na revisão, para detectar o caso em que quem executa e quem julga viram contratos diferentes.

## O que muda

### Novo

- **Grupo `exploracao`** em `operation_metrics` (versão 2), com três blocos: `ligacao` (ADR 021 §8.4), `parada` (estagnação, intervenções, objetivo, saturação e retiradas por restrição, produzidos por `v18.7-exploration-limits`) e `contrato` (ADR 022 §6.3, §7). Cada bloco fica `indisponivel` com o nome da mudança produtora quando ela não existe.
- **Evento `subtask_attempt`** no início de cada tentativa de subtarefa do Developer: `attempt`, `contrato_sha256`, `contrato_chars`, `contrato_tokens_estimados`, `tarefa_original_truncada` e `recorte_sha256` (hash do recorte do regimento, de `AgentContext`; `null` até `v18.7-agent-system-prompts`). O hash do contrato é registrado por tentativa, não por sessão (ADR 022 §7).
- **`contrato_sha256` no evento `subtask_review`** e evento **`contrato_divergente`** quando difere do da tentativa.
- **Seção de exploração** no `relatorio_final.md` (dentro da seção determinística "Métricas de operação"), com a lista das retiradas por similaridade de restrição.
- **Benchmark:** colunas por combinação (experimentos por papel, testes por origem e proporção de hipóteses do sistema, `PREPARA` derivadas, hipóteses do sistema abandonadas, tokens do contrato por execução e sua fração da entrada) e aviso de placar `contrato_divergente`.

### Modificado

- `HypothesisClosureReader` deixa de produzir `reprovacoes_sem_hipotese`; mantém `resultados_sem_mede`, `subtarefas_resultado_negativo`, `hipoteses_sem_tentativa_no_fechamento` e `fechada_por_hipoteses_nao_testadas`.
- `summarize_events` do benchmark resume `subtask_attempt` e os hashes.
- `operation_metrics.versao` passa de 1 a 2; o relatório e o benchmark leem a versão 1 sem o grupo novo (mostram `n/d`).

### Removido

- O contador `reprovacoes_sem_hipotese` e a linha correspondente do relatório (`src/operation_metrics.py:585-589`).

### Fora do escopo

- Produzir os dados de ligação (papel, hipótese do sistema, `PREPARA`): `v18.7-hypothesis-linking`.
- Montar o contrato e calcular o seu hash: `v18.7-subtask-contract`.
- Hash do regimento e do adendo por sessão (evento `regimento_sessao`, ADR 022 §4.4) e o cálculo de `recorte_sha256`: `v18.7-agent-system-prompts`.
- Contagem exata de tokens do contrato pelo provedor: os provedores não separam o custo por bloco; a medida é estimada (design §3).

## Impacto

- **Código:** `src/operation_metrics.py`, `src/autonomous_loop.py` (evento `subtask_attempt` em `:1373-1390`, `contrato_sha256` em `:2401-2425`), `src/config.py`, `scripts/benchmark/interactions.py`, `scripts/benchmark/report.py`, `scripts/benchmark/run_benchmark.py` (avisos de placar).
- **Contratos:** grupo `exploracao` e `versao = 2` em `payload["operation_metrics"]` e `session_metadata.json`; eventos `subtask_attempt` e `contrato_divergente`; campo `contrato_sha256` em `subtask_review`; chaves novas no resultado do benchmark (`exploracao`, `avisos` com `contrato_divergente`).
- **Schema:** nenhum. Os eventos usam a tabela `agent_events` existente; nada muda no grafo.
- **Custo:** nenhuma chamada LLM; leitura de eventos e uma consulta de contagem ao grafo no fechamento.

## Aprovações necessárias

Nenhuma: sem alteração de schema, Dockerfile, `docker-compose.yml`, `AGENTS.md` ou exclusão de arquivo.
