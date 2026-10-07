import asyncio
import json
import pathlib
import re
import time
from typing import List, Optional
from src import config
from src.config import get_env
from src.skills.base import BaseSkill, SkillResult
from src.reserved_files import is_reserved_name
from src.skills.code.sandbox import _SAFE_NAME_RE, NETWORK_UNDECLARED_MESSAGE, PythonSandbox, SandboxResult
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
        "A execução do código NÃO tem acesso à rede: não baixe nada no código. Pesos, corpora e datasets "
        "públicos são declarados no parâmetro 'assets' (url e, se souber, sha256) e lidos de "
        "'/assets/<destino>'. Os insumos do projeto ficam somente leitura em '/inputs/'. "
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
                "description": (
                    "Pacotes pip adicionais (requisitos PEP 508, ex.: 'tabulate' ou 'tabulate==0.9.0'). "
                    "Os do conjunto básico da imagem (numpy, pandas, scipy, matplotlib, scikit-learn, "
                    "seaborn) já estão disponíveis e não precisam ser pedidos."
                )
            },
            "assets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL http(s) pública do ativo."},
                        "sha256": {"type": "string", "description": "sha256 esperado (opcional, recomendado); sem ele a URL precisa ser https."},
                        "destino": {
                            "type": "string",
                            "description": "Nome simples do arquivo; o ativo fica em /assets/<destino>.",
                        },
                    },
                    "required": ["url", "destino"],
                },
                "description": (
                    "Pesos, corpora ou datasets públicos a baixar ANTES da execução (o código não tem rede)."
                ),
            },
            "needs_network": {
                "type": "boolean",
                "description": (
                    "Pede rede na execução. Só é atendido quando todas as entradas são compartilháveis e "
                    "nenhum dado produzido por execuções está visível; caso contrário roda sem rede. Padrão: false."
                ),
            },
        },
        "required": ["code", "session_id", "task_name"]
    }

    def __init__(self):
        # Configuração lida via src/config.py (a leitura acontece na criação da skill, para que
        # o ambiente ajustado antes dela — ex.: nos testes — valha). A imagem (SANDBOX_IMAGE)
        # e os demais limites SANDBOX_* são resolvidos pelo próprio PythonSandbox.
        timeout = int(get_env("CODE_SANDBOX_TIMEOUT_SECONDS", default=str(config.CODE_SANDBOX_TIMEOUT_SECONDS)))
        memory = get_env("CODE_SANDBOX_MEMORY_LIMIT", default=config.CODE_SANDBOX_MEMORY_LIMIT)
        setup_timeout = int(
            get_env(
                "SANDBOX_INSTALL_TIMEOUT_SECONDS",
                default=get_env(
                    "CODE_SANDBOX_SETUP_TIMEOUT_SECONDS", default=str(config.CODE_SANDBOX_SETUP_TIMEOUT_SECONDS)
                ),
            )
        )
        self.output_dir = get_env("OUTPUT_BASE_DIR", default=config.OUTPUT_BASE_DIR)

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

    @staticmethod
    def _run_info(result: SandboxResult) -> dict:
        """Saída estruturada do sandbox gravada no manifest (sem stdout/stderr nem código)."""
        return {
            "exit_code": result.exit_code,
            "oom_killed": bool(result.oom_killed),
            "exception_type": result.exception_type,
            "timed_out": bool(result.timed_out),
            "install_failed": bool(result.install_failed),
            "infra_error": result.infra_error,
            "imagem_sandbox": result.image or None,
            "pacotes": list(result.packages_installed)[:100],
            "fase_falha": result.fase_falha,
            "download_nao_declarado": bool(result.download_nao_declarado),
            "rede_na_execucao": bool(result.rede_na_execucao),
            "modo_entrega": result.modo_entrega,
        }

    @staticmethod
    def _phase_metadata(result: SandboxResult) -> dict:
        """Campos de fase e rede do resultado do sandbox, para o metadata do ``SkillResult``."""
        return {
            "fase_falha": result.fase_falha,
            "download_nao_declarado": bool(result.download_nao_declarado),
            "rede_na_execucao": bool(result.rede_na_execucao),
            "nota_rede": result.nota_rede,
        }

    @staticmethod
    def _readable_prior_dirs() -> List[pathlib.Path]:
        """Saídas de sessões anteriores da cadeia de continuidade (``AgentContext.readable_dirs``), se houver."""
        try:
            from src.agent_runtime.context import get_agent_context_optional

            ctx = get_agent_context_optional()
            return [pathlib.Path(d) for d in ctx.readable_dirs] if ctx is not None else []
        except Exception as exc:  # contexto indisponível: nenhuma sessão anterior é montada
            logger.warning("Falha ao ler as sessões anteriores do contexto", extra={"error": str(exc)})
            return []

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
        assets: Optional[List[dict]] = None,
        needs_network: bool = False,
        **kwargs
    ) -> SkillResult:
        """Executa o código Python.

        Args:
            code: Script Python.
            session_id: ID da sessão atual.
            task_name: Nome da tarefa atual.
            packages: Requisitos (PEP 508) de pacotes fora do conjunto básico da imagem do sandbox.
            assets: Ativos públicos a baixar antes da execução (``url``, ``destino`` e ``sha256`` opcional).
            needs_network: Pede rede na execução (só vale com entradas compartilháveis; ver o sandbox).

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

        # 1.1 session_id e task_name viram pastas do host (e o bind mount do sandbox)
        for label, value in (("session_id", session_id), ("task_name", task_name)):
            if not isinstance(value, str) or not _SAFE_NAME_RE.fullmatch(value) or ".." in value or value == "." or is_reserved_name(value):
                return SkillResult(
                    success=False,
                    output="",
                    error=f"{label} inválido {value!r}: use letras, dígitos, '.', '_' e '-', sem '..'.",
                )

        # 2. Pacotes sob demanda: a validação (PEP 508), o filtro da stdlib e do conjunto básico
        # e a instalação (sem root, em /deps) são do sandbox.
        requested_packages = list(packages or [])

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
                packages=requested_packages,
                extra_files=extra_files,
                assets=list(assets or []),
                needs_network=bool(needs_network),
                prior_dirs=self._readable_prior_dirs(),
            )

            success = not result.timed_out and result.exit_code == 0
            run_info = self._run_info(result)
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
                    task_name=task_name,
                    run_info=run_info,
                )
            else:
                error_info = _extract_error_info(result.stderr)
                summary = (
                    f"Execução falhou. "
                    f"Erro: {error_info.get('error_type', 'desconhecido')}."
                )
                if result.install_failed:
                    summary = "Instalação de pacotes falhou; o script não foi executado."
                    error_info = {
                        "error_type": "PackageInstallError",
                        "error_message": result.stderr[:500],
                        "error_location": "",
                    }
                elif result.download_nao_declarado:
                    summary = "Download não declarado: a execução não tem rede."
                    error_info = {
                        "error_type": "download_nao_declarado",
                        "error_message": "O script tentou baixar algo na fase execute; declare o ativo em assets.",
                        "error_location": "",
                    }
                elif result.fase_falha in ("fetch_assets", "infra"):
                    summary = f"Execução falhou na fase {result.fase_falha}; o script não foi executado."
                    error_info = {
                        "error_type": f"SandboxPhaseError:{result.fase_falha}",
                        "error_message": result.stderr[:500],
                        "error_location": "",
                    }
                elif result.timed_out:
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
                    task_name=task_name,
                    run_info=run_info,
                )

            if result.install_failed:
                return SkillResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr,
                    metadata={
                        "exit_code": result.exit_code,
                        "install_failed": True,
                        "timed_out": result.timed_out,
                        **self._phase_metadata(result),
                    },
                )

            if result.timed_out:
                return SkillResult(
                    success=False,
                    output=result.stdout,
                    error="Timeout atingido durante a execução.",
                    metadata={"exit_code": result.exit_code, "timed_out": True, **self._phase_metadata(result)}
                )

            error = None
            if not success:
                # Download não declarado: mensagem fixa, sem repetir URL nem trechos do stderr (design §5).
                error = NETWORK_UNDECLARED_MESSAGE if result.download_nao_declarado else result.stderr
                if result.nota_rede:
                    error = f"{error}\nRede na execução negada: {result.nota_rede}."

            return SkillResult(
                success=success,
                output=result.stdout,
                error=error,
                metadata={
                    "exit_code": result.exit_code,
                    "artifacts": result.artifacts,
                    "manifest_step": step_number,
                    "packages_installed": result.packages_installed,
                    **self._phase_metadata(result),
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
