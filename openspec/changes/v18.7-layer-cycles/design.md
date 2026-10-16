# Design: ciclo entre o filtro de egresso e a camada de LLM (Etapa 2)

## 1. Direção escolhida

O filtro de egresso envolve o provedor: `GatedProvider` é um `LLMProvider` que recebe outro `LLMProvider` e só repassa a chamada depois de autorizar o conteúdo. Por isso o pacote `src.egress` fica **acima** de `src.llm`: ele importa tipos e a sessão de roteamento do `llm`, e nada em `src.llm` importa `src.egress`. A alternativa (o `llm` receber o gate por injeção e `egress` ficar abaixo) obrigaria o gate a deixar de herdar de `LLMProvider` e a receber a sessão de roteamento por parâmetro, com mais mudança no caminho de segurança.

Arestas atuais de `src.llm` para `src.egress` (caminhos depois de `v18.7-source-layout`) e a solução de cada uma:

| Aresta | Solução |
|---|---|
| `src/llm/model_router.py` → `src.egress.gate` (`Destination`, `GatedProvider`) | o roteador vai para `src/egress/routing.py`; ele é o ponto que compõe provedor e filtro |
| `src/llm/vision.py` → `src.egress.gate` (`Destination`) | `Destination` vai para `src/llm/destination.py`, sem alterar o corpo; `vision` e o gate importam de lá |
| `src/llm/metering.py` → `src.egress.gate` (`GatedProvider`, para achar o provedor interno) | `LLMProvider.unwrap()`; `provider_name` usa `provider.unwrap()` |
| `src/llm/factory.py` → roteador (`get_provider`, usado por `src/llm/agent_loop.py` quando não recebe provedor e por `src/orchestration/autonomous_loop.py`) | resolvedor registrado na partida (§2) |

## 2. Resolvedor de provedor

`src/llm/factory.py` passa a guardar uma função `resolver(papel: str | None) -> LLMProvider`, registrada por `set_provider_resolver(fn)`. `src.egress.routing.install_provider_resolver()` registra `ModelRouter.get_provider`; `main()` de `src/cli/main.py` a chama antes de ler os argumentos. O runtime de agentes roda no mesmo processo e já usa `ModelRouter.get_provider(papel)` direto, então não precisa de registro próprio. `get_provider()` sem resolvedor registrado lança `RuntimeError("resolvedor de provedor não registrado: a partida deve registrar o roteador com filtro de egresso")`; com resolvedor que devolva provedor não envolvido (`provider.unwrap() is provider`), lança `RuntimeError("provedor sem filtro de egresso: o resolvedor registrado deve devolver o provedor do roteador")` (§5, S2). Assim, o único caminho para obter um provedor continua sendo o roteador, que sempre devolve um `GatedProvider` (ADR 019).

Nos testes, uma fixture `autouse` em `tests/conftest.py` chama `install_provider_resolver()` e, no fim, restaura o resolvedor anterior; os testes do estado sem registro removem o resolvedor com `monkeypatch.setattr(factory, "_resolver", None)`.

## 3. Contrato final de camadas

Ordem de cima para baixo, saída da simulação do grafo sem as arestas de `llm` para `egress`:

1. `src.cli`
2. `src.orchestration`
3. `src.agent_runtime`
4. `src.agents`
5. `src.report`, `src.session`
6. `src.claims`, `src.skills`
7. `src.knowledge`
8. `src.numeric_refs`
9. `src.provenance`
10. `src.artifacts`, `src.research_data`
11. `src.egress`
12. `src.documents`, `src.llm`
13. `src.embeddings`, `src.gate`, `src.host`, `src.observability`
14. `src.research_consult`, `src.utils`, `src.config`, `src.logger`, `src.db`

Lista de exceções vazia.

## 4. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Arquitetura | Último ciclo entre pacotes removido; composição de provedor e filtro num só lugar (`src/egress/routing.py`). |
| Dados e schema | Nenhum. |
| Segurança | Caminho crítico: todo envio a provedor precisa continuar passando pelo `GatedProvider`. Mitigado pelo resolvedor obrigatório e por testes de que todo provedor obtido é filtrado. |
| Desempenho e recursos no Pi | Nenhum. |
| Operação | Nenhuma configuração nova. |
| Testes | Testes de ligação do egresso (`tests/unit/egress/test_wiring.py`) estendidos; contrato de camadas sem exceções. |

## 5. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.** A direção (egresso acima de `llm`, composição no roteador) mantém a garantia do ADR 019, e os caminhos de triagem (`get_provider()`), sumarização, curadoria, validação e runtime de agentes (`ModelRouter.get_provider(papel)`) continuam recebendo `GatedProvider`. As ressalvas abaixo são requisitos desta mudança (S1 a S3 têm cenário na spec e tarefa); S4 e S5 são registro.

