"""Agente Validador e Revisor residente como corrotina assíncrona (Roadmap V14.2).

Absorve a validação estrutural de planos e a revisão de subtarefas no processo
principal, sem instanciar container próprio (ADR 014) — o Validator sempre rodou
como corrotina no orquestrador, sem Docker.
"""

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import APP_NAME
from src.logger import get_logger
from src.model_router import ModelRouter
from src.llm.base import LLMProvider
from src.llm.metering import record_llm_call
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


def _evaluate_quantitative_criteria(
    criteria: List[Any], metrics: Dict[str, Any]
) -> Optional[Tuple[bool, str]]:
    """Avalia critérios textuais contra valores reais em ``metrics.json``.

    Retorna ``(passou, detalhe)`` para o primeiro critério reconhecível e comparável
    contra uma métrica real, ou ``None`` se nenhum critério pôde ser mapeado
    (nesse caso o chamador deve recorrer à avaliação genérica via LLM).
    """
    normalized_metrics = {_normalize_metric_name(k): v for k, v in (metrics or {}).items()}

    for criterion in criteria:
        if not isinstance(criterion, str):
            continue
        match = _CRITERION_VALUE_PATTERN.search(criterion)
        if not match:
            continue

        raw_name, operator, raw_value = match.groups()
        key_candidate = _normalize_metric_name(raw_name)
        metric_key = _METRIC_ALIASES.get(key_candidate, key_candidate)
        if metric_key not in normalized_metrics:
            continue

        try:
            actual = float(normalized_metrics[metric_key])
            threshold = float(raw_value.replace(",", "."))
        except (TypeError, ValueError):
            continue

        passed = {
            ">": actual > threshold,
            ">=": actual >= threshold,
            "<": actual < threshold,
            "<=": actual <= threshold,
            "==": actual == threshold,
        }[operator]

        detail = (
            f"Critério '{criterion.strip()}' avaliado contra metrics.json: "
            f"valor real = {actual}, threshold {operator} {threshold} -> "
            f"{'atendido' if passed else 'não atendido'}."
        )
        return passed, detail

    return None


def _resolve_artifact_path(
    available_artifacts: set, output_dir: Optional[Path | str], filename: str
) -> Optional[Path]:
    """Localiza o caminho real de um arquivo (ex: metrics.json) entre os artefatos conhecidos."""
    if output_dir:
        out_p = Path(output_dir)
        if out_p.exists():
            matches = list(out_p.rglob(filename))
            if matches:
                return matches[0]
    for artifact in available_artifacts:
        candidate = Path(artifact)
        if candidate.name == filename and candidate.is_file():
            return candidate
    return None


@dataclass
class ValidationResult:
    """Resultado da validação de um plano."""

    is_valid: bool
    status: str  # "approved" | "revision_needed"
    reason: str
    issues: List[str] = field(default_factory=list)


_TEXT_EVIDENCE_SUFFIXES = {".json", ".md", ".txt", ".csv", ".log"}
_EVIDENCE_HEAD_CHARS = 700
_EVIDENCE_MAX_FILES = 12


