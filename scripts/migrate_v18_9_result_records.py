"""Migra o grafo para os registros de resultado (V18.9, ``v18.9-result-records``; ADR 026).

Faz, nesta ordem:

1. recalcula as contagens de cada hipótese (``n_tentativas``, ``n_atingiu_alvo`` e ``n_abaixo_alvo``);
2. cria ou atualiza os ``RegistroResultado`` de cada abordagem aplicada, com os atalhos ``FUNCIONOU_PARA`` e
   ``FALHOU_PARA`` derivados deles;
3. marca como ``contestada`` os atalhos antigos que nenhum registro sustenta (sem ``registro_id``);
4. remove as propriedades do veredito (``suporte``, ``certeza``, ``veredito``, ``modelo_veredito`` e ``confianca``) e o
   ``peso`` das arestas ``SUSTENTA``/``REFUTA``.

Idempotente. Por padrão **só simula** (não escreve nada) e mostra o que faria; ``--aplicar`` grava, e antes disso faz
``pg_dump`` do banco em ``--backup-dir``. Os status das hipóteses não são reescritos aqui: a regra de réplicas os
reconcilia no fim do próximo ciclo.

Alteração de dados do grafo: rode só com a aprovação explícita do pesquisador.

Uso::

    uv run python scripts/migrate_v18_9_result_records.py                       # simulação
    uv run python scripts/migrate_v18_9_result_records.py --aplicar --backup-dir ~/backup_v18_9
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Garante que src/ seja importável quando executado como script solto.
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.knowledge.errors import GraphStoreError  # noqa: E402
from src.knowledge.graph_store import GraphStore  # noqa: E402
from src.knowledge.provenance import Actor  # noqa: E402
from src.knowledge.service import KnowledgeService  # noqa: E402
from src.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

ACTOR = Actor(kind="orquestrador")
LEGACY_NODE_PROPERTIES: dict[str, tuple[str, ...]] = {
    "Hipotese": ("suporte", "certeza", "veredito", "modelo_veredito"),
    "Descoberta": ("veredito", "modelo_veredito", "confianca"),
}
LEGACY_EDGE_PROPERTIES: dict[str, tuple[str, ...]] = {
    "SUSTENTA": ("peso",),
    "REFUTA": ("peso",),
    "FUNCIONOU_PARA": ("descoberta_id",),
    "FALHOU_PARA": ("descoberta_id",),
}
_PAGE = 200


@dataclass
class MigrationReport:
    """O que a migração fez (ou faria, na simulação)."""

    aplicado: bool = False
    projetos: int = 0
    hipoteses: int = 0
    abordagens: int = 0
    registros: int = 0
    atalhos_contestados: int = 0
    nos_com_legado: int = 0
    arestas_com_legado: int = 0
    ignorados: int = 0


def _all_nodes(store: GraphStore, label: str):
    after: str | None = None
    while True:
        page = store.list_nodes(label, after_id=after, limit=_PAGE)
        if not page:
            return
        yield from page
        after = page[-1].id


def _legacy_shortcuts(store: GraphStore, abordagem_id: str):
    """Atalhos da abordagem que nenhum registro sustenta (sem ``registro_id``) e ainda não estão contestados."""
    for rel in ("FUNCIONOU_PARA", "FALHOU_PARA"):
        sub = store.neighbors(abordagem_id, [rel], direction="out", depth=1)
        for edge in sub.edges:
            if (
                edge.src_id == abordagem_id
                and edge.rel_type == rel
                and not edge.properties.get("registro_id")
                and edge.properties.get("status") != "contestada"
            ):
                yield edge


def migrate(store: GraphStore, *, apply: bool) -> MigrationReport:
    """Migra (ou simula) o grafo de ``store``; ver o docstring do módulo."""
    report = MigrationReport(aplicado=apply)
    service = KnowledgeService(store)
    for projeto in _all_nodes(store, "Projeto"):
        project_id = projeto.properties.get("projeto_id")
        if not project_id:
            continue
        report.projetos += 1
        for hip in store.project_subgraph(str(project_id), labels=["Hipotese"]).nodes:
            report.hipoteses += 1
            if apply:
                try:
                    service.recompute_hypothesis(hip.id)
                except GraphStoreError as exc:
                    report.ignorados += 1
                    logger.info("Hipótese sem critério na migração", extra={"extra": {"motivo": type(exc).__name__}})
        for abordagem in store.project_subgraph(str(project_id), labels=["Abordagem"]).nodes:
            if abordagem.properties.get("status") == "fundida":
                continue
            report.abordagens += 1
            if apply:
                report.registros += service.recompute_approach(abordagem.id)
    for abordagem in _all_nodes(store, "Abordagem"):
        for edge in _legacy_shortcuts(store, abordagem.id):
            report.atalhos_contestados += 1
            if apply:
                store.set_edge_status(edge.src_id, edge.rel_type, edge.dst_id, "contestada", actor=ACTOR)
    legacy = remove_legacy_properties(store, apply=apply)
    report.nos_com_legado, report.arestas_com_legado = legacy
    return report


def remove_legacy_properties(
    store: GraphStore, *, apply: bool, project_id: str | None = None
) -> tuple[int, int]:
    """Conta (e, com ``apply``, remove) as propriedades do veredito em nós e arestas; só no Apache AGE.

    O ``GraphStore`` não remove propriedades (só acrescenta e atualiza), então a remoção usa Cypher direto no
    ``AgeGraphStore``. Em outro armazenamento (grafo em memória dos testes) as propriedades legadas ficam como estão:
    são inofensivas, porque a validação só confere as propriedades que uma escrita muda.

    Args:
        store: Grafo.
        apply: ``True`` remove; ``False`` só conta.
        project_id: Restringe a um projeto (testes); ``None`` vale para o grafo todo.

    Returns:
        ``(nós, arestas)`` com alguma propriedade legada.
    """
    run = getattr(store, "_run_cypher", None)
    if run is None:
        return 0, 0
    scope_node = " AND n.projeto_id = $pid" if project_id else ""
    scope_edge = " AND a.projeto_id = $pid" if project_id else ""
    params = {"pid": project_id} if project_id else {}
    nodes = edges = 0
    for label, keys in LEGACY_NODE_PROPERTIES.items():
        has = "(" + " OR ".join(f"n.{k} IS NOT NULL" for k in keys) + ")" + scope_node
        found = run(f"MATCH (n:{label}) WHERE {has} RETURN count(n)", params)
        nodes += int(found[0]) if found else 0
        if apply:
            removes = ", ".join(f"n.{k}" for k in keys)
            run(f"MATCH (n:{label}) WHERE {has} REMOVE {removes} RETURN count(n)", params)
    for rel, keys in LEGACY_EDGE_PROPERTIES.items():
        has = "(" + " OR ".join(f"r.{k} IS NOT NULL" for k in keys) + ")" + scope_edge
        found = run(f"MATCH (a)-[r:{rel}]->() WHERE {has} RETURN count(r)", params)
        edges += int(found[0]) if found else 0
        if apply:
            removes = ", ".join(f"r.{k}" for k in keys)
            run(f"MATCH (a)-[r:{rel}]->() WHERE {has} REMOVE {removes} RETURN count(r)", params)
    return nodes, edges


def _backup(backup_dir: Path) -> Path:
    from urllib.parse import urlsplit

    from scripts.benchmark.reset_stores import BenchmarkTarget, ResetError, _dump_postgres
    from src import config

    target = BenchmarkTarget(database_url=config.DATABASE_URL, qdrant_url=config.QDRANT_URL)
    try:
        return _dump_postgres(target, backup_dir)
    except ResetError as exc:
        raise SystemExit(f"Backup recusado ({urlsplit(config.DATABASE_URL).path.lstrip('/')}): {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aplicar", action="store_true", help="grava (o padrão só simula)")
    parser.add_argument("--backup-dir", type=Path, default=None, help="diretório do pg_dump feito antes de gravar")
    args = parser.parse_args(argv)
    if args.aplicar:
        if args.backup_dir is None:
            parser.error("--aplicar exige --backup-dir (o dump é feito antes de qualquer escrita).")
        print(f"backup: {_backup(args.backup_dir)}")
    from src.knowledge.factory import open_graph_store

    store = open_graph_store()
    report = migrate(store, apply=args.aplicar)
    for key, value in asdict(report).items():
        print(f"{key}: {value}")
    if not args.aplicar:
        print("Simulação: nada foi gravado. Rode com --aplicar --backup-dir DIR para migrar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
