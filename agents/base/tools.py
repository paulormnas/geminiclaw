"""Ferramentas comuns para todos os agentes GeminiClaw."""

import errno
import logging
import os
from pathlib import Path
from typing import Optional

from src.agent_runtime.context import get_agent_context_optional

logger = logging.getLogger(__name__)


def _resolve_artifacts_dir() -> Path | None:
    """Resolve o diretório de artefatos confinado à sessão da tarefa atual.

    Roadmap V16/ADR 014 (Design §4) — no runtime em processo, o diretório vem
    do ``AgentContext`` vinculado à tarefa (``ctx.output_dir / "artifacts"``).
    No modo container legado, sem ``AgentContext``, usa o caminho fixo
    ``/outputs/artifacts`` montado pelo orquestrador no container.

    Returns:
        Caminho resolvido do diretório de artefatos, ou ``None`` se
        indisponível (ex.: modo container sem ``/outputs`` montado).
    """
    ctx = get_agent_context_optional()
    if ctx is not None:
        return (ctx.output_dir / "artifacts").resolve()

    base_dir = Path("/outputs")
    if not base_dir.exists():
        return None
    return (base_dir / "artifacts").resolve()


async def write_artifact(filename: str, content: str) -> str:
    """Salva um artefato (arquivo) confinado ao diretório de artefatos da sessão.

    Roadmap V16/ADR 014 (Design §4) — a escrita é sempre confinada a
    ``<output_dir>/artifacts/``: o nome do arquivo é normalizado (apenas o
    componente final do caminho é usado, descartando qualquer tentativa de
    ``../``) e a abertura do arquivo usa ``O_NOFOLLOW`` — se o destino já for
    um symlink (inclusive um trocado por um symlink entre uma checagem
    anterior e esta escrita), o próprio ``open()`` falha atomicamente, sem
    janela de TOCTOU.

    Args:
        filename: Nome do arquivo (ex: 'resumo.md').
        content: Conteúdo textual do arquivo.

    Returns:
        Mensagem de sucesso ou erro.
    """
    if not filename or not content:
        return "Erro: Nome do arquivo ou conteúdo vazio."

    try:
        task_dir = _resolve_artifacts_dir()
        if task_dir is None:
            return "Erro: Diretório de outputs não encontrado."

        # Apenas o componente final do path é usado — descarta qualquer
        # tentativa de path traversal (ex.: "../../etc/passwd" -> "passwd").
        safe_name = Path(filename).name
        if not safe_name or safe_name in (".", ".."):
            return "Erro: Nome de arquivo inválido."

        task_dir.mkdir(parents=True, exist_ok=True)

        file_path = task_dir / safe_name

        # Abertura atômica com O_NOFOLLOW: o antigo padrão era check-then-open
        # (is_symlink() e só depois open()), com uma janela de TOCTOU — um
        # atacante com escrita concorrente no diretório de artefatos podia
        # trocar o destino por um symlink exatamente entre a checagem e a
        # escrita, escapando do diretório confinado. Com O_NOFOLLOW, se o
        # componente final já for um symlink, o próprio open() falha com
        # ELOOP; não há intervalo entre checar e escrever para explorar.
        # safe_name não contém "/" (é só o componente final do path), então
        # file_path é sempre filho direto de task_dir — sem travessia possível
        # via diretórios intermediários.
        open_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        try:
            fd = os.open(file_path, open_flags, 0o644)
        except OSError as e:
            if e.errno == errno.ELOOP:
                # Nota: a chave de log não pode se chamar "filename" — colide com o
                # atributo reservado LogRecord.filename e faz logging levantar
                # ValueError ("Attempt to overwrite 'filename' in LogRecord").
                logger.warning(
                    "write_artifact: escrita recusada — destino é um symlink",
                    extra={"artifact_filename": filename, "resolved": str(file_path)},
                )
                return "Erro: escrita recusada — destino é um link simbólico."
            raise

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Artefato salvo com sucesso em {file_path}"

    except Exception as e:
        logger.error(f"Erro ao salvar artefato: {e}")
        return f"Erro ao salvar artefato: {str(e)}"

write_artifact.parameters_schema = {
    "type": "object",
    "properties": {
        "filename": {
            "type": "string",
            "description": "Nome do arquivo (ex: 'resumo.md')."
        },
        "content": {
            "type": "string",
            "description": "Conteúdo textual do arquivo."
        }
    },
    "required": ["filename", "content"]
}

_memory_skill_instance = None

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
    global _memory_skill_instance
    from src.skills.memory.skill import MemorySkill

    # Roadmap V16/ADR 014 — estado por tarefa via AgentContext no runtime em
    # processo (contextvars, isolado por tarefa concorrente); os.environ
    # apenas no modo container legado.
    ctx = get_agent_context_optional()
    if ctx is not None:
        session_id = ctx.agent_session_id
        agent_id = ctx.agent_id
    else:
        session_id = os.environ.get("SESSION_ID")
        agent_id = os.environ.get("AGENT_ID", "agent")

    if _memory_skill_instance is None:
        _memory_skill_instance = MemorySkill()
        
    result = await _memory_skill_instance.run(
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
