# Capacidade: llm-providers

## ADDED Requirements

### Requirement: Resolvedor de provedor registrado na partida
`src.llm.factory.get_provider()` SHALL obter o provedor pela função registrada com `set_provider_resolver`; `src.egress.routing.install_provider_resolver()` SHALL registrar `ModelRouter.get_provider`, e `main()` de `src/cli/main.py` SHALL chamá-la antes de ler os argumentos. Sem resolvedor registrado, `get_provider()` MUST lançar `RuntimeError` com a mensagem "resolvedor de provedor não registrado: a partida deve registrar o roteador com filtro de egresso" e MUST NOT criar provedor (ADR 017; ADR 024 §4).

#### Scenario: Sem registro, falha explícita
- **GIVEN** nenhum resolvedor registrado (`monkeypatch.setattr(factory, "_resolver", None)`, desfazendo o registro da fixture de `tests/conftest.py`) e `ModelRouter.get_provider` substituído por um dublê que conta chamadas
- **WHEN** o código chama `get_provider()`
- **THEN** é lançado `RuntimeError` com a mensagem do requisito e o dublê não foi chamado

#### Scenario: Partida registra o roteador
- **GIVEN** nenhum resolvedor registrado e `sys.argv` igual a `["geminiclaw", "--help"]`
- **WHEN** o teste chama `main()` de `src/cli/main.py` (capturando o `SystemExit` da ajuda) e depois `get_provider()`
- **THEN** o provedor devolvido é um `GatedProvider` do papel `researcher` (`provider.dest.papel == "researcher"`), igual ao de `ModelRouter.get_provider("researcher")`

### Requirement: Provedor interno sem depender do filtro
`LLMProvider` SHALL oferecer `unwrap()`, que devolve o próprio provedor; o `GatedProvider` SHALL devolver o provedor interno. `src.llm.metering.provider_name` SHALL usar `unwrap()` e MUST NOT importar `src.egress` (ADR 024 §4).

#### Scenario: Nome do provedor com e sem filtro
- **GIVEN** um provedor simulado `FakeProvider` e o mesmo provedor envolvido por `GatedProvider`
- **WHEN** o teste chama `provider_name` com cada um
- **THEN** os dois resultados são `fake`
