"""Definição de output estruturado de subtarefas para o GeminiClaw.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any, List, Dict, Optional

@dataclass
class SubtaskOutput:
    """Output estruturado de uma subtarefa para propagação via DAG.
    
    Args:
        task_name: Nome único da subtarefa no plano.
        agent_id: Identificador do agente que executou a tarefa.
        status: Status da execução ("success", "error", "timeout").
        text_summary: Resumo textual do resultado (truncado se necessário).
        artifacts: Lista de metadados de artefatos gerados.
        sources: Lista de fontes citadas com URLs.
        data_points: Dados quantitativos extraídos (opcional).
        confidence: Nível de confiança do resultado (0.0 a 1.0).
        validation_results: Resultados detalhados da revisão (se houver).
    """
    task_name: str
    agent_id: str
    status: str
    text_summary: str = ""
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    data_points: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    validation_results: List[Dict[str, Any]] = field(default_factory=list)
    artifact_aliases: Dict[str, str] = field(default_factory=dict)  # esperado -> caminho real
    # v18.5-egress-gate: o texto veio de modelo que aceita dados brutos (contaminado, ADR 019 §3.8). ``None`` = sem
    # marca (resultado anterior à V18.5): vale a regra de texto legado.
    tainted: Optional[bool] = None

    def to_json(self) -> str:
        """Serializa o objeto para JSON."""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "SubtaskOutput":
        """Reconstrói o objeto a partir de uma string JSON."""
        data = json.loads(json_str)
        return cls(**data)

    def to_context_string(self) -> str:
        """Converte o output em uma string de contexto formatada para outro agente."""
        lines = [f"### Resultado de `{self.task_name}` (Agente: {self.agent_id})"]
        
        if self.text_summary:
            from src.egress.persisted import tag_text

            lines.append(f"**Resumo:**\n{tag_text(self.text_summary, self.tainted)}")
        
        if self.sources:
            lines.append("**Fontes Principais:**")
            for src in self.sources[:5]:  # Limita as 5 principais fontes para poupar tokens
                title = src.get("title", "Sem título")
                url = src.get("url", "#")
                lines.append(f"- [{title}]({url})")
        
        if self.artifacts:
            lines.append("**Artefatos Gerados:**")
            from src.egress.fragments import mark_artifact_names

            names = [f"- `{art.get('name', 'arquivo')}` em `{art.get('path', '')}`" for art in self.artifacts]
            lines.append(mark_artifact_names("\n".join(names)))

        if self.artifact_aliases:
            lines.append("**Arquivos produzidos (esperado → real):**")
            from src.egress.fragments import mark_artifact_names

            aliases = [f"- {expected} → {real}" for expected, real in self.artifact_aliases.items()]
            lines.append(mark_artifact_names("\n".join(aliases)))

        return "\n".join(lines)

    @classmethod
    def from_agent_result(cls, task_name: str, agent_id: str, result: Any, review_data: Optional[Dict[str, Any]] = None) -> "SubtaskOutput":
        """Cria um SubtaskOutput a partir do resultado de um agente e dados de revisão."""
        from src.egress.gate import role_tainted
        from src.utils.json_parser import extract_json

        text = result.response.get("text", "")
        status = result.status
        
        # Tenta extrair fontes e artefatos do texto via heurística simples ou se o agente retornou JSON
        sources = []
        artifacts = []
        
        # Se o texto for JSON, parseia
        json_data = extract_json(text)
        if json_data and isinstance(json_data, dict):
            text_summary = json_data.get("summary", json_data.get("text", text[:2000]))
            sources = json_data.get("sources", [])
            artifacts = json_data.get("artifacts", [])
        else:
            text_summary = text[:2000] # Truncagem conservadora

        # Dados da revisão
        confidence = 1.0
        validation_results = []
        if review_data:
            confidence = review_data.get("confidence", 1.0)
            validation_results = review_data.get("criteria_results", [])
            if review_data.get("status") == "fail":
                status = "failed_review"

        return cls(
            task_name=task_name,
            agent_id=agent_id,
            status=status,
            text_summary=text_summary,
            sources=sources,
            artifacts=artifacts,
            confidence=confidence,
            validation_results=validation_results,
            artifact_aliases=dict((review_data or {}).get("resolved_artifacts") or {}),
            tainted=role_tainted(agent_id),
        )