- **S1 (alta) — escopo do teste estático errado.** As classes de provedor são instanciadas nas fábricas de `src/llm/providers/__init__.py`, e não em `src/llm/registry.py`; o teste como estava escrito falharia no primeiro dia ou seria "consertado" alargando a lista. O provedor sem filtro sai de **funções**, não só de construtores: `create_provider` (`src/llm/registry.py`, hoje chamada pelo roteador, por `src/llm/availability.py` e por `scripts/benchmark/comm_judge.py`), `availability.default_provider_factory` e o novo `unwrap()`. Requisito: o teste estático percorre `src/` e `scripts/` (não `tests/`, onde os testes de provedor instanciam as classes com clientes simulados) e só aceita (a) instanciação de classes de `src/llm/providers/` dentro de `src/llm/providers/`; (b) `create_provider(` em `src/egress/routing.py`, `src/llm/availability.py` e `scripts/benchmark/comm_judge.py`; (c) `default_provider_factory(` em `src/llm/availability.py`; (d) `.unwrap()` em `src/llm/metering.py`; (e) `.inner` em `src/egress/`. Arquivo novo numa dessas listas exige parecer de segurança no PR. O teste atual `test_nenhum_ponto_de_chamada_envia_sem_gated_provider` aceita qualquer arquivo que contenha o texto `GatedProvider(`; a lista explícita o substitui nessa parte.
- **S2 (média) — resolvedor fail-secure.** `set_provider_resolver` aceita qualquer função; um resolvedor que devolva provedor cru (por exemplo, `create_provider` registrado num script) passaria sem aviso. Requisito: `get_provider()` confere `provider.unwrap() is not provider` (sem importar `src.egress`) e, se o provedor não estiver envolvido, lança `RuntimeError("provedor sem filtro de egresso: o resolvedor registrado deve devolver o provedor do roteador")` sem devolvê-lo.
- **S3 (média) — triagem engole o erro.** `_triage` (`src/orchestration/autonomous_loop.py`) chama `get_provider()` dentro de `except Exception` que devolve `True`; sem resolvedor registrado, a sessão seguiria como COMPLEX e o erro de composição sumiria. Não há envio sem filtro (nada é enviado), mas contraria o fail-fast. Requisito: o `RuntimeError` do resolvedor (S2 e §2) propaga na triagem.
- **S4 (registro) — visão é outro canal.** `src/llm/vision.py` chama o SDK do Google e o `/api/chat` do Ollama direto, fora do `GatedProvider`, por desenho: o `ContextLoader` chama `EgressGate.authorize_vision` antes de `describe_image`, e `test_wiring.py` já confere isso. O requisito "todo provedor obtido passa pelo filtro" vale para o canal `llm`; a verificação da visão continua com o caminho novo do `ContextLoader` (`src/research_data/context_loader.py`). Mover `Destination` não altera esse canal.
- **S5 (registro, fora do escopo) — `GatedProvider.__getattr__` repassa qualquer atributo** ao provedor interno, inclusive privados (`_client`), o que dá acesso ao SDK sem filtro. Hoje nenhum provedor tem método público de envio além de `generate`/`generate_stream` (só `fetch_digest` e `aclose`), e o teste estático acusa `generate_content(` fora dos provedores. Recomendação para mudança futura: repassar só nomes de uma lista (`fetch_digest`, `aclose`). Decisão do pesquisador 2026-10-15: adiado; a prioridade é o sistema funcionar.
- **Importadores de `Destination`:** `src/llm/vision.py`, `scripts/benchmark/comm_judge.py` e os testes passam a importar de `src.llm.destination`; `src.egress.gate.Destination` não é caminho público (ADR 024 §6), e alvos de `patch` em texto são atualizados.

## 6. Riscos e mitigações

- **Provedor sem filtro por esquecimento de registro:** `get_provider()` falha em vez de criar provedor; teste.
- **Provedor criado direto, fora do roteador:** teste estático com as listas explícitas da §5 (S1): construtores de provedor, `create_provider`, `default_provider_factory`, `unwrap()` e `.inner`, em `src/` e `scripts/`.
- **Resolvedor que devolve provedor cru:** `get_provider()` confere o envolvimento e falha (§5, S2).
- **`unwrap()` com comportamento diferente do `isinstance`:** teste de `provider_name` com provedor filtrado e sem filtro, mesmo nome de antes.

## 7. Questões em aberto

- **Ciclo `config` ↔ `utils` (resolvida em 2026-10-15).** `src/config.py` importa `src/utils/node_id.py` dentro de função e `src/utils/qdrant.py` importava `src.config`. Decisão do pesquisador: arquivos de conexão com banco não ficam em `utils` quando há pacote mais descritivo; o cliente do Qdrant foi para `src/memory/qdrant.py`, e `utils` passou para baixo de `config` no contrato. A lista de exceções ficou vazia.
