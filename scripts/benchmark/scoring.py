"""Pontuação da tarefa Iris do ``run.sh``.

A tarefa pede: análise exploratória, pré-processamento, ao menos dois algoritmos, avaliação
comparativa e recomendação final justificada, com artefatos salvos. Há duas réguas determinísticas (sem LLM):

- **Placar oficial** (v18.6-benchmark-harness §4): :func:`validated_scoreboard` lê o grafo (``Resultado`` validado com
  ``MEDE`` para a métrica do ``Problema``) e as subtarefas aprovadas pelo revisor. Só ele vale como acurácia e
  checklist.
- **Leitura de texto** (:func:`score_session`): procura palavras e números nos arquivos da sessão. Fica no resultado
  como ``checks_texto`` e ``acuracia_declarada_texto``, só para comparação: palavras no plano não provam que o
  algoritmo rodou, e um número perto de "accuracy" pode ser uma contagem.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ALGORITHMS = {
    "logistic regression": r"logistic\s*regression|regress[aã]o\s+log[ií]stica|LogisticRegression",
    "random forest": r"random\s*forest|RandomForest",
    "svm": r"\bSVM\b|\bSVC\b|support\s+vector",
    "knn": r"\bk-?nn\b|KNeighbors|k-nearest",
    "decision tree": r"decision\s*tree|DecisionTree|[aá]rvore\s+de\s+decis",
    "gradient boosting": r"gradient\s*boosting|GradientBoosting|XGB|LightGBM",
    "naive bayes": r"naive\s*bayes|GaussianNB",
}
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".csv", ".log"}
# Arquivos injetados pelo framework em toda subtarefa: trazem exemplos (ex.: {"accuracy": 0.87}) que não
# são resultado do modelo e contaminariam o checklist.
FRAMEWORK_FILES = {"scientific_helpers.py"}
# Acurácia só é lida de saídas (métricas, relatórios), nunca do código gerado.
ACCURACY_SUFFIXES = {".md", ".txt", ".json", ".csv"}
TRAIN_RE = re.compile(r"train|treino|cv_|cross", re.I)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}
ACCURACY_RE = re.compile(r"accuracy|acur[aá]cia", re.I)
NUMBER_RE = re.compile(r"(?<![\d.])(0[.,]\d{2,4}|1[.,]0+|\d{2,3}(?:[.,]\d+)?\s*%)")

CHECKS = ("eda", "preprocessing", "two_algorithms", "comparison", "recommendation", "artifacts")


def _texts(session_dir: Path) -> tuple[str, str, list[Path]]:
    """Texto de todos os arquivos, texto só das saídas (para acurácia) e a lista de arquivos."""
    chunks, outputs, files = [], [], []
    for path in sorted(session_dir.rglob("*")):
        if not path.is_file() or path.name in FRAMEWORK_FILES:
            continue
        files.append(path)
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size < 2_000_000:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks.append(content)
            if path.suffix.lower() in ACCURACY_SUFFIXES:
                outputs.append(content)
    return "\n".join(chunks), "\n".join(outputs), files


def reported_accuracies(text: str) -> list[float]:
    """Valores entre 0 e 1 citados perto da palavra acurácia/accuracy."""
    found = []
    for line in text.splitlines():
        if not ACCURACY_RE.search(line) or TRAIN_RE.search(line):
            continue
        for match in NUMBER_RE.findall(line):
            raw = match.replace(",", ".").replace("%", "").strip()
            value = float(raw)
            found.append(value / 100 if value > 1 else value)
    return [v for v in found if 0.0 <= v <= 1.0]


def score_session(session_dir: Path) -> dict:
    """Leitura de texto da sessão: ``{checks_texto, score_texto, acuracia_declarada_texto, algorithms, ...}``.

    Não é o placar oficial (ver o módulo); serve à comparação com :func:`validated_scoreboard`.
    """
    text, outputs, files = _texts(session_dir)
    algos = sorted(name for name, pattern in ALGORITHMS.items() if re.search(pattern, text, re.I))
    accuracies = reported_accuracies(outputs)
    plausible = [a for a in accuracies if 0.85 <= a <= 1.0]
    has_image = any(f.suffix.lower() in IMAGE_SUFFIXES for f in files)
    checks = {
        "eda": bool(re.search(r"describe\(|pairplot|histogram|correla|an[aá]lise explorat|exploratory", text, re.I)),
        "preprocessing": bool(re.search(r"train_test_split|StandardScaler|MinMaxScaler|normaliz|padroniz", text, re.I)),
        "two_algorithms": len(algos) >= 2,
        "comparison": bool(plausible) and len(algos) >= 2,
        "recommendation": bool(re.search(r"recomend|recommend|em produ[cç][aã]o|in production", text, re.I))
        and bool(re.search(r"justific|porque|because|pois|devido", text, re.I)),
        "artifacts": has_image or any(f.suffix.lower() in {".pkl", ".joblib", ".csv"} for f in files),
    }
    return {
        "checks_texto": checks,
        "score_texto": sum(checks.values()),
        "max_score": len(CHECKS),
        "algorithms": algos,
        # Abaixo de 0,5 em 3 classes é limiar de tolerância ou ruído do texto, não acurácia do modelo.
        "acuracia_declarada_texto": (
            max(plausible) if plausible else max((a for a in accuracies if a >= 0.5), default=None)
        ),
        "artifact_files": len(files),
    }


def session_outcome(session_dir: Path) -> dict:
    """Lê ``session_metadata.json``: quantas subtarefas terminaram e tokens totais."""
    path = session_dir / "session_metadata.json"
    if not path.is_file():
        return {"metadata": False, "subtasks": 0, "subtasks_ok": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    subtasks = data.get("subtasks", [])
    return {
        "metadata": True,
        "subtasks": len(subtasks),
        "subtasks_ok": sum(1 for s in subtasks if s.get("status") == "success"),
        "duration_seconds": data.get("duration_seconds"),
        "cost_usd": data.get("cost_usd"),
        "token_usage": data.get("token_usage", {}),
    }


# --------------------------------------------------------------------------------------------
# Placar oficial: grafo + subtarefas aprovadas (v18.6-benchmark-harness §4)
# --------------------------------------------------------------------------------------------

SOURCE_VALIDATED = "grafo_validado"
NOTE_NO_MEDE = "sem MEDE"
PREPROCESSING_RE = re.compile(r"train_test_split|StandardScaler|MinMaxScaler|normaliz|padroniz|divis[aã]o|split", re.I)
RECOMMENDATION_RE = re.compile(r"^#+\s.*(recomenda|recommend)", re.I | re.M)


def graph_accuracy(store: Any, project_id: str, session_id: str | None) -> dict[str, Any]:
    """Maior acurácia de teste entre os ``Resultado``s validados com ``MEDE`` para a métrica do ``Problema``.

    Elegível: ``status_validacao == "validado"``, aresta ``MEDE`` para a ``Metrica`` do ``Problema`` do projeto,
    qualificador ausente/vazio/``teste`` e, quando informada, a mesma sessão. Sem elegível, ``accuracy_validated`` é
    ``None`` (nunca um valor inventado, AGENTS.md §1.6).

    Returns:
        ``accuracy_validated``, ``accuracy_source``, ``accuracy_note`` (``"sem MEDE"`` quando há ``Resultado``s mas
        nenhum com ``MEDE``), ``resultados`` (todos da sessão), ``resultados_mede``, ``metrica_aprovada`` e
        ``elegiveis`` (id, valor e experimento de cada resultado elegível).
    """
    sub = store.project_subgraph(project_id)
    problem = next((n for n in sub.nodes if n.label == "Problema"), None)
    metric_id = ((problem.properties.get("criterio_sucesso") or {}).get("metrica_id")) if problem else None
    # A ``Metrica`` é do vocabulário global (fora do projeto): a aresta ``MEDE`` não aparece no subgrafo do projeto.
    metric = store.get_node(metric_id) if metric_id else None
    results = [
        n for n in sub.nodes
        if n.label == "Resultado" and (session_id is None or n.properties.get("sessao_id") == session_id)
    ]
    measuring = {
        n.id for n in results
        if metric_id and any(e.src_id == n.id and e.dst_id == metric_id
                             for e in store.neighbors(n.id, ["MEDE"], "out").edges)
    }
    producer = {e.dst_id: e.src_id for e in sub.edges if e.rel_type == "PRODUZIU"}
    eligible = []
    for node in results:
        props = node.properties
        if node.id not in measuring or props.get("status_validacao") != "validado":
            continue
        if (props.get("qualificador") or "") not in ("", "teste"):
            continue
        try:
            value = float(props["valor"])
        except (KeyError, TypeError, ValueError):
            continue
        eligible.append({"id": node.id, "valor": value, "experimento": producer.get(node.id)})
    best = max((r["valor"] for r in eligible), default=None)
    return {
        "accuracy_validated": best,
        "accuracy_source": SOURCE_VALIDATED,
        "accuracy_note": NOTE_NO_MEDE if results and not measuring else None,
        "resultados": len(results),
        "resultados_mede": len(measuring),
        "metrica_aprovada": bool(metric and metric.properties.get("status") == "aprovado"),
        "elegiveis": eligible,
    }


def _approved_reviews(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Última revisão aprovada por subtarefa (``task_name``) a partir dos eventos ``subtask_review``."""
    approved: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload") or {}
        name = event.get("task_name")
        if event.get("event_type") == "subtask_review" and payload.get("approved") and name:
            approved[name] = payload
    return approved


