import asyncio
import json
import pathlib
import re
import time
from dataclasses import dataclass
from typing import Any, List, Optional
from src import config
from src.config import get_env
from src.logger import get_logger
from src.reserved_files import is_reserved_name
from src.skills.base import BaseSkill, SkillResult
from src.skills.code.manifest import WorkspaceManifest
from src.logger import get_logger
from src.provenance.errors import ProvenanceError
from src.provenance.hashing import HashCache
from src.provenance.ledger import get_ledger
from src.provenance.records import (
    collect_inputs,
    collect_outputs,
    inicio_body,
    read_metrics,
    snapshot_dir_state,
    status_of,
    termino_body,
)

logger = get_logger(__name__)

PROVENANCE_BEGIN_ERROR = "registro de início indisponível; execução não iniciada"

# Roadmap V15.2 / Spec G2 — bibliotecas cuja presença no código indica um script
# científico/de dados, para o qual scientific_helpers.py é injetado automaticamente.
_SCIENTIFIC_LIBRARY_MARKERS = ("numpy", "pandas", "sklearn")

_SCIENTIFIC_HELPERS_PATH = pathlib.Path(__file__).parent / "scientific_helpers.py"


def _uses_scientific_libraries(code: str) -> bool:
    """Detecta se o código importa bibliotecas científicas/de dados (Spec G2)."""
    return any(marker in code for marker in _SCIENTIFIC_LIBRARY_MARKERS)


_hash_cache: HashCache | None = None


def _provenance_hash_cache() -> HashCache:
    """Cache de hash de arquivos grandes do processo (``PROVENANCE_HASH_CACHE_*``)."""
    global _hash_cache
    if _hash_cache is None or str(_hash_cache.path) != str(config.PROVENANCE_HASH_CACHE_PATH):
        _hash_cache = HashCache(config.PROVENANCE_HASH_CACHE_PATH, config.PROVENANCE_HASH_CACHE_MIN_BYTES)
    return _hash_cache


def _load_scientific_helpers_source() -> str:
    """Lê o código-fonte de scientific_helpers.py para injeção no sandbox."""
    return _SCIENTIFIC_HELPERS_PATH.read_text(encoding="utf-8")

@dataclass
class _Provenance:
    """Estado do registro de proveniência de uma chamada da skill."""

    ledger: Any
    began: Any
    inicio: dict
    project_id: Optional[str]
    subtask_id: Optional[str]
    session_id: str
    task_name: str
    output_root: pathlib.Path
    finished: bool = False
    record: Any = None
    pending: bool = False

    @property
    def exec_id(self) -> str:
        return self.began.exec_id

    def metadata(self) -> dict:
        """Campos de proveniência do ``SkillResult`` (``exec_id`` alimenta as referências numéricas)."""
        meta: dict = {"exec_id": self.exec_id, "provenance_pending": self.pending}
        if self.record is not None:
            meta["record_hash"] = self.record.record_hash
        return meta


