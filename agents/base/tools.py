"""Ferramentas comuns para todos os agentes GeminiClaw."""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

async def write_artifact(filename: str, content: str) -> str:
    """Salva um artefato (arquivo) no diretório de saídas do container.

    Args:
        filename: Nome do arquivo (ex: 'resumo.md').
        content: Conteúdo textual do arquivo.

    Returns:
        Mensagem de sucesso ou erro.
    """
    if not filename or not content:
        return "Erro: Nome do arquivo ou conteúdo vazio."

    try:
        agent_id = os.environ.get("AGENT_ID", "default_agent")
        # O Orquestrador mapeia outputs/<session_id>/ para /outputs/
        # Espera-se que artefatos fiquem em <agent_id>/artifacts/
        base_dir = Path("/outputs")
        if not base_dir.exists():
            return "Erro: Diretório /outputs não encontrado no container."

        task_dir = base_dir / agent_id / "artifacts"
        
        # Se for um caminho absoluto como "/outputs/.../arquivo.txt", transforma em relativo para a tarefa
        safe_name = Path(filename).name
        
        task_dir.mkdir(parents=True, exist_ok=True)

        file_path = task_dir / safe_name
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Artefato salvo com sucesso em {file_path}"

    except Exception as e:
        logger.error(f"Erro ao salvar artefato: {e}")
        return f"Erro ao salvar artefato: {str(e)}"
