"""Tipos de tarefa e resultado de agente.

Movidos de ``src/orchestration/orchestrator.py`` sem alterar o corpo (ADR 024 §2).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTask:
    """Definição de uma tarefa a ser executada por um agente.

    Args:
        agent_id: Identificador do agente.
        prompt: Prompt/solicitação a ser enviada ao agente.
        task_name: Identificador único da subtarefa no plano (snake_case).
        depends_on: Lista de task_names que devem concluir antes desta tarefa.
        expected_artifacts: Lista de artefatos esperados como output.
    """

    agent_id: str
    prompt: str
    task_name: str = ""
    depends_on: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    validation_criteria: list[str] = field(default_factory=list)
    preferred_model: str | None = None
    subtask_id: str | None = None  # V9: ID único para telemetria
    created_at: str | None = None  # V9: Timestamp de criação
    retry_attempt: int = 0  # V12.3.3: Número da tentativa atual (0-indexed)
    mode: str = ""  # V15.6/G10: SessionMode ("assisted" | "semi" | "auto")
    # V15.1/G1: metadados de epistemologia científica gerados pelo Researcher
    task_type: str | None = None  # "reproduction" | "eda" | "model_impl" | "validation" | "synthesis"
    hypothesis: str = ""  # o que esta subtarefa testa ou produz
    scientific_rationale: str = ""  # por que esta etapa é metodologicamente necessária
    # v17-structural-fact-ingestion: abordagem declarada pelo Researcher ({"nome", "tipo", "descricao"?}).
    approach: dict[str, str] | None = None
    # v18-hypothesis-loop: referência do plano à hipótese que a subtarefa testa e o ``id`` resolvido no grafo.
    hypothesis_ref: str = ""
    hypothesis_id: str = ""
    # v18.5-egress-gate: o ``prompt`` foi escrito por um modelo que aceita dados brutos (contaminado, ADR 019 §3.8);
    # o despacho o envolve na marca de contaminação ao montar o prompt da execução.
    prompt_tainted: bool = False


@dataclass
class AgentResult:
    """Resultado da execução de um agente.

    Args:
        agent_id: Identificador do agente.
        session_id: ID da sessão associada.
        status: Status da execução ("success", "error", "timeout").
        response: Payload da resposta do agente.
        error: Mensagem de erro, se houver.
        error_category: Categoria estruturada da falha de infraestrutura, se conhecida.
    """

    agent_id: str
    session_id: str
    status: str
    response: dict[str, Any]
    error: str | None = None
    # Categoria estruturada de falha de infraestrutura (``llm_connection``); ``None`` quando
    # desconhecida. Usada pela ingestão de fatos (v17-structural-fact-ingestion), sem heurística de texto.
    error_category: str | None = None
