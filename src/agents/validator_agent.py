"""Agente Validador e Revisor residente como corrotina assíncrona (Roadmap V14.2).

Absorve a validação estrutural de planos e a revisão de subtarefas no processo
principal, sem instanciar container próprio (ADR 014) — o Validator sempre rodou
como corrotina no orquestrador, sem Docker.
"""

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.artifact_match import ArtifactResolution, resolve_artifacts
from src.config import APP_NAME, ARTIFACT_MATCH_MODE
from src.llm.base import LLMProvider
from src.llm.metering import record_llm_call
from src.logger import get_logger
from src.model_router import ModelRouter
from src.utils.json_parser import extract_json

logger = get_logger(__name__)

MANDATORY_KEYS = ["agent_id", "task_name", "prompt", "validation_criteria"]

# Roadmap V15.1 / Spec G1 — tipos de tarefa que exigem ao menos 1 critério quantitativo
# (com threshold numérico) em validation_criteria, por serem confirmatórios por natureza.
_QUANTITATIVE_REQUIRED_TASK_TYPES = {"reproduction", "validation"}

# Heurística de "critério quantitativo": presença de um dígito combinado com um operador
# de comparação (símbolo ou palavra) — ex: "acurácia > 0.85", "pelo menos 90% de cobertura".
_QUANTITATIVE_PATTERN = re.compile(
    r"\d.*(?:[<>]=?|==)|(?:[<>]=?|==).*\d"
    r"|\d.*(?:maior|menor|acima|abaixo|m[ií]nimo|m[áa]ximo|pelo menos|no m[íi]nimo|no m[áa]ximo|igual)"
    r"|(?:maior|menor|acima|abaixo|m[ií]nimo|m[áa]ximo|pelo menos|no m[íi]nimo|no m[áa]ximo|igual).*\d",
    re.IGNORECASE,
)


def _has_quantitative_criterion(criteria: List[Any]) -> bool:
    """Verifica se ao menos um critério de validação contém um threshold numérico explícito."""
    return any(
        isinstance(c, str) and _QUANTITATIVE_PATTERN.search(c) for c in criteria
    )


SCHEMA_INSTRUCTION = """Cada subtarefa no plano DEVE ser um objeto JSON contendo estritamente:
- "agent_id": string (ex: 'developer', 'researcher')
- "task_name": string única em snake_case (ex: 'carregar_dados')
- "task_type": opcional — 'reproduction' | 'eda' | 'model_impl' | 'validation' | 'synthesis'
- "prompt": string com instrução clara e completa
- "hypothesis": opcional (recomendado) — o que esta subtarefa testa ou produz
- "scientific_rationale": opcional (recomendado) — por que esta etapa é metodologicamente necessária
- "validation_criteria": list[str] (OBRIGATÓRIO: lista com ao menos 1 critério verificável de aceite;
  para task_type 'reproduction' ou 'validation', ao menos 1 critério deve conter um threshold numérico)
- "expected_artifacts": list[str] (arquivos esperados a serem gerados em /outputs/)
- "depends_on": list[str] (nomes de tarefas das quais esta depende)
"""

# Roadmap V15.2 / Spec G2 — parsing de critérios quantitativos contra metrics.json real.
_METRIC_ALIASES = {
    "acuracia": "accuracy",
    "accuracy": "accuracy",
    "precisao": "precision",
    "precision": "precision",
    "recall": "recall",
    "revocacao": "recall",
    "sensibilidade": "recall",
    "f1": "f1",
    "f1score": "f1",
    "erro": "error",
    "error": "error",
    "mse": "mse",
    "rmse": "rmse",
    "mae": "mae",
    "r2": "r2",
    "auc": "auc",
    "loss": "loss",
    "perda": "loss",
}

_CRITERION_VALUE_PATTERN = re.compile(r"([^<>=]+?)\s*(>=|<=|==|>|<)\s*(\d+(?:[.,]\d+)?)\s*%?")


