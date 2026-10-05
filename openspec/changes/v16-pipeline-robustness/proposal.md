# Proposta: Robustez do Pipeline de Planejamento, Revisão e Relatório

**ID:** `v16-pipeline-robustness` · **Versão:** V16 (etapa de robustez, anterior à V17) ·
**Capacidade:** `pipeline-robustness`
**ADRs de origem:** [ADR 002](../../../docs/decisions/adr_002_arquitetura_multi_agent_system.md)
(DAG de execução e papéis) e [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md)
(o assistente precisa concluir a tarefa de forma autônoma); o princípio 6 do `AGENTS.md`
(fail-fast, sem dados inventados) orienta o relatório. Não há ADR novo: nenhuma decisão
arquitetural é criada, apenas contratos de módulos existentes.
**Origem dos requisitos:** benchmark de 2026-10-01
([`docs/benchmarks/2026-10-01-modelos-baixo-custo-resultados.md`](../../../docs/benchmarks/2026-10-01-modelos-baixo-custo-resultados.md))
e a decisão de 2026-10-01 de tornar o pipeline robusto antes de repetir avaliações.
**Depende de:** — (módulos já implementados: `src/orchestrator.py`, `src/autonomous_loop.py`,
`src/agents/validator_agent.py`, `agents/summarizer/agent.py`)
**Habilita:** `v16-agent-communication-eval` (reutiliza o comparador de artefatos e os eventos
novos) e toda a V17 (o grafo só recebe fatos de sessões que concluem)

## Por quê

No benchmark da tarefa Iris, só duas das oito combinações de modelos concluíram o pipeline. As
demais não falharam por qualidade de modelo: tropeçaram em regras do próprio framework.

| Falha observada | Causa no código |
|---|---|
| O revisor reprova subtarefa porque o agente gravou `iris_*.png` e o plano esperava `eda_*.png` | `review_result` exige o nome exato do artefato esperado (`src/agents/validator_agent.py:443-463`) |
| Subtarefa com critério como "ao menos 3 gráficos" é reprovada por faltar `metrics.json` | `_has_quantitative_criterion` trata qualquer dígito junto de "pelo menos" como critério de métrica (`validator_agent.py:33-38`, `:402-410`); o `metrics.json` de OUTRA subtarefa também satisfaz a busca (`:147`) |
| Só o primeiro critério mapeável decide o veredito | `_evaluate_quantitative_criteria` retorna no primeiro acerto (`validator_agent.py:135`) |
| O plano nunca é aprovado (GPT-6 Luna) | Planos com `depends_on` em string, critérios em string ou `task_type` `validation` sem limiar numérico são rejeitados e o planejador não corrige pelo feedback (`validator_agent.py:249-289`); o Validator LLM pode reprovar o mesmo plano repetidamente (`orchestrator.py:692-791`) |
| A sessão encerra com "zero progresso" depois de um ciclo | O disjuntor compara só o conjunto de subtarefas bem-sucedidas entre ciclos (`autonomous_loop.py:1003-1004`): dois ciclos seguidos sem sucesso encerram, mesmo que o replanejamento tenha mudado de erro |
| A sessão para por "limite de 30 execuções" | O contador soma toda chamada de `_execute_agent`, inclusive as 1 a 10 iterações de planejamento por ciclo, as retentativas e a síntese (`orchestrator.py:540-548`); o erro vira falha de subtarefa e não fecha a sessão com consolidação |
| O relatório lista "Containers Utilizados" | O Summarizer escreve os metadados em Markdown a partir de uma instrução desatualizada (`agents/summarizer/agent.py:85`); depois do ADR 014 não há container por agente |

## O que muda

- **Novo:** **normalizador determinístico de plano** (`src/plan_normalizer.py`), executado
  entre o parse do JSON do planejador e o Validator. Corrige só o que é recuperável sem
  inventar conteúdo (envelopes, tipos de campo, nomes duplicados, dependências inexistentes) e
  registra cada reparo. Nada de limiar numérico inventado.
- **Novo:** **comparador de artefatos tolerante** (`src/artifact_match.py`), usado pelo
  revisor e pela propagação de contexto entre subtarefas. Resolve o artefato esperado em
  camadas (exato, padrão glob, nome normalizado, extensão equivalente) e devolve o mapa
  *esperado → real*, que passa a alimentar as subtarefas dependentes.
