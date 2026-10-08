"""Modelo estruturado do relatório final (V16 / ``v16-pipeline-robustness`` §6).

Os dados do relatório (metadados, tabela de resultados, interações, divergências, artefatos) vêm do
disco e da telemetria e são renderizados de forma determinística. O Summarizer só produz a
narrativa, em JSON validado: nenhum número passa por LLM (AGENTS.md, princípio 6).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from src.utils.json_parser import extract_json

NARRATIVE_FIELDS = (
    "resumo_executivo",
    "contexto_e_objetivo",
    "metodologia",
    "analise_divergencias",
    "limitacoes",
    "proximos_passos",
    "confianca_nivel",
    "confianca_justificativa",
)
CONFIDENCE_LEVELS = ("alto", "medio", "baixo")


@dataclass(frozen=True)
class ReportMetadata:
    """Metadados de execução, todos medidos (nunca estimados por LLM)."""

    duration_s: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    agent_runs: dict[str, int] = field(default_factory=dict)
    sandbox_runs: int = 0
    models_by_role: dict[str, str] = field(default_factory=dict)
    stop_reason: str | None = None
    replans: int = 0


@dataclass(frozen=True)
class ResultRow:
    """Uma métrica de uma subtarefa, com a origem em disco."""

    task_name: str
    metric: str
    value: float | str
    expected: float | None
    divergence_pct: float | None
    source: str


@dataclass(frozen=True)
class ReportData:
    """Dados do relatório, montados sem LLM."""

    title: str
    request: str
    metadata: ReportMetadata
    results: list[ResultRow] = field(default_factory=list)
    divergences: list[dict[str, Any]] = field(default_factory=list)
    interactions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    narrativa_indisponivel: bool = False
    # v18.5-research-data-ingestion: marcações dos arquivos de input_context/ (payload["research_data_markings"]).
    research_data: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializa para ``report_data.json``."""
        return asdict(self)


@dataclass(frozen=True)
class Narrative:
    """Texto livre produzido pelo Summarizer."""

    resumo_executivo: str
    contexto_e_objetivo: str
    metodologia: str
    analise_divergencias: str
    limitacoes: str
    proximos_passos: str
    confianca_nivel: str
    confianca_justificativa: str


class NarrativeError(ValueError):
    """A resposta do Summarizer não é uma narrativa válida."""


def parse_narrative(text: str) -> Narrative:
    """Valida o JSON de narrativa devolvido pelo Summarizer.

    Raises:
        NarrativeError: Se não houver JSON de objeto, faltar campo ou o nível de confiança for inválido.
    """
    data = extract_json(text or "")
    if not isinstance(data, dict):
        raise NarrativeError("a resposta não contém um objeto JSON")
    missing = [f for f in NARRATIVE_FIELDS if f not in data]
    if missing:
        raise NarrativeError("campos ausentes: " + ", ".join(missing))
    values = {f: str(data[f]).strip() for f in NARRATIVE_FIELDS}
    values["confianca_nivel"] = values["confianca_nivel"].lower().replace("é", "e")
    if values["confianca_nivel"] not in CONFIDENCE_LEVELS:
        raise NarrativeError("confianca_nivel deve ser alto, medio ou baixo")
    empty = [f for f, v in values.items() if not v]
    if empty:
        raise NarrativeError("campos vazios: " + ", ".join(empty))
    return Narrative(**values)


def unavailable_narrative(error: str) -> Narrative:
    """Narrativa marcada como indisponível, sem texto inventado."""
    note = f"[narrativa indisponível: {error}]"
    return Narrative(**{f: note for f in NARRATIVE_FIELDS if f != "confianca_nivel"}, confianca_nivel="baixo")


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_results(metrics_by_task: dict[str, dict[str, Any]], sources: dict[str, str] | None = None) -> list[ResultRow]:
    """Monta a tabela de resultados a partir dos ``metrics.json`` lidos do disco."""
    rows: list[ResultRow] = []
    for task_name, data in sorted(metrics_by_task.items()):
        metrics = data.get("metrics") or {}
        expected = data.get("expected") or data.get("expected_metrics") or {}
        source = (sources or {}).get(task_name, f"{task_name}/metrics.json")
        for metric, value in metrics.items():
            exp = _number(expected.get(metric)) if isinstance(expected, dict) else None
            actual = _number(value)
            divergence = None
            if exp not in (None, 0.0) and actual is not None:
                divergence = round((actual - exp) / abs(exp) * 100, 2)
            rows.append(ResultRow(task_name, str(metric), value, exp, divergence, source))
    return rows


