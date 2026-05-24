"""context_injection.py — Construção do bloco de contexto do workspace.

Implementa V13.4.1 e V13.4.2:
- Lê o manifest da sessão e constrói um bloco de contexto estruturado.
- Se o último step falhou, inclui o código do step anterior (limitado a
  MAX_CODE_CONTEXT_LINES linhas).
- Retorna string vazia se o diretório da sessão não existir (primeira execução).
"""
from __future__ import annotations

import pathlib
from typing import Optional

from src.logger import get_logger
from src.skills.code.manifest import WorkspaceManifest

logger = get_logger(__name__)

_CONTEXT_HEADER = "[CONTEXTO DO WORKSPACE]"


def build_workspace_context_block(
    session_dir: pathlib.Path,
    session_id: str,
    task_name: str,
    max_code_context_lines: int = 150,
) -> str:
    """Constrói o bloco de contexto do workspace para injeção no prompt do LLM.

    Lê o manifest da sessão e gera texto estruturado contendo:
    - Sessão, tarefa e número de steps concluídos.
    - Artefatos disponíveis em /outputs/.
    - Resumo e status do último step.
    - Se o último step falhou: erro detalhado + código do step (últimas N linhas).
    - Sugestão de próximo passo, se houver.

    Args:
        session_dir: Caminho para o diretório da sessão no host.
        session_id: Identificador canônico da sessão.
        task_name: Nome da subtarefa associada.
        max_code_context_lines: Limite máximo de linhas do código anterior a injetar.

    Returns:
        Bloco de contexto como string. Nunca retorna None.
    """
    session_dir = pathlib.Path(session_dir)

    manifest = WorkspaceManifest(
        session_dir=session_dir,
        session_id=session_id,
        task_name=task_name,
    )
    data = manifest.read()

    step_count = len(data.get("steps", []))
    artifacts = data.get("artifacts_available", [])
    steps = data.get("steps", [])
    last_step = steps[-1] if steps else None
    hint = data.get("next_step_hint", "")

    # --- Cabeçalho ---
    lines: list[str] = [
        _CONTEXT_HEADER,
        f"Sessão: {session_id} | Tarefa: {task_name} | Steps concluídos: {step_count}",
        "",
    ]

    # --- Artefatos disponíveis ---
    if artifacts:
        lines.append("Artefatos disponíveis em /outputs/:")
        for art in artifacts:
            lines.append(f"  - {art}")
    else:
        lines.append("Artefatos disponíveis em /outputs/: nenhum")
    lines.append("")

    # --- Último step ---
    if last_step:
        status = last_step.get("status", "unknown")
        summary = last_step.get("summary", "")
        lines.append(f"Último step (status: {status}):")
        lines.append(f"  {summary}")

        if status == "failed":
            error_type = last_step.get("error_type", "")
            error_msg = last_step.get("error_message", "")
            error_loc = last_step.get("error_location", "")
            if error_type:
                lines.append(f"  Erro: {error_type}: {error_msg}")
            if error_loc:
                lines.append(f"  Local: {error_loc}")

            # --- Código do step anterior (V13.4.2) ---
            code_file = last_step.get("code_file")
            if code_file:
                code_path = session_dir / code_file
                code_block = _read_code_tail(code_path, max_code_context_lines)
                if code_block:
                    lines.append("")
                    lines.append(f"Código do step anterior ({code_file}) que falhou:")
                    lines.append("```python")
                    lines.append(code_block)
                    lines.append("```")
                    if error_loc:
                        lines.append(
                            f"O erro ocorreu em {error_loc}. "
                            "Corrija especificamente esse ponto. "
                            "NÃO reescreva o código inteiro — corrija apenas a parte problemática."
                        )
    else:
        lines.append("Nenhum step anterior registrado. Esta é a primeira execução.")

    lines.append("")

    # --- Sugestão de próximo passo ---
    if hint:
        lines.append(f"Próximo passo sugerido: {hint}")
        lines.append("")

    # --- Instrução invariante ---
    lines.append(
        "IMPORTANTE: NÃO recriar artefatos já listados acima. Construa sobre o que já existe."
    )

    block = "\n".join(lines)
    logger.debug(
        "Bloco de contexto construído",
        extra={
            "session_id": session_id,
            "step_count": step_count,
            "artifacts_count": len(artifacts),
            "has_error": last_step is not None and last_step.get("status") == "failed",
        },
    )
    return block


def _read_code_tail(path: pathlib.Path, max_lines: int) -> str:
    """Lê as últimas `max_lines` linhas de um arquivo de código.

    Args:
        path: Caminho para o arquivo.
        max_lines: Número máximo de linhas a retornar (a partir do final).

    Returns:
        Conteúdo do arquivo (últimas N linhas) ou string vazia se o arquivo
        não existir ou não puder ser lido.
    """
    if not path.exists():
        logger.warning(
            "Snapshot de código não encontrado para injeção no contexto",
            extra={"path": str(path)},
        )
        return ""
    try:
        content = path.read_text(encoding="utf-8")
        all_lines = content.splitlines()
        tail = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines
        return "\n".join(tail)
    except OSError as exc:
        logger.warning(
            "Erro ao ler snapshot de código",
            extra={"path": str(path), "error": str(exc)},
        )
        return ""
