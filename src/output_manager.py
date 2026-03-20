"""Gerenciador de outputs e artefatos do GeminiClaw.

Centraliza a criação de diretórios para sessões e tarefas, 
além de permitir a listagem de artefatos produzidos pelos agentes.
"""

import shutil
from pathlib import Path
from typing import Any
from src.config import OUTPUT_BASE_DIR
from src.logger import get_logger

logger = get_logger(__name__)

class OutputManager:
    """Gerencia a estrutura de diretórios de outputs no host."""

    def __init__(self, base_dir: str | None = None):
        """Inicializa o gerenciador.

        Args:
            base_dir: Diretório raiz para outputs. Se None, usa o do config.
        """
        self.base_dir = Path(base_dir or OUTPUT_BASE_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def init_session(self, session_id: str) -> Path:
        """Cria o diretório base para uma sessão.

        Args:
            session_id: ID único da sessão.

        Returns:
            Path para o diretório da sessão.
        """
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Diretório de sessão inicializado", extra={"session_id": session_id, "path": str(session_dir)})
        return session_dir

    def get_task_dir(self, session_id: str, task_name: str) -> Path:
        """Cria e retorna o diretório para uma tarefa específica com subpastas.

        Args:
            session_id: ID da sessão.
            task_name: Nome da tarefa (será usado como nome da pasta).

        Returns:
            Path para o diretório da tarefa.
        """
        # Sanitização básica do nome da tarefa para evitar problemas de path
        safe_task_name = task_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
        task_dir = self.base_dir / session_id / safe_task_name
        
        # Cria a estrutura completa (Etapa 1)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "logs").mkdir(exist_ok=True)
        (task_dir / "artifacts").mkdir(exist_ok=True)
        
        return task_dir

    def list_artifacts(self, session_id: str) -> list[dict[str, Any]]:
        """Lista todos os arquivos produzidos em uma sessão.

        Args:
            session_id: ID da sessão.

        Returns:
            Lista de dicionários com 'task', 'name', 'type', 'size' e 'path'.
        """
        session_dir = self.base_dir / session_id
        if not session_dir.exists():
            return []

        artifacts = []
        for file_path in session_dir.rglob("*"):
            if file_path.is_file():
                # Determina o tipo via extensão (Etapa 1)
                file_type = file_path.suffix.lstrip(".").lower() or "unknown"
                
                artifacts.append({
                    "task": file_path.parent.name if file_path.parent.name not in ["logs", "artifacts"] else file_path.parent.parent.name,
                    "name": file_path.name,
                    "type": file_type,
                    "size": file_path.stat().st_size,
                    "path": str(file_path.absolute())
                })
        return artifacts
    def cleanup_session(self, session_id: str) -> None:
        """Remove recursivamente o diretório de uma sessão.

        Args:
            session_id: ID da sessão.
        """
        session_dir = self.base_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info("Diretório de sessão removido", extra={"session_id": session_id})
