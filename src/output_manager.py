"""Gerenciador de outputs e artefatos do GeminiClaw.

Centraliza a criação de diretórios para sessões e tarefas, 
além de permitir a listagem de artefatos produzidos pelos agentes.
"""

import shutil
import re
import datetime
import unicodedata
from pathlib import Path
from typing import Any
from src.config import OUTPUT_BASE_DIR
from src.logger import get_logger

logger = get_logger(__name__)

def generate_session_slug(prompt: str) -> str:
    """Gera um slug legível para a sessão baseado no prompt e timestamp.

    Args:
        prompt: O prompt original do usuário.

    Returns:
        String no formato YYYYMMDD_HHMMSS_slug_do_prompt.
    """
    # Timestamp
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    
    # Limpa o prompt para ser um slug seguro
    # 1. Normaliza (remove acentos)
    slug = "".join(
        c for c in unicodedata.normalize("NFD", prompt)
        if unicodedata.category(c) != "Mn"
    )
    # 2. Lowercase e remove caracteres especiais
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    
    # 3. Limita o tamanho do slug do prompt
    prompt_slug = slug[:40]
    
    return f"{ts}_{prompt_slug}"

class OutputManager:
    """Gerencia a estrutura de diretórios de outputs no host."""

    def __init__(self, base_dir: str | None = None, logs_base_dir: str | None = None):
        """Inicializa o gerenciador.

        Args:
            base_dir: Diretório raiz para outputs. Se None, usa o do config.
            logs_base_dir: Diretório raiz para logs. Se None, usa o do config.
        """
        from src.config import LOGS_BASE_DIR
        self.base_dir = Path(base_dir or OUTPUT_BASE_DIR)
        self.logs_base_dir = Path(logs_base_dir or LOGS_BASE_DIR)
        
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.logs_base_dir.mkdir(parents=True, exist_ok=True)

    def init_session(self, session_id: str) -> Path:
        """Cria os diretórios base de sessão para outputs e logs.

        Estrutura:
        outputs/<session_id>/
        ├── artifacts/
        └── logs/

        Args:
            session_id: ID único (slug) da sessão.

        Returns:
            Path para o diretório da sessão (outputs).
        """
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        session_dir.chmod(0o777)
        
        # Cria pasta de artefatos plana
        artifacts_dir = session_dir / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        artifacts_dir.chmod(0o777)
        
        # Cria pasta de logs
        # Note: No V10.2, unificamos os logs dentro da pasta da sessão para facilitar a portabilidade
        logs_dir = session_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        logs_dir.chmod(0o777)
        
        logger.info("Diretórios de sessão inicializados", extra={
            "session_id": session_id, 
            "artifacts_path": str(artifacts_dir),
            "logs_path": str(logs_dir)
        })
        return session_dir

    def get_artifacts_dir(self, session_id: str) -> Path:
        """Retorna o caminho para a pasta de artefatos da sessão.

        Args:
            session_id: ID da sessão.

        Returns:
            Path para a pasta artifacts.
        """
        path = self.base_dir / session_id / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_logs_dir(self, session_id: str, agent_id: str | None = None) -> Path:
        """Retorna o caminho para a pasta de logs da sessão.

        Args:
            session_id: ID da sessão.
            agent_id: Se fornecido, retorna o caminho para o arquivo de log do agente.

        Returns:
            Path para a pasta logs ou arquivo de log do agente.
        """
        logs_dir = self.base_dir / session_id / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        if agent_id:
            return logs_dir / f"{agent_id}.log"
        return logs_dir

    def list_artifacts(self, session_id: str) -> list[dict[str, Any]]:
        """Lista todos os arquivos produzidos em uma sessão.

        Args:
            session_id: ID da sessão.

        Returns:
            Lista de dicionários com 'name', 'type', 'size' e 'path'.
        """
        artifacts_dir = self.base_dir / session_id / "artifacts"
        if not artifacts_dir.exists():
            return []

        artifacts = []
        for file_path in artifacts_dir.rglob("*"):
            if file_path.is_file():
                file_type = file_path.suffix.lstrip(".").lower() or "unknown"
                
                artifacts.append({
                    "name": file_path.name,
                    "type": file_type,
                    "size": file_path.stat().st_size,
                    "path": str(file_path.absolute()),
                    "task": "shared"
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
