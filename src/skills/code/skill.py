import os
import re
from typing import List, Optional
from src.skills.base import BaseSkill, SkillResult
from src.skills.code.sandbox import PythonSandbox, SandboxResult
from src.logger import get_logger

logger = get_logger(__name__)

class CodeSkill(BaseSkill):
    """Skill para execução de código Python em sandbox seguro."""
    
    name = "python_interpreter"
    description = (
        "Use esta skill para executar código Python e realizar análise de dados. Forneça o código completo como string. "
        "Você PODE instalar novos pacotes via parâmetro 'packages' (recomendado) ou usando 'subprocess' no código. "
        "Todo arquivo salvo em '/outputs/' estará disponível como artefato."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "O código Python a ser executado."
            },
            "session_id": {
                "type": "string",
                "description": "ID da sessão atual (obrigatório para isolamento)."
            },
            "task_name": {
                "type": "string",
                "description": "Nome da tarefa atual (usado para subdiretórios de output)."
            },
            "packages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de pacotes pip adicionais para instalar."
            }
        },
        "required": ["code", "session_id", "task_name"]
    }

    def __init__(self):
        # Carregar configurações do ambiente
        timeout = int(os.getenv("CODE_SANDBOX_TIMEOUT_SECONDS", "60"))
        memory = os.getenv("CODE_SANDBOX_MEMORY_LIMIT", "256m")
        self.output_dir = os.getenv("OUTPUT_BASE_DIR", "/outputs")
        
        self.sandbox = PythonSandbox(
            timeout=timeout,
            memory_limit=memory
        )
        
        # Expressões regulares para proibição de código malicioso simples
        self.forbidden_patterns = [
            r"os\.system",
            r"subprocess\.",
            r"getattr\(os",
            r"__import__\(['\"]os['\"]\)",
            r"open\(['\"]/etc/",
            r"open\(['\"]/root/",
            r"shutil\.",
        ]

    def _validate_code(self, code: str) -> Optional[str]:
        """Valida o código contra padrões proibidos.
        
        Returns:
            Mensagem de erro se inválido, None se válido.
        """
        for pattern in self.forbidden_patterns:
            if re.search(pattern, code):
                return f"Código contém padrão proibido: {pattern}"
        return None

    async def run(
        self, 
        code: str, 
        session_id: str, 
        task_name: str, 
        packages: Optional[List[str]] = None,
        **kwargs
    ) -> SkillResult:
        """Executa o código Python.

        Args:
            code: Script Python.
            session_id: ID da sessão atual.
            task_name: Nome da tarefa atual.
            packages: Lista de pacotes para instalar via pip.

        Returns:
            SkillResult com a saída da execução.
        """
        # 1. Validar código
        validation_error = self._validate_code(code)
        if validation_error:
            logger.warning(f"Execução bloqueada: {validation_error}")
            return SkillResult(
                success=False,
                output="",
                error=validation_error
            )

        # 2. Preparar comandos de setup
        setup_commands = []
        if packages:
            # Filtrar pacotes built-in ou inválidos (ex: json)
            builtin_packages = ["json", "os", "sys", "re", "math", "time", "io", "pathlib", "pickle"]
            filtered_packages = [p for p in packages if p not in builtin_packages]
            
            if filtered_packages:
                # Usando uv para instalação ultra-rápida (requer uv na imagem base)
                setup_commands.append(["uv", "pip", "install", "--no-cache-dir"] + filtered_packages)

        # 3. Executar no sandbox
        try:
            # Nota: PythonSandbox.run não é async pois usa docker-py síncrono.
            # Em um cenário real, poderíamos usar um wrapper async ou threads.
            result: SandboxResult = self.sandbox.run(
                code=code,
                session_id=session_id,
                task_name=task_name,
                output_dir=self.output_dir,
                setup_commands=setup_commands
            )

            if result.timed_out:
                return SkillResult(
                    success=False,
                    output=result.stdout,
                    error="Timeout atingido durante a execução.",
                    metadata={"exit_code": result.exit_code, "timed_out": True}
                )

            success = result.exit_code == 0
            return SkillResult(
                success=success,
                output=result.stdout,
                error=result.stderr if not success else None,
                metadata={
                    "exit_code": result.exit_code,
                    "artifacts": result.artifacts
                }
            )

        except Exception as e:
            logger.error(f"Erro na CodeSkill: {str(e)}")
            return SkillResult(
                success=False,
                output="",
                error=f"Erro ao executar código: {str(e)}"
            )