def build_report_data(
    *,
    title: str,
    request: str,
    metrics_by_task: dict[str, dict[str, Any]],
    metadata: ReportMetadata,
    interactions: list[dict[str, Any]] | None = None,
    divergence_reports: list[dict[str, Any]] | None = None,
    artifacts: list[str] | None = None,
    references: list[dict[str, Any]] | None = None,
    research_data: list[dict[str, Any]] | None = None,
) -> ReportData:
    """Reúne os dados do relatório. Divergências incluem as notas de ``metrics.json``."""
    divergences = list(divergence_reports or [])
    for task_name, data in sorted(metrics_by_task.items()):
        note = data.get("divergence_note")
        if note:
            divergences.append({"task_name": task_name, "divergence_note": note,
                                "investigation_notes": data.get("investigation_notes") or []})
    return ReportData(
        title=title,
        request=request,
        metadata=metadata,
        results=build_results(metrics_by_task),
        divergences=divergences,
        interactions=list(interactions or []),
        artifacts=list(artifacts or []),
        references=list(references or []),
        research_data=list(research_data or []),
    )


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _results_table(data: ReportData) -> str:
    if not data.results:
        return "Nenhum `metrics.json` foi encontrado nas subtarefas desta sessão."
    lines = ["| Subtarefa | Métrica | Valor | Valor Esperado | Divergência (%) | Origem |", "|---|---|---|---|---|---|"]
    for r in data.results:
        expected = "—" if r.expected is None else _fmt(r.expected)
        divergence = "—" if r.divergence_pct is None else _fmt(r.divergence_pct)
        lines.append(f"| {r.task_name} | {r.metric} | {_fmt(r.value)} | {expected} | {divergence} | {r.source} |")
    return "\n".join(lines)


def _interactions_section(data: ReportData) -> str:
    if not data.interactions:
        return "Nenhuma interação com o pesquisador: a sessão foi totalmente autônoma."
    blocks = []
    for i, item in enumerate(data.interactions, start=1):
        blocks.append(
            f"{i}. **Pergunta:** {item.get('question', '')}\n"
            f"   - **Resposta:** {item.get('researcher_response', item.get('answer', item.get('resposta', '')))}\n"
            f"   - **Respondido por:** {item.get('respondido_por', item.get('answered_by', 'pesquisador'))}"
        )
    return "\n".join(blocks)


def _cell(value: Any) -> str:
    """Texto de uma célula de tabela Markdown: sem quebras de linha e com ``|`` escapado."""
    text = str(value) if value not in (None, "") else "—"
    return text.replace("\n", " ").replace("|", "\\|")


def _research_data_section(data: ReportData) -> str:
    """Marcações dos dados de entrada, geradas do payload da sessão (sem LLM)."""
    if not data.research_data:
        return "Nenhum arquivo em `input_context/` nesta sessão."
    lines = [
        "| Arquivo | Classe | Marcação | Motivo | Origem |",
        "|---|---|---|---|---|",
    ]
    for item in data.research_data:
        cells = (
            item.get("caminho"), item.get("classe_efetiva"), item.get("marcacao"), item.get("motivo"),
            item.get("origem"),
        )
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines)


def _divergence_section(data: ReportData, narrative: Narrative) -> str:
    facts = []
    for d in data.divergences:
        facts.append(f"- `{d.get('task_name', '?')}`: {d.get('divergence_note') or d.get('summary') or d}")
    head = "\n".join(facts) if facts else "Nenhuma divergência foi registrada nesta sessão."
    return f"{head}\n\n{narrative.analise_divergencias}"


def _metadata_section(data: ReportData, narrative: Narrative) -> str:
    m = data.metadata
    runs = ", ".join(f"{role}: {n}" for role, n in sorted(m.agent_runs.items())) or "nenhuma"
    models = ", ".join(f"{role}: {model}" for role, model in sorted(m.models_by_role.items())) or "não registrado"
    lines = [
        f"- **Duração**: {m.duration_s:.0f} s",
        f"- **Consumo de Tokens**: {m.tokens_in} de entrada, {m.tokens_out} de saída",
        f"- **Custo Estimado**: US$ {m.cost_usd:.4f}",
        f"- **Execuções de agente**: {runs}",
        f"- **Execuções no sandbox**: {m.sandbox_runs}",
        f"- **Modelos por papel**: {models}",
        f"- **Replanejamentos**: {m.replans}",
    ]
    if m.stop_reason:
        lines.append(f"- **Motivo de parada**: {m.stop_reason}")
    lines.append(f"- **Nível de Confiança Consolidado**: {narrative.confianca_nivel} — {narrative.confianca_justificativa}")
    return "\n".join(lines)


def render_report_markdown(data: ReportData, narrative: Narrative) -> str:
    """Renderiza ``relatorio_final.md`` de forma determinística (dez seções fixas, nesta ordem)."""
    refs = ""
    if data.references:
        refs = "\n\n### Referências\n" + "\n".join(
            f"[{i}] {r.get('title', 'Sem título')} — {r.get('url', '')}" for i, r in enumerate(data.references, 1)
        )
    sections = [
        f"# {data.title}",
        f"## Resumo Executivo\n{narrative.resumo_executivo}",
        f"## Contexto e Objetivo\n**Solicitação:** {data.request}\n\n{narrative.contexto_e_objetivo}",
        f"## Metodologia\n{narrative.metodologia}",
        f"## Resultados\n{_results_table(data)}",
        f"## Análise das Divergências\n{_divergence_section(data, narrative)}",
        f"## Decisões do Pesquisador\n{_interactions_section(data)}",
        f"## Limitações Identificadas\n{narrative.limitacoes}",
        f"## Próximos Passos Sugeridos\n{narrative.proximos_passos}{refs}",
        f"## Dados de Entrada e Marcações\n{_research_data_section(data)}",
        f"## Metadados de Execução\n{_metadata_section(data, narrative)}",
    ]
    return "\n\n".join(sections) + "\n"


def report_data_json(data: ReportData) -> str:
    """JSON de ``report_data.json`` (auditoria e avaliação de comunicação)."""
    return json.dumps(data.to_dict(), ensure_ascii=False, indent=2, default=str)
