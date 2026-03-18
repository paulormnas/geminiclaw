---
trigger: model_decision
description: Regras para usar durante o teste da aplicação
---

# Regras de Testes — GeminiClaw

Framework de testes: **pytest + pytest-asyncio**.
Gerenciador de pacotes: **uv** (nunca pip).

---

## Filosofia

Os testes devem ser:

- **Rápidos** — suite completa em menos de 2 minutos no Pi 5
- **Determinísticos** — sem dependência de estado externo mutável
- **Isolados** — cada teste cria e limpa seus próprios containers e dados
- **Econômicos** — minimize chamadas reais à API do Gemini (use mocks)

---

## Estrutura de testes

```
tests/
├── conftest.py              # Fixtures globais
├── unit/                    # Sem Docker, sem API
│   ├── test_session.py
│   ├── test_ipc.py
│   └── test_runner.py
├── integration/             # Docker local + mock de API
│   ├── test_container_lifecycle.py
│   └── test_agent_session.py
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

## Níveis de teste

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
- Use a imagem local `geminiclaw-agent:test` — nunca faça pull em CI
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

## Escrevendo testes

### Teste unitário padrão

```python
# tests/unit/test_session.py
import pytest
import sqlite3
from src.session import SessionManager


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    yield conn
    conn.close()


@pytest.fixture
def session_manager(db):
    return SessionManager(db)


class TestSessionManager:
    def test_cria_sessao_com_id_unico(self, session_manager):
        s1 = session_manager.create(agent_id="agent-01")
        s2 = session_manager.create(agent_id="agent-01")
        assert s1.id != s2.id

    def test_retorna_sessao_existente(self, session_manager):
        criada = session_manager.create(agent_id="agent-02")
        recuperada = session_manager.get(criada.id)
        assert recuperada.id == criada.id

    def test_lanca_erro_para_sessao_inexistente(self, session_manager):
        with pytest.raises(ValueError, match="Session not found"):
            session_manager.get("id-inexistente")
```

### Teste de agente ADK padrão

```python
# tests/unit/test_agent_base.py
import pytest
from unittest.mock import AsyncMock, patch
from agents.base.agent import root_agent


@pytest.fixture
def mock_gemini():
    with patch("google.adk.models.gemini.generate", new_callable=AsyncMock) as mock:
        mock.return_value = {"text": "Resposta de teste"}
        yield mock


class TestBaseAgent:
    def test_agente_tem_atributos_obrigatorios(self):
        assert root_agent.name
        assert root_agent.model.startswith("gemini-")
        assert root_agent.instruction

    @pytest.mark.asyncio
    async def test_agente_responde_a_prompt_simples(self, mock_gemini):
        resposta = await root_agent.run("Olá, tudo bem?")
        assert isinstance(resposta, str) and len(resposta) > 0
        mock_gemini.assert_called_once()
```

### `tests/conftest.py` — fixtures globais

```python
import pytest
import sqlite3
from dotenv import load_dotenv

load_dotenv(".env.test", override=True)


@pytest.fixture
def in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "30")
```

---

## Limpeza pós-teste

```python
# tests/helpers/cleanup.py
import docker
import pathlib


def cleanup_test_containers() -> None:
    client = docker.from_env()
    for c in client.containers.list(all=True, filters={"name": "geminiclaw-test"}):
        c.remove(force=True)


def cleanup_test_databases(store_dir: str = "store") -> None:
    for db_file in pathlib.Path(store_dir).glob("test-*.db"):
        db_file.unlink(missing_ok=True)
```

---

## Cobertura mínima

| Módulo | Mínimo |
|---|---|
| `src/runner.py` | 80% |
| `src/session.py` | 90% |
| `src/ipc.py` | 80% |
| `agents/*/agent.py` | 70% |

---

## Relatório esperado

```
✅ TESTES APROVADOS
═══════════════════════════════════════════
Unit        : 24/24  (100%)  —  0.9s
Integration :  8/8   (100%)  — 13.2s
E2E         :  3/3   (100%)  — 31.4s  [tokens: ~420]
───────────────────────────────────────────
Total       : 35/35  (100%)  — 45.5s
Cobertura   : src/ 84%  |  agents/ 77%
🌡️  Temperatura: 72°C ✅
```

---

## O agente nunca deve

- Usar `pytest.mark.skip` sem justificativa documentada
- Alterar asserções para forçar um teste a passar sem corrigir o bug
- Usar `pip install` para instalar dependências de teste — use `uv add --dev`
- Commitar com testes falhando

---

## Comandos de referência

```bash
# Rodar testes unitários
uv run pytest -m unit -v

# Rodar testes de integração
uv run pytest -m integration -v

# Todos os testes com cobertura
uv run pytest --cov=src --cov=agents --cov-report=term-missing

# Teste específico
uv run pytest tests/unit/test_session.py::TestSessionManager::test_cria_sessao_com_id_unico -v

# Com output em tempo real (testes lentos)
uv run pytest tests/integration/ -v -s

# Containers de teste ativos
docker ps --filter "name=geminiclaw-test"

# Limpeza de emergência
uv run python -c "from tests.helpers.cleanup import cleanup_test_containers; cleanup_test_containers()"
```

---

## Testes de regressão — issues conhecidas

| Issue | Descrição | Arquivo |
|---|---|---|
| #001 | Container não removido após timeout | `tests/integration/test_container_lifecycle.py` |
| #002 | Sessão SQLite corrompida em concorrência | `tests/unit/test_session.py` |
