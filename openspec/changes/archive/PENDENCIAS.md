# Pendências das Mudanças Arquivadas (V16–V18.5)

As 32 mudanças das versões V16 a V18.5 foram arquivadas em 2026-10-13, com o código mergeado em
`dev`. Os itens que estavam abertos nos `tasks.md` foram reunidos aqui por categoria, para não
se perderem no arquivo. Cada item cita a mudança de origem.

- **Validação em ambiente real:** entra na bateria final no Raspberry Pi 5, que só começa com a
  confirmação do pesquisador. A etapa V18.6 (`roadmaps/roadmap_V18.6.md`) termina com essa bateria.
- **Segurança:** pareceres do Analista de Segurança ainda não registrados.
- **Administrativo:** itens de PR, revisão e lint cumpridos pelo merge do PR da mudança; mantidos
  só para rastreabilidade.
- **Débito técnico ou decisão pendente:** trabalho que precisa de uma mudança OpenSpec nova ou de
  decisão do pesquisador antes de ser feito.

## Segurança

- [ ] [`v16-pipeline-robustness`](v16-pipeline-robustness/tasks.md): 6.4 Revisão do Analista de Segurança (comparador e `sandbox_run`); revisão nos 7 eixos; PR
- [ ] [`v16-agent-communication-eval`](v16-agent-communication-eval/tasks.md): 7.4 Revisão do Analista de Segurança (redação e política do juiz); revisão nos 7 eixos; PR
- [ ] [`v16-model-catalog-router`](v16-model-catalog-router/tasks.md): 6.5 Revisão do Analista de Segurança (design §8); revisão nos 7 eixos; PR para `dev`; ADR 017 → Aceito após o merge.
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 4.5 Revisão do Analista de Segurança (design §6); revisão nos 7 eixos; PR para `dev`.
- [ ] [`v17-graph-store`](v17-graph-store/tasks.md): 5.1 **Revisão do Analista de Segurança.**
- [ ] [`v17-domain-search`](v17-domain-search/tasks.md): 6.4 Revisão do Analista de Segurança (entrada da ferramenta e telemetria); revisão nos 7 eixos; PR para
- [ ] [`v18-researcher-consult`](v18-researcher-consult/tasks.md): 5.4 Revisão do Analista de Segurança (guarda de consulta); revisão nos 7 eixos; PR para `dev`.
- [ ] [`v18.5-egress-gate`](v18.5-egress-gate/tasks.md): 0.4 Revisão do Analista de Segurança sobre este design. *(Achados do PR #113 corrigidos; aguardando a ratificação da revisão.)*
- [ ] [`v18.5-sandbox-phases`](v18.5-sandbox-phases/tasks.md): 5.5.1 Cota de disco para os bind mounts `/outputs` e `/deps` (hoje só o `/tmp` em `tmpfs` tem limite; um script ou instalação pode encher o disco do Pi). Motivo: depende de decisão do mecanismo (quota de sistema de arquivos, `ulimit fsize` ou monitor) e de validação no Pi. **RISCO ACEITO PENDENTE** (revisão de segurança M1): mitigado só pela checagem de espaço livre antes de iniciar (`SANDBOX_MIN_FREE_BYTES`), pelo teto por ativo (512 MiB) e pelo teto somado (2 GiB); não limita o que o script grava durante a execução.
- [ ] [`v18.5-claim-verification`](v18.5-claim-verification/tasks.md): 5.2 Revisão do Analista de Segurança (evidência como dado, egresso).
- [ ] [`v18.5-operation-metrics`](v18.5-operation-metrics/tasks.md): 9.2 Revisão do Analista de Segurança (ativação do modo, ausência de ativação por agente).

## Validação em ambiente real (bateria no Pi 5)

- [ ] [`v16-anthropic-provider`](v16-anthropic-provider/tasks.md): 4.2 Sessão de referência com Developer no Google e Researcher/Validator/Reviewer no Claude; registrar tempo, RAM e tokens.
- [ ] [`v16-local-embeddings`](v16-local-embeddings/tasks.md): 5.1 **Com aprovação do pesquisador**, rodar a reindexação no ambiente com dados. **Não executado nesta entrega** — requer aprovação explícita do pesquisador (AGENTS.md §1 regra 5); comando `geminiclaw embeddings reindex` está pronto para uso quando aprovado.
- [ ] [`v16-in-process-agents`](v16-in-process-agents/tasks.md): 6.2 Sessão completa no Pi 5 comparando tempo e RAM com o modo container (registrar no PR). — pendente: requer hardware Pi 5, indisponível neste ambiente de desenvolvimento.
- [ ] [`v16-research-assistant-prompts`](v16-research-assistant-prompts/tasks.md): 4.1 Rodar duas sessões de referência (uma de reprodução, uma de EDA) antes e depois; registrar no PR diferenças de plano e resultado.
- [ ] [`v16-pipeline-robustness`](v16-pipeline-robustness/tasks.md): 6.3 Sessão real da tarefa Iris no Pi 5, **uma execução**, com o mapa de modelos que antes
- [ ] [`v16-agent-communication-eval`](v16-agent-communication-eval/tasks.md): 7.3 Avaliar **uma** sessão já existente no Pi (`~/bench/`), sem juiz externo
- [ ] [`v16-model-catalog-router`](v16-model-catalog-router/tasks.md): 6.4 Sessão real no Pi 5 com o `.env` atualizado (mapa resolvido no banner e no payload).
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 1.4 Medir o tamanho da imagem no Pi 5 e registrar no PR.
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 3.2 Integração (Mac e Pi 5): conteúdo da imagem; escrita fora das áreas permitidas; pacote inexistente; pacote real instalado e registrado; socket para fora falha no script; dono e modo dos artefatos; symlink que escapa. _(escrito em `tests/integration/test_sandbox_slim_image.py`; execução pendente no Mac e no Pi 5, pula sem imagem)_
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 4.4 Benchmark de referência (`run.sh`) no Pi 5 completo com a nova imagem.
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 5.4 Validação real no Pi 5 e no Mac das correções acima (container e imagem reais): em particular, que o `uv` instala de `/tmp` com `noexec` e que `put_archive` funciona depois da desconexão. Motivo: sem imagem nem daemon neste ambiente.
- [ ] [`v17-graph-store`](v17-graph-store/tasks.md): 1.3 Subir no Pi 5 e confirmar que os dados existentes do volume continuam acessíveis.
- [ ] [`v17-graph-store`](v17-graph-store/tasks.md): 4.3 Integração com AGE: criar nó, aresta, `neighbors`, `project_subgraph`.
- [ ] [`v17-graph-store`](v17-graph-store/tasks.md): 5.2 Carga sintética de 10 mil nós no Pi 5: medir `neighbors(depth=2)` e `project_subgraph`; registrar no PR.
- [ ] [`v17-research-project`](v17-research-project/tasks.md): 5.1 Validar no Pi, com Apache AGE real, as propriedades de mapa (`criterio_sucesso`, `caracteristicas_dados`), `find_nodes` por `projeto_id`/`status` e `project_subgraph` (quando o projeto estiver mais estável).
- [ ] [`v17-structural-fact-ingestion`](v17-structural-fact-ingestion/tasks.md): 5.2 Validar a ingestão contra o Apache AGE real (Pi 5): idempotência de arestas via `neighbors`, `find_nodes` por `sessao_id`/`hash_conteudo`, propriedades `dict`/`list` (`ambiente`, `consumo`, `dataset_ids`, `APLICOU.config`) e `geminiclaw knowledge sync` ponta a ponta. Os testes desta mudança usam `InMemoryGraphStore`; o AGE não estava disponível no ambiente de desenvolvimento.
- [ ] [`v17-structural-fact-ingestion`](v17-structural-fact-ingestion/tasks.md): 5.3 Medir o campo `python` de `Experimento.ambiente` (hoje só `imagem_sandbox` e `pacotes`; a versão do Python do sandbox não é medida no host).
- [ ] [`v17-knowledge-semantic-index`](v17-knowledge-semantic-index/tasks.md): 7.0b Pendente no Pi 5: validação com AGE, PostgreSQL e Qdrant reais (incl. `list_nodes` Cypher e o teste de integração da fila).
- [ ] [`v17-domain-search`](v17-domain-search/tasks.md): 5.3 Rodar a avaliação no Pi 5 com o modelo padrão e com um multilíngue; anexar o relatório ao PR.
- [ ] [`v17-domain-search`](v17-domain-search/tasks.md): 6.3 Reindexação dos 1335 domínios no Pi 5 e medição do tempo de indexação e de consulta; confirmar que o processo do Researcher (em processo no host) enxerga `KNOWLEDGE_READER_DATABASE_URL`, `QDRANT_URL` e o modelo de embedding já em cache (sem download na primeira chamada).
- [ ] [`v17-domain-search`](v17-domain-search/tasks.md): 7.5 Carga do vocabulário (`scripts/seed_vocabulary.py`) pelo `IndexedGraphStore` vetoriza cada domínio na criação (sem ancestrais) e de novo na reconciliação: semear no grafo cru e reconciliar uma vez (dobra o custo de embeddings no Pi).
- [ ] [`v17-domain-search`](v17-domain-search/tasks.md): 7.6 Marcação dos descendentes (`mark_descendants_pending`) é síncrona e um update por nó; mover para a reconciliação ou para tarefa em segundo plano se a medição de 6.3 mostrar custo.
- [ ] [`v17-curator-agent`](v17-curator-agent/tasks.md): 8.1 Validar com **Apache AGE real**: `update_edge`, `FUNDIDA_EM`, auditoria de arestas e as consultas do `KnowledgeService`.
- [ ] [`v17-curator-agent`](v17-curator-agent/tasks.md): 8.2 **Benchmark do `KnowledgeService` no Raspberry Pi 5** (~200 tentativas): mede o ganho do memo de leituras; considerar atualização incremental.
- [ ] [`v17-graph-cli`](v17-graph-cli/tasks.md): 6.1 Validar com Apache AGE real: `audit_history`, `record_audit_note` e a reversão (inclui a semântica de `None`).
- [ ] [`v17-input-document-index`](v17-input-document-index/tasks.md): 5.3 Sessão real no Pi 5 com PDFs e um CSV: tempo de indexação e número de pontos registrados no PR.
- [ ] [`v18-research-continuity`](v18-research-continuity/tasks.md): 6.2 **Pendente:** validar com Apache AGE real as consultas do contexto de retomada (`find_nodes` por
- [ ] [`v18-hypothesis-loop`](v18-hypothesis-loop/tasks.md): 8.1 **Pendente (sem AGE neste ambiente):** validar com Apache AGE real as leituras novas do ciclo — `find_nodes` por
- [ ] [`v18-researcher-consult`](v18-researcher-consult/tasks.md): 5.3 Sessão `auto` real (tarefa de referência) com ao menos uma consulta registrada; anexar o trecho de `researcher_interactions` ao PR.
- [ ] [`v18.5-model-catalog-locality`](v18.5-model-catalog-locality/tasks.md): 5.2 `uv run ruff check .`; testes unit locais e de integração (unit executados; integração fica para a bateria final, sem testes no Pi).
- [ ] [`v18.5-egress-gate`](v18.5-egress-gate/tasks.md): 7.5 Medir no Pi 5 o custo do filtro em prompt de 16 000 caracteres. *(Pendente: sem testes no Pi até a bateria final, a ser combinada com o pesquisador.)*
- [ ] [`v18.5-egress-gate`](v18.5-egress-gate/tasks.md): 8.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`. *(Parcial: `ruff` sem erros novos e `pytest -m unit` verde; a suíte de integração foi escrita e não foi executada.)*
- [ ] [`v18.5-research-data-ingestion`](v18.5-research-data-ingestion/tasks.md): 6.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`. *(Parcial: `ruff` limpo nos arquivos novos/alterados e `pytest -m unit` verde, exceto `test_limite_de_egresso_e_um_motivo_retomavel`, corrigido no PR #117; integração fica para a bateria final.)*
- [ ] [`v18.5-sandbox-phases`](v18.5-sandbox-phases/tasks.md): 6.1 Medição no Pi 5: tempo por fase com e sem pacotes (registrar no PR).
- [ ] [`v18.5-execution-provenance`](v18.5-execution-provenance/tasks.md): 5.5 Sessão completa com sandbox: registros, ponta no checkpoint, seção no relatório, exportação e `verify --from-export`.
- [ ] [`v18.5-execution-provenance`](v18.5-execution-provenance/tasks.md): 7.1 Medição no Pi 5: tempo de `begin`/`finish` com 4 subtarefas paralelas e hash de um dataset de 500 MB com e sem cache (registrar no PR).
- [ ] [`v18.5-execution-provenance`](v18.5-execution-provenance/tasks.md): 7.2 Ruff, `uv run pytest -m "unit or integration"`. *(Parcial: unitários verdes e `ruff` limpo nos arquivos novos; integração na bateria final.)*
- [ ] [`v18.5-numeric-references`](v18.5-numeric-references/tasks.md): 7.2 Sessões de referência com o prompt novo; registrar taxa de números não verificados no PR.
- [ ] [`v18.5-claim-verification`](v18.5-claim-verification/tasks.md): 5.1 Sessões de referência: distribuição de status e custo em tokens no PR.

## Administrativo (encerrado pelo merge do PR)

- [ ] [`v16-provider-registry`](v16-provider-registry/tasks.md): 5.2 Revisão nos 7 eixos; PR para `dev`.
- [ ] [`v16-in-process-agents`](v16-in-process-agents/tasks.md): 7.6 Ruff, testes, revisão, PR da fase 2.
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 4.3 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] [`v16-platform-images`](v16-platform-images/tasks.md): 7.2 Revisão nos 7 eixos; PR para `dev`; ADR 018 → Aceito quando esta mudança e a `v16-sandbox-slim-image` estiverem no `dev`.
- [ ] [`v17-graph-store`](v17-graph-store/tasks.md): 5.3 Ruff, testes, revisão nos 7 eixos, PR.
- [ ] [`v17-input-document-index`](v17-input-document-index/tasks.md): 5.2 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] [`v17-input-document-index`](v17-input-document-index/tasks.md): 5.4 Revisão nos 7 eixos; PR para `dev`.
- [ ] [`v18-usage-limits`](v18-usage-limits/tasks.md): 6.2 Revisão nos 7 eixos, PR.
- [ ] [`v18.5-model-catalog-locality`](v18.5-model-catalog-locality/tasks.md): 5.3 Revisão nos 7 eixos; PR para `dev`.
- [ ] [`v18.5-egress-gate`](v18.5-egress-gate/tasks.md): 8.2 Revisão nos 7 eixos; PR para `dev`.
- [ ] [`v18.5-research-data-ingestion`](v18.5-research-data-ingestion/tasks.md): 6.2 Revisão nos 7 eixos; PR para `dev`.
- [ ] [`v18.5-sandbox-phases`](v18.5-sandbox-phases/tasks.md): 6.3 Revisão nos 7 eixos, PR para `dev`.
- [ ] [`v18.5-execution-provenance`](v18.5-execution-provenance/tasks.md): 7.3 Revisão nos 7 eixos, PR para `dev`.
- [ ] [`v18.5-numeric-references`](v18.5-numeric-references/tasks.md): 7.3 Ruff, `uv run pytest -m "unit or integration"`; revisão nos 7 eixos; PR para `dev`. *(Parcial: unitários verdes e `ruff` limpo nos arquivos novos.)*

## Débito técnico ou decisão pendente

- [ ] [`v16-anthropic-provider`](v16-anthropic-provider/tasks.md): 4.1 Definir `ANTHROPIC_API_KEY` no `.env` do Pi.
- [ ] [`v16-agent-communication-eval`](v16-agent-communication-eval/tasks.md): 5.5 Rotulagem humana de cerca de 20 eventos (ação do pesquisador); registrar no PR.
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 0.2 Liberar espaço em disco antes de construir imagens (o hook local bloqueia comandos de Docker com menos de 10 GB livres).
- [ ] [`v16-sandbox-slim-image`](v16-sandbox-slim-image/tasks.md): 5.5 Lock multi-arquitetura e digests das imagens base: movidos para `v16-platform-images` (5.5.1, 5.5.2). Cota de disco e FIFO real: `v18.5-sandbox-phases` (5.5.1, 5.5.2).
- [ ] [`v16-platform-images`](v16-platform-images/tasks.md): 5.5.1 Gerar `containers/sandbox/requirements.lock` multi-arquitetura (hoje só `aarch64-unknown-linux-gnu`; em `amd64` o `--require-hashes` falha). Motivo: precisa de decisão sobre uma lock por plataforma ou universal e de rede para compilar/validar em cada arquitetura.
- [ ] [`v16-platform-images`](v16-platform-images/tasks.md): 5.5.2 Fixar por digest (`@sha256`) as imagens base `python:3.11-slim-bookworm` e `ghcr.io/astral-sh/uv:0.8.9` no `containers/sandbox/Dockerfile`. Motivo: exige rede para o registro e política de atualização dos digests (por plataforma).
- [ ] [`v17-knowledge-semantic-index`](v17-knowledge-semantic-index/tasks.md): 1.4 Reconciliação no início da sessão e `geminiclaw knowledge reindex`. Entregue: `reconcile_on_session_start` (`semantic_runtime.py`) e o comando `knowledge reindex`. **Pendente:** chamar o helper no início da sessão — nenhum código de sessão usa o grafo ainda; tarefa 5.4 em `v17-curator-agent/tasks.md`.
- [ ] [`v17-knowledge-semantic-index`](v17-knowledge-semantic-index/tasks.md): 7.0a Adiado: S4 lote/cache na varredura (`enqueue_many`, N+1) e S5 auditoria agregada de `estado_vetorizacao` em `upsert_many` (exige API de atualização em lote de campos de sistema no `GraphStore`).
- [ ] [`v17-curator-agent`](v17-curator-agent/tasks.md): 8.3 Rodar `scripts/migrate_v17_knowledge.py` nos ambientes já migrados (cria o rótulo `FUNDIDA_EM`).
- [ ] [`v17-curator-agent`](v17-curator-agent/tasks.md): 8.6 `VARIANTE_DE` entre `Descoberta`s (hoje `SEMELHANTE_A` + `diferenca`): extensão de schema a aprovar.
- [ ] [`v17-curator-agent`](v17-curator-agent/tasks.md): 8.7 Fechar a limitação residual de `read_query` (provar que todo nó casado é do projeto da sessão: reescrita do Cypher ou views por projeto no AGE).
- [ ] [`v17-graph-cli`](v17-graph-cli/tasks.md): 6.2 Usar o papel `knowledge_reader` (ou transação `READ ONLY`) na visualização, em vez da fachada apenas.
- [ ] [`v17-graph-cli`](v17-graph-cli/tasks.md): 6.3 Carregar o subgrafo em streaming (hoje o projeto inteiro vai para a memória antes do corte); limite de 10.000
- [ ] [`v17-graph-cli`](v17-graph-cli/tasks.md): 6.4 Compare-and-set no store para eliminar a janela entre conferência e escrita.
- [ ] [`v17-graph-cli`](v17-graph-cli/tasks.md): 6.5 `HumanConfirmation` é construível por qualquer código Python do mesmo processo; a guarda estática é regex e
- [ ] [`v17-graph-cli`](v17-graph-cli/tasks.md): 6.7 A reversão grava `None` em campos que antes não existiam (equivalente a "sem valor" no store em memória);
- [ ] [`v18-research-continuity`](v18-research-continuity/tasks.md): 6.1 **Pendente (decisão do pesquisador: fora da condição de merge):** smoke do SQL novo de `src/session.py`
- [ ] [`v18-research-continuity`](v18-research-continuity/tasks.md): 6.3 **Pendente (débito):** fatos de falha de infraestrutura ingeridos por um falso positivo de obsolescência não são
- [ ] [`v18-hypothesis-loop`](v18-hypothesis-loop/tasks.md): 8.2 **Pendente:** as decisões reservadas `autorizar_escrita_instrumento` e `ativar_modo_sem_limite` seguem sem
- [ ] [`v18-hypothesis-loop`](v18-hypothesis-loop/tasks.md): 8.3 **Pendente (Arquiteto):** ver "Notas de implementação" em `design.md` (~~resultado_posterior~~ ratificado na spec e no design, alvo ausente,
