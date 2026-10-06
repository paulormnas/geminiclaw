"""Fluxo de projeto e confirmação do Problema na CLI (v17-research-project).

Antes de qualquer planejamento, a sessão precisa de um projeto e de um ``Problema`` confirmado
pelo pesquisador, em **todos** os modos (``assisted``, ``semi`` e ``auto``). A confirmação é
pedida uma única vez por projeto; sessões seguintes a reutilizam. Sem terminal interativo e sem
problema confirmado, a execução é recusada antes de gastar qualquer chamada de LLM.

Entrada/saída são injetáveis (``input_fn``/``output_fn``/``interactive``) para testes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.knowledge import projects
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore
from src.knowledge.problem import (
    EDITABLE_FIELDS,
    ProblemDraft,
    ProblemDraftError,
    apply_edit,
    clean_text,
    parse_number,
)
from src.logger import get_logger

logger = get_logger(__name__)

MAX_REDRAFTS = 5
MAX_COMMENT = 2000
MAX_MENU_ROUNDS = 50

Drafter = Callable[..., Awaitable[ProblemDraft]]

_NON_INTERACTIVE_MESSAGE = (
    "Projeto {projeto} sem Problema confirmado e esta execução não é interativa (sem TTY). "
    "Confirme o problema em um terminal interativo antes ({cmd}); a confirmação é pedida uma única "
    "vez por projeto. Acompanhe o estado com `geminiclaw project show <id>`."
)
_GRAPH_DOWN_HINT = (
    "Suba o PostgreSQL/Qdrant (`docker compose up -d`) e confira KNOWLEDGE_READER_DATABASE_URL no .env; "
    "ou defina RESEARCH_PROJECT_GRAPH_OPTIONAL=true para rodar sem projeto enquanto o grafo estiver fora."
)


class ProjectFlowError(RuntimeError):
    """A sessão não pode começar (recusa, cancelamento ou erro acionável)."""


@dataclass(frozen=True)
class ProjectBinding:
    """Projeto resolvido para a sessão.

    Attributes:
        project_id: ``projeto_id`` gravado no payload da sessão (``None`` em ``sem_grafo``).
        context_block: Bloco de texto (título, resumo e critério) injetado no planejamento.
        created: True se o projeto foi criado automaticamente a partir do prompt.
        mode: ``"projeto"`` ou ``"sem_grafo"`` (gravado como ``project_mode`` no payload).
    """

    project_id: str | None
    context_block: str
    created: bool = False
    mode: str = "projeto"  # "projeto" ou "sem_grafo" (RESEARCH_PROJECT_GRAPH_OPTIONAL e grafo fora do ar)


def is_interactive() -> bool:
    """True quando stdin e stdout são terminais (TTY)."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def resolve_project(
    store: GraphStore,
    prompt: str,
    *,
    project_arg: str | None = None,
    config_dir: Path | None = None,
    output_fn: Callable[[str], Any] = print,
    allow_create: bool = True,
) -> tuple[str, bool]:
    """Escolhe o projeto da sessão: ``--project`` > projeto padrão > criação automática.

    Returns:
        ``(projeto_id, criado_automaticamente)``.

    Raises:
        ProjectFlowError: Projeto informado inexistente/inválido, ou criação automática necessária
            com ``allow_create=False`` (sem TTY: nenhum nó ``Projeto`` órfão é criado).
    """
    try:
        chosen = project_arg or projects.get_default_project(config_dir)
        if chosen:
            return projects.get_project(store, chosen).projeto_id, False
        if not allow_create:
            raise ProjectFlowError(_NON_INTERACTIVE_MESSAGE.format(projeto="novo", cmd="`geminiclaw project new ...`"))
        titulo = projects.derive_title(prompt)
        objetivo = prompt.strip()[: projects.MAX_OBJETIVO_PROJETO]
        projeto_id = projects.create_project(store, titulo, objetivo, [])
    except (GraphStoreError, ProblemDraftError) as exc:
        raise ProjectFlowError(str(exc)) from exc
    output_fn(f"Projeto criado: {projeto_id} ({titulo})")
    return projeto_id, True


