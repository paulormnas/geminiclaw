# Tarefas: v18.7-agent-system-prompts

**Estado (2026-10-18):** seções 0 a 5 implementadas (regimento v1, carga, recorte, injeção no `system` de todas as chamadas de papel, registro por sessão, `ler_regimento` e adendo de projeto com aprovação no gate); faltam os esquemas (6), os prompts (7), a coerência e a redação (8) e a validação (9).

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada pelo pesquisador, com as questões do design §10 decididas.
- [x] 0.2 Parecer do Analista de Segurança registrado no design §8.
- [x] 0.3 `v18.7-subtask-contract`, `v18.7-hypothesis-linking`, `v18.7-exploration-limits` e `v18.7-persistent-human-gate` mergeadas (a prova da aprovação do adendo é um pedido em `gate_requests`, design §5.5 e §8 parecer item 1; o valor `ativar_adendo_regimento` já está no `CHECK` daquela mudança). Questão §10.6 alinhada com `v18.7-persistent-human-gate` (leitura por `referencia` sem consumo, com `authorized_reference` também no `FakeGate`). Ajudas reaproveitadas, sem cópia local: `FakeRecordingProvider` (`v18.7-benchmark-fixes`) e `FakeGate` (`tests/support/fake_gate.py`).
- [x] 0.4 Worktree `.worktrees/feat-v18.7-agent-system-prompts`.

## 1. Auditoria
- [x] 1.1 Refazer a auditoria do design §1 contra o código mergeado (prompts, `_is_bound` ou o que o substituiu, ids de parada e retirada, construtores de contexto) e registrar a versão final no design §1, com as referências de linha atualizadas.

## 2. Regimento v1
- [x] 2.1 `src/agents/regimento/regimento.md` com as seções do design §2.1, escrito de forma direta, sem tabelas nem listas de códigos.
- [x] 2.2 `src/agents/regimento/regimento.yaml` com a estrutura do design §2.2 e os textos tirados dos ADRs 021 e 022, inclusive `regras_seguranca` com ids estáveis e destino, e `decisoes_reservadas` com os tipos do gate persistente.
- [x] 2.3 Texto do regimento apresentado ao pesquisador no PR para aprovação (ADR 022 §4.4).

## 3. Carga, recorte e registro
- [x] 3.1 `src/agents/regimento/carga.py` (pacote `src/agents/regimento`, sem módulo `src/regimento.py` por causa das camadas do ADR 024): `carregar_regimento`, `recorte`, `secao`, tabelas geradas, hashes (design §3.1-§3.2).
- [x] 3.2 `REGIMENTO_EXCERPT_MAX_CHARS` e `REGIMENTO_ADDENDUM_FILE` em `src/config.py` e `.env.example`.
- [x] 3.3 Carga por sessão no orquestrador; evento `regimento_sessao`; payload `regimento`; `AgentContext.regimento_sha256` e `recorte_sha256`; `regimento_alterado` na retomada (design §4).
- [x] 3.4 Injeção do recorte no `system` de todas as chamadas de papel listadas no design §3.3 (runtime em processo e chamadas diretas do Validator, Summarizer, consultor e revisão de conclusões); o parâmetro `regimento_excerpt` dos construtores de `v18.7-subtask-contract` não existe no código mergeado e o recorte vai no `system`, não na mensagem, então nada é passado a eles. Pontos de injeção: `_get_agent_instruction` (`agents/base/agent.py`, que cobre Developer, Researcher no plano, replanejamento e rascunho, e Summarizer), Validator (plano, revisão, afirmações), consultor, `CuratorRunner` (execução e edição) e a revisão de conclusões (o chamador passa `system_wrapper`, porque `claims` não importa `agents`). Sem regimento vinculado (fora de uma sessão) o `system` fica como estava.
- [x] 3.5 `_MODE_GUIDANCE` removido de `agents/base/agent.py` (conteúdo na seção de modos).
- [x] 3.6 Testes: "Carga do regimento", "Metadados inválidos", "Discriminação no auto", "Sem projeto", "Recorte grande demais", "Início da sessão", "Arquivo alterado no meio da sessão", "Retomada com regimento novo".

## 4. Ferramenta de leitura
- [x] 4.1 `ler_regimento` em `agents/base/tools.py`, registrada para Researcher, Developer e Curator.
- [x] 4.2 Testes: "Seção fora do recorte", "Caminho no argumento".

