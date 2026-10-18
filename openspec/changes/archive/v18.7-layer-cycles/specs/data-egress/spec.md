# Capacidade: data-egress

## ADDED Requirements

### Requirement: Todo provedor obtido passa pelo filtro de egresso
O único caminho para obter um provedor de LLM do canal `llm` SHALL ser o roteador com filtro (`src.egress.routing.ModelRouter`), diretamente ou pelo resolvedor registrado em `src.llm.factory`; todo provedor devolvido MUST ser um `GatedProvider`. Em `src/` e `scripts/`, o que devolve ou expõe provedor sem filtro MUST aparecer só nestes arquivos: construtores das classes de provedor em `src/llm/providers/`; `create_provider(` em `src/egress/routing.py`, `src/llm/availability.py` e `scripts/benchmark/comm_judge.py`; `default_provider_factory(` em `src/llm/availability.py`; `.unwrap()` em `src/llm/metering.py`; `.inner` em `src/egress/` (ADR 019; ADR 024 §4).

#### Scenario: Provedor de cada papel é filtrado
- **GIVEN** o catálogo de modelos dos testes (`src/llm/catalog.yaml` com o health check simulado da fixture `isolate_model_routing`) e o resolvedor registrado pela fixture de `tests/conftest.py`
- **WHEN** o teste obtém o provedor dos papéis `researcher`, `developer`, `validator`, `summarizer`, `curator`, `base` e do alias `planner` por `ModelRouter.get_provider(papel)`, e o provedor sem papel por `get_provider()`
- **THEN** todos os objetos devolvidos são `GatedProvider`

#### Scenario: Provedor sem filtro só nos arquivos permitidos
- **WHEN** o teste estático percorre os arquivos `.py` de `src/` e `scripts/` procurando construtores das classes de `src/llm/providers/`, `create_provider(`, `default_provider_factory(`, `.unwrap()` e `.inner`
- **THEN** cada ocorrência está num arquivo da lista do requisito para aquele padrão (padrões com limite de palavra: `_default_provider_factory` de `src/cli/graph.py`, que devolve o provedor do Curator pelo roteador, não conta)
- **AND** a mesma verificação, rodada sobre um diretório temporário (`tmp_path`) com um arquivo `src/qualquer.py` que chama `create_provider(`, acusa esse arquivo

#### Scenario: Resolvedor que devolve provedor cru é recusado
- **GIVEN** um resolvedor registrado com `set_provider_resolver` que devolve um `FakeProvider` sem `GatedProvider`
- **WHEN** o código chama `get_provider()`
- **THEN** é lançado `RuntimeError` com a mensagem "provedor sem filtro de egresso: o resolvedor registrado deve devolver o provedor do roteador" e o provedor não é devolvido

#### Scenario: Triagem não engole a falta de resolvedor
- **GIVEN** nenhum resolvedor registrado (`monkeypatch.setattr(factory, "_resolver", None)`)
- **WHEN** a triagem do laço autônomo classifica um pedido
- **THEN** o `RuntimeError` do resolvedor propaga e nenhuma chamada de geração é feita
