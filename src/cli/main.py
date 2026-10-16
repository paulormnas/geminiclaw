"""Interface de linha de comando do assistente digital de pesquisa (ADR 010).

Ponto de entrada para o pesquisador interagir com o framework.
Suporta execução direta com prompt ou modo interativo (REPL).
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Adiciona a raiz do projeto ao sys.path para permitir imports de 'src'
# quando o script é executado diretamente (ex: python3 src/cli/main.py)
root_path = str(Path(__file__).resolve().parents[2])
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.cli.context_commands import clear_context
from src.cli.direct import continue_project, resume_research, start_research
from src.cli.repl import interactive_mode
from src.cli.sandboxes import show_sandboxes, stop_sandboxes
from src.cli.unlimited import _project_marked_unlimited, resolve_unlimited_budget  # noqa: F401 - API pública da CLI
from src.config import (
    APP_NAME,
    OUTPUT_BASE_DIR,
    SESSION_DEFAULT_MODE,
    SessionMode,
)
from src.egress.routing import install_provider_resolver
from src.host.health import thermal_protection_warning
from src.logger import get_logger
from src.orchestration.usage import UsageBudget
from src.utils.terminal import BOLD, CYAN, GREEN, RED, RESET, STATUS_ICONS, VERSION, YELLOW

logger = get_logger(__name__)


# Roadmap V15.6 / Spec G10 — texto de ajuda completo exibido em --help / -h / sem argumentos
_BANNER_TITLE = f"{APP_NAME} — Assistente Digital de Pesquisa Científica"
FULL_HELP_TEXT = f"""{CYAN}{BOLD}
╔══════════════════════════════════════════════════════════════╗
║{_BANNER_TITLE:^62}║
╚══════════════════════════════════════════════════════════════╝
{RESET}
{BOLD}USO:{RESET}
  geminiclaw [opções] "<tarefa>"
  geminiclaw sandboxes
  geminiclaw parar-sandboxes [--session <id>]
  geminiclaw resume --session <id>   (retoma a partir do checkpoint, em nova sessão com orçamento novo)
  geminiclaw continue --project <id> (retoma a sessão mais recente do projeto)
  geminiclaw convert --session <id> --format latex|html|docx
  geminiclaw clear-context
  geminiclaw history
  geminiclaw embeddings reindex [--collection <nome>] [--yes]
  geminiclaw provenance verify <projeto>|--session <id> [--full] [--json] | --from-export <dir>
  geminiclaw provenance export --session <id>
  geminiclaw claims list [--project <id>] [--session <id>] [--status <s>] [--json]
  geminiclaw claims resolve <afirmacao_id> --decisao mantida|descartada --motivo "<texto>"
  geminiclaw project new --titulo <t> --objetivo <o> [--dominio <termo>]|list [--status <s>]|show <id>|use <id>
  geminiclaw project confirm <id>   (confirma o Problema do projeto sem iniciar uma sessão)
  geminiclaw project unlimited <id> --on|--off   (marca o projeto para o modo sem limite; cada sessão ainda confirma)
  geminiclaw --project <id> "<tarefa>"
  geminiclaw --unlimited "<tarefa>"   (sem limite de tokens, tempo, custo e egresso; pede confirmação digitada)
  geminiclaw graph show [--project <id>] [--label <r>] [--dominio <t>] [--status <s>] [--depth N]
                        [--format text|table|json|mermaid]
  geminiclaw graph node <id> [--format text|json]
  geminiclaw graph edit "<pedido>" [--project <id>]   (o Curator propõe; você confirma no terminal)
  geminiclaw vocab pending|approve <id>|reject <id> [--motivo <texto>]|map <id> --para <id>
  geminiclaw opportunities list [--project <id>] [--status <s>]|approve <id> [--motivo <t>]|reject <id> --motivo <t>
  geminiclaw knowledge stats|reindex [--yes]|sync [--session <id>]
  geminiclaw --metrics <execution_id>

{BOLD}MODOS DE OPERAÇÃO (--mode):{RESET}
  {GREEN}assisted{RESET}   Padrão. Consulta o pesquisador apenas quando o contexto
              está genuinamente ausente. Divergências são investigadas
              autonomamente antes de qualquer consulta.

  {YELLOW}semi{RESET}       Nunca bloqueia. Faz suposições razoáveis, documenta
              todas as decisões e continua. Ideal para execuções
              longas sem supervisão ativa.

  {RED}auto{RESET}       Totalmente autônomo. Consulta a web para resolver
              incertezas técnicas. Use apenas sem pesquisador disponível.

