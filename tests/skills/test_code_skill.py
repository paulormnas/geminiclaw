import pytest
import os
import pathlib
from src.skills.code.skill import CodeSkill
from src.skills.code.sandbox import PythonSandbox

@pytest.mark.integration
@pytest.mark.asyncio
async def test_code_skill_basic_execution():
    """Testa execução básica de código Python."""
    skill = CodeSkill()
    code = "print('Hello from Sandbox')"
    result = await skill.run(
        code=code,
        session_id="test_session",
        task_name="test_basic"
    )
    
    assert result.success is True
    assert "Hello from Sandbox" in result.output
    assert result.metadata["exit_code"] == 0

@pytest.mark.integration
@pytest.mark.asyncio
async def test_code_skill_artifact_creation():
    """Testa criação de artefatos no sandbox."""
    skill = CodeSkill()
    code = (
        "import os\n"
        "with open('/outputs/test_file.txt', 'w') as f:\n"
        "    f.write('artifact content')\n"
        "print('File created')"
    )
    
    session_id = "test_session_artifacts"
    task_name = "test_artifact"
    
    result = await skill.run(
        code=code,
        session_id=session_id,
        task_name=task_name
    )
    
    assert result.success is True
    assert "test_file.txt" in result.metadata["artifacts"]
    
    # Verificar se o arquivo existe no host
    output_base = os.getenv("OUTPUTS_DIR", "outputs")
    host_path = pathlib.Path(output_base) / session_id / task_name / "test_file.txt"
    assert host_path.exists()
    assert host_path.read_text() == "artifact content"

@pytest.mark.unit
def test_code_skill_security_validation():
    """Testa a validação de segurança contra padrões proibidos."""
    from unittest.mock import patch
    with patch("docker.from_env"):
        skill = CodeSkill()
    
    dangerous_codes = [
        "import os; os.system('ls')",
        "import subprocess; subprocess.run(['ls'])",
        "open('/etc/passwd', 'r')",
        "__import__('os').system('whoami')"
    ]
    
    for code in dangerous_codes:
        error = skill._validate_code(code)
        assert error is not None
        assert "proibido" in error.lower()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_code_skill_package_installation():
    """Testa instalação de pacotes (requer rede no Docker)."""
    # Nota: Este teste pode demorar e requer acesso à internet do daemon Docker
    skill = CodeSkill()
    code = "import itsdangerous; print('Import success')"
    
    # Primeiro tenta sem o pacote (deve falhar se não estiver na imagem base)
    result_fail = await skill.run(
        code=code,
        session_id="test_session_pkg",
        task_name="test_pkg_fail"
    )
    # python:slim não deve ter itsdangerous
    assert result_fail.success is False 
    
    # Agora tenta com instalação do pacote
    result_success = await skill.run(
        code=code,
        session_id="test_session_pkg",
        task_name="test_pkg_success",
        packages=["itsdangerous"]
    )
    
    assert result_success.success is True
    assert "Import success" in result_success.output
