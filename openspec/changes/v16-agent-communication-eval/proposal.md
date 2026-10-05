# Proposta: Avaliação da Comunicação entre Agentes

**ID:** `v16-agent-communication-eval` · **Versão:** V16 (etapa de robustez) ·
**Capacidade:** `communication-eval`
**ADRs de origem:** [ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §8
(as perguntas e respostas ficam registradas "para avaliar depois se a consulta foi relevante e
se mudou a decisão do agente");
[ADR 002](../../../docs/decisions/adr_002_arquitetura_multi_agent_system.md) (mensagens entre
agentes de um sistema multiagente);
[ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §3
(o que pode sair do nó: vale para o juiz externo);
[ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) (provedor do juiz escolhido
por configuração). Não há ADR novo.
**Depende de:** [`v16-pipeline-robustness`](../v16-pipeline-robustness/proposal.md) (comparador
de artefatos, eventos `plan_normalized`, `sandbox_run`, `subtask_review` ampliado)
**Relaciona-se com:** [`v18-researcher-consult`](../v18-researcher-consult/proposal.md) (a
mudança que passará a produzir respostas do Researcher às perguntas; esta avaliação já mede
perguntas sem resposta e passa a medir as respostas quando existirem)

## Por quê

A avaliação do projeto inclui a qualidade da comunicação entre agentes: o revisor acerta? as
reprovações levam a correção ou a laço? as perguntas ao pesquisador eram necessárias?

Hoje `scripts/benchmark/interactions.py` só **conta** mensagens e aprovações
(`MESSAGE_EVENTS`, `summarize_events`). Uma taxa de aprovação do revisor não diz se o revisor
estava certo: no benchmark de 2026-10-01 o revisor reprovou subtarefas que tinham gerado os
artefatos pedidos (`docs/benchmarks/2026-10-01-modelos-baixo-custo-resultados.md`, "Por que as
combinações falharam"), e não havia como medir isso sem ler as sessões à mão. Também não há
medida de laços de reprovação nem juízo sobre as dez chamadas de `ask_researcher` que o
GPT-6 Luna fez em modo autônomo.

## O que muda

- **Novo:** **verdade determinística por subtarefa**, calculada **depois** da execução a partir
  do disco (artefatos esperados via comparador tolerante, critérios com métrica nomeada contra
  `metrics.json`, código de saída do `sandbox_run`). Subtarefa cujos critérios são todos
  qualitativos fica `indeterminada` e é excluída das taxas.
- **Novo:** **matriz de confusão do revisor** contra essa verdade: falsos reprovados (revisor
  reprovou, a verdade é cumprida), falsos aprovados, acertos e indeterminadas, por sessão e por
  modelo do revisor.
- **Novo:** **taxa de resolução** de reprovações (de plano e de subtarefa): fração que foi
  seguida de aprovação na tentativa seguinte do mesmo alvo, e o número médio de tentativas até
  resolver.
- **Novo:** **detecção de laços de reprovação**: sequências de reprovações com a mesma
  assinatura (definida em `v16-pipeline-robustness` §1.3 e §3), com tamanho máximo e por alvo.
- **Novo:** **juiz LLM das perguntas de `ask_researcher`**, de **outro provedor** que o do agente
  que perguntou, com rubrica fixa (necessidade, clareza, resposta, efeito) e **calibração
  humana** de cerca de 20 eventos: concordância medida (kappa de Cohen) e relatada junto a toda
  nota do juiz; sem calibração suficiente, a nota sai marcada como não calibrada.
- **Novo:** comando de avaliação **pós-execução** (`scripts/benchmark/communication.py` e
  subcomando no runner): nada roda dentro da sessão, nenhum custo de LLM é incorrido durante a
  pesquisa.
- **Modificado:** `scripts/benchmark/interactions.py` e `report.py` incluem o novo bloco no
  relatório do benchmark; `summarize_events` mantém a sua saída atual.
- **Fora do escopo:**
  - Mudar o comportamento do revisor ou do Validator (é a `v16-pipeline-robustness`).
  - Responder perguntas de `ask_researcher` (é a `v18-researcher-consult`).
  - Repetir a matriz de modelos: a spec entrega o instrumento; a decisão de quando medir é do
    pesquisador (a ordem acordada em 2026-10-01 pede o pipeline concluindo primeiro).
  - Avaliar a qualidade científica do relatório (verificação de afirmações é
    `v18.5-claim-verification`).

## Impacto

- **Código:** `scripts/benchmark/communication.py` (novo), `scripts/benchmark/interactions.py`,
  `scripts/benchmark/report.py`, `scripts/benchmark/run_benchmark.py` (opção `--eval-comm`),
  `src/config.py` (variáveis `COMM_EVAL_*`), `.env.example`.
- **Dados:** rótulos humanos em arquivo versionado de calibração
  (`docs/benchmarks/calibracao/ask_researcher.jsonl`, design §5); resultados em
  `results.json` do benchmark. Sem schema de banco novo: lê `agent_events`, `token_usage` e a
  pasta da sessão.
- **Custo:** o juiz faz uma chamada por evento de `ask_researcher` (poucas por sessão) mais as
  chamadas de calibração. Teto por execução de avaliação em `COMM_EVAL_MAX_USD`; nenhuma
  chamada sem provedor e modelo configurados.
- **Dados que saem do nó:** o juiz recebe texto da pergunta, do motivo e das opções. Por padrão
  o juiz **externo é recusado**; o pesquisador o habilita explicitamente e o texto passa por
  redação (design §6).

## Aprovações necessárias

- Nenhuma alteração de schema, Dockerfile, `docker-compose.yml`, exclusão de arquivos ou
  `AGENTS.md`.
- **Decisão do pesquisador** sobre as questões em aberto do `design.md` §9: provedor e modelo do
  juiz (e o limite de gasto), e quem rotula os 20 eventos de calibração.
- **Saída de texto para provedor externo** (juiz): política de dados do ADR 019 §3; o Analista de
  Segurança revisa a redação (design §6) antes do merge.
