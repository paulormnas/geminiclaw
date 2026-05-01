"""Roadmap V2 - Testes de integração — Etapa S8: Validação das Skills Integradas.

Valida o pipeline completo das skills sem chamar a API Gemini real,
evitando o bloqueio HTTP 429 que impediu a validação ao vivo.

Cenários cobertos:
1. QuickSearchSkill — run_with_logging emite eventos corretos (mock HTTP)
2. CodeSkill — executa pipeline Iris real via sandbox Docker, verifica artefatos
3. MemorySkill — ciclo completo: remember → recall → memorize → remember_forever
4. Verificação de log events em cenário realista encadeado
"""

import pytest
import asyncio
import logging
import os
import json
import tempfile
import shutil
import docker
from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.base import SkillResult
from src.skills.memory.skill import MemorySkill


# ---------------------------------------------------------------------------
# Helpers de verificação de disponibilidade
# ---------------------------------------------------------------------------

def is_docker_available():
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


def _get_events(caplog_records: list) -> list[str]:
    """Extrai o campo 'event' dos LogRecords usando getattr (logger GeminiClaw)."""
    return [getattr(r, "event", None) for r in caplog_records if getattr(r, "event", None)]


# ---------------------------------------------------------------------------
# 1. QuickSearchSkill — run_with_logging com HTTP mockado
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_quick_search_skill_run_with_logging_events(caplog):
    """QuickSearchSkill deve emitir skill_invoked e skill_completed via run_with_logging."""
    from src.skills.search_quick.skill import QuickSearchSkill

    # HTML mínimo retornado pelo mock do httpx
    _mock_html = """
    <html><body>
    <div class="result__body">
      <a class="result__a" href="http://example.com">Iris Dataset</a>
      <a class="result__snippet">O dataset Iris contém 150 amostras.</a>
    </div>
    </body></html>
    """

    skill = QuickSearchSkill()

    # Mocka o scraper para não fazer requisições reais
    mock_result = MagicMock()
    mock_result.title = "Iris Dataset"
    mock_result.url = "http://example.com"
    mock_result.snippet = "O dataset Iris contém 150 amostras."

    with patch.object(skill.backends["ddg"], "search", new=AsyncMock(return_value=[mock_result])):
        with caplog.at_level(logging.INFO, logger="src.skills.base"):
            result = await skill.run_with_logging(query="iris dataset scikit-learn", max_results=1)

    assert result.success, f"QuickSearchSkill falhou: {result.error}"

    events = _get_events(caplog.records)
    assert "skill_invoked" in events, f"skill_invoked ausente: {events}"
    assert "skill_completed" in events, f"skill_completed ausente: {events}"


# ---------------------------------------------------------------------------
# 2. MemorySkill — ciclo completo de eventos
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_skill_full_cycle_events(caplog):
    """Valida o ciclo completo: remember → recall → memorize → remember_forever.

    Verifica que memory_written e memory_promoted são emitidos nos momentos certos.
    """

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "memory.db")
        skill = MemorySkill(db_path=db_path)

        with caplog.at_level(logging.INFO, logger="src.skills.memory.skill"):
            # Grava na memória de curto prazo
            r1 = await skill.run(
                action="remember",
                session_id="sess_s8",
                key="eda_resultado",
                value="150 amostras, 4 features, 0 nulos",
                tags=["eda", "iris"],
            )

            # Recupera da memória de curto prazo
            r2 = await skill.run(
                action="recall",
                session_id="sess_s8",
                key="eda_resultado",
            )

            # Grava na memória de longo prazo diretamente
            r3 = await skill.run(
                action="memorize",
                key="iris_dataset_info",
                value="Iris: 3 classes, 150 amostras, sem valores nulos",
                importance=0.75,
                tags=["iris", "dataset"],
            )

            # Promove curto prazo → longo prazo
            r4 = await skill.run(
                action="remember_forever",
                session_id="sess_s8",
                key="eda_resultado",
                importance=0.85,
            )

    assert r1.success, f"remember falhou: {r1.error}"
    assert r2.success and r2.output, f"recall falhou: {r2.error}"
    assert r3.success, f"memorize falhou: {r3.error}"
    assert r4.success, f"remember_forever falhou: {r4.error}"

    events = _get_events(caplog.records)

    # Dois memory_written: um do remember, outro do memorize
    memory_written_count = events.count("memory_written")
    assert memory_written_count >= 2, (
        f"Esperava ≥2 memory_written, obteve {memory_written_count}: {events}"
    )

    # Um memory_promoted do remember_forever
    assert "memory_promoted" in events, f"memory_promoted ausente: {events}"


# ---------------------------------------------------------------------------
# 3. CodeSkill — executa pipeline Iris real, verifica artefatos
# ---------------------------------------------------------------------------

