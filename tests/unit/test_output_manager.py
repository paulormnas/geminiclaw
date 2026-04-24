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
    assert str(tmp_output_dir) in str(path)

def test_get_task_dir(manager):
    session_id = "session-456"
    task_name = "Minha Tarefa / de Teste"
    
    task_dir = manager.get_task_dir(session_id, task_name)
    
    assert task_dir.exists()
    # Verifica estrutura de subpastas (Etapa 1)
    assert (task_dir / "artifacts").exists()
    
    # Verifica sanitização básica (espaços e barras)
    assert "Minha_Tarefa___de_Teste" in str(task_dir)

def test_list_artifacts(manager):
    session_id = "session-789"
    task_1 = "task1"
    task_2 = "task2"
    
    dir1 = manager.get_task_dir(session_id, task_1)
    dir2 = manager.get_task_dir(session_id, task_2)
    
    (dir1 / "file1.txt").write_text("conteudo 1")
    (dir2 / "file2.json").write_text('{"key": "value"}')
    (dir1 / "subdir").mkdir()
    (dir1 / "subdir" / "file3.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    
    artifacts = manager.list_artifacts(session_id)
    
    assert len(artifacts) == 3
    
    # Verifica um artefato específico
    file1 = next(a for a in artifacts if a["name"] == "file1.txt")
    assert file1["task"] == "task1"
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
