"""Testes unitários para WorkspaceManifest — V13.3.4.

Cenários:
    1. Criação de manifest em diretório novo.
    2. record_step com sucesso atualiza artifacts_available e steps.
    3. record_step com falha registra error_type e error_message.
    4. Crash durante escrita não corrompe o manifest anterior (atomicidade).
    5. get_last_error() retorna o erro do step mais recente com status "failed".
"""
import json
import pathlib
import pytest

from src.skills.code.manifest import WorkspaceManifest


# ---------------------------------------------------------------------------
# Cenário 1 — Criação de manifest em diretório novo
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_manifest_created_in_new_directory(tmp_path: pathlib.Path) -> None:
    """O manifest.json deve ser criado automaticamente no __init__."""
    session_dir = tmp_path / "outputs" / "sess_001"
    manifest = WorkspaceManifest(
        session_dir=session_dir,
        session_id="sess_001",
        task_name="eda_iris",
    )

    manifest_path = session_dir / "manifest.json"
    assert manifest_path.exists(), "manifest.json deve existir após __init__"

    data = json.loads(manifest_path.read_text())
    assert data["session_id"] == "sess_001"
    assert data["task_name"] == "eda_iris"
    assert data["steps"] == []
    assert data["artifacts_available"] == []
    assert "created_at" in data
    assert "last_updated" in data


# ---------------------------------------------------------------------------
# Cenário 2 — record_step com sucesso atualiza artifacts_available e steps
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_record_step_success_updates_manifest(tmp_path: pathlib.Path) -> None:
    """Um step de sucesso deve atualizar steps e artifacts_available."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_ok",
        task_name="task_ok",
    )

    manifest.record_step(
        step=1,
        status="success",
        artifacts=["iris.csv", "boxplot.png"],
        summary="Dataset carregado e gráficos gerados.",
        code_file="step_01.py",
    )

    data = manifest.read()
    assert len(data["steps"]) == 1
    step = data["steps"][0]
    assert step["step"] == 1
    assert step["status"] == "success"
    assert step["artifacts_created"] == ["iris.csv", "boxplot.png"]
    assert step["code_file"] == "step_01.py"
    assert "timestamp" in step

    # artifacts_available deve incluir os artefatos + o code_file
    available = data["artifacts_available"]
    assert "iris.csv" in available
    assert "boxplot.png" in available
    assert "step_01.py" in available

    # get_artifacts_available deve retornar o mesmo
    assert set(manifest.get_artifacts_available()) == set(available)
    assert manifest.get_step_count() == 1


@pytest.mark.unit
def test_record_multiple_steps_accumulates_artifacts(tmp_path: pathlib.Path) -> None:
    """Múltiplos steps acumulam os artefatos em artifacts_available."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_multi",
        task_name="task_multi",
    )

    manifest.record_step(1, "success", ["a.csv"], "step 1", code_file="step_01.py")
    manifest.record_step(2, "success", ["b.png"], "step 2", code_file="step_02.py")

    available = manifest.get_artifacts_available()
    assert "a.csv" in available
    assert "b.png" in available
    assert "step_01.py" in available
    assert "step_02.py" in available
    assert manifest.get_step_count() == 2


# ---------------------------------------------------------------------------
# Cenário 3 — record_step com falha registra error_type e error_message
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_record_step_failure_stores_error_info(tmp_path: pathlib.Path) -> None:
    """Um step de falha deve registrar error_type, error_message e error_location."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_fail",
        task_name="task_fail",
    )

    error = {
        "error_type": "AttributeError",
        "error_message": "'tuple' object has no attribute 'items'",
        "error_location": "step_02.py, linha 258",
    }
    manifest.record_step(
        step=2,
        status="failed",
        artifacts=["step_02.py"],
        summary="Script falhou com AttributeError.",
        error=error,
        code_file="step_02.py",
    )

    data = manifest.read()
    step = data["steps"][0]
    assert step["status"] == "failed"
    assert step["error_type"] == "AttributeError"
    assert step["error_message"] == "'tuple' object has no attribute 'items'"
    assert step["error_location"] == "step_02.py, linha 258"


@pytest.mark.unit
def test_record_step_invalid_status_raises(tmp_path: pathlib.Path) -> None:
    """status inválido deve levantar ValueError."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_bad",
        task_name="task_bad",
    )
    with pytest.raises(ValueError, match="status deve ser"):
        manifest.record_step(1, "unknown", [], "summary")


