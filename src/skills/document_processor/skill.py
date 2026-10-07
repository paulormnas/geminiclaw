import asyncio
from pathlib import Path
from typing import Any, Dict

from src.agent_runtime.context import get_agent_context_optional
from src.logger import get_logger
from src.skills.base import BaseSkill
from src.skills.document_processor.enrichment import ProjectMeta
from src.skills.document_processor.extractors.registry import ExtractorRegistry
from src.skills.document_processor.indexer import DocumentIndexer
from src.skills.document_processor.pipeline import ORIGEM_ARTEFATO, SEM_PROJETO, index_file

logger = get_logger(__name__)

_CONTENT_LIMIT = 4000
_TITLE_LIMIT = 200


def _untrusted(origem: str, text: object, limit: int) -> str:
    """Texto livre de insumo, em uma linha e entre delimitadores: dado não confiável, nunca instrução."""
    from src.knowledge.curator_tools import wrap_data
    from src.knowledge.normalization import clean_free_text

    return wrap_data(origem, clean_free_text(str(text if text is not None else "")), limit)


def _resolve_ingest_path(file_path: str) -> str:
    """Resolve o caminho de ingestão, confinando-o ao diretório da sessão do agente.

    O ``file_path`` chega de um LLM (potencialmente induzido por prompt injection),
    então um agente só pode ingerir arquivos de ``input_snapshot/`` ou ``artifacts/``
    da própria sessão. Caminhos relativos são interpretados a partir de
    ``input_snapshot/``. Symlinks são resolvidos antes da checagem, de modo que um link
    apontando para fora da sessão é recusado. Fora do runtime de agentes (uso
    programático, testes) não há contexto e o caminho é usado como recebido.

    Args:
        file_path: Caminho informado pelo agente.

    Returns:
        Caminho absoluto resolvido a ser extraído.

    Raises:
        PermissionError: Se o arquivo estiver fora do diretório permitido da sessão.
    """
    ctx = get_agent_context_optional()
    if ctx is None:
        return file_path

    session_dir = ctx.output_dir.resolve()
    roots = [session_dir / "input_snapshot", session_dir / "artifacts"]
    # v18-research-continuity: artefatos de sessões anteriores da cadeia (somente leitura).
    extra_roots = [d.resolve() / "artifacts" for d in ctx.readable_dirs]
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in [*roots, *extra_roots]):
        logger.warning(
            "document_processor: ingest recusado, arquivo fora do diretório da sessão",
            extra={"requested": file_path, "resolved": str(resolved)},
        )
        raise PermissionError(
            "Só é possível ingerir arquivos de input_snapshot/ ou artifacts/ da sessão atual."
        )
    return str(resolved)


def _session_project() -> tuple[str | None, ProjectMeta]:
    """Projeto da sessão do agente e seus metadados (v17-input-document-index).

    Dentro de uma sessão sem projeto o escopo é ``SEM_PROJETO``; fora do runtime de agentes (uso
    programático) não há projeto de sessão (``None``: sem filtro) e a ingestão usa ``SEM_PROJETO``.
    """
    ctx = get_agent_context_optional()
    if ctx is None:
        return None, ProjectMeta(projeto_id=SEM_PROJETO)
    pid = ctx.project_id or SEM_PROJETO
    meta = ctx.extra.get("project_meta")
    return pid, meta if isinstance(meta, ProjectMeta) and meta.projeto_id == pid else ProjectMeta(projeto_id=pid)


