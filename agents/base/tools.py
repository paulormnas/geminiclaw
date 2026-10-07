"""Ferramentas comuns para todos os agentes GeminiClaw."""

import asyncio
import errno
import logging
import os
from pathlib import Path
from typing import Any, Optional

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
        ctx_ro = get_agent_context_optional()
        if ctx_ro is not None and _targets_readonly_dir(filename, ctx_ro.readable_dirs):
            logger.warning("write_artifact: escrita recusada — sessão anterior é somente leitura")
            return "Erro: escrita recusada — artefatos de sessões anteriores são somente leitura."

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


def _targets_readonly_dir(filename: str, readable_dirs: tuple[Path, ...]) -> bool:
    """``True`` se ``filename`` aponta para dentro de uma sessão anterior (somente leitura).

    Cobre caminho absoluto resolvido (inclusive via link simbólico) e caminho relativo que cita o diretório da
    sessão anterior (``<sessão>/artifacts/x``).
    """
    if not readable_dirs:
        return False
    candidate = Path(filename)
    for root in readable_dirs:
        try:
            if candidate.is_absolute() and candidate.resolve().is_relative_to(root.resolve()):
                return True
        except OSError:
            return True
        if root.name in candidate.parts:
            return True
    return False


_READ_TOP_FILES = frozenset({"manifest.json", "relatorio_final.md", "plan.json", "results.json"})
_READ_DENIED_DIRS = frozenset({"logs"})


def _read_artifact_sync(ctx: Any, path: str, session_id: str) -> str:
    """Leitura bloqueante (roda em thread): ver ``read_artifact``."""
    import stat as _stat

    from src import config
    from src.continuity import SESSION_ID_RE

    try:
        if session_id and session_id != ctx.output_dir.name:
            if not SESSION_ID_RE.fullmatch(session_id):
                return "Erro: session_id inválido."
            roots = [d for d in ctx.readable_dirs if d.name == session_id]
            if not roots:
                return "Erro: sessão não permitida; só sessões anteriores da cadeia do projeto podem ser lidas."
            root = roots[0].resolve()
        else:
            root = ctx.output_dir.resolve()
        rel = Path(path)
        if not path or rel.is_absolute() or ".." in rel.parts or len(rel.parts) > 8:
            return "Erro: caminho inválido (use caminho relativo dentro da sessão)."
        if len(rel.parts) == 1 and rel.parts[0] not in _READ_TOP_FILES:
            return "Erro: arquivo de controle da sessão não é legível por agentes."
        if rel.parts[0] in _READ_DENIED_DIRS:
            return "Erro: diretório não legível."
        target = root.joinpath(*rel.parts)
        if target.resolve() != target or not target.resolve().is_relative_to(root):
            return "Erro: caminho com link simbólico ou fora da sessão; recusado."
        limit = int(config.RESUME_ARTIFACT_MAX_READ_BYTES)
        # O_NONBLOCK: abrir um FIFO (criável pelo código do sandbox) sem escritor não pode travar a leitura.
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            if not _stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return "Erro: não é um arquivo comum."
            data = handle.read(limit + 1)
        text = data[:limit].decode("utf-8", errors="replace")
        suffix = "\n[...truncado]" if len(data) > limit else ""
        return f"[artefato da sessão {root.name}: {path}]\n{text}{suffix}"
    except FileNotFoundError:
        return "Erro: artefato não encontrado."
    except OSError as exc:
        return f"Erro ao ler artefato: {type(exc).__name__}"


async def read_artifact(path: str, session_id: str = "") -> str:
    """Lê (somente leitura) um artefato da sessão atual ou de uma sessão anterior da cadeia do projeto.

    A leitura roda em thread, com ``O_NONBLOCK`` e só aceita arquivo comum (FIFO e dispositivo são recusados sem
    travar o laço de eventos).

    Args:
        path: Caminho relativo ao diretório da sessão (ex.: ``artifacts/dados.csv`` ou ``<tarefa>/metrics.json``).
        session_id: Sessão anterior (listada no contexto de retomada); vazio = sessão atual.

    Returns:
        Conteúdo em texto (truncado no limite configurado) ou mensagem de erro.
    """
    ctx = get_agent_context_optional()
    if ctx is None:
        return "Erro: read_artifact só funciona dentro de uma execução de agente."
    return await asyncio.to_thread(_read_artifact_sync, ctx, path, session_id)


read_artifact.parameters_schema = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Caminho relativo dentro da sessão (ex.: 'artifacts/dados.csv')."},
        "session_id": {"type": "string", "description": "Sessão anterior da cadeia; vazio = sessão atual."},
    },
    "required": ["path"],
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


async def flag_for_curator(tipo: str, texto: str, refs: Optional[list[str]] = None) -> str:
    """Sinaliza um ponto importante ao Curator, que o avalia no próximo checkpoint (ADR 012 §2).

    A sinalização é gravada em ``curator_flags.jsonl`` na pasta de outputs da sessão, com agente, subtarefa e horário;
    o Curator decide registrar (e onde) ou descartar com motivo. Sinalizar não cria nada no grafo.

    Args:
        tipo: ``descoberta_potencial``, ``caminho_relevante``, ``oportunidade`` ou ``falha_relevante``.
        texto: Descrição curta (sem dados brutos; até o limite configurado).
        refs: IDs de nós ou caminhos de artefatos da sessão que sustentam o ponto.

    Returns:
        Mensagem de sucesso ou erro.
    """
    from src.knowledge.curator_flags import FlagError, record_flag

    ctx = get_agent_context_optional()
    if ctx is None:
        return "Erro: flag_for_curator só funciona dentro de uma execução de agente."
    try:
        flag_id = record_flag(
            ctx.output_dir, agente=ctx.agent_id, subtarefa=ctx.task_name, tipo=tipo, texto=texto, refs=refs
        )
    except FlagError as exc:
        return f"Erro: {exc}"
    except OSError as exc:
        logger.warning("flag_for_curator: gravação falhou", extra={"error": type(exc).__name__})
        return "Erro: não foi possível gravar a sinalização."
    return f"Sinalização {flag_id} registrada para o Curator."


flag_for_curator.parameters_schema = {
    "type": "object",
    "properties": {
        "tipo": {
            "type": "string",
            "enum": ["descoberta_potencial", "caminho_relevante", "oportunidade", "falha_relevante"],
            "description": "Tipo da sinalização.",
        },
        "texto": {"type": "string", "description": "Descrição curta do ponto importante."},
        "refs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs de nós ou caminhos de artefatos da sessão.",
        },
    },
    "required": ["tipo", "texto"],
}
