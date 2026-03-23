"""Ferramentas comuns para todos os agentes GeminiClaw."""

import os
from typing import Optional
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

async def manage_memory(action: str, key: str, value: Optional[str] = None, importance: float = 0.5, tags: list[str] = []) -> str:
    """Gerencia memórias de curto e longo prazo do agente.

    Args:
        action: 'remember' (curto prazo), 'memorize' (longo prazo), 'recall' (lê curto prazo), 'retrieve' (lê ambos), 'remember_forever' (curto -> longo).
        key: Chave identificadora da memória.
        value: Conteúdo da memória (obrigatório para 'remember', 'memorize').
        importance: Nível de importância de 0.0 a 1.0 (apenas para longo prazo).
        tags: Lista de tags para categorização.

    Returns:
        Resultado da operação de memória.
    """
    from src.skills.memory.skill import MemorySkill
    import os
    
    session_id = os.environ.get("SESSION_ID")
    agent_id = os.environ.get("AGENT_ID", "agent")
    
    skill = MemorySkill()
    result = await skill.run(
        action=action,
        session_id=session_id,
        key=key,
        value=value,
        source=agent_id,
        importance=importance,
        tags=tags
    )
    
    if result.success:
        return result.output
    else:
        return f"Erro na operação de memória: {result.error}"