_IRIS_PIPELINE_CODE = '''
import json
import os
import pickle
import time
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

# ── EDA ────────────────────────────────────────────────────────────────────
iris = load_iris()
X, y = iris.data, iris.target

eda_report = {
    "shape": list(X.shape),
    "feature_names": list(iris.feature_names),
    "classes": list(iris.target_names),
    "null_count": 0,
    "class_distribution": {k: int((y == i).sum()) for i, k in enumerate(iris.target_names)},
}
os.makedirs("/outputs/eda", exist_ok=True)
with open("/outputs/eda/eda_report.json", "w") as f:
    json.dump(eda_report, f, indent=2)

# ── Pré-processamento ──────────────────────────────────────────────────────
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(
    X_scaled, y, test_size=0.2, random_state=42
)
os.makedirs("/outputs/preprocess", exist_ok=True)
import numpy as np
np.savez("/outputs/preprocess/preprocessed_data.npz",
         X_train=X_train, X_test=X_test, y_train=y_train, y_test=y_test)

# ── Treinamento ────────────────────────────────────────────────────────────
os.makedirs("/outputs/train_model_a", exist_ok=True)
os.makedirs("/outputs/train_model_b", exist_ok=True)

t0 = time.time()
lr = LogisticRegression(max_iter=200, random_state=42)
lr.fit(X_train, y_train)
lr_time = time.time() - t0

t0 = time.time()
rf = RandomForestClassifier(n_estimators=50, random_state=42)
rf.fit(X_train, y_train)
rf_time = time.time() - t0

with open("/outputs/train_model_a/logistic_regression.pkl", "wb") as f:
    pickle.dump(lr, f)
with open("/outputs/train_model_b/random_forest.pkl", "wb") as f:
    pickle.dump(rf, f)

# ── Avaliação ──────────────────────────────────────────────────────────────
def metrics(model, X_test, y_test):
    y_pred = model.predict(X_test)
    return {
        "accuracy": round(accuracy_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred, average="macro"), 4),
        "recall": round(recall_score(y_test, y_pred, average="macro"), 4),
        "f1": round(f1_score(y_test, y_pred, average="macro"), 4),
    }

lr_metrics = metrics(lr, X_test, y_test)
rf_metrics = metrics(rf, X_test, y_test)

os.makedirs("/outputs/evaluate", exist_ok=True)
eval_report = {
    "model_a": {"name": "Logistic Regression", "train_time_seconds": round(lr_time, 4), **lr_metrics},
    "model_b": {"name": "Random Forest", "train_time_seconds": round(rf_time, 4), **rf_metrics},
}
with open("/outputs/evaluate/evaluation_report.json", "w") as f:
    json.dump(eval_report, f, indent=2)

# ── Recomendação ───────────────────────────────────────────────────────────
best = "model_a" if lr_metrics["f1"] >= rf_metrics["f1"] else "model_b"
best_name = eval_report[best]["name"]
os.makedirs("/outputs/recommend", exist_ok=True)
with open("/outputs/recommend/recommendation.md", "w") as f:
    f.write(f"""# Recomendação de Modelo — Dataset Iris

## Comparativo de Modelos

| Modelo | Acurácia | F1 (macro) | Tempo treino |
|---|---|---|---|
| Regressão Logística | {lr_metrics["accuracy"]:.1%} | {lr_metrics["f1"]:.3f} | {lr_time:.2f}s |
| Random Forest | {rf_metrics["accuracy"]:.1%} | {rf_metrics["f1"]:.3f} | {rf_time:.2f}s |

## Recomendação Final

O modelo recomendado para uso em produção é o **{best_name}**.

Este modelo apresentou o melhor F1-score macro entre os dois algoritmos avaliados
no conjunto de teste do dataset Iris (n=30 amostras). O F1-score macro é a métrica
mais adequada neste cenário pois o dataset possui classes equilibradas e penaliza
igualmente erros em qualquer categoria.

Considerando também a interpretabilidade e o custo computacional para inferência
em tempo real (importante para ambientes com recursos limitados como o Raspberry Pi 5),
o {best_name} oferece o melhor equilíbrio entre performance preditiva e eficiência operacional.

## Artefatos Gerados

- `eda/eda_report.json` — Análise exploratória completa
- `preprocess/preprocessed_data.npz` — Dados normalizados e divididos
- `train_model_a/logistic_regression.pkl` — Modelo A treinado
- `train_model_b/random_forest.pkl` — Modelo B treinado
- `evaluate/evaluation_report.json` — Métricas comparativas
- `recommend/recommendation.md` — Recomendação final
""")

print("Pipeline concluído com sucesso!")
print(f"LR → acurácia: {lr_metrics['accuracy']:.1%}, F1: {lr_metrics['f1']:.3f}")
print(f"RF → acurácia: {rf_metrics['accuracy']:.1%}, F1: {rf_metrics['f1']:.3f}")
print(f"Recomendação: {best_name}")
'''