{BOLD}CONTEXTO DE ENTRADA:{RESET}
  Deposite arquivos em input_context/ antes de executar:
    context.md   → objetivo, hipóteses, instruções
    artigo.pdf   → artigos de referência
    dados.csv    → datasets
    imagem.tif   → imagens para análise
  Use 'geminiclaw clear-context' para limpar input_context/ entre sessões.

{BOLD}EXEMPLOS:{RESET}
  geminiclaw "Reproduza a Tabela 3 do artigo"
  geminiclaw --mode semi "Análise exploratória do dataset"
  geminiclaw --mode auto "Execute sem interrupção"
  geminiclaw sandboxes
  geminiclaw parar-sandboxes --session 20260922_iris
  geminiclaw convert --session 20260922_iris --format latex

{BOLD}RELATÓRIO:{RESET}
  Sempre gerado em outputs/<session>/relatorio_final.md.
  Use 'geminiclaw convert' para gerar também em LaTeX, DOCX ou HTML.
"""


def print_full_help() -> None:
    """Exibe o texto de ajuda completo (banner + modos + exemplos)."""
    print(FULL_HELP_TEXT)


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos da CLI.

    Returns:
        Parser configurado com todos os argumentos suportados.
    """
    parser = argparse.ArgumentParser(
        prog="geminiclaw",
        description=f"{APP_NAME} — assistente digital de pesquisa científica.",
        epilog="Sem argumentos, entra em modo interativo (REPL).",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Prompt a ser enviado ao orquestrador. Se omitido, entra em modo interativo.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        metavar="PROVEDOR/MODELO",
        help=(
            "Pin de modelo do papel researcher no formato provedor/modelo (ex.: ollama/qwen3:8b); "
            "sujeito à política LLM_DATA_POLICY e à disponibilidade. Sem ele, o catálogo decide."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    parser.add_argument(
        "--metrics",
        type=str,
        metavar="EXECUTION_ID",
        default=None,
        help="Exibe métricas de telemetria de uma execução específica.",
    )
    parser.add_argument(
        "--export",
        type=str,
        metavar="EXECUTION_ID",
        default=None,
        help="Exporta métricas de telemetria de uma execução para CSV.",
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        default="./metrics",
        help="Diretório de saída para exportação CSV (padrão: ./metrics).",
    )
    parser.add_argument(
        "--log",
        type=str,
        metavar="SESSION_ID",
        default=None,
        help="Exibe e agrega os logs de todos os agentes de uma sessão.",
    )
    parser.add_argument(
        "--session",
        type=str,
        metavar="SESSION_ID",
        default=None,
        help="ID da sessão alvo para operações direcionadas (ex: parar-sandboxes --session <id>).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in SessionMode],
        default=None,
        help=(
            "Nível de autonomia da sessão: assisted (padrão), semi ou auto "
            f"(padrão configurável via SESSION_DEFAULT_MODE, atualmente '{SESSION_DEFAULT_MODE}')."
        ),
    )
    parser.add_argument(
        "--project",
        type=str,
        metavar="PROJETO_ID",
        default=None,
        help=(
            "Projeto de pesquisa da sessão (ver `geminiclaw project list`). Sem ele, usa o projeto "
            "padrão (`project use`) ou cria um projeto a partir do prompt."
        ),
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["latex", "html", "docx"],
        default=None,
        help="Formato de saída para 'geminiclaw convert --session <id> --format <fmt>'.",
    )
    # Roadmap V18 / Spec usage-limits — orçamento de uso da sessão (overrides de config).
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        metavar="N",
        help="Limite de tokens da sessão, todos os agentes inclusos (padrão: SESSION_MAX_TOKENS).",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        metavar="N",
        help="Limite de tempo de relógio da sessão, em minutos (padrão: SESSION_MAX_MINUTES).",
    )
    parser.add_argument(
        "--max-egress-bytes",
        type=int,
        default=None,
        metavar="N",
        help="Limite de volume (bytes) de saídas de execução enviadas fora do nó (padrão: EGRESS_SESSION_MAX_BYTES).",
    )
    parser.add_argument(
        "--unlimited",
        action="store_true",
        help=(
            "Modo sem limite: tokens, tempo, custo e egresso não interrompem a sessão (retentativas e regras de "
            "localidade continuam). Pede confirmação digitada a cada execução; incompatível com --max-tokens, "
            "--max-minutes e --max-egress-bytes."
        ),
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help=(
            "Cria o processo da pesquisa, imprime o apelido e o PID e sai com 0, sem esperar o fim (sem presença de "
            "terminal). Não combina com --mode assisted. Sem ele, o comando espera o fim e sai com o código do "
            "motivo de parada (0 parada de pesquisa, 1 erro, 2 modo sem limite não confirmado, 3 limite, "
            "4 aguarda o pesquisador, 5 memória insuficiente, 6 sessão perdida, 130 interrupção)."
        ),
    )
    parser.add_argument(
        "--max-task-retries",
        type=int,
        default=None,
        metavar="N",
        help="Limite de retentativas da mesma tarefa (padrão: SESSION_MAX_TASK_RETRIES).",
    )
    parser.add_argument(
        "--max-connection-retries",
        type=int,
        default=None,
        metavar="N",
        help="Limite de retentativas de conexão da sessão (padrão: SESSION_MAX_CONNECTION_RETRIES).",
    )
    return parser


def build_usage_budget(args: "argparse.Namespace") -> UsageBudget:
    """Constrói o `UsageBudget` efetivo da sessão a partir dos argumentos da CLI.

    Args:
        args: Argumentos parseados por `build_parser()`.

    Returns:
        `UsageBudget` com os defaults de `src/config.py`, sobrescritos pelas
        opções ``--max-tokens``, ``--max-minutes``, ``--max-task-retries`` e
        ``--max-connection-retries`` quando fornecidas.
    """
    return UsageBudget.from_config(
        max_tokens=getattr(args, "max_tokens", None),
        max_minutes=getattr(args, "max_minutes", None),
        max_task_retries=getattr(args, "max_task_retries", None),
        max_connection_retries=getattr(args, "max_connection_retries", None),
        max_egress_bytes=getattr(args, "max_egress_bytes", None),
        unlimited=bool(getattr(args, "unlimited", False)),
    )


def convert_report(session_id: str, format: str) -> None:
    """Converte o relatório final de uma sessão para outro formato (Roadmap V15.4 / Spec G8).

    Args:
        session_id: ID da sessão cujo `relatorio_final.md` será convertido.
        format: Formato de saída (``latex`` | ``html`` | ``docx``).
    """
    from src.report.base_converter import ReportConverterFactory

    session_dir = Path(OUTPUT_BASE_DIR) / session_id
    markdown_path = session_dir / "relatorio_final.md"
    if not markdown_path.exists():
        print(f"\n  {RED}❌ Sessão '{session_id}' não encontrada em /outputs/ (ou sem relatorio_final.md).{RESET}\n")
        return

    try:
        converter = ReportConverterFactory.create(format)
    except ValueError as e:
        print(f"\n  {RED}❌ {e}{RESET}\n")
        return

    extension = {"latex": "tex", "html": "html", "docx": "docx"}[format.lower().strip()]
    output_path = session_dir / f"relatorio_final.{extension}"
    try:
        converter.convert(markdown_path, output_path)
    except Exception as e:
        print(f"\n  {RED}❌ Falha ao converter relatório: {e}{RESET}\n")
        logger.error(
            "Falha ao converter relatório",
            extra={"session_id": session_id, "format": format, "error": str(e)},
        )
        return

    print(f"\n  {GREEN}✅ Relatório convertido: {output_path}{RESET}\n")


def run_embeddings_reindex(collection: str | None, auto_confirm: bool) -> None:
    """Executa `geminiclaw embeddings reindex` (Roadmap V16 / ADR 011 §3).

    Revetoriza as coleções do Qdrant com o provedor de embeddings local
    atualmente configurado. É uma operação sobre dados persistidos: apaga os
    vetores existentes de cada ponto reescrito. Por isso, pede confirmação
    interativa a menos que `--yes` seja informado (AGENTS.md §1 regra 5).

    Args:
        collection: Nome da coleção a reindexar, ou None para reindexar todas
            as coleções reindexáveis (`geminiclaw_knowledge`,
            `geminiclaw_documents`).
        auto_confirm: Se True, pula a confirmação interativa.
    """
    from src.documents.reindex import (
        REINDEXABLE_COLLECTIONS,
        CollectionNotFoundError,
        CollectionReindexer,
    )

    if collection is not None and collection not in REINDEXABLE_COLLECTIONS:
        print(
            f"\n  {RED}❌ Coleção '{collection}' não é reindexável. "
            f"Coleções suportadas: {', '.join(REINDEXABLE_COLLECTIONS)}.{RESET}\n"
        )
        sys.exit(1)

    targets = [collection] if collection else list(REINDEXABLE_COLLECTIONS)

    print(f"\n  {CYAN}Verificando pontos desatualizados...{RESET}")
    reindexers: dict[str, CollectionReindexer] = {}
    outdated_counts: dict[str, int] = {}
    for name in targets:
        reindexer = CollectionReindexer(name)
        try:
            outdated_counts[name] = reindexer.count_outdated()
            reindexers[name] = reindexer
        except CollectionNotFoundError:
            print(f"  {YELLOW}⚠ Coleção '{name}' não existe no Qdrant configurado — ignorada.{RESET}")

    if not reindexers:
        print(f"\n  {YELLOW}Nenhuma coleção reindexável encontrada no Qdrant configurado.{RESET}\n")
        return

    total_outdated = sum(outdated_counts.values())
    print(f"\n  {BOLD}Resumo:{RESET}")
    for name, count in outdated_counts.items():
        print(f"    {name}: {count} ponto(s) desatualizado(s)")

    if total_outdated == 0:
        print(f"\n  {GREEN}✅ Todas as coleções já estão vetorizadas com o modelo atual.{RESET}\n")
        return

    print(
        f"\n  {YELLOW}⚠ Esta operação reescreve vetores persistidos no Qdrant e é IRREVERSÍVEL "
        f"para os pontos afetados.{RESET}"
    )
    if not auto_confirm:
        answer = input(f"  Confirma a reindexação de {total_outdated} ponto(s)? [s/N] ").strip().lower()
        if answer not in ("s", "sim", "y", "yes"):
            print(f"\n  {YELLOW}Reindexação cancelada pelo usuário.{RESET}\n")
            return

    for name, reindexer in reindexers.items():
        print(f"\n  {CYAN}Reindexando '{name}'...{RESET}")
        report = reindexer.run()
        print(f"  {GREEN}{report.summary()}{RESET}")
        if report.recreated_collection:
            print(
                f"  {YELLOW}⚠ A dimensão do modelo mudou: '{name}' foi recriada vazia. "
                f"Reingerir a fonte (crawl/documentos) para repovoá-la.{RESET}"
            )
    print()


def _handle_embeddings_command(argv: list[str]) -> None:
    """Trata `geminiclaw embeddings <ação> [opções]` (Roadmap V16 / ADR 011 §3).

    Tratado separadamente do parser principal (que só aceita um único
    argumento posicional de prompt) para suportar a sintaxe de subcomando
    `geminiclaw embeddings reindex --collection <nome> --yes` sem exigir que
    o usuário cite (quote) as duas palavras juntas.

    Args:
        argv: Argumentos após "embeddings" (ex.: ``["reindex", "--yes"]``).
    """
    sub_parser = argparse.ArgumentParser(
        prog="geminiclaw embeddings",
        description="Comandos de gestão de embeddings locais.",
    )
    sub_parsers = sub_parser.add_subparsers(dest="action", required=True)
    reindex_parser = sub_parsers.add_parser(
        "reindex",
        help="Revetoriza coleções do Qdrant com o modelo de embeddings atual.",
    )
    reindex_parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Coleção a reindexar (padrão: todas as coleções reindexáveis).",
    )
    reindex_parser.add_argument(
        "--yes",
        action="store_true",
        help="Pula a confirmação interativa.",
    )
    try:
        sub_args = sub_parser.parse_args(argv)
    except SystemExit as e:
        sys.exit(e.code)

    if sub_args.action == "reindex":
        run_embeddings_reindex(collection=sub_args.collection, auto_confirm=sub_args.yes)