- **Modificado:** revisão de subtarefa: critério quantitativo só dispara a checagem em
  `metrics.json` quando o critério cita uma métrica conhecida; `metrics.json` é procurado na
  pasta da própria subtarefa; todos os critérios mapeáveis são avaliados (não só o primeiro);
  a evidência entregue ao revisor LLM usa o mapa de artefatos resolvidos.
- **Modificado:** laço de reprovação do plano: o Validator LLM passa a ser **consultivo** depois
  de repetir a mesma reprovação; reprovações determinísticas trazem correção acionável e, se
  repetirem, encerram o planejamento com erro explícito (não com laço até o limite).
- **Modificado:** **disjuntor de progresso**: progresso é qualquer mudança no conjunto de
  sucessos **ou** na assinatura dos erros das subtarefas falhas; só dispara após
  `CIRCUIT_BREAKER_STALL_CYCLES` ciclos consecutivos idênticos.
- **Modificado:** **limite de execuções de agente**: execuções de planejamento têm contador e
  limite próprios; o limite de execuções de subtarefa tem piso derivado do plano aprovado; ao
  atingir qualquer um, a sessão **fecha com consolidação** e `motivo_parada`
  `limite_execucoes` (novo membro de `StopReason`), em vez de lançar exceção.
- **Novo:** **modelo estruturado de relatório** (`src/report/report_model.py`). O orquestrador
  monta os dados (metadados, tabela de resultados, interações, divergências, artefatos) a
  partir do disco e da telemetria e renderiza o Markdown de forma determinística; o Summarizer
  passa a produzir só as seções narrativas, em JSON validado. "Containers Utilizados" é
  substituído por execuções de agente e execuções no sandbox.
- **Novo:** eventos de telemetria `plan_normalized`, `sandbox_run` e `circuit_breaker` com
  `reason` ampliado, consumidos pela avaliação de comunicação.
- **Fora do escopo:**
  - Veredito do revisor contra verdade determinística, taxa de resolução e juiz LLM:
    [`v16-agent-communication-eval`](../v16-agent-communication-eval/proposal.md).
  - Consumo de tokens do Researcher (40 a 98 % do total): o normalizador e o laço de
    reprovação mais curto reduzem as iterações de planejamento, mas a medição por papel fica
    na avaliação de comunicação; nenhuma meta de redução é prometida aqui.
  - `ask_researcher` nos modos `semi`/`auto`: [`v18-researcher-consult`](../v18-researcher-consult/proposal.md).
  - `OLLAMA_NUM_CTX` aplicado a modelos de nuvem: decisão pendente do pesquisador
    (design, "Questões em aberto").
  - Qualquer chamada nova a provedor pago.

## Impacto

- **Código:** `src/plan_normalizer.py` (novo), `src/artifact_match.py` (novo),
  `src/report/report_model.py` (novo), `src/orchestrator.py` (normalização, contadores,
  fechamento por limite), `src/autonomous_loop.py` (disjuntor, contexto com mapa de artefatos,
  síntese), `src/agents/validator_agent.py` (revisão e laço de reprovação), `src/usage.py`
  (`StopReason`), `src/skills/code/` (evento `sandbox_run`), `src/subtask_output.py` (campo
  `artifact_aliases`), `agents/summarizer/agent.py`, `src/config.py`, `.env.example`.
- **Contratos:** payload do evento `plan_validation` ganha `approved_with_warnings` e
  `signature`; `subtask_review` ganha `attempt`, `resolved_artifacts` e `signature`; o
  relatório passa a ter `report_data.json` ao lado de `relatorio_final.md`
  (`ReportData`, design §6).
- **Schema de banco:** nenhuma alteração (eventos usam `payload_json`; sessão usa `payload`).
- **Compatibilidade:** `ARTIFACT_MATCH_MODE=strict` e `PLAN_NORMALIZER_ENABLED=false` devolvem o
  comportamento anterior, para comparar nas avaliações.
- **Custo:** reduz chamadas (menos iterações de planejamento e menos retentativas inúteis); o
  Summarizer deixa de gerar tabelas e metadados, gerando só narrativa.
- **Hardware (Pi 5):** sem impacto relevante; o comparador lê nomes de arquivos, não conteúdo.

## Aprovações necessárias

- Nenhuma alteração de schema de banco, Dockerfile, `docker-compose.yml`, exclusão de arquivos
  ou `AGENTS.md`.
- **Decisão do pesquisador** sobre as questões em aberto do `design.md` §10, em especial o
  tratamento de `task_type` `validation`/`reproduction` sem limiar numérico (§1.3) e a regra de
  extensão equivalente do comparador (§2.2), antes de implementar.