# ---------------------------------------------------------------------------
# Cenário 4 — Atomicidade: crash durante escrita não corrompe manifest anterior
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_atomic_write_does_not_corrupt_on_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Se a escrita falhar após criar o tmp, o manifest original permanece intacto."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_atomic",
        task_name="task_atomic",
    )

    # Registrar um step bem-sucedido para termos um manifest válido
    manifest.record_step(1, "success", ["good_file.csv"], "Step bom.")
    original_data = manifest.read()

    # Simular falha no os.replace (após escrever tmp)
    import os as _os

    original_replace = _os.replace

    def broken_replace(src, dst):
        # Remove o tmp para simular falha de I/O
        try:
            _os.unlink(src)
        except OSError:
            pass
        raise OSError("Disco cheio simulado")

    monkeypatch.setattr("src.skills.code.manifest.os.replace", broken_replace)

    with pytest.raises(OSError, match="Disco cheio simulado"):
        manifest.record_step(2, "success", ["new_file.csv"], "Step que vai falhar.")

    # O manifest original deve estar inalterado
    after_data = manifest.read()
    assert after_data["steps"] == original_data["steps"]
    assert len(after_data["steps"]) == 1
    assert after_data["steps"][0]["artifacts_created"] == ["good_file.csv"]


# ---------------------------------------------------------------------------
# Cenário 5 — get_last_error() retorna erro do step mais recente com "failed"
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_get_last_error_returns_most_recent_failed(tmp_path: pathlib.Path) -> None:
    """get_last_error deve retornar o erro do último step quando ele é failed."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_last_err",
        task_name="task_last_err",
    )

    # Step 1: sucesso
    manifest.record_step(1, "success", ["data.csv"], "Carregou dados.")

    # Nenhum erro ainda (ultimo step é success)
    assert manifest.get_last_error() is None

    # Step 2: falha
    manifest.record_step(
        2,
        "failed",
        [],
        "Falhou.",
        error={
            "error_type": "KeyError",
            "error_message": "'species'",
            "error_location": "step_02.py, linha 42",
        },
    )

    # Step 3: outra falha (mais recente, é o último step)
    manifest.record_step(
        3,
        "failed",
        [],
        "Falhou de novo.",
        error={
            "error_type": "ValueError",
            "error_message": "invalid literal for int()",
            "error_location": "step_03.py, linha 10",
        },
    )

    last_error = manifest.get_last_error()
    assert last_error is not None
    # Deve ser o erro do step 3 (mais recente = último step)
    assert last_error["error_type"] == "ValueError"
    assert last_error["error_message"] == "invalid literal for int()"
    assert last_error["error_location"] == "step_03.py, linha 10"


@pytest.mark.unit
def test_get_last_error_returns_none_when_last_step_is_success(
    tmp_path: pathlib.Path,
) -> None:
    """get_last_error deve retornar None quando o último step é success,
    mesmo que haja steps failed anteriores."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_skip_ok",
        task_name="task_skip_ok",
    )

    manifest.record_step(
        1,
        "failed",
        [],
        "Primeiro erro.",
        error={
            "error_type": "ImportError",
            "error_message": "No module named 'pandas'",
            "error_location": "step_01.py, linha 1",
        },
    )
    # Step 2: sucesso — o último step não é failed
    manifest.record_step(2, "success", ["result.csv"], "Corrigido e executado.")

    # get_last_error deve retornar None porque o último step é success
    assert manifest.get_last_error() is None


# ---------------------------------------------------------------------------
# Cenário extra — update_next_hint persiste no manifest
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_update_next_hint_persists(tmp_path: pathlib.Path) -> None:
    """update_next_hint deve atualizar apenas o campo next_step_hint."""
    manifest = WorkspaceManifest(
        session_dir=tmp_path / "sess",
        session_id="sess_hint",
        task_name="task_hint",
    )

    hint = "Corrigir linha 258: substituir .items() por enumerate()."
    manifest.update_next_hint(hint)

    data = manifest.read()
    assert data["next_step_hint"] == hint