class DocumentProcessorSkill(BaseSkill):
    """Skill de processamento de documentos do usuário."""

    name = "document_processor"
    description = (
        "Processa documentos fornecidos pelo usuário (PDF, CSV, XLSX, TXT, MD, DOCX, PPTX) "
        "e os indexa para consulta durante pesquisas. "
        "Use 'ingest' para processar um novo arquivo. "
        "Use 'search' para buscar informações nos documentos do usuário. "
        "Use 'list' para ver os documentos indexados do projeto da sessão. "
        "A busca e a lista valem só para o projeto da sessão; use 'todos_os_projetos' para buscar em todos. "
        "Use 'info' para ver metadados de um documento específico."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ingest", "search", "list", "info"],
                "description": "Ação a executar"
            },
            "file_path": {
                "type": "string",
                "description": "Caminho do arquivo para ingest (obrigatório para 'ingest')"
            },
            "query": {
                "type": "string",
                "description": "Texto de busca (obrigatório para 'search')"
            },
            "document_id": {
                "type": "string",
                "description": "ID do documento (para 'info' ou 'search' filtrado)"
            },
            "todos_os_projetos": {
                "type": "boolean",
                "description": "Busca/lista em todos os projetos (padrão: só o projeto da sessão)",
                "default": False
            },
            "top_k": {
                "type": "integer",
                "description": "Número máximo de resultados (para 'search')",
                "default": 5
            }
        },
        "required": ["action"]
    }

    def __init__(self):
        self.extractor_registry = ExtractorRegistry()
        self.indexer = DocumentIndexer()

    def execute(self, **kwargs) -> Dict[str, Any]:
        """A API da skill é síncrona/wrapper para chamadas assíncronas."""
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action")

        if action == "ingest":
            file_path = kwargs.get("file_path")
            if not file_path:
                return {"error": "file_path é obrigatório para ingest"}
            
            try:
                resolved = Path(_resolve_ingest_path(file_path))
                _, projeto = _session_project()
                outcome = await index_file(
                    self.indexer, self.extractor_registry, resolved, root=resolved.parent,
                    projeto=projeto, origem=ORIGEM_ARTEFATO,
                )
                return {
                    "success": True,
                    "document_id": outcome.document_id,
                    "title": outcome.title,
                    "status": outcome.status,
                    "vetorizacao": outcome.vetorizacao,
                }
            except Exception as e:
                logger.error(f"Erro em document_processor ingest: {e}")
                return {"error": str(e)}

        elif action == "search":
            query = kwargs.get("query")
            if not query:
                return {"error": "query é obrigatória para search"}
                
            top_k = kwargs.get("top_k", 5)
            document_id = kwargs.get("document_id")
            projeto_id = None if kwargs.get("todos_os_projetos") else _session_project()[0]

            try:
                results = self.indexer.search(
                    query=query, limit=top_k, document_id=document_id, projeto_id=projeto_id
                )
                safe = [
                    {
                        **r,
                        "content": _untrusted("trecho_de_documento", r.get("content"), _CONTENT_LIMIT),
                        "titulo": _untrusted("titulo_de_documento", r.get("titulo"), _TITLE_LIMIT),
                    }
                    for r in results
                ]
                return {"results": safe}
            except Exception as e:
                return {"error": str(e)}

        elif action == "list":
            try:
                projeto_id = None if kwargs.get("todos_os_projetos") else _session_project()[0]
                docs = self.indexer.list_documents(limit=50, projeto_id=projeto_id)
                # Omitimos metadata_json muito longos para não poluir
                summary = []
                for d in docs:
                    summary.append({
                        "id": d["id"],
                        "title": _untrusted("titulo_de_documento", d["title"], _TITLE_LIMIT),
                        "format": d["format"],
                        "chunks": d["num_chunks"],
                        "projeto_id": (d.get("metadata_json") or {}).get("projeto_id"),
                    })
                return {"documents": summary}
            except Exception as e:
                return {"error": str(e)}

        elif action == "info":
            document_id = kwargs.get("document_id")
            if not document_id:
                return {"error": "document_id é obrigatório para info"}
                
            try:
                doc = self.indexer.get_document_info(document_id)
                if not doc:
                    return {"error": "Documento não encontrado"}
                
                # Para serialização JSON, converte datetime se existir
                for k, v in doc.items():
                    if hasattr(v, 'isoformat'):
                        doc[k] = v.isoformat()
                return {"document": doc}
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": f"Ação desconhecida: {action}"}
