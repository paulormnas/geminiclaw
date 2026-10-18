# Proposta: Artefatos das dependências entregues à subtarefa

**ID:** `v18.7-dependency-artifacts` · **Versão:** V18.7 · **Capacidades:** `code-sandbox`, `agent-prompts`, `execution-provenance`
**ADRs de origem:** [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) §9 (artefatos das dependências, decisão do pesquisador de 2026-10-18) e §2 item 8 (lado produtor, já implementado); ADR 014 (sandbox isolado), ADR 018 §3 (saída por bind mount restrito à subtarefa), ADR 019 §5 (execução sem rede com dados produzidos) e ADR 021 (proveniência por execução).
**Depende de:** `v18.7-subtask-contract` (mergeada, #203 a #211: contrato da subtarefa, item 8 e `consumed_by`). Usa o mecanismo de montagem somente leitura de sessões anteriores (`/prior/<sessão>`, `v18-research-continuity`) como modelo.
**Nota de data:** escrita em 2026-10-18, a partir do achado da bateria parcial da V18.7 e da decisão do pesquisador registrada no design §14 de `v18.7-subtask-contract`.

## Por quê

Na bateria parcial de 2026-10-18 (`docs/benchmarks/2026-10-18-bateria-v18-7-parcial-resultados.md`), a `haiku-dev-sol-juiz` fechou com `erro` pelo disjuntor: `treinar_regressao_logistica` falhou em ciclos seguidos porque `/outputs/baseline_metrics.json` e `y_train.csv`, gravados por subtarefas das quais ela depende, não existiam no sandbox dela.

O código confirma a lacuna:

| Onde | O que acontece hoje |
|---|---|
| `src/skills/code/sandbox.py` (`run`, volume `abs_output_dir`) | `/outputs` é um bind mount de `<saída>/<sessão>/<task_name>/`: só a pasta da própria subtarefa. |
| `src/skills/code/sandbox.py` (`prior_mounts`) | Só sessões anteriores da cadeia de continuidade são montadas, em `/prior/<sessão>`, somente leitura. Nada monta as saídas das dependências da **mesma** sessão. |
| `src/artifacts/subtask_output.py` (`to_context_string`) | O prefixo de contexto diz ao Developer o nome e o caminho do artefato da dependência, relativo à pasta da sessão no host, que não existe no container. |
| `src/agents/developer/agent.py` (regra 2 do prompt) | Manda ler artefatos de etapas anteriores de `/outputs/`, onde eles não estão. |
| `src/agents/subtask_contract.py` (item 8) | Diz ao produtor quais artefatos outras subtarefas consomem; não diz ao consumidor onde encontrar os das dependências. |

A nomeação correta (contrato, colisão de artefatos) é necessária e insuficiente: sem a entrega, um plano perfeito ainda falha na primeira subtarefa que lê um arquivo de outra.

## O que muda

- **Novo:** montagem somente leitura das pastas das dependências da subtarefa em `/deps_out/<projeto>/<task_name>/` (decisão do pesquisador, 2026-10-18), com origem conferida (`check_mount_source`), uma montagem por dependência, nunca a pasta da própria subtarefa nem a raiz da sessão. `<projeto>` é o `project_id` da sessão (ou `sem_projeto`, quando não há projeto).
- **Novo:** escopo das dependências por `DEPENDENCY_ARTIFACTS_SCOPE` (`transitivas`, padrão, ou `diretas`) e teto de montagens por `DEPENDENCY_ARTIFACTS_MAX_MOUNTS`; acima do teto, a execução é recusada com erro acionável (nunca monta parte em silêncio).
- **Novo:** dependência concluída numa sessão anterior (retomada) é montada a partir da pasta daquela sessão, no mesmo caminho `/deps_out/<projeto>/<task_name>/`.
- **Novo:** item 10 do contrato, "Artefatos das dependências (somente leitura)": para cada dependência, o caminho montado e os arquivos esperados dela, com o nome real resolvido quando houver alias (`SubtaskOutput.artifact_aliases`). Item sem conteúdo aparece com "não se aplica".
- **Novo:** a execução com dependências montadas roda sem rede (como já acontece com `/prior` e com dados produzidos em `/outputs`, ADR 019 §5).
- **Modificado:** a regra 2 do prompt do Developer passa a apontar para `/deps_out/` e para o item 10 do contrato (só essa frase; a revisão completa dos prompts é de `v18.7-agent-system-prompts`).
- **Modificado:** o registro de proveniência de cada execução (`collect_inputs`) passa a listar os arquivos das dependências montadas como entradas, com hash, para a cadeia ligar a execução consumidora à produtora.
- **Modificado:** o `SubtaskOutput.to_context_string` passa a mostrar o caminho no container (`/deps_out/...`) quando a dependência é montada.
- **Removido:** nada da verdade atual.
- **Fora do escopo:** escrita nas pastas das dependências (continua proibida); cópia de arquivos entre pastas de subtarefas; montagem de subtarefas que não são dependências declaradas; o `read_artifact` do host (já lê a sessão inteira); várias pesquisas disputando a máquina.

## Impacto

- **Código:** `src/skills/code/sandbox.py` (montagens `/deps_out`, decisão de rede), `src/skills/code/skill.py` (lê as dependências do `AgentContext`), `src/skills/code/inputs.py` (validação da origem), `src/utils/agent_context.py` (`dependency_dirs`), `src/orchestration/orchestrator.py` (`_execute_agent` preenche o contexto), `src/orchestration/autonomous_loop.py` (resolve as dependências e a pasta de cada uma, inclusive na retomada), `src/agents/subtask_contract.py` (item 10), `src/agents/developer/agent.py` (regra 2), `src/artifacts/subtask_output.py`, `src/provenance/records.py`, `src/config.py`, `.env.example`.
- **Contratos:** `AgentContext` ganha `dependency_dirs: tuple[DependencyMount, ...]`; `SubtaskContract` ganha `dependency_artifacts` (muda o hash do contrato: `CONTRACT_VERSION = 2`); `SandboxResult` ganha `dependencias_montadas` (lista de `task_name`); o registro `inicio` da proveniência ganha `dependencias` (lista de `{task_name, sessao}`).
- **Schema de banco:** nenhum. O registro de proveniência já guarda `entradas` em JSON.
- **Localidade (ADR 019):** os arquivos das dependências ficam no nó; o Developer os lê dentro do sandbox, sem rede. Nenhum dado novo sai para provedor: o contrato só leva nomes de arquivo, sujeitos à regra de nomes.
- **Custo:** nenhuma chamada a mais; o item 10 acrescenta algumas centenas de caracteres ao contrato.
- **Hardware (Pi 5):** montagens bind sem cópia; sem efeito em memória.

## Aprovações necessárias

- **Parecer do Analista de Segurança** (design §7): nova superfície de leitura entre pastas de subtarefas da mesma sessão, dentro do sandbox. Registrado no design; a implementação começa depois da aprovação do pesquisador.
- **Decisão do pesquisador** sobre as questões em aberto do design §9 (escopo padrão, retomada e o ajuste pontual do prompt do Developer).
- Nenhuma alteração de schema relacional, Dockerfile, `docker-compose.yml`, exclusão de arquivos ou `AGENTS.md`.