def _handle_vocab_command(argv: list[str], store: Any | None = None) -> int:
    """Trata `geminiclaw vocab pending|approve|reject|map` (v17-controlled-vocabulary).

    Operações tipadas e determinísticas do grafo, com autor ``pesquisador`` e sem LLM.

    Args:
        argv: Argumentos após "vocab".
        store: ``GraphStore`` a usar (padrão: o grafo de produção); injetável em testes.

    Returns:
        Código de saída (0 em sucesso).
    """
    from src.knowledge import vocabulary

    parser = argparse.ArgumentParser(
        prog="geminiclaw vocab",
        description="Decisões do pesquisador sobre candidatos do vocabulário controlado.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("pending", help="Lista candidatos e sinônimos candidatos.")
    sub.add_parser("approve", help="Aprova um candidato.").add_argument("id")
    reject_p = sub.add_parser("reject", help="Rejeita um candidato (sem apagar).")
    reject_p.add_argument("id")
    reject_p.add_argument("--motivo", default=None, help="Motivo da rejeição.")
    map_p = sub.add_parser("map", help="Funde um candidato em um termo canônico.")
    map_p.add_argument("id")
    map_p.add_argument("--para", required=True, help="ID do termo canônico.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    try:
        if store is None:
            from src.knowledge.factory import open_graph_store

            store = open_graph_store()
        if args.action == "pending":
            items = vocabulary.list_pending(store)
            if not items:
                print("Nenhum candidato pendente.")
            for item in items:
                extra = f" sinônimos candidatos: {item['sinonimos_candidatos']}" if item["tipo"] == "sinonimo" else ""
                print(f"{item['id']}  {item['label']}  {item['tipo']}  {item['termo']}{extra}")
        elif args.action == "approve":
            from src.gate.human_gate import authorize_from_cli

            if not authorize_from_cli("aprovar_termo_vocabulario", args.id):
                print("Aprovação não autorizada pelo gate (exige a ação do pesquisador na CLI).")
                return 1
            vocabulary.approve_term(store, args.id)
            print(f"Aprovado: {args.id}")
        elif args.action == "reject":
            vocabulary.reject_term(store, args.id, args.motivo)
            print(f"Rejeitado: {args.id}")
        elif args.action == "map":
            vocabulary.map_term(store, args.id, args.para)
            print(f"Mapeado: {args.id} -> {args.para}")
    except (vocabulary.VocabularyError, RuntimeError) as e:
        print(f"\n  {RED}❌ {e}{RESET}\n")
        return 1
    return 0


def main() -> None:
    """Ponto de entrada principal da CLI."""
    install_provider_resolver()
    thermal_protection_warning()  # registra o aviso de proteção térmica desligada, se couber

    # Roadmap V15.6 / Spec G10 — help completo customizado, sem passar pelo argparse padrão
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print_full_help()
        sys.exit(0)

    # Roadmap V16 — 'geminiclaw embeddings <ação>' é um subcomando de verdade
    # (múltiplas palavras sem aspas), tratado antes do parser genérico de
    # prompt (que só aceita um único argumento posicional).
    if len(sys.argv) >= 2 and sys.argv[1] == "embeddings":
        _handle_embeddings_command(sys.argv[2:])
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "project":
        from src.cli.project import handle_project_command

        sys.exit(handle_project_command(sys.argv[2:]))

    if len(sys.argv) >= 2 and sys.argv[1] == "graph":
        from src.cli.graph import handle_graph_command

        sys.exit(handle_graph_command(sys.argv[2:]))

    if len(sys.argv) >= 2 and sys.argv[1] == "vocab":
        sys.exit(_handle_vocab_command(sys.argv[2:]))

    # V18.5 (v18.5-execution-provenance) — 'geminiclaw provenance verify|export'.
    if len(sys.argv) >= 2 and sys.argv[1] == "provenance":
        from src.cli.provenance import run as run_provenance

        sys.exit(run_provenance(sys.argv[2:]))

    # V18.5 (v18.5-claim-verification) — 'geminiclaw claims list|resolve'.
    if len(sys.argv) >= 2 and sys.argv[1] == "claims":
        from src.cli.claims import run as run_claims

        sys.exit(run_claims(sys.argv[2:]))

    # V18 (v18-hypothesis-loop) — decisão do pesquisador sobre oportunidades documentadas.
    if len(sys.argv) >= 2 and sys.argv[1] == "opportunities":
        from src.cli.opportunities import handle_opportunities_command

        sys.exit(handle_opportunities_command(sys.argv[2:]))

    # Roadmap V17 — 'geminiclaw knowledge stats|reindex' (índice semântico do grafo).
    if len(sys.argv) >= 2 and sys.argv[1] == "knowledge":
        from src.db import get_pool
        from src.knowledge.semantic_runtime import run_knowledge_command

        pool = get_pool()
        pool.open()
        try:
            code = run_knowledge_command(sys.argv[2:])
        finally:
            pool.close()
        sys.exit(code)

    parser = build_parser()
    args = parser.parse_args()
    mode = args.mode or SESSION_DEFAULT_MODE
    # Roadmap V18 / Spec usage-limits — orçamento efetivo da sessão (config + overrides de CLI).
    try:
        budget = build_usage_budget(args)
    except ValueError as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}Orçamento de uso inválido: {e}{RESET}\n")
        logger.error("Orçamento de uso inválido", extra={"error": str(e)})
        sys.exit(1)

    if args.prompt:
        p_lower = args.prompt.strip().lower()
        if p_lower == "history":
            from src.cli.reports import show_history

            show_history()
            sys.exit(0)
        elif p_lower == "sandboxes":
            show_sandboxes()
            sys.exit(0)
        elif p_lower == "parar-sandboxes" or p_lower.startswith("parar-sandboxes "):
            target_sess = args.session
            if not target_sess and " " in args.prompt.strip():
                target_sess = args.prompt.strip().split(maxsplit=1)[1]
            stop_sandboxes(session_id=target_sess)
            sys.exit(0)
        elif p_lower == "clear-context":
            clear_context()
            sys.exit(0)
        elif p_lower == "convert":
            if not args.session or not args.format:
                print(f"\n  {RED}❌ Use: geminiclaw convert --session <id> --format latex|html|docx{RESET}\n")
                sys.exit(1)
            convert_report(args.session, args.format)
            sys.exit(0)

    # Subcomando: --metrics <execution_id>
    if args.metrics:
        from src.cli.reports import show_metrics
        from src.db import get_pool
        pool = get_pool()
        pool.open()
        try:
            show_metrics(args.metrics)
        finally:
            pool.close()
        sys.exit(0)

    # Subcomando: --export <execution_id>
    if args.export:
        from scripts.export_metrics import export_all
        from src.db import get_pool
        pool = get_pool()
        pool.open()
        try:
            export_all(args.export, Path(args.export_dir))
        finally:
            pool.close()
        sys.exit(0)

    # Subcomando: --log <session_id>
    if args.log:
        from src.cli.reports import show_session_logs

        show_session_logs(args.log)
        sys.exit(0)

    # v18.7-background-sessions — toda pesquisa roda em processo próprio (ADR 023 §1): o comando direto é o terminal
    # que cria o processo, mostra a saída dele e sai com o código do motivo de parada; o REPL só lança e acompanha.
    if args.prompt:
        p_lower_resume = args.prompt.strip().lower()
        if p_lower_resume == "resume" or p_lower_resume.startswith("resume "):
            target_sess = args.session
            if not target_sess and " " in args.prompt.strip():
                target_sess = args.prompt.strip().split(maxsplit=1)[1]
            if not target_sess:
                print(f"\n  {RED}❌ Especifique --session <id> (ex: geminiclaw resume --session <id>).{RESET}\n")
                sys.exit(1)
            sys.exit(
                asyncio.run(
                    resume_research(
                        target_sess, args, mode=args.mode, budget=budget, background=args.background
                    )
                )
            )
        if p_lower_resume == "continue" or p_lower_resume.startswith("continue "):
            target_project = args.project
            if not target_project and " " in args.prompt.strip():
                target_project = args.prompt.strip().split(maxsplit=1)[1]
            if not target_project:
                print(f"\n  {RED}❌ Especifique --project <id> (ex: geminiclaw continue --project <id>).{RESET}\n")
                sys.exit(1)
            sys.exit(
                asyncio.run(
                    continue_project(target_project, args, mode=args.mode, budget=budget, background=args.background)
                )
            )
        sys.exit(
            asyncio.run(start_research(args.prompt, args, mode=mode, budget=budget, background=args.background))
        )

    if args.background:
        print(f"\n  {STATUS_ICONS['error']} {RED}--background exige uma tarefa.{RESET}\n")
        sys.exit(1)
    code = asyncio.run(interactive_mode(mode=mode, explicit_mode=args.mode, budget=budget, args=args))
    try:
        from src.observability.telemetry import get_telemetry

        asyncio.run(get_telemetry().flush())  # V11.1.2 — flush explícito ao sair do modo interativo
    except Exception as _e:
        logger.error("Erro no flush de telemetria final (REPL)", extra={"error": str(_e)})
    sys.exit(code)


if __name__ == "__main__":
    main()