def _normalize_metric_name(name: str) -> str:
    """Normaliza um nome de métrica para comparação (remove acentos, minúsculas, sem espaços)."""
    stripped = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", stripped.lower())


def _metric_key(raw_name: str) -> Optional[str]:
    """Mapeia o nome citado em um critério a uma métrica conhecida, ou ``None``.

    Tenta o nome inteiro e depois cada palavra ("acurácia no teste" -> ``accuracy``).
    """
    whole = _normalize_metric_name(raw_name)
    if whole in _METRIC_ALIASES:
        return _METRIC_ALIASES[whole]
    for word in re.split(r"\s+", raw_name.strip()):
        key = _normalize_metric_name(word)
        if key in _METRIC_ALIASES:
            return _METRIC_ALIASES[key]
    return None


@dataclass(frozen=True)
class MetricCriterion:
    """Critério de aceite que cita uma métrica conhecida, operador e limiar."""

    text: str
    metric: str
    operator: str
    threshold: float


def _metric_criteria(criteria: List[Any]) -> List[MetricCriterion]:
    """Seleciona os critérios que citam uma métrica conhecida com operador e valor.

    Critérios de contagem ("pelo menos 3 gráficos") ou qualitativos não entram: seguem para o
    revisor LLM (``v16-pipeline-robustness`` §3).
    """
    found: List[MetricCriterion] = []
    for criterion in criteria or []:
        if not isinstance(criterion, str):
            continue
        match = _CRITERION_VALUE_PATTERN.search(criterion)
        if not match:
            continue
        raw_name, operator, raw_value = match.groups()
        metric = _metric_key(raw_name)
        if metric is None:
            continue
        found.append(MetricCriterion(criterion.strip(), metric, operator, float(raw_value.replace(",", "."))))
    return found


def _evaluate_metric_criteria(
    criteria: List[MetricCriterion], metrics: Dict[str, Any]
) -> List[Tuple[bool, str]]:
    """Avalia TODOS os critérios com métrica nomeada contra os valores reais de ``metrics.json``."""
    normalized: Dict[str, Any] = {}
    for key, value in (metrics or {}).items():
        norm = _normalize_metric_name(str(key))
        normalized[_METRIC_ALIASES.get(norm, norm)] = value

    results: List[Tuple[bool, str]] = []
    for crit in criteria:
        if crit.metric not in normalized:
            results.append((False, f"Critério '{crit.text}': a métrica '{crit.metric}' não está em metrics.json."))
            continue
        try:
            actual = float(normalized[crit.metric])
        except (TypeError, ValueError):
            results.append((False, f"Critério '{crit.text}': valor de '{crit.metric}' em metrics.json não é numérico."))
            continue
        passed = {
            ">": actual > crit.threshold,
            ">=": actual >= crit.threshold,
            "<": actual < crit.threshold,
            "<=": actual <= crit.threshold,
            "==": actual == crit.threshold,
        }[crit.operator]
        results.append((
            passed,
            f"Critério '{crit.text}' avaliado contra metrics.json: valor real = {actual}, "
            f"threshold {crit.operator} {crit.threshold} -> {'atendido' if passed else 'não atendido'}.",
        ))
    return results


def _find_metrics_file(output_dir: Optional[Path | str], task_name: str, depends_on: List[str]) -> Optional[Path]:
    """Localiza ``metrics.json`` na pasta da própria subtarefa e, depois, nas de suas dependências."""
    if not output_dir:
        return None
    root = Path(output_dir)
    for folder in [task_name, *depends_on]:
        if not folder:
            continue
        direct = root / folder / "metrics.json"
        if direct.is_file():
            return direct
        nested = sorted((root / folder).rglob("metrics.json")) if (root / folder).is_dir() else []
        if nested:
            return nested[0]
    return None