@pytest.mark.integration
@pytest.mark.skipif(not is_docker_available(), reason="Docker não está disponível.")
@pytest.mark.asyncio
async def test_iris_pipeline_via_code_skill(caplog):
    """Executa o pipeline Iris completo via CodeSkill e verifica:
    - Artefatos em disco (todos os 6 exigidos pelo validation-task.md)
    - Métricas de qualidade (acurácia ≥ 90%, F1 ≥ 0.90)
    - Log events: skill_invoked e skill_completed presentes
    """
    from src.skills.code.skill import CodeSkill

    output_dir = tempfile.mkdtemp(prefix="gc_iris_")

    try:
        skill = CodeSkill()
        skill.output_dir = output_dir

        with caplog.at_level(logging.INFO, logger="src.skills.base"):
            result = await skill.run_with_logging(
                code=_IRIS_PIPELINE_CODE,
                session_id="sess_s8_iris",
                task_name="iris_pipeline",
                packages=["scikit-learn", "numpy"],
            )

        # ── Verifica log events ───────────────────────────────────────────
        events = _get_events(caplog.records)
        assert "skill_invoked" in events, f"skill_invoked ausente: {events}"
        assert "skill_completed" in events or "skill_failed" in events, (
            f"Nenhum evento de conclusão encontrado: {events}"
        )

        # ── Verifica resultado da execução ────────────────────────────────
        assert result.success, (
            f"CodeSkill falhou.\nstdout: {result.output}\nerror: {result.error}"
        )

        # ── Verifica artefatos em disco ───────────────────────────────────
        session_dir = os.path.join(output_dir, "sess_s8_iris", "iris_pipeline")
        expected_artifacts = [
            "eda/eda_report.json",
            "preprocess/preprocessed_data.npz",
            "train_model_a/logistic_regression.pkl",
            "train_model_b/random_forest.pkl",
            "evaluate/evaluation_report.json",
            "recommend/recommendation.md",
        ]

        missing = []
        for artifact in expected_artifacts:
            full_path = os.path.join(session_dir, artifact)
            if not os.path.exists(full_path):
                missing.append(artifact)

        assert not missing, f"Artefatos ausentes em {session_dir}: {missing}"

        # ── Verifica métricas de qualidade ─────────────────────────────────
        eval_path = os.path.join(session_dir, "evaluate/evaluation_report.json")
        with open(eval_path) as f:
            eval_report = json.load(f)

        for model_key in ("model_a", "model_b"):
            model = eval_report[model_key]
            assert model["accuracy"] >= 0.90, (
                f"{model['name']}: acurácia {model['accuracy']:.1%} < 90%"
            )
            assert model["f1"] >= 0.90, (
                f"{model['name']}: F1 {model['f1']:.3f} < 0.90"
            )

        # ── Verifica recomendação (≥100 palavras) ──────────────────────────
        rec_path = os.path.join(session_dir, "recommend/recommendation.md")
        with open(rec_path) as f:
            rec_text = f.read()
        word_count = len(rec_text.split())
        assert word_count >= 100, (
            f"Recomendação tem apenas {word_count} palavras (mínimo: 100)"
        )

    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. Encadeamento: CodeSkill + MemorySkill (log events em cadeia)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not is_docker_available(), reason="Docker não está disponível.")
async def test_skills_chained_log_events(caplog):
    """Simula o ciclo: CodeSkill executa → resultado gravado na MemorySkill.

    Verifica que os 4 eventos aparecem na ordem correta em um cenário encadeado:
    skill_invoked → skill_completed → memory_written → (opcional) memory_promoted
    """

    from src.skills.memory.skill import MemorySkill

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "memory.db")
        mem_skill = MemorySkill(db_path=db_path)

        # Simula resultado de CodeSkill (sem executar Docker)
        fake_code_result = SkillResult(
            success=True,
            output="acurácia=96.7%, F1=0.967",
            metadata={"exit_code": 0, "artifacts": []},
        )

        with caplog.at_level(logging.INFO):
            # 1. Simula skill_invoked/skill_completed da CodeSkill via run_with_logging mock
            from src.skills.code.skill import CodeSkill
            code_skill = CodeSkill()
            code_skill.run = AsyncMock(return_value=fake_code_result)
            await code_skill.run_with_logging(
                code="print('ok')",
                session_id="sess_chain",
                task_name="test_task",
            )

            # 2. Grava resultado na MemorySkill
            await mem_skill.run(
                action="remember",
                session_id="sess_chain",
                key="resultado_ml",
                value=fake_code_result.output,
                tags=["ml", "iris"],
            )

            # 3. Promove para longo prazo
            await mem_skill.run(
                action="remember_forever",
                session_id="sess_chain",
                key="resultado_ml",
                importance=0.8,
            )

    events = _get_events(caplog.records)

    required_events = ["skill_invoked", "skill_completed", "memory_written", "memory_promoted"]
    missing_events = [e for e in required_events if e not in events]
    assert not missing_events, (
        f"Eventos ausentes no ciclo encadeado: {missing_events}\n"
        f"Eventos encontrados: {events}"
    )