## 5. Adendo de projeto
_Desvios (2026-10-18): o diretório do adendo é o diretório de insumos da sessão (`ContextBundle.context_dir`, o `INPUT_CONTEXT_DIR` por padrão), porque o código só conhece um diretório de insumos; o texto do pedido comporta até `GATE_QUESTION_MAX_CHARS` (1000) caracteres, sem truncar, e o adendo que não cabe é recusado com erro explícito; o cenário "Consultor perguntado" já é coberto por `tests/unit/test_human_gate.py`, parametrizado sobre `DECISOES_RESERVADAS`._
- [x] 5.1 Leitura e validação do formato fechado; exclusão da indexação e da ingestão de insumos.
- [x] 5.2 `ativar_adendo_regimento` em `DECISOES_RESERVADAS` (já existia, criado por `v18.7-persistent-human-gate`); pedido ao gate com `referencia` igual ao sha256, texto, hash, linha fixa sobre egresso e linhas fixas de aviso de ids sensíveis (design §5.4). A cópia informativa do hash no projeto **não foi implementada**: nada a lê para decidir e não há onde gravá-la sem schema novo; o hash aprovado fica no pedido de `gate_requests` e no evento `regimento_sessao`.
- [x] 5.2a Decisão de injeção só pela consulta a `gate_requests` (design §5.5); a cópia do projeto nunca é lida para decidir.
- [x] 5.2b Leitura única do arquivo sem seguir link simbólico, hash e injeção dos mesmos bytes; recusa de link simbólico ou caminho fora dos insumos (design §5.6).
- [x] 5.3 Comportamento por modo com adendo pendente ou inválido (design §5.7), com código de saída 1 no `auto` e no adendo inválido (tabela única de `v18.7-background-sessions/design.md` §1.4).
- [x] 5.4 Testes, com `FakeGate` e `FakeRecordingProvider`: "Adendo aprovado", "Adendo alterado depois da aprovação", "Adendo pendente no auto", "Adendo que tenta afrouxar", "Aviso no pedido", "Adendo sem ids sensíveis", "Hash aprovado só no projeto", "Pedido negado", "Adendo trocado depois da verificação", "Adendo como link simbólico", "Consultor perguntado", "Decisões do gate no regimento".

## 6. Esquemas dos formatos
- [ ] 6.1 Esquemas únicos do plano (com `papel`), dos pareceres do Validator, do rascunho do Problema (com o tipo de objetivo), da resposta do consultor, da narrativa do Summarizer e de `metrics.json`, usados pelo código que valida e pela renderização dos prompts.
- [ ] 6.2 `SCHEMA_INSTRUCTION`, `PLAN_FORMAT_INSTRUCTION` e a estrutura do plano no prompt do Researcher gerados do esquema; o bloco de exploração passa a levar só dado delimitado.
- [ ] 6.3 Fixture gravada `tests/fixtures/plans/plano_regimento_v1.json` (resposta do Researcher com o prompt revisado, gravada uma vez e versionada). Testes, sem LLM real: "Plano", "Formato uma vez", "Plano compatível", "Plano antigo".

## 7. Prompts revisados
- [ ] 7.1 Researcher (plano, replanejamento, rascunho do Problema, consultor com `APP_NAME`), Developer, Validator (plano, revisão, afirmações, definição de métricas), Curator (execução e edição), Summarizer (narrativa e revisão de conclusões), com as seções do design §7 e sem repetir o regimento.
- [ ] 7.2 Textos de instrução de `src/orchestrator.py` (planejamento e replanejamento) reduzidos ao que é da chamada; regras movidas para o prompt do papel ou para o regimento.
- [ ] 7.3 `agents/base/agent.py` conforme a decisão da questão §10.1.
- [ ] 7.4 Testes: "Seções", "Developer", "Developer reenviado a cada chamada", "Troca de nome", "Regras de segurança preservadas", "Regra de segurança removida", "Regra de segurança sem o texto no destino"; o teste existente "Política de prompts" continua verde.

## 8. Coerência e redação
- [ ] 8.1 `tests/unit/test_regimento_coerencia.py` com as verificações do design §6; `INTEGRITY_RULES` e as constantes de `src/knowledge/objective.py` passam a ler o YAML.
- [ ] 8.2 Testes: "Motivo de parada não declarado", "Conjuntos iguais", "Código na prosa", "Caractere proibido", "Regra repetida", "Prompts reais".

## 9. Validação
- [ ] 9.1 `uv run ruff check .` sem erros novos; `uv run pytest -m "unit or integration" -v` verde.
- [ ] 9.2 Medir, sem LLM, o tamanho em caracteres do `system` de cada papel antes e depois (prompt mais recorte) e registrar no PR.
- [ ] 9.3 Bateria curta comparada à V18.6 (ADR 022 §4.6 e Revisão): só depois da confirmação explícita do pesquisador, porque usa provedores pagos e o Raspberry Pi; comparar taxa de aprovação na revisão, retentativas por subtarefa e tokens de entrada por execução do Developer.
- [ ] 9.4 `tasks.md` com caixas e linha **Estado** atualizadas no PR; confirmação com o Arquiteto para o status do ADR 022.
