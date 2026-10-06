"""Avaliação do modelo de embedding na busca de domínio (v17-domain-search §8).

Carrega a Tabela de Áreas do CNPq em um índice **em memória** (grafo e Qdrant locais; nada é
gravado em banco), roda as consultas rotuladas de ``tests/fixtures/domain_queries.jsonl`` e
calcula, por idioma, ``hit@1``, ``hit@3`` e a posição média do primeiro acerto.

Precisa do modelo de embedding (pode baixá-lo na primeira execução): **não roda no CI**.

Uso::

    uv run python -m scripts.eval_domain_search [--model ID] [--queries ARQUIVO] [--min-score X]

Cada linha do arquivo de consultas é um JSON com ``consulta``, ``esperados`` (códigos CNPq aceitos,
em qualquer nível) e ``idioma``. Acerto = qualquer código esperado entre os resultados.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

DEFAULT_QUERIES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "domain_queries.jsonl"
# Posições consideradas: o resultado é uma lista ordenada de códigos CNPq.
SearchFn = Callable[[str], list[str]]


@dataclass(frozen=True)
class LanguageMetrics:
    """Métricas de um idioma.

    Attributes:
        total: Consultas do idioma.
        hit_at_1: Fração com acerto na primeira posição.
        hit_at_3: Fração com acerto entre as três primeiras.
        mean_first_rank: Posição média (1 = topo) do primeiro acerto, só entre as consultas
            com algum acerto; ``None`` se nenhuma acertou.
    """

    total: int
    hit_at_1: float
    hit_at_3: float
    mean_first_rank: float | None


def load_queries(path: Path) -> list[dict]:
    """Lê as consultas rotuladas (JSON Lines).

    Raises:
        ValueError: Linha sem ``consulta``, ``esperados`` (lista não vazia) ou ``idioma``.
    """
    queries: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if (
            not isinstance(item.get("consulta"), str)
            or not item.get("idioma")
            or not isinstance(item.get("esperados"), list)
            or not item["esperados"]
        ):
            raise ValueError(f"{path}:{number}: use 'consulta', 'idioma' e 'esperados' (lista não vazia).")
        queries.append(item)
    return queries


def compute_metrics(queries: list[dict], search: SearchFn) -> dict[str, LanguageMetrics]:
    """Calcula ``hit@1``, ``hit@3`` e a posição média do primeiro acerto por idioma.

    Args:
        queries: Consultas rotuladas (``consulta``, ``esperados``, ``idioma``).
        search: Devolve os códigos CNPq dos resultados, em ordem de ranking.

    Returns:
        Métricas por idioma.
    """
    ranks: dict[str, list[int | None]] = defaultdict(list)
    for item in queries:
        accepted = set(item["esperados"])
        codes = search(item["consulta"])
        first = next((pos for pos, code in enumerate(codes, start=1) if code in accepted), None)
        ranks[item["idioma"]].append(first)
    result: dict[str, LanguageMetrics] = {}
    for language, positions in ranks.items():
        hits = [p for p in positions if p is not None]
        total = len(positions)
        result[language] = LanguageMetrics(
            total=total,
            hit_at_1=sum(1 for p in hits if p == 1) / total,
            hit_at_3=sum(1 for p in hits if p <= 3) / total,
            mean_first_rank=(sum(hits) / len(hits)) if hits else None,
        )
    return result


def format_report(metrics: dict[str, LanguageMetrics], *, model: str) -> str:
    """Relatório em texto (uma linha por idioma)."""
    lines = [f"Modelo: {model}"]
    for language in sorted(metrics):
        m = metrics[language]
        rank = "n/d" if m.mean_first_rank is None else f"{m.mean_first_rank:.2f}"
        lines.append(
            f"  {language}: consultas={m.total} hit@1={m.hit_at_1:.2f} hit@3={m.hit_at_3:.2f} "
            f"posicao_media_do_primeiro_acerto={rank}"
        )
    return "\n".join(lines)


def build_search(model: str | None, vocabulary_dir: Path | None) -> tuple[SearchFn, str]:
    """Monta o índice em memória com a tabela do CNPq e devolve a função de busca.

    Args:
        model: Modelo de embedding (padrão: ``EMBEDDING_MODEL``).
        vocabulary_dir: Diretório do vocabulário (padrão: ``data/vocabulary``).

    Returns:
        ``(busca, nome do modelo)``.
    """
    from qdrant_client import QdrantClient

    from src.embeddings.fastembed_provider import FastEmbedProvider
    from src.knowledge.domain_search import DomainSearch
    from src.knowledge.graph_store import InMemoryGraphStore
    from src.knowledge.semantic_index import SemanticIndex
    from src.knowledge.vocabulary import seed_vocabulary

    provider = FastEmbedProvider(model_name=model) if model else FastEmbedProvider()
    store = InMemoryGraphStore()
    seed_vocabulary(store, vocabulary_dir=vocabulary_dir)
    index = SemanticIndex(store, QdrantClient(location=":memory:"), provider=provider)
    report = index.reconcile()
    print(f"Índice em memória: {report.reindexed} nó(s) vetorizado(s) em {report.elapsed_seconds:.1f}s.")
    domain_search = DomainSearch(store, index)
    code_by_id = {n.id: n.properties.get("codigo_cnpq") for n in store.find_nodes("Dominio", {}, limit=100_000)}

    def search(text: str) -> list[str]:
        hits = domain_search.search(text, limit=10)
        return [str(code_by_id.get(h.node_id)) for h in hits]

    return search, provider.info.model


def main(argv: list[str] | None = None) -> int:
    """Executa a avaliação e imprime o relatório."""
    parser = argparse.ArgumentParser(description="Avalia o modelo de embedding na busca de domínio.")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES, help="Arquivo JSON Lines de consultas.")
    parser.add_argument("--model", default=None, help="Modelo de embedding (padrão: EMBEDDING_MODEL).")
    parser.add_argument("--dir", type=Path, default=None, help="Diretório do vocabulário (cnpq_areas.csv).")
    parser.add_argument(
        "--min-score", type=float, default=None,
        help="Escore mínimo (DOMAIN_SEARCH_MIN_SCORE) para esta avaliação; 0 mede o ranking puro.",
    )
    args = parser.parse_args(argv)
    from src import config

    if args.min_score is not None:
        config.DOMAIN_SEARCH_MIN_SCORE = args.min_score
    try:
        queries = load_queries(args.queries)
        search, model_name = build_search(args.model, args.dir)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(format_report(compute_metrics(queries, search), model=model_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
