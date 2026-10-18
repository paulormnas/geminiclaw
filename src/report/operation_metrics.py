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

VERSION = 2
BEGIN_MARK = "<!-- operation-metrics:begin -->"
END_MARK = "<!-- operation-metrics:end -->"
SECTION_TITLE = "Métricas de operação"

STATE_OK = "disponivel"
STATE_UNAVAILABLE = "indisponivel"
STATE_ERROR = "erro"

GROUPS: tuple[str, ...] = (
    "egresso", "proveniencia", "verificacao", "custo_recursos", "intervencoes_humanas", "exploracao",
)


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


_EXPLORATION_BLOCKS = ("ligacao", "parada", "contrato")


def _exploration_state(group: dict[str, Any]) -> dict[str, Any]:
    """O grupo ``exploracao`` é ``disponivel`` se ao menos um bloco o for; senão ``indisponivel`` (ou ``erro``)."""
    blocks = {name: group[name] for name in _EXPLORATION_BLOCKS if isinstance(group.get(name), dict)}
    if not blocks:
        return group
    states = {block.get("estado") for block in blocks.values()}
    if STATE_OK in states:
        return {**group, "estado": STATE_OK}
    if states == {STATE_ERROR}:
        return {**group, "estado": STATE_ERROR, "mensagem": "; ".join(b.get("mensagem", "") for b in blocks.values())}
    producers = sorted({str(b.get("produtor")) for b in blocks.values() if b.get("produtor")})
    return {**group, "estado": STATE_UNAVAILABLE, "produtor": ", ".join(producers), "motivo": "sem dados de exploração"}


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
        if group == "exploracao":
            outcome = _exploration_state(outcome)
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
        from src.egress.log import egress_bytes_for_session

        # v18.7-benchmark-fixes: a grandeza que o limite de egresso limita (saídas de execução novas), à parte do total.
        limited_bytes = egress_bytes_for_session(session_id)
        limit = None
        if self._budget_loader is not None:
            limit = (self._budget_loader(session_id) or {}).get("max_egress_bytes")
        return {
            # "Egresso" = bytes enviados a destinos fora do nó; destinos no nó aparecem em ``por_destino``.
            "bytes_total": sum(int(row["bytes"] or 0) for row in destinations if row["localidade"] == "fora_do_no"),
            "bytes_limitados": limited_bytes,
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
        # v18.7-benchmark-fixes: a causa da divergência (contagens por tipo de problema e os primeiros arquivos).
        changed = [str(item["caminho"]) for report in reports for item in report.arquivos_alterados]
        return {
            "cadeia": {
                "resultado": "integra" if integra else "divergente",
                "orfas": len(orphans),
                "pendentes": sum(1 for o in orphans if o.get("classe") == "pendente_local"),
                "ponta": tip["record_hash"] if tip else None,
                "motivos": {
                    "cadeia": sum(len(report.problemas_cadeia) for report in reports),
                    "pares": sum(len(report.problemas_pares) for report in reports),
                    "arquivos_alterados": len(changed),
                    "checkpoints_divergentes": sum(len(report.checkpoints_divergentes) for report in reports),
                    "conflitos_pendencia": sum(len(report.conflitos_pendencia) for report in reports),
                },
                "arquivos_alterados_exemplos": changed[:5],
            }
        }


class PlanRejectionReader:
    """Grupo ``verificacao`` (``ciclos_rejeicao_plano``): planos reprovados (eventos ``plan_validation``)."""

    group = "verificacao"
    producer = "orquestrador (plan_validation)"

    def read(self, session_id: str) -> dict[str, Any]:
        from src.observability.telemetry import get_telemetry

        events = get_telemetry().get_events(session_id, "plan_validation")
        return {"ciclos_rejeicao_plano": sum(1 for e in events if not (e.get("payload") or {}).get("approved", True))}


class HypothesisClosureReader:
    """Grupo ``verificacao`` (``v18.6-hypothesis-closure``): resultados sem ``MEDE``, subtarefas com resultado
    negativo e hipóteses sem tentativa no fechamento (eventos ``resultado_sem_mede``, ``subtask_review`` e
    ``hipoteses_sem_tentativa``). ``v18.6-auto-metrics-and-stop-reasons``: fechamento por
    ``hipoteses_nao_testadas`` (evento ``exploration_stop``). O contador ``reprovacoes_sem_hipotese`` deixou de existir
    (ADR 021 §8.1); os contadores de ligação estão no grupo ``exploracao``."""

    group = "verificacao"
    producer = "orquestrador (fechamento de hipóteses)"

    def read(self, session_id: str) -> dict[str, Any]:
        from src.observability.telemetry import get_telemetry

        telemetry = get_telemetry()
        no_mede = telemetry.get_events(session_id, "resultado_sem_mede")
        reviews = telemetry.get_events(session_id, "subtask_review")
        untested = telemetry.get_events(session_id, "hipoteses_sem_tentativa")
        stops = telemetry.get_events(session_id, "exploration_stop")
        negative_tasks = {
            e.get("task_name")
            for e in reviews
            if (e.get("payload") or {}).get("outcome") == "resultado_negativo"
        }
        last = untested[-1] if untested else None
        return {
            "resultados_sem_mede": len(no_mede),
            "subtarefas_resultado_negativo": len(negative_tasks),
            "hipoteses_sem_tentativa_no_fechamento": len((last.get("payload") or {}).get("hipoteses") or [])
            if last
            else 0,
            "fechada_por_hipoteses_nao_testadas": any(
                (e.get("payload") or {}).get("motivo_parada") == STOP_UNTESTED_HYPOTHESES for e in stops
            ),
        }


def _guarded_block(name: str, producer: str, session_id: str, read: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    """Bloco do grupo ``exploracao``: ``indisponivel`` com o produtor, ou ``erro``, sem derrubar os outros blocos."""
    try:
        return {name: read(session_id)}
    except MetricsUnavailable as exc:
        return {name: {"estado": STATE_UNAVAILABLE, "produtor": exc.producer or producer, "motivo": str(exc)}}
    except Exception as exc:  # noqa: BLE001 - falha de leitura de um bloco não bloqueia os outros
        logger.error(
            "Falha ao ler o bloco de exploração",
            extra={"block": name, "error": type(exc).__name__, "session_id": session_id},
        )
        return {name: {"estado": STATE_ERROR, "mensagem": f"{type(exc).__name__}: {exc}"[:300]}}


class ExplorationLinkingReader:
    """Grupo ``exploracao`` (bloco ``ligacao``): experimentos por papel e testes por origem da hipótese.

    Os papéis e as origens vêm do grafo, sobre os ``Experimento`` executados na sessão (``EXECUTADO_EM``); os
    contadores de ligação derivada e de hipóteses do sistema, da soma dos eventos ``hypothesis_cycle``
    (produtor: ``v18.7-hypothesis-linking``). Sem os campos do produtor o bloco fica ``indisponivel``.
    """

    group = "exploracao"
    producer = "v18.7-hypothesis-linking"

    def __init__(self, store_getter: Callable[[], Any] | None = None) -> None:
        self._store_getter = store_getter

    @staticmethod
    def _sum(cycles: list[dict[str, Any]], key: str) -> int:
        return sum(int(c.get(key) or 0) for c in cycles)

    def read(self, session_id: str) -> dict[str, Any]:
        return _guarded_block("ligacao", self.producer, session_id, self._read)

    def _read(self, session_id: str) -> dict[str, Any]:
        from src.observability.telemetry import get_telemetry

        if self._store_getter is None:
            raise MetricsUnavailable("grafo de conhecimento indisponível", self.producer)
        cycles = [e.get("payload") or {} for e in get_telemetry().get_events(session_id, "hypothesis_cycle")]
        store = self._store_getter()
        roles = {"teste": 0, "preparacao": 0, "referencia": 0}
        origins = {"pesquisador": 0, "researcher": 0, "curator": 0, "oportunidade": 0, "sistema": 0}
        has_role = False
        for session in store.find_nodes("Sessao", {"sessao_id": session_id}, limit=2):
            for exp in store.neighbors(session.id, ["EXECUTADO_EM"], direction="in", depth=1).nodes:
                if exp.label != "Experimento":
                    continue
                declared = exp.properties.get("papel")
                has_role = has_role or declared in roles
                role = declared if declared in roles else "teste"  # sem papel (nó antigo) conta como teste
                roles[role] += 1
                if role != "teste":
                    continue
                for hyp in store.neighbors(exp.id, ["TESTA"], direction="out", depth=1).nodes:
                    if hyp.label == "Hipotese":
                        origin = str(hyp.properties.get("origem") or "researcher")
                        if origin in origins:
                            origins[origin] += 1
        produced = has_role or any("ligacoes_prepara" in c or "hipoteses_sistema_criadas" in c for c in cycles)
        if not produced:
            raise MetricsUnavailable("campos de ligação ausentes nos eventos e nos Experimento", self.producer)
        tests = roles["teste"]
        return {
            "estado": STATE_OK,
            "experimentos_por_papel": roles,
            "testes_por_origem": origins,
            "proporcao_testes_sistema": round(origins["sistema"] / tests, 3) if tests else None,
            "ligacoes_prepara_derivadas": self._sum(cycles, "ligacoes_prepara"),
            "hipoteses_sistema_criadas": self._sum(cycles, "hipoteses_sistema_criadas"),
            "hipoteses_sistema_abandonadas": self._sum(cycles, "hipoteses_sistema_abandonadas"),
            "removidas_pelo_replanejamento": sum(len(c.get("removidas_pelo_replanejamento") or []) for c in cycles),
        }


class ExplorationStopReader:
    """Grupo ``exploracao`` (bloco ``parada``): estagnação, saturação, objetivo e retiradas por restrição.

    Lê os eventos de ``v18.7-exploration-limits``; sem nenhum deles (nem ciclo de exploração) o bloco fica
    ``indisponivel`` com o nome do produtor.
    """

    group = "exploracao"
    producer = "v18.7-exploration-limits"
    _EVENTS = (
        "estagnacao_intervencao", "intervencoes_esgotadas", "saturacao_avaliada", "objetivo_atingido",
        "objetivo_desfecho", "restricao_retirada", "hypothesis_cycle",
    )

    def read(self, session_id: str) -> dict[str, Any]:
        return _guarded_block("parada", self.producer, session_id, self._read)

    def _read(self, session_id: str) -> dict[str, Any]:
        from src import config
        from src.observability.telemetry import get_telemetry

        telemetry = get_telemetry()
        events = {
            name: [e.get("payload") or {} for e in telemetry.get_events(session_id, name)] for name in self._EVENTS
        }
        if not any(events.values()):
            raise MetricsUnavailable("nenhum evento de exploração nesta sessão", self.producer)
        withdrawals = events["restricao_retirada"]
        by_criterion: dict[str, int] = {}
        for item in withdrawals:
            criterion = str(item.get("criterio") or "desconhecido")
            by_criterion[criterion] = by_criterion.get(criterion, 0) + 1
        similarity = [
            {
                "hipotese_id": str(w.get("hipotese_id")), "restricao_id": str(w.get("restricao_id")),
                "similaridade": w.get("similaridade"),
            }
            for w in withdrawals if w.get("criterio") == "similaridade"
        ]
        limit = int(config.OPERATION_METRICS_LIST_MAX_ITEMS)
        outcomes = events["objetivo_desfecho"]
        return {
            "estado": STATE_OK,
            "ciclos": len(events["hypothesis_cycle"]),
            "intervencoes_estagnacao": len(events["estagnacao_intervencao"]),
            "saturacao_avaliada": bool(events["saturacao_avaliada"]),
            "objetivo_atingido": bool(events["objetivo_atingido"]),
            "desfecho_objetivo": outcomes[-1].get("desfecho") if outcomes else None,
            "retiradas_restricao": by_criterion,
            "retiradas_restricao_similaridade": similarity[:limit],
            "retiradas_restricao_similaridade_omitidas": max(len(similarity) - limit, 0),
        }


class ContractReader:
    """Grupo ``exploracao`` (bloco ``contrato``): tentativas, tokens estimados e hashes do contrato da subtarefa.

    Produtor: ``v18.7-subtask-contract`` (eventos ``subtask_attempt``, ``subtask_review`` e ``contrato_divergente``).
    """

    group = "exploracao"
    producer = "v18.7-subtask-contract"

    def read(self, session_id: str) -> dict[str, Any]:
        return _guarded_block("contrato", self.producer, session_id, self._read)

    def _read(self, session_id: str) -> dict[str, Any]:
        from src.observability.telemetry import get_telemetry

        telemetry = get_telemetry()
        attempts = [e.get("payload") or {} for e in telemetry.get_events(session_id, "subtask_attempt")]
        if not attempts:
            raise MetricsUnavailable("nenhuma tentativa com o evento subtask_attempt", self.producer)
        divergences = len(telemetry.get_events(session_id, "contrato_divergente"))
        with_hash = [a for a in attempts if a.get("contrato_sha256")]
        tokens = [int(a.get("contrato_tokens_estimados") or 0) for a in with_hash]
        total = sum(tokens)
        prompt_tokens = self._prompt_tokens(telemetry, session_id)
        return {
            "estado": STATE_OK,
            "tentativas": len(attempts),
            "tokens_estimados_total": total,
            "tokens_estimados_medio": round(total / len(with_hash)) if with_hash else None,
            "fracao_entrada": round(total / prompt_tokens, 3) if prompt_tokens else None,
            "divergencias": divergences,
            "tentativas_sem_hash": len(attempts) - len(with_hash),
            "tarefa_original_truncada": sum(1 for a in attempts if a.get("tarefa_original_truncada")),
        }

    @staticmethod
    def _prompt_tokens(telemetry: Any, session_id: str) -> int:
        """Soma dos ``prompt_tokens`` das chamadas dos papéis developer e validator da sessão."""
        total = 0
        for row in telemetry.get_usage_by_role(session_id):
            if str(row.get("agent_id")) in ("developer", "validator"):
                total += int(row.get("prompt_tokens") or 0)
        return total


def _consult_usage_of(telemetry: Any, session_id: str) -> dict[str, Any] | None:
    """Tokens e custo da consulta do terminal; ``None`` se a leitura não existir (telemetria simulada, banco fora)."""
    try:
        usage = telemetry.get_usage_by_origin(session_id)["consulta"]
    except Exception:  # noqa: BLE001 - métrica aditiva: a falta dela não invalida o grupo
        return None
    return {
        "tokens": int(usage["total_tokens"]), "custo_usd": float(usage["custo_usd"]), "chamadas": int(usage["calls"]),
    }


class CostResourcesReader:
    """Grupo ``custo_recursos``: tokens e custo por tarefa e papel, hardware do nó (telemetria existente)."""

    group = "custo_recursos"
    producer = "telemetria"

    def __init__(
        self,
        runs_loader: Callable[[str], dict[str, Any] | None] | None = None,
        budget_loader: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._runs_loader = runs_loader
        self._budget_loader = budget_loader

    @staticmethod
    def _consult_usage(telemetry: Any, session_id: str) -> dict[str, Any] | None:
        return _consult_usage_of(telemetry, session_id)

    def read(self, session_id: str) -> dict[str, Any]:
        from src.observability.telemetry import get_telemetry

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
        budget = (self._budget_loader(session_id) or {}) if self._budget_loader else {}
        return {
            "custo_limite_usd": budget.get("max_cost_usd"),  # ``None`` no modo sem limite
            "custo_por_provedor": self._cost_by_provider(telemetry, session_id),
            "custo_limite_por_provedor": dict(budget.get("max_cost_usd_by_provider") or {}),
            "tokens_total": sum(int(r["tokens"] or 0) for r in rows),
            "custo_usd_total": cost([r["cost_usd"] for r in rows]),
            "chamadas_sem_custo": sum(int(r.get("calls_sem_custo") or 0) for r in rows),
            # Execuções de agente da sessão (sem limite, ADR 021 §5.1): só relatadas; ``None`` sem o registro.
            "execucoes_agente": self._runs_loader(session_id) if self._runs_loader else None,
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
            # v18.7-session-events-terminal: o que as perguntas do terminal à pesquisa gastaram (já está no total).
            "consulta": self._consult_usage(telemetry, session_id),
            "no": {
                "cpu_pct_medio": round(avg_cpu, 1) if avg_cpu is not None else None,
                "cpu_pct_pico": peaks.get("max_cpu_pct"),
                "ram_pct_pico": peaks.get("max_mem_pct"),
                "ram_disponivel_min_mb": peaks.get("min_mem_available_mb"),
                "temperatura_pico_c": peaks.get("max_temp_c"),
                "incidentes_throttling": int(peaks.get("throttle_incidents") or 0),
            },
        }


    @staticmethod
    def _cost_by_provider(telemetry: Any, session_id: str) -> dict[str, float | None]:
        """US$ por provedor; ``None`` para o provedor em que nenhuma chamada tem preço (nunca soma ausente como 0)."""
        out: dict[str, float | None] = {}
        for row in telemetry.get_token_summary(session_id).get("by_provider_model", []):
            provider, value = str(row.get("llm_provider")), row.get("total_cost_usd")
            if value is None:
                out.setdefault(provider, None)
            else:
                out[provider] = round((out.get(provider) or 0.0) + float(value), 6)
        return out


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
    grafo, sem vínculo com a sessão: ficam ``None`` (não medidas), nunca zero, salvo quando o gate persistente é
    informado (``gate_loader``): então vêm de ``gate_requests`` (pedidos resolvidos pelo pesquisador na cadeia).
    """

    group = "intervencoes_humanas"
    producer = "sessão e telemetria"

    def __init__(
        self,
        payload_loader: Callable[[str], dict[str, Any]] | None = None,
        gate_loader: Callable[[str], list[Any]] | None = None,
    ) -> None:
        self._payload_loader = payload_loader
        self._gate_loader = gate_loader

    def read(self, session_id: str) -> dict[str, Any]:
        from src.observability.telemetry import get_telemetry

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
        approvals = rejections = edits = None
        if self._gate_loader is not None:
            # Aprovações, rejeições e edições vêm do gate persistente (``gate_requests``), nunca do grafo.
            resolved = self._gate_loader(session_id)
            approvals = rejections = edits = 0
            for req in resolved:
                action = (req.resposta or {}).get("acao")
                if action in ("aprovar", "autorizar"):
                    approvals += 1
                elif action in ("rejeitar", "negar") or req.estado == "negada":
                    rejections += 1
                elif action == "editar":
                    edits += 1
                events.append(
                    {"tipo": f"gate:{req.decisao}:{action or req.estado}", "em": req.resolvido_em,
                     "referencia": req.referencia}
                )
        return {
            "aprovacoes": approvals,
            "rejeicoes": rejections,
            "edicoes": edits,
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
    store_getter: Callable[[], Any] | None = None,
) -> list[MetricsGroupReader]:
    """Leitores padrão: um por produtor (cada mudança produtora registra o seu aqui)."""
    from src.claims.metrics import ClaimVerificationReader
    from src.numeric_refs.provenance_file import NumericProvenanceReader

    if output_dir is None:
        from src import config

        output_dir = config.OUTPUT_BASE_DIR

    def budget_of(session_id: str) -> dict[str, Any]:
        return ((payload_loader(session_id) or {}).get("budget") or {}) if payload_loader else {}

    def gate_of(session_id: str) -> list[Any]:
        """Pedidos que o pesquisador resolveu na sessão e nas antecessoras da cadeia (``continues_session_id``)."""
        from src.gate.persistent_gate import session_gate

        chain, current = [], session_id
        while current and current not in chain and len(chain) < 200 and payload_loader is not None:
            chain.append(current)
            nxt = (payload_loader(current) or {}).get("continues_session_id")
            current = nxt if isinstance(nxt, str) else None
        return session_gate().resolved(chain or [session_id])

    def runs_of(session_id: str) -> dict[str, Any] | None:
        runs = (payload_loader(session_id) or {}).get("execucoes_agente") if payload_loader else None
        return runs if isinstance(runs, dict) else None

    return [
        EgressMetricsReader(budget_loader=budget_of),
        NumericProvenanceReader(output_dir),
        ProvenanceChainReader(),
        ClaimVerificationReader(output_dir),
        PlanRejectionReader(),
        HypothesisClosureReader(),
        CostResourcesReader(runs_loader=runs_of, budget_loader=budget_of),
        HumanInterventionsReader(payload_loader, gate_loader=gate_of),
        JudgeIndependenceReader(payload_loader),
        ExplorationLinkingReader(store_getter),
        ExplorationStopReader(),
        ContractReader(),
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


STOP_UNTESTED_HYPOTHESES = "hipoteses_nao_testadas"
STOP_PROVIDER_QUOTA = "limite_cota_provedor"
_STOP_DESCRIPTIONS = {
    "limite_custo": "limite de custo da sessão atingido",
    "saturacao": "a melhora possível ficou abaixo do erro da medida depois das intervenções",
    STOP_PROVIDER_QUOTA: (
        "cota ou teto de gasto esgotado no provedor; aumente o teto ou troque o provedor e retome a sessão"
    ),
    STOP_UNTESTED_HYPOTHESES: (
        "hipóteses em teste sem nenhuma tentativa ao esgotar os ciclos ociosos (parada de pesquisa, não falha de "
        "infraestrutura)"
    ),
    "aguarda_pesquisador": "só restam pedidos ao pesquisador; responda e retome a sessão",
    "suspensa_sem_pesquisador": "o terminal saiu durante uma sessão assisted; retome a sessão",
    "encerrada_pesquisador": "encerrada pelo pesquisador no terminal",
    "pausada_pesquisador": "pausada pelo pesquisador no terminal; retome a sessão para continuar",
}


def describe_stop_reason(stop_reason: str | None) -> str | None:
    """``motivo (explicação)`` para os motivos de parada que pedem explicação; o próprio motivo nos demais."""
    if not stop_reason:
        return None
    explanation = _STOP_DESCRIPTIONS.get(stop_reason)
    return f"{stop_reason} ({explanation})" if explanation else stop_reason


def _block_unavailable(title: str, block: dict[str, Any]) -> str:
    if block.get("estado") == STATE_ERROR:
        return f"  - {title}: erro de leitura: {block.get('mensagem', '')}"
    return f"  - {title}: indisponível ({block.get('produtor', '?')})"


def _exploration_lines(group: dict[str, Any]) -> list[str]:
    """Linha "Exploração" e sublinhas dos blocos ``ligacao``, ``parada`` e ``contrato`` (design §4)."""
    lines = ["- **Exploração:**"]
    link = group.get("ligacao") or {}
    if link.get("estado") != STATE_OK:
        lines.append(_block_unavailable("ligação", link))
    else:
        roles = link.get("experimentos_por_papel") or {}
        origins = link.get("testes_por_origem") or {}
        share = link.get("proporcao_testes_sistema")
        lines.append(
            "  - ligação: experimentos por papel: " + ("; ".join(f"{k}={_fmt(v)}" for k, v in roles.items()) or "n/d")
            + "; testes por origem: " + ("; ".join(f"{k}={_fmt(v)}" for k, v in origins.items()) or "n/d")
            + f"; proporção de testes do sistema: {'n/d' if share is None else _fmt(float(share))}"
            + f"; PREPARA derivadas: {_fmt(link.get('ligacoes_prepara_derivadas'))}"
            + f"; hipóteses do sistema criadas/abandonadas: {_fmt(link.get('hipoteses_sistema_criadas'))}"
            + f"/{_fmt(link.get('hipoteses_sistema_abandonadas'))}"
        )
    stop = group.get("parada") or {}
    if stop.get("estado") != STATE_OK:
        lines.append(_block_unavailable("parada", stop))
    else:
        outcome = stop.get("desfecho_objetivo")
        withdrawals = stop.get("retiradas_restricao") or {}
        lines.append(
            f"  - parada: ciclos: {_fmt(stop.get('ciclos'))}; intervenções por estagnação: "
            f"{_fmt(stop.get('intervencoes_estagnacao'))}; saturação avaliada: {_fmt(stop.get('saturacao_avaliada'))}; "
            f"objetivo atingido: {_fmt(stop.get('objetivo_atingido'))}" + (f" (desfecho: {outcome})" if outcome else "")
            + "; retiradas por restrição: "
            + ("; ".join(f"{k}={_fmt(v)}" for k, v in sorted(withdrawals.items())) or "nenhuma")
        )
        for item in stop.get("retiradas_restricao_similaridade") or []:
            lines.append(
                f"    - retirada por similaridade: restrição {item['restricao_id']}, hipótese {item['hipotese_id']}, "
                f"similaridade {item['similaridade']}"
            )
        if stop.get("retiradas_restricao_similaridade_omitidas"):
            lines.append(f"    - e mais {_fmt(stop['retiradas_restricao_similaridade_omitidas'])} retiradas omitidas")
    contract = group.get("contrato") or {}
    if contract.get("estado") != STATE_OK:
        lines.append(_block_unavailable("contrato", contract))
    else:
        fraction = contract.get("fracao_entrada")
        lines.append(
            f"  - contrato: tentativas: {_fmt(contract.get('tentativas'))}; tokens estimados: "
            f"{_fmt(contract.get('tokens_estimados_total'))} (médio {_fmt(contract.get('tokens_estimados_medio'))}); "
            f"fração da entrada: {'n/d' if fraction is None else _fmt(float(fraction))}; "
            f"divergências de hash: {_fmt(contract.get('divergencias'))}; "
            f"tentativas sem hash: {_fmt(contract.get('tentativas_sem_hash'))}"
        )
    return lines


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
        lines.append(f"- **Motivo de parada:** {describe_stop_reason(stop_reason)}")
    if metrics.get("parcial"):
        lines.append("- **Aviso:** métricas parciais (a sessão não foi fechada normalmente).")

    egress = metrics["egresso"]
    if egress["estado"] != STATE_OK:
        lines.append(_unavailable_line("Egresso", egress))
    else:
        limit = egress.get("limite_bytes")
        limited = egress.get("bytes_limitados")
        limit_text = "sem limite" if limit is None else _fmt(limit, " bytes")
        limited_text = (
            f"saídas de execução novas (sujeitas ao limite): {_fmt(limited)} de {limit_text}"
            if limited is not None else f"limite das saídas de execução novas: {limit_text}"
        )
        lines.append(
            f"- **Egresso:** {_fmt(egress['bytes_total'], ' bytes')} enviados fora do nó; "
            f"{limited_text}; "
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
        causes = {k: v for k, v in ((chain or {}).get("motivos") or {}).items() if v}
        cause_text = (", causas: " + ", ".join(f"{k}={v}" for k, v in causes.items())) if causes else ""
        chain_text = (
            f"cadeia {chain['resultado']} (órfãs: {_fmt(chain['orfas'])}, pendentes: {_fmt(chain['pendentes'])}"
            f"{cause_text})"
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
        if stop_reason == STOP_UNTESTED_HYPOTHESES:
            lines.append(
                f"  - hipóteses sem tentativa no fechamento: {_fmt(ver.get('hipoteses_sem_tentativa_no_fechamento'))}"
            )
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
        consult = cost.get("consulta")
        if consult and consult.get("tokens"):
            lines.append(
                f"  - consulta (perguntas do terminal, já somadas acima): {_fmt(consult['tokens'])} tokens, "
                f"{_fmt(consult['custo_usd'], ' USD')}"
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
    exploration = metrics.get("exploracao")
    if exploration is None:
        lines.append("- **Exploração:** n/d (métricas anteriores à versão 2)")
    elif exploration["estado"] != STATE_OK:
        lines.append(_unavailable_line("Exploração", exploration))
    else:
        lines.extend(_exploration_lines(exploration))
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
