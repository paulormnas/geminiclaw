"""Instantâneo do grafo para o replay (E0): tentativas por Problema e abordagem, derivações e semelhança.

O instantâneo é um JSON autocontido e reprodutível (o replay não toca no banco): o sha256 do arquivo entra no
``replay.json``. A abordagem é identificada pelo nome normalizado (``abordagem_key``), porque os nós ``Abordagem`` são
por projeto e o mesmo nome em projetos diferentes designa a mesma abordagem. Essa chave é uma heurística: nomes
diferentes para a mesma abordagem (``SVM RBF`` e ``SVM com kernel RBF``) contam como abordagens distintas.

Uso::

    DATABASE_URL=... QDRANT_URL=... uv run python -m scripts.memory_eval.snapshot --saida snapshot.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

root_path = str(Path(__file__).parent.parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.embeddings.base import get_embedding_provider  # noqa: E402
from src.knowledge.graph_store import GraphStore, Node  # noqa: E402
from src.knowledge.semantic_index import canonical_text  # noqa: E402
from src.knowledge.service import KnowledgeService, KnowledgeServiceError  # noqa: E402
from src.knowledge.structural_candidates import approach_key  # noqa: E402

VERSAO = 1
_PAGE = 200


def problem_signature(caracteristicas: Any) -> str:
    """Assinatura dos dados do Problema; Problemas com a mesma assinatura são o mesmo problema de dados."""
    if not isinstance(caracteristicas, dict) or not caracteristicas:
        return ""
    return json.dumps({k: str(v) for k, v in sorted(caracteristicas.items())}, ensure_ascii=False)


def _all_nodes(store: GraphStore, label: str) -> Iterator[Node]:
    after: str | None = None
    while True:
        page = store.list_nodes(label, after_id=after, limit=_PAGE)
        if not page:
            return
        yield from page
        after = page[-1].id


def _cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def build_snapshot(
    store: GraphStore,
    *,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
    excluded_projects: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Lê o grafo e monta o instantâneo (sem escrever nada).

    Args:
        store: Grafo (somente leitura).
        embed: Função de embeddings locais (padrão: o provedor do projeto).
        excluded_projects: Projetos fora do corpus (por exemplo, a sessão vazia por cota).
    """
    service = KnowledgeService(store)
    problemas: list[dict[str, Any]] = []
    tentativas: list[dict[str, Any]] = []
    derivacoes: list[dict[str, Any]] = []
    sem_tentativa: list[str] = []
    abordagens_por_projeto: dict[str, list[Node]] = {}
    for node in _all_nodes(store, "Abordagem"):
        abordagens_por_projeto.setdefault(str(node.properties.get("projeto_id")), []).append(node)
    all_approaches = [n for ns in abordagens_por_projeto.values() for n in ns]
    key_of = {n.id: approach_key(str(n.properties.get("nome", ""))) for n in all_approaches}
    for problema in _all_nodes(store, "Problema"):
        projeto = str(problema.properties.get("projeto_id"))
        if projeto in excluded_projects or problema.properties.get("status") != "confirmado":
            continue
        try:
            criterion, _ = service.criterion_for(problema)
        except KnowledgeServiceError:
            continue
        found: list[dict[str, Any]] = []
        for abordagem in abordagens_por_projeto.get(projeto, []):
            attempts, reference = service.approach_attempts(abordagem.id, problema)
            for item in attempts:
                at = item.attempt
                base = at.baseline if at.baseline is not None else reference
                found.append(
                    {
                        "id": at.attempt_id, "problema_id": problema.id, "abordagem_key": key_of[abordagem.id],
                        "abordagem_nome": abordagem.properties.get("nome"), "criado_em": at.timestamp,
                        "valor": at.value, "baseline": base, "config_hash": at.config_hash, "seed": at.seed,
                        "dataset_ids": list(at.dataset_ids),
                    }
                )
        if not found:
            sem_tentativa.append(problema.id)
            continue
        tentativas.extend(found)
        problemas.append(
            {
                "id": problema.id, "projeto_id": projeto, "titulo": problema.properties.get("titulo"),
                "assinatura": problem_signature(problema.properties.get("caracteristicas_dados")),
                "criterio": {"sentido": criterion.sentido, "delta_min": criterion.delta_min, "alvo": criterion.alvo},
                "texto": canonical_text("Problema", problema.properties) or "",
            }
        )
    for abordagem in all_approaches:
        for edge in store.neighbors(abordagem.id, ["VARIANTE_DE"], direction="out", depth=1).edges:
            if edge.rel_type == "VARIANTE_DE" and edge.src_id == abordagem.id and edge.dst_id in key_of:
                derivacoes.append(
                    {
                        "filha": key_of[abordagem.id], "pai": key_of[edge.dst_id],
                        "criado_em": str(edge.properties.get("criado_em") or abordagem.properties.get("criado_em")),
                    }
                )
    embedder = embed or get_embedding_provider().embed_documents
    vectors = embedder([p["texto"] for p in problemas]) if problemas else []
    similaridade = {
        f"{a['id']}|{b['id']}": round(_cosine(va, vb), 6)
        for i, (a, va) in enumerate(zip(problemas, vectors, strict=True))
        for b, vb in list(zip(problemas, vectors, strict=True))[i + 1 :]
    }
    for p in problemas:
        del p["texto"]
    tentativas.sort(key=lambda t: (t["criado_em"], t["id"]))
    return {
        "versao": VERSAO, "problemas": sorted(problemas, key=lambda p: p["id"]), "tentativas": tentativas,
        "derivacoes": sorted(derivacoes, key=lambda d: (d["criado_em"], d["filha"], d["pai"])),
        "similaridade": similaridade, "problemas_sem_tentativa": sorted(sem_tentativa),
    }


def dump(snapshot: dict[str, Any]) -> str:
    """Serialização canônica (chaves ordenadas), a mesma sobre a qual se calcula o sha256."""
    return json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--excluir-projeto", action="append", default=[], help="projeto_id fora do corpus")
    args = parser.parse_args()
    from src.knowledge.factory import open_graph_store

    snapshot = build_snapshot(open_graph_store(), excluded_projects=frozenset(args.excluir_projeto))
    text = dump(snapshot)
    args.saida.write_text(text, encoding="utf-8")
    print(
        f"{len(snapshot['problemas'])} problemas, {len(snapshot['tentativas'])} tentativas, "
        f"sem tentativa: {len(snapshot['problemas_sem_tentativa'])}; sha256 {sha256_of(text)}"
    )


if __name__ == "__main__":
    main()