def _format_draft(draft: ProblemDraft) -> str:
    dados = "; ".join(f"{k}={v}" for k, v in draft.caracteristicas_dados.items()) or "-"
    delta = draft.delta_min if draft.delta_min is not None else "NÃO DEFINIDO"
    return (
        "\n--- Rascunho do Problema ---\n"
        f"Título: {draft.titulo}\n"
        f"Classe: {draft.classe or '-'}\n"
        f"Domínios: {'; '.join(draft.dominios) or '-'}\n"
        f"Dados: {dados}\n"
        f"Métrica: {draft.metrica or '-'} | alvo: {draft.alvo if draft.alvo is not None else '-'}"
        f" | delta_min: {delta} | baseline: {draft.baseline_descricao or '-'}\n"
        f"Resumo:\n{draft.resumo}\n"
        "----------------------------"
    )


def _ask_required_number(input_fn: Callable[[str], str], output_fn: Callable[[str], Any], label: str) -> float | None:
    """Pede um número positivo; vazio cancela (devolve ``None``)."""
    for _ in range(5):
        raw = input_fn(f"{label} (positivo; vazio para voltar): ").strip()
        if not raw:
            return None
        try:
            value = parse_number(raw, label, positive=True)
        except ProblemDraftError as exc:
            output_fn(f"  {exc}")
            continue
        if value is not None:
            return value
    return None


async def ensure_confirmed_problem(
    store: GraphStore,
    projeto_id: str,
    prompt: str,
    context: Any,
    *,
    drafter: Drafter,
    interactive: bool,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], Any] = print,
    researcher_model: str | None = None,
) -> projects.ProjectDetail:
    """Garante um ``Problema`` confirmado antes do planejamento; pede a confirmação se faltar.

    Returns:
        O ``ProjectDetail`` já com o problema confirmado.

    Raises:
        ProjectFlowError: Sessão não interativa sem problema confirmado, cancelamento do
            pesquisador ou falha do rascunho.
    """
    detail = projects.get_project(store, projeto_id)
    if detail.problema is not None:
        return detail
    if not interactive:
        raise ProjectFlowError(
            _NON_INTERACTIVE_MESSAGE.format(
                projeto=projeto_id, cmd=f'rode `geminiclaw --project {projeto_id} "<prompt>"` num terminal'
            )
        )

    comentario: str | None = None
    redrafts = 0
    try:
        draft = await drafter(prompt, context, detail, comentario)
        sentido: str | None = None
        for _ in range(MAX_MENU_ROUNDS):
            output_fn(_format_draft(draft))
            choice = input_fn("[c]onfirmar, [e]ditar campo, [n]ovo rascunho, [q] cancelar: ").strip().lower()
            if choice in ("q", "sair", "cancelar"):
                raise ProjectFlowError("Confirmação do problema cancelada; a sessão não foi iniciada.")
            if choice in ("e", "editar"):
                campo = input_fn(f"Campo ({', '.join(EDITABLE_FIELDS)}): ").strip().lower()
                valor = input_fn(f"Novo valor de {campo} (domínios separados por ';'): ")
                try:
                    draft = apply_edit(draft, campo, valor)
                except ProblemDraftError as exc:
                    output_fn(f"  {exc}")
                continue
            if choice in ("n", "novo"):
                if redrafts >= MAX_REDRAFTS:
                    output_fn(f"  Limite de {MAX_REDRAFTS} novos rascunhos atingido; edite os campos ou cancele.")
                    continue
                redrafts += 1
                raw_comment = input_fn("Comentário para o novo rascunho: ")
                comentario = clean_text(raw_comment, "comentário", MAX_COMMENT)
                draft = await drafter(prompt, context, detail, comentario)
                continue
            if choice in ("c", "confirmar"):
                if draft.missing_delta_min:
                    value = _ask_required_number(input_fn, output_fn, "delta_min")
                    if value is None:
                        continue
                    draft = apply_edit(draft, "delta_min", str(value))
                if not draft.metrica:
                    output_fn("  A métrica do critério de sucesso é obrigatória; edite o campo 'metrica'.")
                    continue
                try:
                    projects.confirm_problem(
                        store, projeto_id, draft, researcher_model=researcher_model, sentido_metrica=sentido,
                    )
                except projects.MetricSentidoRequired:
                    answer = input_fn("Métrica nova. Sentido ([m]aior_melhor / [n] menor_melhor): ").strip().lower()
                    sentido = {"m": "maior_melhor", "maior_melhor": "maior_melhor",
                               "n": "menor_melhor", "menor_melhor": "menor_melhor"}.get(answer)
                    if sentido is None:
                        output_fn("  Sentido inválido.")
                    continue
                output_fn("Problema confirmado.")
                return projects.get_project(store, projeto_id)
            output_fn("  Opção inválida.")
        raise ProjectFlowError("Confirmação do problema interrompida: muitas interações sem confirmar.")
    except (EOFError, KeyboardInterrupt):
        raise ProjectFlowError("Confirmação do problema interrompida; a sessão não foi iniciada.") from None
    except (ProblemDraftError, GraphStoreError) as exc:
        raise ProjectFlowError(str(exc)) from exc