class CodeSkill(BaseSkill):
    """Skill para execução de código Python em sandbox seguro."""
    
    name = "python_interpreter"
    description = (
        "Use esta skill para executar código Python e realizar análise de dados. "
        "Forneça o código completo como string. "
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
                        "sha256": {
                            "type": "string",
                            "description": "sha256 esperado (opcional, recomendado); sem ele a URL precisa ser https.",
                        },
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

    def _persist_streams(
        self,
        session_dir: pathlib.Path,
        session_id: str,
        task_name: str,
        step: int,
        result: SandboxResult,
        success: bool,
    ) -> dict:
        """Grava a saída integral (``step_NN.stdout.txt``/``.stderr.txt``) no nó, antes de devolvê-la ao modelo.

        O filtro de egresso (v18.5-egress-gate) cita o caminho nos avisos de retenção e de elisão. Devolve os campos do
        ``metadata`` da skill (``integral_path``, ``egress_source``); sem escrita possível, devolve só a origem.
        """
        base = session_dir / task_name
        shown = "stdout" if success else "stderr"
        paths: dict[str, str] = {}
        try:
            base.mkdir(parents=True, exist_ok=True)
            for kind, text in (("stdout", result.stdout), ("stderr", result.stderr)):
                if not text:
                    continue
                name = f"step_{step:02d}.{kind}.txt"
                (base / name).write_text(text, encoding="utf-8")
                paths[kind] = (pathlib.Path(self.output_dir) / session_id / task_name / name).as_posix()
        except OSError as exc:
            logger.warning("Não foi possível gravar a saída integral da execução", extra={"error": str(exc)})
        meta: dict = {"egress_source": f"step_{step:02d}:{shown}"}
        chosen = paths.get(shown) or paths.get("stdout") or paths.get("stderr")
        if chosen:
            meta["integral_path"] = chosen
        return meta

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

    async def _provenance_begin(
        self,
        code: str,
        extra_files: Optional[dict],
        packages: List[str],
        assets: Optional[List[dict]],
        session_id: str,
        task_name: str,
        session_dir: pathlib.Path,
    ) -> "_Provenance | SkillResult":
        """Grava o ``inicio`` (fail-fast): sem o registro a execução não começa (design §4)."""
        from src.agent_runtime.context import get_agent_context_optional

        ctx = get_agent_context_optional()
        project_id = ctx.project_id if ctx is not None else None
        subtask_id = ctx.subtask_id if ctx is not None else None
        output_root = session_dir.parent
        ledger = get_ledger()
        try:
            inputs = await asyncio.to_thread(
                collect_inputs,
                output_root=output_root,
                session_id=session_id,
                task_name=task_name,
                prior_dirs=self._readable_prior_dirs(),
                cache=_provenance_hash_cache(),
            )
            body = inicio_body(
                code=code,
                extra_files=extra_files,
                inputs=inputs,
                packages=packages,
                assets=list(assets or []),
                image=str(getattr(self.sandbox, "image", "") or ""),
            )
            began = await asyncio.to_thread(
                ledger.begin,
                project_id=project_id,
                session_id=session_id,
                subtask_id=subtask_id,
                task_name=task_name,
                body=body,
                output_dir=output_root,
            )
        except Exception as exc:  # noqa: BLE001 — banco fora do ar, tabela ausente ou corpo inválido: nada executa
            logger.error("Registro de início da execução indisponível", extra={"error": str(exc)[:300]})
            return SkillResult(
                success=False,
                output="",
                error=f"{PROVENANCE_BEGIN_ERROR}: {exc}",
                metadata={"fase_falha": "infra", "provenance_unavailable": True},
            )
        return _Provenance(ledger, began, body, project_id, subtask_id, session_id, task_name, output_root)

    async def _provenance_finish(
        self,
        provenance: "_Provenance",
        result: Optional[SandboxResult],
        error: Optional[BaseException],
        task_dir_before: dict,
        extra_files: Optional[dict],
    ) -> Optional[SkillResult]:
        """Grava o ``termino``. Devolve um ``SkillResult`` de falha só quando nem o registro nem o arquivo local
        aceitaram o término (um resultado sem registro não pode virar ``Resultado`` no grafo)."""
        provenance.finished = True
        try:
            outputs = await asyncio.to_thread(
                collect_outputs,
                output_root=provenance.output_root,
                session_id=provenance.session_id,
                task_name=provenance.task_name,
                before=task_dir_before,
                ignore_names={"script.py", *(extra_files or {})},
                cache=_provenance_hash_cache(),
            )
            metrics = await asyncio.to_thread(
                read_metrics, provenance.output_root / provenance.session_id / provenance.task_name
            )
            body = termino_body(
                inicio=provenance.inicio,
                inicio_hash=provenance.began.record.record_hash,
                status=status_of(result, error),
                result=result,
                outputs=outputs,
                metrics=metrics,
                error=error,
            )
            finished = await asyncio.to_thread(
                provenance.ledger.finish,
                exec_id=provenance.began.exec_id,
                chain_id=provenance.began.chain_id,
                session_id=provenance.session_id,
                subtask_id=provenance.subtask_id,
                task_name=provenance.task_name,
                body=body,
                output_dir=provenance.output_root,
            )
        except ProvenanceError as exc:
            logger.error("Término da execução não registrado", extra={"error": str(exc)[:300]})
            return SkillResult(
                success=False, output="", error=str(exc), metadata=provenance.metadata()
            )
        except Exception as exc:  # noqa: BLE001 — falha ao montar o término: sem registro confiável, a execução falha
            logger.error("Término da execução não montado", extra={"error": str(exc)[:300]})
            return SkillResult(
                success=False,
                output="",
                error=f"término não registrado nem guardado localmente: {exc}",
                metadata=provenance.metadata(),
            )
        provenance.record = finished.record
        provenance.pending = finished.pending
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
            if (
                not isinstance(value, str)
                or not _SAFE_NAME_RE.fullmatch(value)
                or ".." in value
                or value == "."
                or is_reserved_name(value)
            ):
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

        # Roadmap V15.2 / Spec G2 — injeta scientific_helpers.py quando o código usa bibliotecas
        # científicas/de dados, permitindo save_experiment_artifacts().
        extra_files = None
        if _uses_scientific_libraries(code):
            extra_files = {"scientific_helpers.py": _load_scientific_helpers_source()}

        # v18.5-execution-provenance — registro de início ANTES de qualquer container (fail-fast, design §4).
        provenance = await self._provenance_begin(
            code, extra_files, requested_packages, assets, session_id, task_name, session_dir
        )
        if isinstance(provenance, SkillResult):
            return provenance
        task_dir_before = snapshot_dir_state(session_dir / task_name)

        # 3. Executar no sandbox
        result: Optional[SandboxResult] = None
        try:
            # Nota: PythonSandbox.run é síncrono; a chamada abaixo o executa em thread.

            # O sandbox usa o SDK síncrono do daemon de containers e pode levar minutos
            # (instalação de pacotes + execução): rodar direto na corrotina congelaria o
            # orquestrador e os demais agentes do processo. Vai para uma thread para manter
            # o event loop livre.
            _started = time.monotonic()
            result = await asyncio.to_thread(
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

            # v18.5-execution-provenance — término registrado logo após o sandbox, antes de qualquer outro passo.
            finish_error = await self._provenance_finish(provenance, result, None, task_dir_before, extra_files)
            if finish_error is not None:
                return finish_error

            success = not result.timed_out and result.exit_code == 0
            run_info = self._run_info(result)
            egress_meta = self._persist_streams(session_dir, session_id, task_name, step_number, result, success)
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
                    exec_id=provenance.exec_id,
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
                    exec_id=provenance.exec_id,
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
                        **egress_meta,
                        **provenance.metadata(),
                    },
                )

            if result.timed_out:
                return SkillResult(
                    success=False,
                    output=result.stdout,
                    error="Timeout atingido durante a execução.",
                    metadata={
                        "exit_code": result.exit_code,
                        "timed_out": True,
                        **self._phase_metadata(result),
                        **egress_meta,
                        **provenance.metadata(),
                    }
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
                    **egress_meta,
                    **provenance.metadata(),
                }
            )

        except Exception as e:
            logger.error(f"Erro na CodeSkill: {str(e)}")
            # v18.5-execution-provenance — o término é gravado em qualquer desfecho (design §4).
            if not provenance.finished:
                finish_error = await self._provenance_finish(provenance, result, e, task_dir_before, extra_files)
                if finish_error is not None:
                    return finish_error
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
                    exec_id=provenance.exec_id,
                )
            except Exception:
                pass
            return SkillResult(
                success=False,
                output="",
                error=f"Erro ao executar código: {str(e)}",
                metadata=provenance.metadata(),
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
