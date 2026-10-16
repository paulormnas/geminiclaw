"""Comandos `sessions` e `stop`: listam e param containers de sandbox de código.

Movido de ``src/cli/main.py`` sem alterar o comportamento (v18.7-background-sessions, tarefa 0.9; ADR 024 §5).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from src.config import (
    APP_NAME,
)
from src.logger import get_logger
from src.utils.terminal import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW

logger = get_logger(__name__)


def show_sessions(docker_client: Any | None = None) -> list[dict[str, Any]]:
    """Lista os containers de sandbox de código ativos do GeminiClaw (Roadmap V14.6).

    Os agentes rodam no processo do orquestrador (ADR 014); o único container é o sandbox.

    Args:
        docker_client: Cliente Docker opcional (para injeção em testes).

    Returns:
        Lista com metadados dos containers ativos encontrados.
    """
    if docker_client is None:
        try:
            import docker
            docker_client = docker.from_env()
        except Exception as e:
            print(f"\n  {RED}❌ Erro ao conectar ao Docker: {e}{RESET}\n")
            return []

    try:
        containers = docker_client.containers.list(
            filters={"label": "project=geminiclaw"}
        )
    except Exception as e:
        print(f"\n  {RED}❌ Erro ao listar containers: {e}{RESET}\n")
        return []

    _sep = "─" * 80
    print(f"\n{BOLD}  📦 Sandboxes de Código Ativos do {APP_NAME}{RESET}")
    print(f"{BOLD}{_sep}{RESET}")

    if not containers:
        print(f"  {DIM}Nenhum sandbox de código ativo encontrado.{RESET}")
        print(f"{BOLD}{_sep}{RESET}\n")
        return []

    header = (
        f"  {BOLD}{'SESSION ID':<24} {'CONTAINER ID':<14} {'TASK':<12} "
        f"{'MODE':<10} {'IMAGE':<24} {'STATUS'}{RESET}"
    )
    print(header)
    print(f"  {DIM}{'─' * 88}{RESET}")

    active_info = []
    for c in containers:
        labels = getattr(c, "labels", {}) or {}
        session_id = labels.get("session_id", "unknown")
        agent_id = labels.get("task_name") or labels.get("agent_id", "unknown")
        session_mode = labels.get("session_mode", "—")
        cid = getattr(c, "short_id", getattr(c, "id", "unknown")[:12])

        image_name = "unknown"
        if hasattr(c, "image"):
            if hasattr(c.image, "tags") and c.image.tags:
                image_name = c.image.tags[0]
            else:
                image_name = str(c.image)

        status = getattr(c, "status", "unknown")
        status_color = GREEN if status == "running" else YELLOW

        print(
            f"  {CYAN}{session_id:<24}{RESET} {DIM}{cid:<14}{RESET} {agent_id:<12} "
            f"{session_mode:<10} {image_name:<24} [{status_color}{status}{RESET}]"
        )
        active_info.append({
            "session_id": session_id,
            "container_id": cid,
            "agent_id": agent_id,
            "mode": session_mode,
            "image": image_name,
            "status": status,
        })

    print(f"{BOLD}{_sep}{RESET}\n")
    return active_info


def stop_sessions(
    session_id: str | None = None,
    docker_client: Any | None = None,
) -> int:
    """Encerra os containers de sandbox de código ativos (Roadmap V14.6).

    Args:
        session_id: ID da sessão a encerrar, ou None para encerrar todas as sessões.
        docker_client: Cliente Docker opcional (para injeção em testes).

    Returns:
        Número de containers encerrados.
    """
    if docker_client is None:
        try:
            import docker
            docker_client = docker.from_env()
        except Exception as e:
            print(f"\n  {RED}❌ Erro ao conectar ao Docker: {e}{RESET}\n")
            return 0

    try:
        containers = docker_client.containers.list(
            filters={"label": "project=geminiclaw"}
        )
    except Exception as e:
        print(f"\n  {RED}❌ Erro ao listar containers para encerramento: {e}{RESET}\n")
        return 0

    if session_id:
        targets = [c for c in containers if (getattr(c, "labels", {}) or {}).get("session_id") == session_id]
    else:
        targets = containers

    if not targets:
        if session_id:
            print(f"\n  {DIM}Nenhum container ativo encontrado para a sessão: {session_id}{RESET}\n")
        else:
            print(f"\n  {DIM}Nenhum container ativo do {APP_NAME} encontrado.{RESET}\n")
        return 0

    stopped_count = 0
    print(f"\n  {YELLOW}🛑 Encerrando {len(targets)} container(s)...{RESET}")
    for c in targets:
        cid = getattr(c, "short_id", getattr(c, "id", "unknown")[:12])
        labels = getattr(c, "labels", {}) or {}
        s_id = labels.get("session_id", "unknown")
        try:
            c.stop(timeout=10)
            stopped_count += 1
            print(f"    {GREEN}✔{RESET} Container {BOLD}{cid}{RESET} (sessão: {DIM}{s_id}{RESET}) encerrado.")
        except Exception as e:
            print(f"    {RED}✘{RESET} Erro ao parar container {cid}: {e}")

    print(f"  {GREEN}✅ {stopped_count} container(s) encerrado(s) com sucesso.{RESET}\n")
    return stopped_count
