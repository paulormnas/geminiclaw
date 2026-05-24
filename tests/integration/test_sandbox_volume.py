import os
import pytest
import docker
import pathlib
from src.skills.code.sandbox import PythonSandbox

def _geminiclaw_image_exists() -> bool:
    """Verifica se a imagem geminiclaw-base está disponível localmente."""
    import subprocess
    try:
        result = subprocess.run(["docker", "images", "-q", "geminiclaw-base:latest"], check=True, capture_output=True, text=True, timeout=2)
        return bool(result.stdout.strip())
    except Exception:
        return False

_SKIP_NO_IMAGE = pytest.mark.skipif(
    not _geminiclaw_image_exists(),
    reason=(
        "Imagem 'geminiclaw-base' não encontrada. "
        "Execute 'docker build -t geminiclaw-base -f containers/Dockerfile .' antes de rodar estes testes."
    ),
)

@_SKIP_NO_IMAGE
@pytest.mark.integration
def test_sandbox_volume_cross_tool_call(tmp_path):
    # Cenário 1: Arquivo criado na tool call 1 é listado por os.listdir('/outputs/') na tool call 2 com o mesmo session_id e task_name.
    sandbox = PythonSandbox()
    session_id = "sess_integration_test_1"
    task_name = "task_integration_test_1"
    output_dir = tmp_path / "outputs"
    
    # Tool call 1: cria um arquivo em /outputs/
    code_1 = """
with open('/outputs/shared_file.txt', 'w') as f:
    f.write('hello from tool call 1')
"""
    result_1 = sandbox.run(
        code=code_1,
        session_id=session_id,
        task_name=task_name,
        output_dir=str(output_dir)
    )
    assert result_1.exit_code == 0
    assert "shared_file.txt" in result_1.artifacts
    
    # Tool call 2: lista os arquivos em /outputs/ e verifica se o arquivo está lá
    code_2 = """
import os
files = os.listdir('/outputs/')
print("FILES:", files)
with open('/outputs/shared_file.txt', 'r') as f:
    print("CONTENT:", f.read())
"""
    result_2 = sandbox.run(
        code=code_2,
        session_id=session_id,
        task_name=task_name,
        output_dir=str(output_dir)
    )
    assert result_2.exit_code == 0
    assert "shared_file.txt" in result_2.stdout
    assert "hello from tool call 1" in result_2.stdout

@_SKIP_NO_IMAGE
@pytest.mark.integration
def test_sandbox_volume_isolation_different_sessions(tmp_path):
    # Cenário 2: Tool calls com session_id diferentes não compartilham diretório.
    sandbox = PythonSandbox()
    task_name = "task_integration_test_2"
    output_dir = tmp_path / "outputs"
    
    # Session A: cria arquivo
    result_a = sandbox.run(
        code="with open('/outputs/secret_a.txt', 'w') as f: f.write('secret')",
        session_id="session_a",
        task_name=task_name,
        output_dir=str(output_dir)
    )
    assert result_a.exit_code == 0
    
    # Session B: tenta listar (não deve ver o arquivo da Session A)
    result_b = sandbox.run(
        code="import os; print(os.listdir('/outputs/'))",
        session_id="session_b",
        task_name=task_name,
        output_dir=str(output_dir)
    )
    assert result_b.exit_code == 0
    assert "secret_a.txt" not in result_b.stdout

@_SKIP_NO_IMAGE
@pytest.mark.integration
def test_sandbox_volume_persistence_on_host(tmp_path):
    # Cenário 3: Container do sandbox encerra mas arquivo persiste no host.
    sandbox = PythonSandbox()
    session_id = "sess_persistence"
    task_name = "task_persistence"
    output_dir = tmp_path / "outputs"
    
    result = sandbox.run(
        code="with open('/outputs/persistent_file.txt', 'w') as f: f.write('persistent data')",
        session_id=session_id,
        task_name=task_name,
        output_dir=str(output_dir)
    )
    assert result.exit_code == 0
    
    # Verifica que o arquivo existe localmente no host no caminho esperado
    host_file = output_dir / session_id / task_name / "persistent_file.txt"
    assert host_file.exists()
    assert host_file.read_text() == "persistent data"
