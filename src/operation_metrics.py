"""Métricas de operação por sessão (v18.5-operation-metrics, design §1, §4 e §5).

Agrega, por leitores injetáveis, os cinco grupos de métricas da sessão (egresso, proveniência, verificação, custo e
recursos, intervenções humanas) mais o bloco do modo sem limite. A agregação é determinística e **sem LLM**: o relatório
recebe a seção pronta (``render_operation_metrics_section``), delimitada para que o verificador de números a trate como
contagens do orquestrador.

Cada grupo tem um ``estado``: ``disponivel``, ``indisponivel`` (produtor não implementado, desligado ou que ainda não
rodou nesta sessão) ou ``erro`` (falha de leitura). Grupos ``indisponivel`` ou ``erro`` não têm valores numéricos
(AGENTS.md §1.6: nenhum zero inventado); uma falha nunca impede os outros grupos nem o fechamento da sessão.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from src.logger import get_logger

logger = get_logger(__name__)

VERSION = 1
BEGIN_MARK = "<!-- operation-metrics:begin -->"
END_MARK = "<!-- operation-metrics:end -->"
SECTION_TITLE = "Métricas de operação"

STATE_OK = "disponivel"
STATE_UNAVAILABLE = "indisponivel"
STATE_ERROR = "erro"

GROUPS: tuple[str, ...] = ("egresso", "proveniencia", "verificacao", "custo_recursos", "intervencoes_humanas")


class MetricsUnavailable(Exception):
    """O produtor do grupo não existe, está desligado ou ainda não produziu dados para esta sessão."""

    def __init__(self, message: str, producer: str = "") -> None:
        super().__init__(message)
        self.producer = producer


class MetricsGroupReader(Protocol):
    """Leitor de um grupo de métricas. Várias instâncias podem alimentar o mesmo grupo (as chaves são mescladas)."""

    group: str
    producer: str

    def read(self, session_id: str) -> dict[str, Any]:
        """Valores do grupo para a sessão; levanta :class:`MetricsUnavailable` se o produtor não tem dados."""
        ...


def _producer(reader: Any) -> str:
    return str(getattr(reader, "producer", "") or type(reader).__name__)


def _empty_group(state: str, **extra: Any) -> dict[str, Any]:
    return {"estado": state, **extra}


def _aggregate_group(group: str, session_id: str, readers: Sequence[Any]) -> dict[str, Any]:
    """Mescla os leitores do grupo: ``disponivel`` se ao menos um leu; lacunas dos outros ficam em ``lacunas``."""
    merged: dict[str, Any] = {}
    lacunas: list[dict[str, str]] = []
    errors: list[str] = []
    ok = 0
    for reader in readers:
        producer = _producer(reader)
        try:
            values = reader.read(session_id)
        except MetricsUnavailable as exc:
            lacunas.append({"produtor": exc.producer or producer, "motivo": str(exc)})
        except FileNotFoundError as exc:  # o produtor não gerou o arquivo desta sessão (ainda não rodou)
            lacunas.append({"produtor": producer, "motivo": f"sem dados nesta sessão ({exc.filename or exc})"})
        except Exception as exc:  # noqa: BLE001 - falha de leitura de um grupo não bloqueia os demais
            logger.error(
                "Falha ao ler o grupo de métricas de operação",
                extra={"group": group, "producer": producer, "error": type(exc).__name__, "session_id": session_id},
            )
            errors.append(f"{producer}: {type(exc).__name__}: {exc}")
        else:
            ok += 1
            merged.update(values)
    if ok:
        result = {"estado": STATE_OK, **merged}
        if lacunas or errors:
            result["lacunas"] = lacunas + [{"produtor": "?", "motivo": f"erro de leitura: {e}"} for e in errors]
        return result
    if errors:
        return _empty_group(STATE_ERROR, mensagem="; ".join(errors))
    if not readers:
        return _empty_group(STATE_UNAVAILABLE, produtor="nenhum leitor registrado", motivo="produtor não implementado")
    return _empty_group(
        STATE_UNAVAILABLE,
        produtor=", ".join(sorted({entry["produtor"] for entry in lacunas})),
        motivo="; ".join(entry["motivo"] for entry in lacunas),
    )


def aggregate_operation_metrics(
    session_id: str,
    *,
    parcial: bool,
    readers: Sequence[MetricsGroupReader] | None = None,
    unlimited: dict[str, Any] | None = None,
    now: Callable[[], datetime] | None = None,
    on_error: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Agrega as métricas de operação da sessão (idempotente: recalcular sobrescreve).

    Args:
        session_id: Sessão mestra.
        parcial: ``True`` quando a sessão não fechou (avisos periódicos, ``--metrics`` de sessão interrompida).
        readers: Leitores (padrão: ``default_readers()``).
        unlimited: Bloco ``modo_sem_limite`` já calculado (ver :func:`unlimited_block`).
        now: Relógio (injetável em testes).
        on_error: Chamado com ``(grupo, mensagem)`` por grupo em ``erro`` (telemetria ``operation_metrics_error``).

    Returns:
        Dicionário no formato do design §1.1.
    """
    readers = list(readers) if readers is not None else default_readers()
    result: dict[str, Any] = {
        "versao": VERSION,
        "gerado_em": (now or (lambda: datetime.now(timezone.utc)))().isoformat(),
        "parcial": bool(parcial),
    }
    for group in GROUPS:
        outcome = _aggregate_group(group, session_id, [r for r in readers if r.group == group])
        result[group] = outcome
        if outcome["estado"] == STATE_ERROR and on_error is not None:
            on_error(group, str(outcome.get("mensagem", "")))
    result["modo_sem_limite"] = unlimited or {
        "ativo": False, "origem": None, "confirmado_em": None, "avisos_emitidos": 0,
    }
    return result