def issue_signature(issues: List[str]) -> str:
    """Assinatura estável de um conjunto de problemas (números e caixa não contam)."""
    normalized = sorted({re.sub(r"\d+", "#", i.lower().strip()) for i in issues if i})
    return hashlib.sha1("|".join(normalized).encode("utf-8")).hexdigest()[:12]


@dataclass
class ValidationResult:
    """Resultado da validação de um plano."""

    is_valid: bool
    status: str  # "approved" | "revision_needed"
    reason: str
    issues: List[str] = field(default_factory=list)
    signature: str = ""
    deterministic: bool = False  # reprovação por checagem estrutural (não por LLM)
    approved_with_warnings: bool = False


_TEXT_EVIDENCE_SUFFIXES = {".json", ".md", ".txt", ".csv", ".log"}
_EVIDENCE_HEAD_CHARS = 700
_EVIDENCE_MAX_FILES = 12


def build_artifact_evidence(
    output_dir: Optional[Path | str],
    expected_artifacts: List[str],
    resolutions: Optional[List[ArtifactResolution]] = None,
) -> str:
    """Resume os artefatos esperados que existem em disco: caminho relativo, tamanho e começo do conteúdo.

    O revisor só via nomes de arquivo e reprovava subtarefas por "não foi possível confirmar o
    conteúdo". Com esta evidência ele julga o que está gravado, não só o que o agente afirma.
    Com ``resolutions`` (comparador tolerante), mostra os arquivos resolvidos mesmo quando o nome
    difere do esperado, indicando a camada de resolução.
    """
    if not output_dir:
        return "(sem diretório de sessão)"
    root = Path(output_dir)
    if not root.exists():
        return "(diretório de sessão inexistente)"
    tier_by_file: Dict[Path, str] = {}
    if resolutions is not None:
        for res in resolutions:
            for matched in res.matched:
                tier_by_file[matched] = res.tier
    wanted = {Path(e).name for e in expected_artifacts}
    lines: List[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in ("scientific_helpers.py", "script.py") or path.suffix == ".pyc":
            continue
        rel = path.relative_to(root)
        if resolutions is not None:
            if rel not in tier_by_file:
                continue
        elif wanted and path.name not in wanted:
            continue
        if len(lines) >= _EVIDENCE_MAX_FILES:
            break
        size = path.stat().st_size
        tier = tier_by_file.get(rel)
        note = f" [resolvido por {tier}]" if tier in ("normalized", "extension") else ""
        if path.suffix.lower() in _TEXT_EVIDENCE_SUFFIXES and size < 2_000_000:
            head = path.read_text(encoding="utf-8", errors="replace")[:_EVIDENCE_HEAD_CHARS].replace("\n", " ")
            lines.append(f"- {rel} ({size} bytes){note}: {head}")
        else:
            lines.append(f"- {rel} ({size} bytes, binário){note}")
    return "\n".join(lines) or "(nenhum dos artefatos esperados encontrado)"


@dataclass
class ReviewResult:
    """Resultado da revisão de uma subtarefa após execução."""

    is_approved: bool
    status: str  # "pass" | "fail"
    feedback: str
    issues: List[str] = field(default_factory=list)
    resolved_artifacts: Dict[str, str] = field(default_factory=dict)  # esperado -> real
    name_mismatch: bool = False
    signature: str = ""


class ValidatorAgent:
    """Agente validador executado como corrotina no processo principal (sem Docker)."""

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or ModelRouter.get_provider("validator")

    async def validate_plan(
        self,
        plan: Any,
        prompt: str,
    ) -> ValidationResult:
        """Valida o plano contra o schema estrito e critérios de viabilidade.

        Regra inegociável: Se qualquer subtarefa não contiver 'validation_criteria'
        com pelo menos um critério, o plano é REJEITADO deterministicamente.

        Args:
            plan: Lista de dicionários representando o plano proposto.
            prompt: Solicitação original do usuário.

        Returns:
            ValidationResult indicando aprovação ou necessidade de revisão.
        """
        if not isinstance(plan, list) or not plan:
            return ValidationResult(
                is_valid=False,
                status="revision_needed",
                reason="O plano deve ser uma lista não vazia de subtarefas.",
                issues=["Plano vazio ou em formato inválido."],
            )

        structural_issues = []
        for idx, task in enumerate(plan):
            if not isinstance(task, dict):
                structural_issues.append(f"Subtarefa {idx+1} não é um objeto JSON.")
                continue

            for key in MANDATORY_KEYS:
                if key not in task:
                    structural_issues.append(
                        f"Subtarefa {task.get('task_name', idx+1)} ausente do campo obrigatório '{key}'."
                    )

            # Validação estrita de validation_criteria
            criteria = task.get("validation_criteria")
            if not criteria or not isinstance(criteria, list) or len(criteria) == 0:
                structural_issues.append(
                    f"Subtarefa '{task.get('task_name', idx+1)}' NÃO possui 'validation_criteria' válido e não-vazio."
                )

            # Roadmap V15.1 / Spec G1 — hypothesis/scientific_rationale, quando presentes,
            # não podem ser strings vazias. Ausência é aceita (retrocompatibilidade com
            # planos gerados antes desta spec).
            hypothesis = task.get("hypothesis")
            if hypothesis is not None and not str(hypothesis).strip():
                structural_issues.append(
                    f"Subtarefa '{task.get('task_name', idx+1)}' possui 'hypothesis' vazia."
                )
            rationale = task.get("scientific_rationale")
            if rationale is not None and not str(rationale).strip():
                structural_issues.append(
                    f"Subtarefa '{task.get('task_name', idx+1)}' possui 'scientific_rationale' vazia."
                )

            # task_type 'reproduction'/'validation' exige ao menos 1 critério quantitativo
            task_type = task.get("task_type")
            if (
                task_type in _QUANTITATIVE_REQUIRED_TASK_TYPES
                and isinstance(criteria, list)
                and criteria
                and not _has_quantitative_criterion(criteria)
            ):
                structural_issues.append(
                    f"Subtarefa '{task.get('task_name', idx+1)}' é do tipo '{task_type}' mas não possui "
                    "nenhum critério quantitativo (com threshold numérico) em 'validation_criteria'. "
                    "Correção: acrescente um critério como 'acurácia no teste >= 0.80', ou, se a tarefa não é "
                    "confirmatória, troque o 'task_type' para 'eda', 'model_impl' ou 'synthesis'."
                )

        if structural_issues:
            logger.warning(
                "Plano rejeitado deterministicamente por problemas estruturais",
                extra={"issues": structural_issues},
            )
            return ValidationResult(
                is_valid=False,
                status="revision_needed",
                reason="Falha na validação de schema: campos obrigatórios ou validation_criteria ausentes.",
                issues=structural_issues,
                signature=issue_signature(structural_issues),
                deterministic=True,
            )

        # Validação semântica e lógica via LLM
        plan_str = json.dumps(plan, indent=2, ensure_ascii=False)
        system_prompt = (
            f"Você é o ValidatorAgent do {APP_NAME}. Sua função é avaliar planos de execução.\n"
            f"{SCHEMA_INSTRUCTION}\n"
            "Avalie se a sequência de subtarefas atende à solicitação original e se as dependências fazem sentido lógico.\n"
            "Não reprove por causa de limiares numéricos em 'validation_criteria': o framework os exige em tarefas "
            "'validation' e 'reproduction'. Reprove só por falha lógica, dependência incoerente ou cobertura "
            "incompleta da solicitação, e liste problemas que o planejador consiga corrigir.\n"
            "Nomenclatura, estilo, escolha de 'task_type' entre tipos válidos e detalhes opcionais não são motivo "
            "de reprovação. Liste no máximo 3 problemas, só os que impediriam a execução ou o cumprimento da "
            "solicitação.\n"
            "Responda EXCLUSIVAMENTE em formato JSON com o seguinte schema:\n"
            '{\n  "status": "approved" | "revision_needed",\n  "reason": "explicação curta",\n  "issues": ["problema 1", ...]\n}'
        )

        user_content = f"SOLICITAÇÃO ORIGINAL:\n{prompt}\n\nPLANO PROPOSTO:\n{plan_str}"

        try:
            _t0 = time.monotonic()
            response = await self.provider.generate(
                messages=[{"role": "user", "content": user_content}],
                system=system_prompt,
                temperature=0.1,
                max_tokens=1000,
            )
            record_llm_call(self.provider, response, int((time.monotonic() - _t0) * 1000), "validator")
            parsed = extract_json(response.text or "")
            if not isinstance(parsed, dict) or "status" not in parsed:
                return ValidationResult(
                    is_valid=False,
                    status="revision_needed",
                    reason="Falha ao interpretar resposta do modelo validador.",
                    issues=["Resposta do modelo validador não continha JSON com campo 'status'."],
                )

            status = parsed.get("status", "revision_needed").lower()
            is_valid = status == "approved"
            llm_issues = [str(i) for i in (parsed.get("issues") or [])]
            return ValidationResult(
                is_valid=is_valid,
                status="approved" if is_valid else "revision_needed",
                reason=parsed.get("reason", ""),
                issues=parsed.get("issues", []),
                signature="" if is_valid else issue_signature(llm_issues or [str(parsed.get("reason", ""))]),
            )

        except Exception as e:
            logger.error(f"Erro ao executar chamada do validador: {e}")
            return ValidationResult(
                is_valid=False,
                status="revision_needed",
                reason=f"Erro durante a validação LLM: {e}",
                issues=[str(e)],
            )

    async def review_result(
        self,
        task: Any,
        response_text: str,
        artifacts_on_disk: Optional[List[str]] = None,
        output_dir: Optional[Path | str] = None,
        manifest_artifacts: Optional[List[str]] = None,
    ) -> ReviewResult:
        """Revisa a execução de uma subtarefa verificando artefatos em disco e critérios.

        Args:
            task: Objeto AgentTask ou dicionário com a definição da tarefa.
            response_text: Texto retornado pelo agente na execução.
            artifacts_on_disk: Lista explícita de caminhos/nomes de arquivos em disco.
            output_dir: Diretório base de saída onde buscar arquivos.
            manifest_artifacts: Lista de artefatos registrados no WorkspaceManifest.

        Returns:
            ReviewResult com status 'pass' ou 'fail'.
        """
        # Extrai atributos de task de forma flexível (objeto ou dict)
        task_name = getattr(task, "task_name", None) or (task.get("task_name") if isinstance(task, dict) else "unknown")
        expected_artifacts = getattr(task, "expected_artifacts", None) or (
            task.get("expected_artifacts", []) if isinstance(task, dict) else []
        )
        validation_criteria = getattr(task, "validation_criteria", None) or (
            task.get("validation_criteria", []) if isinstance(task, dict) else []
        )

        depends_on = getattr(task, "depends_on", None) or (
            task.get("depends_on", []) if isinstance(task, dict) else []
        )
        metric_criteria = _metric_criteria(validation_criteria) if isinstance(validation_criteria, list) else []
        metric_feedback = ""

        # 0. Roadmap V15.2 / Spec G2 — validação científica via metrics.json quando algum critério
        # cita uma métrica conhecida com limiar (v16-pipeline-robustness §3). Avaliada ANTES do
        # response_text, que é frequentemente otimista ou impreciso.
        if metric_criteria:
            metrics_file = _find_metrics_file(output_dir, str(task_name), list(depends_on))
            if metrics_file is None:
                existing = self._list_task_files(output_dir, str(task_name))
                msg = f"metrics.json não encontrado em /outputs/{task_name}/ (existem: {existing})"
                logger.warning(
                    "Subtarefa reprovada: critério quantitativo sem metrics.json",
                    extra={"task_name": task_name},
                )
                return ReviewResult(is_approved=False, status="fail", feedback=msg, issues=[msg],
                                    signature=issue_signature(["metrics.json ausente"]))

            try:
                metrics_data = json.loads(metrics_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                msg = f"Falha ao ler metrics.json: {e}"
                return ReviewResult(is_approved=False, status="fail", feedback=msg, issues=[msg],
                                    signature=issue_signature(["metrics.json ilegível"]))

            divergence_note = metrics_data.get("divergence_note")
            if divergence_note:
                return ReviewResult(
                    is_approved=True,
                    status="divergent_but_documented",
                    feedback=f"Resultado diverge do esperado, mas está documentado: {divergence_note}",
                    issues=[],
                )

            evaluations = _evaluate_metric_criteria(metric_criteria, metrics_data.get("metrics", {}))
            metric_feedback = " ".join(detail for _, detail in evaluations)
            failed = [detail for ok, detail in evaluations if not ok]
            if failed:
                return ReviewResult(
                    is_approved=False,
                    status="fail",
                    feedback=metric_feedback,
                    issues=failed,
                    signature=issue_signature([f"critério {c.metric} {c.operator}" for c in metric_criteria]),
                )

        # 1. Resolução de artefatos em disco (comparador tolerante, v16-pipeline-robustness §2)
        resolutions: List[ArtifactResolution] = []
        if expected_artifacts:
            if output_dir and Path(output_dir).exists():
                resolutions = resolve_artifacts(
                    list(expected_artifacts), output_dir, str(task_name), ARTIFACT_MATCH_MODE
                )
            else:
                resolutions = self._resolve_from_names(
                    list(expected_artifacts), set(artifacts_on_disk or []) | set(manifest_artifacts or [])
                )
        missing_artifacts = [r.expected for r in resolutions if r.tier == "missing"]

        if missing_artifacts:
            existing = self._list_task_files(output_dir, str(task_name))
            msg = (
                f"Artefatos esperados não foram encontrados no disco: {', '.join(missing_artifacts)} "
                f"(existem em {task_name}/: {existing})"
            )
            logger.warning(
                "Subtarefa reprovada por artefatos ausentes no disco",
                extra={"task_name": task_name, "missing": missing_artifacts},
            )
            return ReviewResult(
                is_approved=False,
                status="fail",
                feedback=msg,
                issues=[f"Artefato ausente no disco: {a}" for a in missing_artifacts],
                signature=issue_signature([f"artefato ausente {a}" for a in missing_artifacts]),
            )
        resolved_map = {r.expected: r.matched[0].as_posix() for r in resolutions if r.matched}
        mismatch = any(r.name_mismatch for r in resolutions)

        # Critérios restantes (qualitativos ou de contagem) vão ao revisor LLM
        metric_texts = {c.text for c in metric_criteria}
        validation_criteria = [
            c for c in (validation_criteria or []) if not (isinstance(c, str) and c.strip() in metric_texts)
        ]
        if not validation_criteria and metric_criteria:
            return ReviewResult(
                is_approved=True, status="pass", feedback=metric_feedback, issues=[],
                resolved_artifacts=resolved_map, name_mismatch=mismatch,
            )

        # 2. Avaliação de critérios de validação via LLM se houver critérios
        if validation_criteria:
            criteria_str = "\n".join(f"- {c}" for c in validation_criteria)
            system_prompt = (
                f"Você é o Reviewer do {APP_NAME}. Sua função é avaliar se o resultado de uma subtarefa "
                "satisfaz os critérios de aceite definidos.\n"
                "Regras de julgamento:\n"
                "- A EVIDÊNCIA EM DISCO (caminho relativo, tamanho e começo do conteúdo) é a fonte de verdade; "
                "a resposta do agente é só um resumo.\n"
                "- Os caminhos são relativos à pasta da sessão. Não reprove por diferença de prefixo "
                "(ex.: '/outputs/x.json' no texto do agente e 'subtarefa/x.json' no disco): o que importa é o "
                "arquivo existir com conteúdo coerente.\n"
                "- Não reprove por não ver o conteúdo completo de um arquivo cuja existência e tamanho foram "
                "confirmados; reprove só se a evidência contradiz um critério ou o critério exige algo ausente.\n"
                "- Um artefato com nome diferente do esperado (marcado [resolvido por ...]) NÃO é motivo de "
                "reprovação: avalie o conteúdo.\n"
                "- Cada item em 'issues' deve citar o critério específico não atendido.\n"
                "Responda estritamente em JSON com o formato:\n"
                '{\n  "status": "pass" | "fail",\n  "feedback": "explicação do parecer",\n  "issues": []\n}'
            )
            evidence = build_artifact_evidence(output_dir, expected_artifacts, resolutions if resolutions else None)
            user_content = (
                f"SUBTAREFA: {task_name}\n"
                f"CRITÉRIOS DE ACEITE:\n{criteria_str}\n\n"
                f"EVIDÊNCIA EM DISCO:\n{evidence}\n\n"
                f"RESPOSTA DO AGENTE:\n{response_text[:3000]}"
            )

            try:
                _t0 = time.monotonic()
                response = await self.provider.generate(
                    messages=[{"role": "user", "content": user_content}],
                    system=system_prompt,
                    temperature=0.1,
                    max_tokens=800,
                )
                record_llm_call(self.provider, response, int((time.monotonic() - _t0) * 1000), "reviewer")
                parsed = extract_json(response.text or "")
                if isinstance(parsed, dict) and "status" in parsed:
                    status = parsed.get("status", "pass").lower()
                    is_approved = status == "pass"
                    llm_issues = [str(i) for i in (parsed.get("issues") or [])]
                    return ReviewResult(
                        is_approved=is_approved,
                        status="pass" if is_approved else "fail",
                        feedback=parsed.get("feedback", ""),
                        issues=parsed.get("issues", []),
                        resolved_artifacts=resolved_map,
                        name_mismatch=mismatch,
                        signature=""
                        if is_approved
                        else issue_signature(llm_issues or [str(parsed.get("feedback", ""))]),
                    )
            except Exception as e:
                logger.warning(f"Erro na revisão semântica via LLM: {e}")

        # Se não há critérios ou LLM não falhou os critérios e artefatos estão no disco:
        return ReviewResult(
            is_approved=True,
            status="pass",
            feedback="Subtarefa aprovada com artefatos presentes no disco.",
            issues=[],
            resolved_artifacts=resolved_map,
            name_mismatch=mismatch,
        )

    @staticmethod
    def _list_task_files(output_dir: Optional[Path | str], task_name: str) -> List[str]:
        """Nomes dos arquivos existentes na pasta da subtarefa (para mensagens de reprovação acionáveis)."""
        if not output_dir:
            return []
        folder = Path(output_dir) / task_name
        if not folder.is_dir():
            return []
        ignored = ("script.py", "scientific_helpers.py")
        return sorted(p.name for p in folder.rglob("*") if p.is_file() and p.name not in ignored)[:12]

    @staticmethod
    def _resolve_from_names(expected: List[str], available: set) -> List[ArtifactResolution]:
        """Resolução por nomes quando não há diretório da sessão (revisão sem disco)."""
        names = {Path(a).name for a in available} | set(available)
        out: List[ArtifactResolution] = []
        for exp in expected:
            found = exp in names or Path(exp).name in names or any(exp in a for a in available)
            matched = [Path(Path(exp).name)] if found else []
            out.append(ArtifactResolution(exp, matched, "exact" if found else "missing"))
        return out
