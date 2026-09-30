"""Pontuação da tarefa Iris do ``run.sh`` a partir dos artefatos gravados em disco.

A tarefa pede: análise exploratória, pré-processamento, ao menos dois algoritmos, avaliação
comparativa e recomendação final justificada, com artefatos salvos. O checklist abaixo verifica
cada item de forma determinística (sem chamar LLM), para que duas combinações de modelos sejam
comparáveis com a mesma régua.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

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
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}
ACCURACY_RE = re.compile(r"accuracy|acur[aá]cia", re.I)
NUMBER_RE = re.compile(r"(?<![\d.])(0[.,]\d{2,4}|1[.,]0+|\d{2,3}(?:[.,]\d+)?\s*%)")

CHECKS = ("eda", "preprocessing", "two_algorithms", "comparison", "recommendation", "artifacts")


def _texts(session_dir: Path) -> tuple[str, list[Path]]:
    chunks, files = [], []
    for path in sorted(session_dir.rglob("*")):
        if not path.is_file():
            continue
        files.append(path)
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size < 2_000_000:
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    return "\n".join(chunks), files


def reported_accuracies(text: str) -> list[float]:
    """Valores entre 0 e 1 citados perto da palavra acurácia/accuracy."""
    found = []
    for line in text.splitlines():
        if not ACCURACY_RE.search(line):
            continue
        for match in NUMBER_RE.findall(line):
            raw = match.replace(",", ".").replace("%", "").strip()
            value = float(raw)
            found.append(value / 100 if value > 1 else value)
    return [v for v in found if 0.0 <= v <= 1.0]


def score_session(session_dir: Path) -> dict:
    """Aplica o checklist e devolve ``{checks, score, max_score, accuracy, algorithms, ...}``."""
    text, files = _texts(session_dir)
    algos = sorted(name for name, pattern in ALGORITHMS.items() if re.search(pattern, text, re.I))
    accuracies = reported_accuracies(text)
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
        "checks": checks,
        "score": sum(checks.values()),
        "max_score": len(CHECKS),
        "algorithms": algos,
        "accuracy": max(plausible) if plausible else (max(accuracies) if accuracies else None),
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
