import pytest
import os
import shutil
from pathlib import Path
from src.output_manager import OutputManager

@pytest.fixture
def tmp_output_dir(tmp_path):
    """Cria um diretório temporário para outputs de teste."""
    d = tmp_path / "outputs"
    d.mkdir()
    return d

@pytest.fixture
def manager(tmp_output_dir):
    """Retorna uma instância de OutputManager apontando para o diretório temporário."""
    return OutputManager(base_dir=str(tmp_output_dir))

def test_init_session(manager, tmp_output_dir):
    session_id = "test-session-123"
    path = manager.init_session(session_id)
    
    assert path.exists()
    assert path.is_dir()
    assert path.name == session_id
    assert (path / "artifacts").exists()
    assert (path / "logs").exists()
    assert str(tmp_output_dir) in str(path)

def test_get_artifacts_dir(manager):
    session_id = "session-456"
    art_dir = manager.get_artifacts_dir(session_id)
    assert art_dir.exists()
    assert art_dir.name == "artifacts"
    assert art_dir.parent.name == session_id

def test_get_logs_dir(manager):
    session_id = "session-456"
    log_dir = manager.get_logs_dir(session_id)
    assert log_dir.exists()
    assert log_dir.name == "logs"
    assert log_dir.parent.name == session_id

def test_list_artifacts(manager):
    session_id = "session-789"
    art_dir = manager.get_artifacts_dir(session_id)
    
    (art_dir / "file1.txt").write_text("conteudo 1")
    (art_dir / "file2.json").write_text('{"key": "value"}')
    (art_dir / "subdir").mkdir()
    (art_dir / "subdir" / "file3.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    
    artifacts = manager.list_artifacts(session_id)
    
    # Deve listar recursivamente (3 arquivos)
    assert len(artifacts) == 3
    
    # Verifica um artefato específico
    file1 = next(a for a in artifacts if a["name"] == "file1.txt")
    assert file1["type"] == "txt"
    assert file1["size"] == 10
    assert os.path.exists(file1["path"])

def test_cleanup_session(manager):
    session_id = "to-be-deleted"
    manager.init_session(session_id)
    session_path = manager.base_dir / session_id
    
    assert session_path.exists()
    
    manager.cleanup_session(session_id)
    
    assert not session_path.exists()

def test_list_artifacts_empty_session(manager):
    artifacts = manager.list_artifacts("non-existent")
    assert artifacts == []
