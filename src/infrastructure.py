"""Verificação da infraestrutura externa na partida (PostgreSQL, Qdrant e daemon de containers).

Antes do ADR 014 essas checagens moravam no ``ContainerRunner``, que também construía imagens
e a rede dos agentes. Os agentes agora rodam no processo do orquestrador, então só resta
conferir se os serviços de apoio respondem. Todas as checagens apenas avisam: a ausência de um
serviço afeta só a skill que depende dele, e cada skill falha de forma explícita quando usada.
"""

from __future__ import annotations

from src.config import DATABASE_URL, QDRANT_URL, SKILL_CODE_ENABLED, SKILL_DEEP_SEARCH_ENABLED
from src.logger import get_logger
from src.utils.terminal import BOLD, RESET, STATUS_ICONS, YELLOW

logger = get_logger(__name__)


def check_postgres() -> bool:
    """Verifica se o PostgreSQL responde em ``DATABASE_URL``.

    Returns:
        ``True`` se a conexão foi aberta.
    """
    try:
        import psycopg

        psycopg.connect(DATABASE_URL, connect_timeout=3).close()
    except Exception as exc:  # noqa: BLE001 — a checagem é apenas informativa
        print(f"{STATUS_ICONS['warning']}  {YELLOW}Aviso: Não foi possível conectar ao PostgreSQL.{RESET}")
        print("   Suba o serviço: docker compose up postgres -d")
        logger.warning("PostgreSQL inacessível", extra={"error": str(exc)})
        return False
    print(f"{STATUS_ICONS['success']} PostgreSQL está online.")
    return True


def check_qdrant() -> bool:
    """Verifica o Qdrant quando a busca profunda está habilitada.

    Returns:
        ``True`` se o Qdrant responde ou se a checagem não se aplica.
    """
    if not SKILL_DEEP_SEARCH_ENABLED or QDRANT_URL == ":memory:":
        return True

    print(f"🔎 Verificando Qdrant em {QDRANT_URL}...")
    try:
        from qdrant_client import QdrantClient

        if QDRANT_URL.startswith("http"):
            client = QdrantClient(url=QDRANT_URL)
        else:
            client = QdrantClient(path=QDRANT_URL)
        client.get_collections()
    except Exception as exc:  # noqa: BLE001 — a checagem é apenas informativa
        print(f"{STATUS_ICONS['warning']}  {YELLOW}Aviso: Não foi possível conectar ao Qdrant.{RESET}")
        print("   A skill 'deep_search' pode falhar. Suba o serviço: docker compose up qdrant -d")
        logger.warning(f"Qdrant inacessível em {QDRANT_URL}: {exc}")
        return False
    print(f"{STATUS_ICONS['success']} Qdrant está online.")
    return True


def check_container_daemon() -> bool:
    """Verifica o daemon de containers, necessário só para o sandbox de código.

    Returns:
        ``True`` se o daemon responde ou se a skill de código está desabilitada.
    """
    if not SKILL_CODE_ENABLED:
        return True
    try:
        import docker

        docker.from_env(timeout=5).ping()
    except Exception as exc:  # noqa: BLE001 — a checagem é apenas informativa
        print(f"{STATUS_ICONS['warning']}  {YELLOW}Aviso: daemon de containers inacessível.{RESET}")
        print("   A skill de código executa no sandbox e falhará até o daemon voltar.")
        logger.warning("Daemon de containers inacessível", extra={"error": str(exc)})
        return False
    print(f"{STATUS_ICONS['success']} Daemon de containers está online (sandbox de código).")
    return True


def ensure_infrastructure() -> None:
    """Executa as checagens da partida e imprime o resultado."""
    print(f"\n{BOLD}🔍 Verificando infraestrutura do ambiente...{RESET}")
    check_container_daemon()
    check_postgres()
    check_qdrant()
    print(f"{BOLD}✅ Verificação concluída.{RESET}\n")
