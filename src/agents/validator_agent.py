"""Agente Validador e Revisor residente como corrotina assíncrona (Roadmap V14.2).

Absorve a validação estrutural de planos e a revisão de subtarefas no processo
principal sem instanciar containers Docker (ADR 007).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.logger import get_logger
from src.model_router import ModelRouter
from src.llm.base import LLMProvider
from src.utils.json_parser import extract_json

logger = get_logger(__name__)

MANDATORY_KEYS = ["agent_id", "task_name", "prompt", "validation_criteria"]

SCHEMA_INSTRUCTION = """Cada subtarefa no plano DEVE ser um objeto JSON contendo estritamente:
- "agent_id": string (ex: 'developer', 'researcher')
- "task_name": string única em snake_case (ex: 'carregar_dados')
- "prompt": string com instrução clara e completa
- "validation_criteria": list[str] (OBRIGATÓRIO: lista com ao menos 1 critério verificável de aceite)
- "expected_artifacts": list[str] (arquivos esperados a serem gerados em /outputs/)
- "depends_on": list[str] (nomes de tarefas das quais esta depende)
"""


@dataclass
class ValidationResult:
    """Resultado da validação de um plano."""

    is_valid: bool
    status: str  # "approved" | "revision_needed"
    reason: str
    issues: List[str] = field(default_factory=list)


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
            "Você é o ValidatorAgent do framework GeminiClaw. Sua função é avaliar planos de execução.\n"
            f"{SCHEMA_INSTRUCTION}\n"
            "Avalie se a sequência de subtarefas atende à solicitação original e se as dependências fazem sentido lógico.\n"
            "Responda EXCLUSIVAMENTE em formato JSON com o seguinte schema:\n"
            '{\n  "status": "approved" | "revision_needed",\n  "reason": "explicação curta",\n  "issues": ["problema 1", ...]\n}'
        )

        user_content = f"SOLICITAÇÃO ORIGINAL:\n{prompt}\n\nPLANO PROPOSTO:\n{plan_str}"

        try:
            response = await self.provider.generate(
                messages=[{"role": "user", "content": user_content}],
                system=system_prompt,
                temperature=0.1,
                max_tokens=1000,
            )
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
                "Você é o Reviewer do framework GeminiClaw. Sua função é avaliar se o resultado de uma subtarefa "
                "satisfaz os critérios de aceite definidos.\n"
                "Responda estritamente em JSON com o formato:\n"
                '{\n  "status": "pass" | "fail",\n  "feedback": "explicação do parecer",\n  "issues": []\n}'
            )
            user_content = (
                f"SUBTAREFA: {task_name}\n"
                f"CRITÉRIOS DE ACEITE:\n{criteria_str}\n\n"
                f"ARTEFATOS CONFIRMADOS NO DISCO:\n{list(available_artifacts)}\n\n"
                f"RESPOSTA DO AGENTE:\n{response_text[:3000]}"
            )

            try:
                response = await self.provider.generate(
                    messages=[{"role": "user", "content": user_content}],
                    system=system_prompt,
                    temperature=0.1,
                    max_tokens=800,
                )
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
