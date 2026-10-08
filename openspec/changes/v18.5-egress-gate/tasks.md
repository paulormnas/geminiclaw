# Tarefas: v18.5-egress-gate

## 0. Pré-requisitos
- [x] 0.1 `v18.5-model-catalog-locality` implementada (perfil de alocação e `aceita_dados_brutos` efetivo).
- [x] 0.2 Aprovação explícita do pesquisador para a tabela `egress_log` (aprovada).
- [x] 0.3 Valor de `LOCALITY_MIN_GROUP_SIZE` definido pelo pesquisador (10, em `.env.example`; a configuração segue falhando de forma acionável se ausente).
- [ ] 0.4 Revisão do Analista de Segurança sobre este design. *(Achados do PR #113 corrigidos; aguardando a ratificação da revisão.)*
- [x] 0.5 Confirmar com `v18.5-operation-metrics` a divisão do limite de egresso (design §9): esta mudança entrega `max_egress_bytes`, o motivo de parada e a retenção; o modo sem limite e `--max-egress-bytes` ficam na `operation-metrics`.

## 1. Fundamentos
- [x] 1.1 `src/egress/fragments.py`: `ContentOrigin`, `PromptFragment`, helper `labeled(...)`, renderização.
- [x] 1.2 Configurações em `src/config.py` e `.env.example` (design §12); falha acionável sem `LOCALITY_MIN_GROUP_SIZE`.
- [x] 1.3 Migração `scripts/migrations/v18_5_egress_log.sql`, `scripts/init_db.sql`; `src/egress/log.py` com gravação fail-fast e `envios.jsonl.gz`.

## 2. Filtros
- [x] 2.1 Tracebacks com marcadores tipados e exceção para identificadores conhecidos.
- [x] 2.2 Detecção e retenção de blocos tabulares e listas numéricas.
- [x] 2.3 Estatísticas: `describe()`, extremos em faixa, agregados pela regra de k, `estatistica_sem_n`.
- [x] 2.4 Elisão início/fim; nomes de artefatos.
- [x] 2.5 Números literais em trechos contaminados; preservação de `{{res}}`, `{{calc}}`, `{{src}}`.
- [x] 2.6 Delimitação de conteúdo observado e regra no `system`.

## 3. Camada de saída
- [x] 3.1 `EgressGate.prepare_llm` sobre o prompt inteiro a cada envio.
- [x] 3.2 `GatedProvider`; roteador e `get_provider()` devolvem provedores envolvidos.
- [x] 3.3 Rotulagem em `agent_loop` (sistema, prompt, respostas, resultados de ferramenta, bloco do workspace), compressão, triagem, Validator, síntese e plano inicial (`input_context/` como `dado_de_pesquisa` até a ingestão nova). *(Origem em linha: marcas `⟦T⟧`, `⟦D:fonte⟧` e `⟦S:fonte⟧` levam a origem por concatenações de texto até o `EgressGate`, que as converte em trechos e as remove antes do envio; ver PR.)*
- [x] 3.4 Skill de código grava `step_NN.stdout.txt`/`.stderr.txt` antes de devolver o resultado.
- [x] 3.5 `check_query` na busca rápida; `check_url` no `web_reader`; `authorize_vision`.

## 4. Leitura no host e contaminação
- [x] 4.1 `src/egress/classification.py` (`classify_path`, regra padrão).
- [x] 4.2 `document_processor.ingest` recusa `dado_de_pesquisa`; resultados de busca rotulados pela fonte.
- [x] 4.3 Marca persistida no payload, checkpoint, memória (tag `egress:tainted`) e grafo (propriedade `tainted`); reconstrução na leitura e regra para texto legado. *(Checkpoint: campo irmão `resultado_marca` em vez de objeto aninhado, para manter os leitores; memória: tag; grafo: propriedade opcional `tainted` no schema de nós de agentes.)*
- [x] 4.4 Aviso de perfil misto no banner.

## 5. Limite de volume
- [x] 5.1 `egress_bytes_for_session`; contagem única por trecho e destino, só `fora_do_no`.
- [x] 5.2 `UsageBudget.max_egress_bytes`, leitor no `UsageTracker`, `StopReason.EGRESS`; fechamento com retenção de saídas novas. *(O leitor do tracker é `egress_reader`; o design §9 o chama `connection_retry_reader`, lido como erro de digitação.)*

## 6. Prompt
- [x] 6.1 Regra de agregados no prompt do Developer (design §11).

## 7. Testes
- [x] 7.1 Um teste por cenário da spec `data-egress`.
- [x] 7.2 Teste de que nenhum ponto de chamada a modelo no código envia sem `GatedProvider` (varredura de `generate(`/`generate_content(` fora de `src/egress/` e dos provedores).
- [x] 7.3 Teste de que os caminhos principais não geram `fragmento_sem_origem`.
- [x] 7.4 Corpus de saídas reais (tracebacks do pandas, `print(df)`, `describe()`, logs de treino) com resultado esperado.
- [ ] 7.5 Medir no Pi 5 o custo do filtro em prompt de 16 000 caracteres. *(Pendente: sem testes no Pi até a bateria final, a ser combinada com o pesquisador.)*

- [x] 7.6 Integrar `check_query` (`src/research_consult/query_guard.py`) e as buscas/leituras do consultor (`v18-researcher-consult`) à egress gate, com allowlist de hosts por consulta ligada por padrão (hoje opcional e desligada: `RESEARCHER_CONSULT_ALLOWED_HOSTS`, `RESEARCHER_CONSULT_READ_ONLY_SEARCHED_HOSTS`). *(Allowlist por consulta = hosts vistos na busca da própria consulta, `RESEARCHER_CONSULT_READ_ONLY_SEARCHED_HOSTS`, agora ligada por padrão; `RESEARCHER_CONSULT_ALLOWED_HOSTS` segue vazia, pois a lista estática é decisão do pesquisador. Recusas da guarda entram em `egress_log`.)*

## 8. Fechamento
- [ ] 8.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`. *(Parcial: `ruff` sem erros novos e `pytest -m unit` verde; a suíte de integração foi escrita e não foi executada.)*
- [ ] 8.2 Revisão nos 7 eixos; PR para `dev`.