def build_artifact_evidence(output_dir: Optional[Path | str], expected_artifacts: List[str]) -> str:
    """Resume os artefatos esperados que existem em disco: caminho relativo, tamanho e começo do conteúdo.

    O revisor só via nomes de arquivo e reprovava subtarefas por "não foi possível confirmar o
    conteúdo". Com esta evidência ele julga o que está gravado, não só o que o agente afirma.
    """
    if not output_dir:
        return "(sem diretório de sessão)"
    root = Path(output_dir)
    if not root.exists():
        return "(diretório de sessão inexistente)"
    wanted = {Path(e).name for e in expected_artifacts}
    lines: List[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in ("scientific_helpers.py", "script.py") or path.suffix == ".pyc":
            continue
        if wanted and path.name not in wanted:
            continue
        if len(lines) >= _EVIDENCE_MAX_FILES:
            break
        rel = path.relative_to(root)
        size = path.stat().st_size
        if path.suffix.lower() in _TEXT_EVIDENCE_SUFFIXES and size < 2_000_000:
            head = path.read_text(encoding="utf-8", errors="replace")[:_EVIDENCE_HEAD_CHARS].replace("\n", " ")
            lines.append(f"- {rel} ({size} bytes): {head}")
        else:
            lines.append(f"- {rel} ({size} bytes, binário)")
    return "\n".join(lines) or "(nenhum dos artefatos esperados encontrado)"


@dataclass
class ReviewResult:
    """Resultado da revisão de uma subtarefa após execução."""

    is_approved: bool
    status: str  # "pass" | "fail"
    feedback: str
    issues: List[str] = field(default_factory=list)


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
            return ValidationResult(
                is_valid=is_valid,
                status="approved" if is_valid else "revision_needed",
                reason=parsed.get("reason", ""),
                issues=parsed.get("issues", []),
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

        available_artifacts = set(artifacts_on_disk or [])
        if manifest_artifacts:
            available_artifacts.update(manifest_artifacts)

        # Se um diretório foi fornecido, adiciona os arquivos existentes nele
        if output_dir:
            out_p = Path(output_dir)
            if out_p.exists():
                for f in out_p.rglob("*"):
                    if f.is_file():
                        available_artifacts.add(f.name)
                        available_artifacts.add(str(f))

        # 0. Roadmap V15.2 / Spec G2 — validação científica via metrics.json quando o
        # critério de aceite exige um threshold quantitativo (reprodução/validação).
        # Avaliada ANTES do response_text, que é frequentemente otimista ou impreciso.
        if isinstance(validation_criteria, list) and _has_quantitative_criterion(validation_criteria):
            metrics_file = _resolve_artifact_path(available_artifacts, output_dir, "metrics.json")
            if metrics_file is None:
                msg = f"metrics.json não encontrado em /outputs/{task_name}/"
                logger.warning(
                    "Subtarefa reprovada: critério quantitativo sem metrics.json",
                    extra={"task_name": task_name},
                )
                return ReviewResult(is_approved=False, status="fail", feedback=msg, issues=[msg])

            try:
                metrics_data = json.loads(metrics_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                msg = f"Falha ao ler metrics.json: {e}"
                return ReviewResult(is_approved=False, status="fail", feedback=msg, issues=[msg])

            divergence_note = metrics_data.get("divergence_note")
            if divergence_note:
                return ReviewResult(
                    is_approved=True,
                    status="divergent_but_documented",
                    feedback=f"Resultado diverge do esperado, mas está documentado: {divergence_note}",
                    issues=[],
                )

            evaluation = _evaluate_quantitative_criteria(
                validation_criteria, metrics_data.get("metrics", {})
            )
            if evaluation is not None:
                passed, detail = evaluation
                return ReviewResult(
                    is_approved=passed,
                    status="pass" if passed else "fail",
                    feedback=detail,
                    issues=[] if passed else [detail],
                )
            # Nenhum critério pôde ser mapeado a uma métrica real em metrics.json —
            # prossegue para a avaliação genérica abaixo (artefatos + LLM).

        # 1. Verificação estrita de artefatos em disco
        missing_artifacts = []
        for expected in expected_artifacts:
            exp_name = Path(expected).name
            found = any(
                expected == a or exp_name == Path(a).name or expected in a
                for a in available_artifacts
            )
            if not found:
                missing_artifacts.append(expected)

        if missing_artifacts:
            msg = f"Artefatos esperados não foram encontrados no disco: {', '.join(missing_artifacts)}"
            logger.warning(
                "Subtarefa reprovada por artefatos ausentes no disco",
                extra={"task_name": task_name, "missing": missing_artifacts},
            )
            return ReviewResult(
                is_approved=False,
                status="fail",
                feedback=msg,
                issues=[f"Artefato ausente no disco: {a}" for a in missing_artifacts],
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
                "- Cada item em 'issues' deve citar o critério específico não atendido.\n"
                "Responda estritamente em JSON com o formato:\n"
                '{\n  "status": "pass" | "fail",\n  "feedback": "explicação do parecer",\n  "issues": []\n}'
            )
            evidence = build_artifact_evidence(output_dir, expected_artifacts)
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
                    return ReviewResult(
                        is_approved=is_approved,
                        status="pass" if is_approved else "fail",
                        feedback=parsed.get("feedback", ""),
                        issues=parsed.get("issues", []),
                    )
            except Exception as e:
                logger.warning(f"Erro na revisão semântica via LLM: {e}")

        # Se não há critérios ou LLM não falhou os critérios e artefatos estão no disco:
        return ReviewResult(
            is_approved=True,
            status="pass",
            feedback="Subtarefa aprovada com artefatos presentes no disco.",
            issues=[],
        )