def validated_checks(
    plan: dict[str, dict[str, Any]], events: list[dict[str, Any]], board: dict[str, Any], final_report: str
) -> dict[str, bool]:
    """Checklist só com subtarefas aprovadas pelo revisor, artefatos resolvidos, plano e grafo (design §4.2).

    Args:
        plan: ``{task_name: subtarefa}`` do ``plan.json`` (``task_type``, ``approach``, descrição).
        events: Eventos da sessão (``event_type``, ``task_name``, ``payload``).
        board: Saída de :func:`graph_accuracy`.
        final_report: Texto de ``relatorio_final.md`` (vazio se não foi gerado).
    """
    approved = _approved_reviews(events)
    tasks = {name: plan.get(name, {}) for name in approved}

    def text_of(task: dict[str, Any]) -> str:
        return json.dumps(task, ensure_ascii=False, default=str)

    # ``model_impl`` é o tipo normalizado das subtarefas de treino (src/orchestration/plan_normalizer.py).
    training = [t for t in tasks.values() if str(t.get("task_type", "")).lower() == "model_impl"]
    approaches = {
        str((t.get("approach") or {}).get("nome", "")).strip().lower()
        for t in training
        if isinstance(t.get("approach"), dict)
    } - {""}
    experiments = {r["experimento"] or r["id"] for r in board.get("elegiveis", [])}
    return {
        "eda": any(str(t.get("task_type", "")).lower() == "eda" for t in tasks.values()),
        "preprocessing": any(PREPROCESSING_RE.search(text_of(t)) for t in tasks.values()),
        "two_algorithms": len(approaches) >= 2,
        "comparison": len(experiments) >= 2,
        "recommendation": bool(RECOMMENDATION_RE.search(final_report or "")),
        "artifacts": any(bool(p.get("resolved_artifacts")) for p in approved.values()),
    }


def validated_scoreboard(
    store: Any,
    project_id: str,
    session_id: str | None,
    plan: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    final_report: str,
) -> dict[str, Any]:
    """Placar oficial: ``accuracy_validated``, ``checks_validated``, ``score_validated`` e os campos de diagnóstico."""
    board = graph_accuracy(store, project_id, session_id)
    checks = validated_checks(plan, events, board, final_report)
    return {**board, "checks_validated": checks, "score_validated": sum(checks.values())}


def scoreboard_anomalies(board: dict[str, Any]) -> list[str]:
    """Marcas de conferência manual do placar (design §4.4); nenhuma interrompe o ``--fail-fast``."""
    marks = []
    if board.get("accuracy_validated") == 1.0:
        marks.append("acuracia_perfeita")
    if board.get("resultados") and not board.get("resultados_mede"):
        marks.append("sem_mede")
    if board.get("metrica_aprovada") is False:
        marks.append("vocabulario_nao_semeado")
    return marks
