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

from src.egress.fragments import ARTIFACT_NAMES_SOURCE, ContentOrigin, PromptFragment, plain_text
from src.logger import get_logger
from src.skills.code.manifest import WorkspaceManifest

logger = get_logger(__name__)

_CONTEXT_HEADER = "[CONTEXTO DO WORKSPACE]"


_Line = tuple[str, ContentOrigin, bool, Optional[str]]


def build_workspace_context_fragments(
    session_dir: pathlib.Path,
    session_id: str,
    task_name: str,
    max_code_context_lines: int = 150,
    code_tainted: bool = False,
) -> list[PromptFragment]:
    """Constrói o bloco de contexto do workspace como trechos rotulados (v18.5-egress-gate, design §6).

    Só **nomes** de artefatos são injetados, nunca conteúdo. A mensagem de erro do último step é ``saida_execucao``
    (o filtro a trata), o código do step anterior é ``codigo`` (contaminado se o papel que o escreveu aceita dados
    brutos, ``code_tainted``) e o restante é instrução fixa do orquestrador.

    Args:
        session_dir: Caminho para o diretório da sessão no host.
        session_id: Identificador canônico da sessão.
        task_name: Nome da subtarefa associada.
        max_code_context_lines: Limite máximo de linhas do código anterior a injetar.
        code_tainted: Se o código do step anterior foi escrito por modelo que aceita dados brutos.

    Returns:
        Trechos do bloco, na ordem; o texto plano (``"\\n".join``) é o bloco clássico.
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

    ins = ContentOrigin.INSTRUCAO
    lines: list[_Line] = []

    def add(text: str, origin: ContentOrigin = ins, tainted: bool = False, source: Optional[str] = None) -> None:
        lines.append((text, origin, tainted, source))

    # --- Cabeçalho ---
    add(_CONTEXT_HEADER)
    add(f"Sessão: {session_id} | Tarefa: {task_name} | Steps concluídos: {step_count}")
    add("")

    # --- Artefatos disponíveis (só nomes) ---
    if artifacts:
        add("Artefatos disponíveis em /outputs/:")
        for art in artifacts:
            add(f"  - {art}", ContentOrigin.ESQUEMA_AGREGADO, False, ARTIFACT_NAMES_SOURCE)
    else:
        add("Artefatos disponíveis em /outputs/: nenhum")
    add("")

    # --- Último step ---
    if last_step:
        status = last_step.get("status", "unknown")
        summary = last_step.get("summary", "")
        add(f"Último step (status: {status}):")
        add(f"  {summary}", ContentOrigin.SAIDA_EXECUCAO, False, "manifest:summary")

        if status == "failed":
            error_type = last_step.get("error_type", "")
            error_msg = last_step.get("error_message", "")
            error_loc = last_step.get("error_location", "")
            if error_type:
                add(f"  Erro: {error_type}: {error_msg}", ContentOrigin.SAIDA_EXECUCAO, False, "manifest:erro")
            if error_loc:
                add(f"  Local: {error_loc}")

            # --- Código do step anterior (V13.4.2) ---
            code_file = last_step.get("code_file")
            if code_file:
                code_path = session_dir / code_file
                code_block = _read_code_tail(code_path, max_code_context_lines)
                if code_block:
                    add("")
                    add(f"Código do step anterior ({code_file}) que falhou:")
                    add("```python")
                    add(code_block, ContentOrigin.CODIGO, code_tainted, str(code_file))
                    add("```")
                    if error_loc:
                        add(
                            f"O erro ocorreu em {error_loc}. "
                            "Corrija especificamente esse ponto. "
                            "NÃO reescreva o código inteiro — corrija apenas a parte problemática."
                        )
    else:
        add("Nenhum step anterior registrado. Esta é a primeira execução.")

    add("")

    # --- Sugestão de próximo passo ---
    if hint:
        add(f"Próximo passo sugerido: {hint}", ContentOrigin.SAIDA_EXECUCAO, False, "manifest:hint")
        add("")

    # --- Instrução invariante ---
    add("IMPORTANTE: NÃO recriar artefatos já listados acima. Construa sobre o que já existe.")

    fragments: list[PromptFragment] = []
    for text, origin, tainted, source in lines:
        last = fragments[-1] if fragments else None
        if last is not None and (last.origin, last.tainted, last.source) == (origin, tainted, source):
            fragments[-1] = PromptFragment(
                fragments[-1].text + "\n" + text, origin, tainted=tainted, source=source
            )
        else:
            fragments.append(PromptFragment(text, origin, tainted=tainted, source=source))
    logger.debug(
        "Bloco de contexto construído",
        extra={
            "session_id": session_id,
            "step_count": step_count,
            "artifacts_count": len(artifacts),
            "has_error": last_step is not None and last_step.get("status") == "failed",
        },
    )
    return fragments


def build_workspace_context_block(
    session_dir: pathlib.Path,
    session_id: str,
    task_name: str,
    max_code_context_lines: int = 150,
) -> str:
    """Constrói o bloco de contexto do workspace como texto plano (V13.4.1/V13.4.2).

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
    return plain_text(
        build_workspace_context_fragments(session_dir, session_id, task_name, max_code_context_lines)
    )


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
