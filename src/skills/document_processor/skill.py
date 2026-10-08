import asyncio
from pathlib import Path
from typing import Any, Dict

from src.agent_runtime.context import get_agent_context_optional
from src.egress.classification import classify_path, ensure_not_research_data
from src.egress.fragments import ContentOrigin, mark_research_data
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


def _result_content(result: Dict[str, Any]) -> str:
    """Trecho de documento como dado não confiável; trecho de arquivo de dados leva a marca de dado de pesquisa.

    A origem vem da classificação da fonte (design §6): o conteúdo de ``dado_de_pesquisa`` é retido para destinos
    sem dados brutos.
    """
    wrapped = _untrusted("trecho_de_documento", result.get("content"), _CONTENT_LIMIT)
    source = str(result.get("source_path") or result.get("filename") or "")
    if source and classify_path(source) is ContentOrigin.DADO_DE_PESQUISA:
        return mark_research_data(wrapped, source)
    return wrapped


def _all_projects(action: str) -> None:
    """Auditoria: ``todos_os_projetos`` cruza a fronteira de projeto e é registrado a cada uso."""
    ctx = get_agent_context_optional()
    logger.warning(
        "document_processor: todos_os_projetos usado (acesso entre projetos)",
        extra={
            "acao": action,
            "sessao": ctx.session_id if ctx else None,
            "projeto_id": ctx.project_id if ctx else None,
        },
    )


def _scope(kwargs: Dict[str, Any], action: str) -> str | None:
    """Projeto a que a ação se restringe; ``None`` (sem filtro) só com ``todos_os_projetos`` ou sem runtime."""
    if kwargs.get("todos_os_projetos"):
        _all_projects(action)
        return None
    return _session_project()[0]


def _session_project() -> tuple[str | None, ProjectMeta]:
    """Projeto da sessão do agente e seus metadados (v17-input-document-index).

    Dentro de uma sessão sem projeto o escopo é ``sem_projeto:<session_id>``; fora do runtime de agentes (uso
    programático) não há projeto de sessão (``None``: sem filtro) e a ingestão usa ``SEM_PROJETO``.
    """
    ctx = get_agent_context_optional()
    if ctx is None:
        return None, ProjectMeta(projeto_id=SEM_PROJETO)
    # Sem projeto o escopo é a própria sessão: nunca um bucket global compartilhado entre sessões.
    pid = ctx.project_id or f"{SEM_PROJETO}:{ctx.session_id}"
    meta = ctx.extra.get("project_meta")
    return pid, meta if isinstance(meta, ProjectMeta) and meta.projeto_id == pid else ProjectMeta(projeto_id=pid)


class DocumentProcessorSkill(BaseSkill):
    """Skill de processamento de documentos do usuário."""

    name = "document_processor"

    egress_origin = ContentOrigin.DOCUMENTO
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
                # v18.5-egress-gate: dados de pesquisa entram só pela ingestão de input_context/ (ADR 019 §3.6).
                ensure_not_research_data(resolved)
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
            projeto_id = _scope(kwargs, "search")

            try:
                results = self.indexer.search(
                    query=query, limit=top_k, document_id=document_id, projeto_id=projeto_id
                )
                safe = [
                    {
                        **r,
                        "content": _result_content(r),
                        "titulo": _untrusted("titulo_de_documento", r.get("titulo"), _TITLE_LIMIT),
                    }
                    for r in results
                ]
                return {"results": safe}
            except Exception as e:
                return {"error": str(e)}

        elif action == "list":
            try:
                projeto_id = _scope(kwargs, "list")
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
                scope = _scope(kwargs, "info")
                doc = self.indexer.get_document_info(document_id)
                meta = (doc or {}).get("metadata_json") or {}
                # Documento de outro projeto é tratado como inexistente (não revela que existe).
                if not doc or (scope is not None and meta.get("projeto_id") != scope):
                    return {"error": "Documento não encontrado"}

                # Sem ``source_path`` (caminho no disco do nó) e com texto livre como dado não confiável.
                info = {
                    "id": doc["id"],
                    "filename": _untrusted("nome_de_arquivo", doc.get("filename"), _TITLE_LIMIT),
                    "format": doc.get("format"),
                    "title": _untrusted("titulo_de_documento", doc.get("title"), _TITLE_LIMIT),
                    "num_chunks": doc.get("num_chunks"),
                    "num_pages": doc.get("num_pages"),
                    "file_size_bytes": doc.get("file_size_bytes"),
                    "ingested_at": doc.get("ingested_at"),
                    "projeto_id": meta.get("projeto_id"),
                    "tipo_insumo": meta.get("tipo_insumo"),
                    "vetorizacao": meta.get("vetorizacao"),
                }
                # Para serialização JSON, converte datetime se existir
                return {"document": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in info.items()}}
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": f"Ação desconhecida: {action}"}
