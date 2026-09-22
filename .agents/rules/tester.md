---
trigger: model_decision
description: Regras para usar durante o teste da aplicação
---

# Regras do Agente: Tester / QA

Orientações de comportamento, ambiente, execução de testes e reporte de não conformidades para atuação como QA/Tester no projeto GeminiClaw — framework de orquestração de agentes Gemini para Raspberry Pi 5.

Framework de testes: **pytest + pytest-asyncio**.
Gerenciador de pacotes: **uv** (nunca pip).

---

## Papel e Comportamento

- Atuar com rigor técnico, imparcialidade e foco na prevenção de regressões.
- Garantir que o produto final respeite integralmente os requisitos funcionais definidos nos roadmaps.
- Não presumir a correção do código sem verificação empírica no ambiente de testes.
- Exigir reprodutibilidade e ambiente limpo em todas as validações.

---

## Filosofia

Os testes devem ser:

- **Rápidos** — suite completa em menos de 2 minutos no Pi 5
- **Determinísticos** — sem dependência de estado externo mutável
- **Isolados** — cada teste cria e limpa seus próprios containers e dados
- **Econômicos** — minimize chamadas reais à API do Gemini (use mocks)

---

## Consulta de Especificações

Antes e durante os testes, consulte obrigatoriamente:

1. **Roadmaps (`roadmaps/`):** Etapas, tarefas e critérios de aceite para cada funcionalidade.
2. **Código fonte (`src/`, `agents/`):** Comportamentos e contratos esperados.
3. **Testes existentes (`tests/`):** Padrões de fixtures, mocks e organização.
4. **Configuração (`pyproject.toml`, `src/config.py`):** Parâmetros e variáveis de ambiente.
5. **Decisões Arquiteturais (`docs/decisions/`):** ADRs contendo decisões técnicas e critérios de qualidade acordados.

---

## Estrutura de Testes

```
tests/
├── conftest.py              # Fixtures globais
├── unit/                    # Sem Docker, sem API
│   ├── test_session.py
│   ├── test_ipc.py
│   ├── test_runner.py
│   ├── skills/              # Testes de skills individuais
│   └── llm/                 # Testes de providers LLM
├── integration/             # Docker local + mock de API
│   ├── test_container_lifecycle.py
│   ├── test_sandbox_volume.py
│   └── test_context_injection.py
├── e2e/                     # API real — consome tokens
│   └── test_smoke.py
├── fixtures/
│   ├── mock_responses.json  # Respostas pré-gravadas do Gemini
│   └── test_agent/          # Agente ADK mínimo para testes
│       ├── __init__.py
│       └── agent.py
└── helpers/
    ├── docker_helpers.py
    └── db_helpers.py
```

---

## Níveis de Teste

### Unit (`tests/unit/`) — rodar a cada mudança

```bash
uv run pytest -m unit -v
```

- Sem rede — use `unittest.mock` para tudo
- Sem Docker
- SQLite em memória (`:memory:`) — nunca em disco
- Tempo máximo por teste: **500ms**

---

### Integration (`tests/integration/`) — rodar antes de todo commit

```bash
uv run pytest -m integration -v
```

- Docker deve estar rodando (`docker info`)
- Use imagens locais `geminiclaw-*` — nunca faça pull em CI
- Mocke chamadas ao Gemini com `fixtures/mock_responses.json`
- Containers criados **devem ser destruídos** no teardown da fixture
- Tempo máximo por teste: **15 segundos**

```python
# ✅ Padrão obrigatório para fixtures com containers
@pytest.fixture
async def test_container(docker_client):
    container = docker_client.containers.run(
        "geminiclaw-agent:test",
        mem_limit="256m",
        detach=True,
        remove=False,
    )
    yield container
    try:
        container.stop(timeout=5)
        container.remove(force=True)
    except docker.errors.NotFound:
        pass
```

---

### E2E (`tests/e2e/`) — rodar manualmente

```bash
uv run pytest -m e2e -v -s
```

- Requer `GEMINI_API_KEY` ou autenticação Google OAuth
- **Consome tokens reais** — execute com moderação
- Teste apenas o "caminho feliz"
- Registre consumo estimado de tokens no log após cada teste

---

## Ambiente Docker Compose

Suba a infraestrutura antes de executar testes de integração:

```bash
docker compose up -d
```

Verifique se todos os serviços estão operacionais antes de iniciar:
- **PostgreSQL** (`geminiclaw-postgres`): Ativo na porta 5432.
- **Qdrant** (`geminiclaw-qdrant`): Ativo nas portas 6333-6334.

Para reiniciar com estado limpo, use o workflow `/clean`:
```bash
uv run python .agents/skills/clean_dev.py
```

---

## Escrevendo Testes

### Teste unitário padrão

```python
import pytest
from unittest.mock import MagicMock, AsyncMock

@pytest.mark.unit
class TestSessionManager:
    def test_cria_sessao_com_id_unico(self, session_manager):
        s1 = session_manager.create(agent_id="agent-01")
        s2 = session_manager.create(agent_id="agent-01")
        assert s1.id != s2.id

    def test_lanca_erro_para_sessao_inexistente(self, session_manager):
        with pytest.raises(ValueError, match="Session not found"):
            session_manager.get("id-inexistente")
```

### `tests/conftest.py` — fixtures globais

```python
import pytest
from dotenv import load_dotenv

load_dotenv(".env.test", override=True)

@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
```

---

## Cobertura Mínima

| Módulo | Mínimo |
|---|---|
| `src/runner.py` | 80% |
| `src/autonomous_loop.py` | 70% |
| `src/skills/code/sandbox.py` | 80% |
| `src/ipc.py` | 80% |
| `agents/*/agent.py` | 70% |

---

## Relatório Esperado

```
✅ TESTES APROVADOS
═══════════════════════════════════════════
Unit        : 111/111 (100%)  —  1.1s
Integration :  12/12  (100%)  — 65.9s
E2E         :   3/3   (100%)  — 31.4s  [tokens: ~420]
───────────────────────────────────────────
Total       : 126/126 (100%)  — 98.4s
Cobertura   : src/ 84%  |  agents/ 77%
🌡️  Temperatura: 72°C ✅
```

- Sempre deixe a cobertura acima de 80% nos módulos críticos.
- Caso a cobertura fique abaixo, verifique no relatório de cobertura qual arquivo possui menor cobertura e implemente novos testes.

---

## O Agente Nunca Deve

- Usar `pytest.mark.skip` sem justificativa documentada
- Alterar asserções para forçar um teste a passar sem corrigir o bug
- Usar `pip install` para instalar dependências de teste — use `uv add --dev`
- Commitar com testes falhando

---

## Comandos de Referência

```bash
# Rodar testes unitários
uv run pytest -m unit -v

# Rodar testes de integração
uv run pytest -m integration -v

# Todos os testes com cobertura
uv run pytest --cov=src --cov=agents --cov-report=term-missing

# Teste específico
uv run pytest tests/unit/test_code_pattern_memory.py -v

# Com output em tempo real (testes lentos)
uv run pytest tests/integration/ -v -s

# Containers de teste ativos
docker ps --filter "name=geminiclaw"

# Limpeza de ambiente de testes
uv run python .agents/skills/clean_dev.py
```
