"""Fixtures dos testes de integração do grafo de conhecimento (Apache AGE real).

Estes testes exigem uma instância real de PostgreSQL 16 + Apache AGE, com a
migração ``v17_001`` já aplicada (``scripts/migrate_v17_knowledge.py``). Não
tocam nenhum banco/volume compartilhado — devem ser apontados para uma
instância isolada, por exemplo subida a partir deste worktree com um nome de
projeto Docker Compose próprio:

    docker compose -p v17-graph-test up -d postgres
    export DATABASE_URL=postgresql://geminiclaw:geminiclaw_secret@localhost:5432/geminiclaw
    export KNOWLEDGE_READER_PASSWORD=<senha de teste>
    export KNOWLEDGE_READER_DATABASE_URL=postgresql://knowledge_reader:<mesma senha>@localhost:5432/geminiclaw
    uv run python scripts/migrate_v17_knowledge.py
    uv run pytest tests/integration/knowledge/ -m integration -v
    docker compose -p v17-graph-test down -v   # limpeza

Se a instância não estiver acessível, ou a migração não tiver sido aplicada,
o módulo inteiro é pulado (não falha) — mantém ``pytest -m integration``
seguro de rodar em máquinas sem esta infraestrutura disponível (ex.: CI sem
Apache AGE, ou o ambiente de desenvolvimento deste PR, onde a suíte real
contra AGE não foi executada por restrição de espaço em disco — ver relatório
do PR desta mudança).

Nota: ``tests/conftest.py`` mocka ``src.db.get_connection`` globalmente para
toda a suíte; este diretório é explicitamente excluído desse mock (mesma
exceção usada por ``tests/unit/test_db.py``) para que ``AgeGraphStore`` use a
conexão real configurada acima.
"""

from __future__ import annotations

import pytest

from src import config
from src.knowledge.graph_store import AgeGraphStore


def _graph_ready() -> tuple[bool, str]:
    """Sonda, com timeout curto, se há um grafo AGE migrado e acessível.

    Usa uma conexão avulsa (não o pool singleton de ``src.db``) para não
    afetar outros módulos de teste que compartilham esse singleton.

    Returns:
        ``(True, "")`` se o grafo existe e está acessível; caso contrário
        ``(False, motivo)`` com uma mensagem explicando o que falhou —
        usada como razão do ``skip`` do módulo inteiro.
    """
    try:
        import psycopg

        with psycopg.connect(config.DATABASE_URL, connect_timeout=2) as conn:
            conn.execute("LOAD 'age'")
            conn.execute('SET search_path = ag_catalog, "$user", public')
            row = conn.execute(
                "SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s",
                (config.KNOWLEDGE_GRAPH_NAME,),
            ).fetchone()
            if row is None:
                return (
                    False,
                    f"Grafo '{config.KNOWLEDGE_GRAPH_NAME}' não existe — rode "
                    "scripts/migrate_v17_knowledge.py contra a instância de teste.",
                )
        return True, ""
    except Exception as exc:  # noqa: BLE001 - qualquer falha de infra vira skip, não erro de teste
        return False, f"Apache AGE de teste indisponível ({exc.__class__.__name__}): {exc}"


_ready, _reason = _graph_ready()

pytestmark = pytest.mark.skipif(not _ready, reason=_reason)


@pytest.fixture
def age_store() -> AgeGraphStore:
    """``AgeGraphStore`` real, configurado a partir de ``src.config``.

    Pula o teste (em vez de falhar) se ``KNOWLEDGE_READER_DATABASE_URL`` não
    estiver configurada — necessária apenas pelos testes que exercitam
    ``read_query``.
    """
    return AgeGraphStore(
        config.KNOWLEDGE_GRAPH_NAME,
        reader_conninfo=config.KNOWLEDGE_READER_DATABASE_URL or "",
        read_timeout_ms=config.KNOWLEDGE_READ_TIMEOUT_MS,
    )