# -- leitores padrão ----------------------------------------------------------------------------------


class EgressMetricsReader:
    """Grupo ``egresso``: lê ``egress_log`` por sessão (produtor: ``v18.5-egress-gate``)."""

    group = "egresso"
    producer = "v18.5-egress-gate"

    def __init__(self, budget_loader: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._budget_loader = budget_loader

    def read(self, session_id: str) -> dict[str, Any]:
        from src.db import get_connection

        with get_connection() as conn:
            destinations = conn.execute(
                """
                SELECT provedor, modelo, trust, localidade, SUM(bytes_enviados) AS bytes, COUNT(*) AS chamadas
                FROM egress_log WHERE session_id = %s AND NOT recusado
                GROUP BY provedor, modelo, trust, localidade ORDER BY provedor, modelo
                """,
                (session_id,),
            ).fetchall()
            origins = conn.execute(
                """
                SELECT f->>'origem' AS origem, SUM((f->>'bytes')::bigint) AS bytes
                FROM egress_log e, jsonb_array_elements(e.fragmentos) AS f
                WHERE e.session_id = %s AND NOT e.recusado GROUP BY 1
                """,
                (session_id,),
            ).fetchall()
            interventions = conn.execute(
                """
                SELECT k AS tipo, SUM(v::bigint) AS n
                FROM egress_log e, jsonb_each_text(e.intervencoes) AS t(k, v)
                WHERE e.session_id = %s GROUP BY k ORDER BY k
                """,
                (session_id,),
            ).fetchall()
            canais = conn.execute(
                "SELECT canal, COUNT(*) AS n FROM egress_log WHERE session_id = %s AND NOT recusado GROUP BY canal",
                (session_id,),
            ).fetchall()
            refused = conn.execute(
                "SELECT COUNT(*) AS n FROM egress_log WHERE session_id = %s AND recusado", (session_id,)
            ).fetchone()
        by_channel = {row["canal"]: int(row["n"]) for row in canais}
        origin_bytes = {str(row["origem"]): int(row["bytes"] or 0) for row in origins}
        limit = None
        if self._budget_loader is not None:
            limit = (self._budget_loader(session_id) or {}).get("max_egress_bytes")
        return {
            # "Egresso" = bytes enviados a destinos fora do nó; destinos no nó aparecem em ``por_destino``.
            "bytes_total": sum(int(row["bytes"] or 0) for row in destinations if row["localidade"] == "fora_do_no"),
            "por_destino": [
                {
                    "provedor": row["provedor"], "modelo": row["modelo"], "trust": row["trust"],
                    "localidade": row["localidade"], "bytes": int(row["bytes"] or 0), "chamadas": int(row["chamadas"]),
                }
                for row in destinations
            ],
            "por_origem": origin_bytes,
            "intervencoes_filtro": {row["tipo"]: int(row["n"]) for row in interventions},
            "consultas_busca": by_channel.get("busca", 0),
            "chamadas_visao": by_channel.get("visao", 0),
            "envios_recusados": int(refused["n"]) if refused else 0,
            "limite_bytes": limit,
        }


class ProvenanceChainReader:
    """Grupo ``proveniencia`` (``cadeia``): verificação da cadeia de execuções (``v18.5-execution-provenance``)."""

    group = "proveniencia"
    producer = "v18.5-execution-provenance"

    def read(self, session_id: str) -> dict[str, Any]:
        from src.provenance.ledger import get_ledger
        from src.provenance.verify import verify_session

        ledger = get_ledger()
        try:
            reports = verify_session(ledger.store, session_id, ledger.output_dir)
        except Exception as exc:  # noqa: BLE001 - armazenamento indisponível: a cadeia não pôde ser verificada
            raise MetricsUnavailable(f"cadeia não verificada ({type(exc).__name__})", self.producer) from exc
        if not reports:
            raise MetricsUnavailable("a sessão não registrou execuções", self.producer)
        integra = all(report.integra for report in reports)
        orphans = [o for report in reports for o in report.orfas]
        tip = reports[-1].ponta
        return {
            "cadeia": {
                "resultado": "integra" if integra else "divergente",
                "orfas": len(orphans),
                "pendentes": sum(1 for o in orphans if o.get("classe") == "pendente_local"),
                "ponta": tip["record_hash"] if tip else None,
            }
        }


class PlanRejectionReader:
    """Grupo ``verificacao`` (``ciclos_rejeicao_plano``): planos reprovados (eventos ``plan_validation``)."""

    group = "verificacao"
    producer = "orquestrador (plan_validation)"

    def read(self, session_id: str) -> dict[str, Any]:
        from src.telemetry import get_telemetry

        events = get_telemetry().get_events(session_id, "plan_validation")
        return {"ciclos_rejeicao_plano": sum(1 for e in events if not (e.get("payload") or {}).get("approved", True))}


class CostResourcesReader:
    """Grupo ``custo_recursos``: tokens e custo por tarefa e papel, hardware do nó (telemetria existente)."""

    group = "custo_recursos"
    producer = "telemetria"

    def read(self, session_id: str) -> dict[str, Any]:
        from src.telemetry import get_telemetry

        telemetry = get_telemetry()
        rows = telemetry.get_usage_by_task(session_id)
        peaks = telemetry.get_hardware_peaks(session_id)
        avg_cpu = telemetry.get_average_cpu(session_id)

        def cost(values: list[Any]) -> float | None:  # nunca soma custo ausente como zero
            known = [float(v) for v in values if v is not None]
            return round(sum(known), 6) if known else None

        per_role: dict[str, dict[str, Any]] = {}
        for row in rows:
            entry = per_role.setdefault(str(row["agent_id"]), {"tokens": 0, "custos": []})
            entry["tokens"] += int(row["tokens"] or 0)
            entry["custos"].append(row["cost_usd"])
        return {
            "tokens_total": sum(int(r["tokens"] or 0) for r in rows),
            "custo_usd_total": cost([r["cost_usd"] for r in rows]),
            "chamadas_sem_custo": sum(int(r.get("calls_sem_custo") or 0) for r in rows),
            "por_tarefa": [
                {
                    "task_name": r["task_name"], "agent_id": r["agent_id"], "tokens": int(r["tokens"] or 0),
                    "custo_usd": cost([r["cost_usd"]]),
                }
                for r in rows
            ],
            "por_papel": [
                {"agent_id": role, "tokens": entry["tokens"], "custo_usd": cost(entry["custos"])}
                for role, entry in sorted(per_role.items())
            ],
            "no": {
                "cpu_pct_medio": round(avg_cpu, 1) if avg_cpu is not None else None,
                "cpu_pct_pico": peaks.get("max_cpu_pct"),
                "ram_pct_pico": peaks.get("max_mem_pct"),
                "ram_disponivel_min_mb": peaks.get("min_mem_available_mb"),
                "temperatura_pico_c": peaks.get("max_temp_c"),
                "incidentes_throttling": int(peaks.get("throttle_incidents") or 0),
            },
        }


class JudgeIndependenceReader:
    """Grupo ``verificacao``: independência do julgamento (ADR 020), lida do payload da sessão.

    Sessões sem o registro (anteriores a v18.6-validator-independence) ficam como lacuna, nunca como "atendida".
    """

    group = "verificacao"
    producer = "independencia_julgamento"

    def __init__(self, payload_loader: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._payload_loader = payload_loader

    def read(self, session_id: str) -> dict[str, Any]:
        if self._payload_loader is None:
            raise MetricsUnavailable("payload da sessão indisponível", self.producer)
        payload = self._payload_loader(session_id) or {}
        record = payload.get("independencia_julgamento")
        if not isinstance(record, dict):
            raise MetricsUnavailable("sessão sem o registro independencia_julgamento", self.producer)
        events = [e for e in (payload.get("eventos_independencia_julgamento") or []) if isinstance(e, dict)]
        validator = record.get("validator") or {}
        developer = record.get("developer") or {}
        return {
            "independencia_julgamento_modo": record.get("modo"),
            "independencia_julgamento_atendida": record.get("atendida"),
            "independencia_julgamento_rejeicoes": sum(1 for e in events if e.get("decisao") == "rejeitado"),
            "independencia_julgamento_familias": {
                "validator": validator.get("familia"), "developer": developer.get("familia"),
            },
        }


class HumanInterventionsReader:
    """Grupo ``intervencoes_humanas``: o que o pesquisador fez na sessão.

    Fontes: ``researcher_interactions`` e ``divergence_reports`` do payload da sessão, e os eventos
    ``researcher_interruption`` e ``unlimited_*``. Aprovações, rejeições e edições de hipótese/oportunidade vivem no
    grafo, sem vínculo com a sessão: ficam ``None`` (não medidas), nunca zero.
    """

    group = "intervencoes_humanas"
    producer = "sessão e telemetria"

    def __init__(self, payload_loader: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._payload_loader = payload_loader

    def read(self, session_id: str) -> dict[str, Any]:
        from src.telemetry import get_telemetry

        if self._payload_loader is None:
            raise MetricsUnavailable("payload da sessão indisponível", self.producer)
        payload = self._payload_loader(session_id) or {}
        telemetry = get_telemetry()
        interactions = payload.get("researcher_interactions") or []
        answered = [i for i in interactions if i.get("respondido_por", "pesquisador") == "pesquisador"]
        interruptions = telemetry.get_events(session_id, "researcher_interruption")
        suspensions = payload.get("suspensoes")
        events = [
            {
                "tipo": "resposta_ask_researcher", "em": i.get("timestamp") or i.get("answered_at"),
                "referencia": i.get("subtask_name") or "",
            }
            for i in answered
        ] + [
            {"tipo": "interrupcao", "em": e["timestamp"], "referencia": e.get("task_name") or ""} for e in interruptions
        ]
        decisions = [r for r in (payload.get("divergence_reports") or []) if isinstance(r, dict) and r.get("decisao")]
        return {
            "aprovacoes": None,
            "rejeicoes": None,
            "edicoes": None,
            "respostas_ask_researcher": len(answered),
            "decisoes_divergencia": len(decisions) if decisions else None,
            "suspensoes": int(suspensions) if isinstance(suspensions, int) else None,
            "interrupcoes": len(interruptions),
            "eventos": events,
        }


def default_readers(
    output_dir: Path | str | None = None,
    *,
    payload_loader: Callable[[str], dict[str, Any]] | None = None,
) -> list[MetricsGroupReader]:
    """Leitores padrão: um por produtor (cada mudança produtora registra o seu aqui)."""
    from src.claims.metrics import ClaimVerificationReader
    from src.numeric_refs.provenance_file import NumericProvenanceReader

    if output_dir is None:
        from src import config

        output_dir = config.OUTPUT_BASE_DIR

    def budget_of(session_id: str) -> dict[str, Any]:
        return ((payload_loader(session_id) or {}).get("budget") or {}) if payload_loader else {}

    return [
        EgressMetricsReader(budget_loader=budget_of),
        NumericProvenanceReader(output_dir),
        ProvenanceChainReader(),
        ClaimVerificationReader(output_dir),
        PlanRejectionReader(),
        CostResourcesReader(),
        HumanInterventionsReader(payload_loader),
        JudgeIndependenceReader(payload_loader),
    ]


def unlimited_block(budget_payload: dict[str, Any] | None, notices: int) -> dict[str, Any]:
    """Bloco ``modo_sem_limite`` a partir de ``payload["budget"]`` e da contagem de avisos emitidos."""
    budget_payload = budget_payload or {}
    active = bool(budget_payload.get("unlimited"))
    return {
        "ativo": active,
        "origem": budget_payload.get("unlimited_origem") if active else None,
        "confirmado_em": budget_payload.get("unlimited_confirmado_em") if active else None,
        "avisos_emitidos": int(notices),
    }


# -- renderização -------------------------------------------------------------------------------------


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/d"
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, int):
        return f"{value:,}{suffix}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _unavailable_line(title: str, group: dict[str, Any]) -> str:
    if group["estado"] == STATE_ERROR:
        return f"- **{title}:** erro de leitura: {group.get('mensagem', '')}"
    return f"- **{title}:** indisponível ({group.get('produtor', '?')}: {group.get('motivo', 'sem dados')})"


def _gaps(group: dict[str, Any]) -> list[str]:
    return [f"  - parcial: {g['produtor']}: {g['motivo']}" for g in group.get("lacunas", [])]


def render_operation_metrics_section(metrics: dict[str, Any], *, stop_reason: str | None = None) -> str:
    """Seção Markdown determinística "Métricas de operação", delimitada para o verificador de números."""
    lines = [BEGIN_MARK, f"## {SECTION_TITLE}", ""]
    unlimited = metrics.get("modo_sem_limite") or {}
    if unlimited.get("ativo"):
        lines.append(
            f"- **Modo:** SEM LIMITE (origem: {unlimited.get('origem')}, "
            f"confirmado em {unlimited.get('confirmado_em')}); "
            f"avisos de consumo emitidos: {_fmt(unlimited.get('avisos_emitidos'))}"
        )
    else:
        lines.append("- **Modo:** com limites de orçamento")
    if stop_reason:
        lines.append(f"- **Motivo de parada:** {stop_reason}")
    if metrics.get("parcial"):
        lines.append("- **Aviso:** métricas parciais (a sessão não foi fechada normalmente).")

    egress = metrics["egresso"]
    if egress["estado"] != STATE_OK:
        lines.append(_unavailable_line("Egresso", egress))
    else:
        limit = egress.get("limite_bytes")
        lines.append(
            f"- **Egresso:** {_fmt(egress['bytes_total'], ' bytes')} enviados fora do nó "
            f"(limite: {'sem limite' if limit is None else _fmt(limit, ' bytes')}); "
            f"buscas: {_fmt(egress['consultas_busca'])}; chamadas de visão: {_fmt(egress['chamadas_visao'])}; "
            f"envios recusados: {_fmt(egress.get('envios_recusados'))}"
        )
        lines.extend(_gaps(egress))
        for dest in egress["por_destino"]:
            lines.append(
                f"  - {dest['provedor']}/{dest['modelo']} ({dest['trust']}, {dest['localidade']}): "
                f"{_fmt(dest['bytes'], ' bytes')} em {_fmt(dest['chamadas'])} chamadas"
            )
        if egress["por_origem"]:
            origins = "; ".join(f"{k}={_fmt(v)}" for k, v in sorted(egress["por_origem"].items()))
            lines.append(f"  - por origem: {origins}")
        if egress["intervencoes_filtro"]:
            lines.append(
                "  - intervenções do filtro: "
                + "; ".join(f"{k}={_fmt(v)}" for k, v in sorted(egress["intervencoes_filtro"].items()))
            )

    prov = metrics["proveniencia"]
    if prov["estado"] != STATE_OK:
        lines.append(_unavailable_line("Proveniência", prov))
    else:
        origins = prov.get("numeros_por_origem")
        chain = prov.get("cadeia")
        numbers = (
            "números por origem: " + "; ".join(f"{k}={_fmt(v)}" for k, v in origins.items())
            + f"; não verificados: {_fmt(prov.get('numeros_nao_verificados'))}; "
            f"métricas literais: {_fmt(prov.get('metricas_literais'))}"
            if origins is not None else "números: indisponível"
        )
        chain_text = (
            f"cadeia {chain['resultado']} (órfãs: {_fmt(chain['orfas'])}, pendentes: {_fmt(chain['pendentes'])})"
            if chain else "cadeia: indisponível"
        )
        lines.append(f"- **Proveniência:** {numbers}; {chain_text}")
        lines.extend(_gaps(prov))

    ver = metrics["verificacao"]
    if ver["estado"] != STATE_OK:
        lines.append(_unavailable_line("Verificação", ver))
    else:
        status = ver.get("afirmacoes_por_status")
        claims = (
            "afirmações: " + "; ".join(f"{k}={_fmt(v)}" for k, v in status.items()) if status is not None
            else "afirmações: indisponível"
        )
        lines.append(f"- **Verificação:** {claims}; planos reprovados: {_fmt(ver.get('ciclos_rejeicao_plano'))}")
        lines.extend(_gaps(ver))
        if ver.get("independencia_julgamento_modo") is not None:
            families = ver.get("independencia_julgamento_familias") or {}
            lines.append(
                f"- **Independência do julgamento:** modo {ver['independencia_julgamento_modo']}; "
                f"{families.get('validator')} (validator) / {families.get('developer')} (developer); "
                f"atendida: {_fmt(ver.get('independencia_julgamento_atendida'))}; "
                f"conferências rejeitadas: {_fmt(ver.get('independencia_julgamento_rejeicoes'))}"
            )
        for cycle in ver.get("ciclos_correcao_conclusoes") or []:
            lines.append(
                f"  - {cycle['conclusao_id']}: {_fmt(cycle['ciclos'])} ciclo(s) de correção, "
                f"aprovada: {_fmt(cycle['aprovada'])}"
            )

    cost = metrics["custo_recursos"]
    if cost["estado"] != STATE_OK:
        lines.append(_unavailable_line("Custo e recursos", cost))
    else:
        node = cost["no"]
        lines.append(
            f"- **Custo e recursos:** {_fmt(cost['tokens_total'])} tokens; custo "
            f"{_fmt(cost['custo_usd_total'], ' USD') if cost['custo_usd_total'] is not None else 'não informado'} "
            f"({_fmt(cost.get('chamadas_sem_custo'))} chamadas sem custo informado); "
            f"CPU média {_fmt(node['cpu_pct_medio'], '%')}, pico {_fmt(node['cpu_pct_pico'], '%')}; "
            f"RAM pico {_fmt(node['ram_pct_pico'], '%')}; "
            f"temperatura pico {_fmt(node['temperatura_pico_c'], ' °C')}; "
            f"throttling: {_fmt(node['incidentes_throttling'])}"
        )
        for role in cost["por_papel"]:
            lines.append(
                f"  - {role['agent_id']}: {_fmt(role['tokens'])} tokens, "
                f"{_fmt(role['custo_usd'], ' USD') if role['custo_usd'] is not None else 'custo não informado'}"
            )

    human = metrics["intervencoes_humanas"]
    if human["estado"] != STATE_OK:
        lines.append(_unavailable_line("Intervenções humanas", human))
    else:
        lines.append(
            f"- **Intervenções humanas:** respostas ao ask_researcher: {_fmt(human['respostas_ask_researcher'])}; "
            f"decisões de divergência: {_fmt(human['decisoes_divergencia'])}; suspensões: {_fmt(human['suspensoes'])}; "
            f"interrupções: {_fmt(human['interrupcoes'])}; aprovações/rejeições/edições: não medidas por sessão"
        )
    lines.extend(["", f"_Gerado em {metrics.get('gerado_em')} (versão {metrics.get('versao')})._", END_MARK])
    return "\n".join(lines)


def render_chain_line(sessions: Sequence[dict[str, Any]]) -> str:
    """Linha informativa da soma da cadeia de sessões continuadas (tokens, custo e egresso; design §5)."""
    tokens = sum(int((s.get("custo_recursos") or {}).get("tokens_total") or 0) for s in sessions)
    costs = [(s.get("custo_recursos") or {}).get("custo_usd_total") for s in sessions]
    known = [c for c in costs if c is not None]
    egress = sum(int((s.get("egresso") or {}).get("bytes_total") or 0) for s in sessions)
    cost_text = f"{sum(known):.2f} USD" if known else "não informado"
    return (
        f"- **Cadeia de {len(sessions)} sessões continuadas (informativo):** {_fmt(tokens)} tokens; custo {cost_text}; "
        f"egresso {_fmt(egress, ' bytes')}"
    )
