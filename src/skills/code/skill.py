import asyncio
import json
import os
import pathlib
import re
import time
from typing import List, Optional
from src.skills.base import BaseSkill, SkillResult
from src.skills.code.sandbox import PythonSandbox, SandboxResult
from src.skills.code.manifest import WorkspaceManifest
from src.logger import get_logger

logger = get_logger(__name__)

# Roadmap V15.2 / Spec G2 — bibliotecas cuja presença no código indica um script
# científico/de dados, para o qual scientific_helpers.py é injetado automaticamente.
_SCIENTIFIC_LIBRARY_MARKERS = ("numpy", "pandas", "sklearn")

_SCIENTIFIC_HELPERS_PATH = pathlib.Path(__file__).parent / "scientific_helpers.py"


def _uses_scientific_libraries(code: str) -> bool:
    """Detecta se o código importa bibliotecas científicas/de dados (Spec G2)."""
    return any(marker in code for marker in _SCIENTIFIC_LIBRARY_MARKERS)


def _load_scientific_helpers_source() -> str:
    """Lê o código-fonte de scientific_helpers.py para injeção no sandbox."""
    return _SCIENTIFIC_HELPERS_PATH.read_text(encoding="utf-8")

class CodeSkill(BaseSkill):
    """Skill para execução de código Python em sandbox seguro."""
    
    name = "python_interpreter"
    description = (
        "Use esta skill para executar código Python e realizar análise de dados. Forneça o código completo como string. "
        "Para instalar pacotes adicionais, use EXCLUSIVAMENTE o parâmetro 'packages' — "
        "instalação via 'subprocess'/'pip' dentro do código não é suportada (a instalação de "
        "pacotes acontece no próprio sandbox, fora do código gerado). "
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
        setup_timeout = int(os.getenv("CODE_SANDBOX_SETUP_TIMEOUT_SECONDS", "300"))
        self.output_dir = os.getenv("OUTPUT_BASE_DIR", "/outputs")
        
        self.sandbox = PythonSandbox(
            timeout=timeout,
            memory_limit=memory,
            setup_timeout=setup_timeout,
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

    @staticmethod
    def _record_sandbox_run(session_id: str, task_name: str, result: SandboxResult, duration_ms: int) -> None:
        """Emite o evento ``sandbox_run`` (sem o conteúdo do script) para o relatório e a avaliação."""
        try:
            from src.agent_runtime.context import get_agent_context_optional
            from src.telemetry import get_telemetry

            ctx = get_agent_context_optional()
            get_telemetry().record_agent_event(
                execution_id=(ctx.execution_id if ctx is not None and ctx.execution_id else session_id),
                session_id=session_id,
                agent_id=ctx.agent_id if ctx is not None else "code",
                event_type="sandbox_run",
                task_name=task_name or None,
                payload={
                    "task_name": task_name,
                    "exit_code": result.exit_code,
                    "duration_ms": duration_ms,
                    "timed_out": bool(result.timed_out),
                },
            )
        except Exception as exc:  # observabilidade nunca derruba a execução
            logger.warning("Falha ao registrar sandbox_run", extra={"error": str(exc)})

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

        # Garantir que o diretório da sessão existe antes de rodar o sandbox (V13.2.2)
        session_dir = pathlib.Path(self.output_dir).resolve() / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # V13.3 — Inicializar manifest da sessão
        manifest = WorkspaceManifest(
            session_dir=session_dir,
            session_id=session_id,
            task_name=task_name,
        )

        # V13.3.3 — Salvar snapshot do código antes de executar
        step_number = manifest.get_step_count() + 1
        code_filename = f"step_{step_number:02d}.py"
        code_snapshot_path = session_dir / code_filename
        try:
            code_snapshot_path.write_text(code, encoding="utf-8")
            logger.info(
                f"Snapshot do código salvo: {code_filename}",
                extra={"session_id": session_id, "step": step_number},
            )
        except OSError as e:
            logger.warning(f"Não foi possível salvar snapshot do código: {e}")
            code_filename = None  # type: ignore[assignment]

        # Artefatos antes da execução (para calcular novos artefatos depois)
        artifacts_before = set(manifest.get_artifacts_available())

        # 3. Executar no sandbox
        try:
            # Nota: PythonSandbox.run é síncrono; a chamada abaixo o executa em thread.
            # Roadmap V15.2 / Spec G2 — injeta scientific_helpers.py quando o código
            # usa bibliotecas científicas/de dados, permitindo save_experiment_artifacts().
            extra_files = None
            if _uses_scientific_libraries(code):
                extra_files = {"scientific_helpers.py": _load_scientific_helpers_source()}

            # O sandbox usa o SDK síncrono do daemon de containers e pode levar minutos
            # (instalação de pacotes + execução): rodar direto na corrotina congelaria o
            # orquestrador e os demais agentes do processo. Vai para uma thread para manter
            # o event loop livre.
            _started = time.monotonic()
            result: SandboxResult = await asyncio.to_thread(
                self.sandbox.run,
                code=code,
                session_id=session_id,
                task_name=task_name,
                output_dir=self.output_dir,
                setup_commands=setup_commands,
                extra_files=extra_files,
            )

            success = not result.timed_out and result.exit_code == 0
            self._record_sandbox_run(session_id, task_name, result, int((time.monotonic() - _started) * 1000))

            # V13.3.2 — Detectar novos artefatos e atualizar manifest
            new_artifacts = [
                a for a in result.artifacts
                if a not in artifacts_before and not a.startswith("step_")
            ]

            if success:
                summary = (
                    f"Execução bem-sucedida. "
                    f"Artefatos gerados: {new_artifacts or 'nenhum'}."
                )

                # Roadmap V15.2 / Spec G2 — rastreia params.json/metrics.json no manifest
                params_path: Optional[str] = None
                metrics_path: Optional[str] = None
                seed_used = None
                divergence_detected: Optional[bool] = None
                task_output_dir = session_dir / task_name
                metrics_file = task_output_dir / "metrics.json"
                if metrics_file.exists():
                    metrics_path = str(metrics_file.relative_to(session_dir))
                    try:
                        metrics_data = json.loads(metrics_file.read_text(encoding="utf-8"))
                        seed_used = metrics_data.get("seed")
                        divergence_detected = metrics_data.get("divergence_note") is not None
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning(f"Falha ao ler metrics.json para o manifest: {e}")
                params_file = task_output_dir / "params.json"
                if params_file.exists():
                    params_path = str(params_file.relative_to(session_dir))

                manifest.record_step(
                    step=step_number,
                    status="success",
                    artifacts=new_artifacts,
                    summary=summary,
                    code_file=code_filename,
                    params_path=params_path,
                    metrics_path=metrics_path,
                    seed_used=seed_used,
                    divergence_detected=divergence_detected,
                )
            else:
                error_info = _extract_error_info(result.stderr)
                summary = (
                    f"Execução falhou. "
                    f"Erro: {error_info.get('error_type', 'desconhecido')}."
                )
                if result.timed_out:
                    summary = "Execução cancelada por timeout."
                    error_info = {
                        "error_type": "TimeoutError",
                        "error_message": "Timeout atingido durante a execução.",
                        "error_location": "",
                    }
                manifest.record_step(
                    step=step_number,
                    status="failed",
                    artifacts=new_artifacts,
                    summary=summary,
                    error=error_info,
                    code_file=code_filename,
                )

            if result.timed_out:
                return SkillResult(
                    success=False,
                    output=result.stdout,
                    error="Timeout atingido durante a execução.",
                    metadata={"exit_code": result.exit_code, "timed_out": True}
                )

            return SkillResult(
                success=success,
                output=result.stdout,
                error=result.stderr if not success else None,
                metadata={
                    "exit_code": result.exit_code,
                    "artifacts": result.artifacts,
                    "manifest_step": step_number,
                }
            )

        except Exception as e:
            logger.error(f"Erro na CodeSkill: {str(e)}")
            # Registrar falha no manifest mesmo em caso de exceção inesperada
            try:
                manifest.record_step(
                    step=step_number,
                    status="failed",
                    artifacts=[],
                    summary=f"Erro inesperado: {type(e).__name__}: {e}",
                    error={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "error_location": "",
                    },
                    code_file=code_filename,
                )
            except Exception:
                pass
            return SkillResult(
                success=False,
                output="",
                error=f"Erro ao executar código: {str(e)}"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ERROR_TYPE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*(Error|Exception|Warning)):\s*(.*)$", re.MULTILINE)
_ERROR_LOC_RE = re.compile(r'File "([^"]+)", line (\d+)')


def _extract_error_info(stderr: str) -> dict:
    """Extrai error_type, error_message e error_location do stderr.

    Args:
        stderr: Texto do stderr do container.

    Returns:
        Dicionário com as chaves ``error_type``, ``error_message`` e
        ``error_location``. Valores podem ser string vazia se não encontrados.
    """
    error_type = ""
    error_message = ""
    error_location = ""

    # Capturar todos os matches e usar o último (mais específico)
    type_matches = list(_ERROR_TYPE_RE.finditer(stderr))
    if type_matches:
        m = type_matches[-1]
        error_type = m.group(1)
        error_message = m.group(3).strip()

    loc_matches = list(_ERROR_LOC_RE.finditer(stderr))
    if loc_matches:
        m = loc_matches[-1]
        error_location = f"{m.group(1)}, linha {m.group(2)}"

    return {
        "error_type": error_type,
        "error_message": error_message,
        "error_location": error_location,
    }