class ProjectBinder:
    """Resolve o projeto e garante o problema confirmado uma vez por execução da CLI.

    No REPL o resultado é reutilizado em todos os prompts (um projeto por REPL).
    """

    def __init__(
        self,
        store_factory: Callable[[], GraphStore],
        *,
        project_arg: str | None = None,
        drafter: Drafter | None = None,
        interactive: bool | None = None,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], Any] = print,
        config_dir: Path | None = None,
        researcher_model: str | None = None,
        graph_optional: bool | None = None,
    ) -> None:
        self._store_factory = store_factory
        self._project_arg = project_arg
        self._drafter = drafter
        self._interactive = interactive
        self._input_fn = input_fn
        self._output_fn = output_fn
        self._config_dir = config_dir
        self._researcher_model = researcher_model
        self._graph_optional = graph_optional
        self._binding: ProjectBinding | None = None

    def _optional(self) -> bool:
        if self._graph_optional is not None:
            return self._graph_optional
        from src import config

        return bool(config.RESEARCH_PROJECT_GRAPH_OPTIONAL)

    def _open_store(self) -> GraphStore | None:
        """Abre e testa o grafo. ``None`` = fora do ar E contorno explícito ligado.

        Raises:
            ProjectFlowError: Grafo fora do ar sem o contorno (inclui erros de driver Postgres/Qdrant).
        """
        try:
            store = self._store_factory()
            store.list_nodes("Projeto", limit=1)  # sonda: abrir o pool é preguiçoso
        except Exception as exc:  # noqa: BLE001 - qualquer falha de driver/serviço é "grafo fora do ar"
            if self._optional():
                logger.warning("Grafo indisponível; sessão sem projeto", extra={"extra": {"error": str(exc)}})
                return None
            raise ProjectFlowError(
                f"Grafo de conhecimento indisponível ({type(exc).__name__}: {exc}). {_GRAPH_DOWN_HINT}"
            ) from exc
        return store

    async def bind(self, prompt: str, context: Any = None) -> ProjectBinding:
        """Devolve o vínculo projeto/contexto, resolvendo e confirmando na primeira chamada.

        Raises:
            ProjectFlowError: Se a sessão não puder começar.
        """
        if self._binding is not None:
            return self._binding
        store = self._open_store()
        if store is None:
            self._output_fn(
                "SEM GRAFO: projeto e Problema não aplicados nesta sessão (RESEARCH_PROJECT_GRAPH_OPTIONAL)."
            )
            self._binding = ProjectBinding(None, "", False, "sem_grafo")
            return self._binding
        interactive = is_interactive() if self._interactive is None else self._interactive
        try:
            projeto_id, created = resolve_project(
                store, prompt, project_arg=self._project_arg, config_dir=self._config_dir,
                output_fn=self._output_fn, allow_create=interactive,
            )
            drafter = self._drafter
            if drafter is None:
                from agents.researcher.agent import draft_problem as drafter  # noqa: PLC0415
            detail = await ensure_confirmed_problem(
                store, projeto_id, prompt, context,
                drafter=drafter, interactive=interactive, input_fn=self._input_fn,
                output_fn=self._output_fn, researcher_model=self._researcher_model,
            )
        except ProjectFlowError:
            raise
        except Exception as exc:  # noqa: BLE001 - erro de driver no meio do fluxo vira mensagem acionável
            raise ProjectFlowError(
                f"Falha ao acessar o grafo de conhecimento ({type(exc).__name__}: {exc}). {_GRAPH_DOWN_HINT}"
            ) from exc
        self._binding = ProjectBinding(projeto_id, projects.format_project_context(detail), created)
        return self._binding
