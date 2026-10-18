# Proposta: ciclo entre o filtro de egresso e a camada de LLM (Etapa 2)

**ID:** `v18.7-layer-cycles` · **Versão:** V18.7 · **Capacidade:** `project-structure`, `data-egress`, `llm-providers`
**ADRs de origem:** [ADR 024](../../../../docs/decisions/adr_024_organizacao_do_codigo.md) §3.5 (exceções com dono) e §4 (Etapa 2); [ADR 019](../../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) (todo envio a provedor passa pelo filtro de egresso); [ADR 017](../../../../docs/decisions/adr_017_catalogo_modelos_roteador.md) (roteador por papel)
**Depende de:** `v18.7-source-layout` (caminhos novos e contrato de camadas com a exceção que esta mudança remove). Implementada logo depois dela e antes das demais mudanças da V18.7.

## Por quê

Depois da reorganização, a simulação do grafo de importações deixa um único ciclo entre pacotes: `src.egress` ↔ `src.llm`. O gate de egresso envolve o provedor (`GatedProvider(LLMProvider)`) e lê a sessão e a alocação de modelos do `llm`; na outra direção, o roteador (`src/llm/model_router.py`, antes `src/model_router.py`) cria o `GatedProvider`, `vision` usa o tipo `Destination` do gate, `metering` usa `isinstance(..., GatedProvider)` para achar o provedor interno, e `llm/factory.get_provider` (usado pelo laço de agente sem provedor explícito) chama o roteador. Resolver exige mudar onde as peças são compostas, o que não é movimentação pura (ADR 024 §4).

## O que muda

### Novo
- `LLMProvider.unwrap()` em `src/llm/base.py`: devolve o próprio provedor; o `GatedProvider` devolve o provedor interno.
- Registro do resolvedor de provedor em `src/llm/factory.py` (`set_provider_resolver`), preenchido na partida pela camada de composição; sem registro, `get_provider()` falha com erro explícito.

### Modificado
- `Destination` sai de `src/egress/gate.py` para `src/llm/destination.py`, sem alterar o corpo.
- O roteador por papel (`ModelRouter` e o cache de provedores filtrados) sai de `src/llm/model_router.py` para `src/egress/routing.py`, sem alterar o corpo, e passa a ser a camada que compõe provedor e filtro.
- `src/llm/metering.py` usa `unwrap()` em vez de importar `GatedProvider`.
- Contrato de camadas: `src.egress` passa a ficar acima de `src.llm`, e a lista de exceções fica vazia.

### Removido
- A exceção `egress` ↔ `llm` do contrato de camadas.

### Fora do escopo
- Qualquer mudança nas regras do filtro de egresso, na localidade dos modelos ou no catálogo.

## Impacto

- **Código:** `src/llm/base.py`, `src/llm/factory.py`, `src/llm/metering.py`, `src/llm/vision.py`, `src/egress/gate.py`, `src/egress/routing.py` (novo, recebe o roteador), e quem importa o roteador (orquestração, agentes, runtime, CLI), mais o ponto de partida que registra o resolvedor (`main()` de `src/cli/main.py`); a triagem em `src/orchestration/autonomous_loop.py` (o erro do resolvedor propaga); `scripts/benchmark/comm_judge.py` (importa `Destination` do caminho novo); `tests/conftest.py` (fixture que registra o resolvedor).
- **Contratos:** `src.egress.routing.ModelRouter` substitui `src.llm.model_router.ModelRouter`; `get_provider()` exige o resolvedor registrado.
- **Schema:** nenhum. **Custo:** nenhum.

## Aprovações necessárias

Nenhuma além das já aprovadas no ADR 024. Mudança em caminho de segurança (filtro de egresso): exige parecer do Analista de Segurança.
