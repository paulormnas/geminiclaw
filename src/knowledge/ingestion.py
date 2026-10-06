"""Ingestão determinística de fatos estruturais no grafo (``v17-structural-fact-ingestion``).

O orquestrador grava no grafo, **sem LLM**, o que aconteceu: ``Sessao``, ``Insumo``, ``Experimento``,
``Resultado`` e ``Abordagem`` aplicada (ADR 009 §2, ADR 015 §1, §2, §5, §9.3). Os valores vêm dos
artefatos em disco (``params.json``, ``metrics.json``, ``manifest.json``, ``input_snapshot/``) e do
parecer do Validator; texto de LLM nunca vira consulta.

Regras de segurança:

- toda escrita passa pela porta única (``GraphStore``): operações tipadas, valores só como parâmetros;
- só os rótulos de ``WRITABLE_LABELS`` são criados; ``Problema`` e o estado ``confirmado`` são do
  pesquisador (``validate_human_only``) e este módulo nunca os toca;
- tudo o que se lê do disco é dado não confiável (``ingestion_io``): nomes validados, caminhos
  confinados, JSON malformado tolerado, tamanhos limitados;
- toda operação é idempotente (obter ou criar): reingerir o mesmo evento não duplica nós nem arestas
  e completa uma ingestão que falhou no meio;
- falha de escrita (grafo fora do ar) **não interrompe a sessão**: o evento vai para
  ``knowledge_pending.jsonl`` e ``geminiclaw knowledge sync`` o reaplica.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.knowledge import schema
from src.knowledge.errors import GraphStoreError
from src.knowledge.failure_cause import classify_failure
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.ingestion_io import (
    MAX_DATASETS,
    MAX_METRICS,
    MAX_NAME_CHARS,
    IngestionFileError,
    collect_evidence,
    finite_number,
    list_regular_files,
    sha256_file,
)
from src.knowledge.ingestion_queue import (
    DEAD_FILENAME,
    MAX_SYNC_ATTEMPTS,
    PENDING_FILENAME,
    PendingQueue,
)
from src.knowledge.normalization import clean_free_text, normalize_domain_term
from src.knowledge.projects import validate_project_id
from src.knowledge.provenance import Actor
from src.knowledge.vocabulary import VocabularyError, resolve_metric
from src.logger import get_logger

logger = get_logger(__name__)

ACTOR_ORQUESTRADOR = Actor(kind="orquestrador")
ACTOR_RESEARCHER = Actor(kind="agente", role="researcher")

# Únicos rótulos que a ingestão cria. ``Problema`` (e a confirmação do pesquisador) e o vocabulário
# controlado (``Metrica``, ``Dominio``) ficam de fora de propósito.
WRITABLE_LABELS = frozenset({"Sessao", "Insumo", "Experimento", "Resultado", "Abordagem", "Hipotese"})

MODOS = schema.NODE_SCHEMAS["Sessao"].properties["modo"].enum or ()
MOTIVOS_PARADA = schema.NODE_SCHEMAS["Sessao"].properties["motivo_parada"].enum or ()
TIPOS_ABORDAGEM = schema.NODE_SCHEMAS["Abordagem"].properties["tipo"].enum or ()

_DATASET_EXT = frozenset({".csv", ".tsv", ".xlsx", ".xls", ".ods", ".json", ".jsonl", ".parquet"})
_ARTIGO_EXT = frozenset({".pdf", ".docx", ".md", ".txt", ".rst"})
EXPERIMENTAL_TASK_TYPES = frozenset({"reproduction", "eda", "model_impl", "validation"})

# Chaves que não descrevem o método (design §4).
_NON_METHOD_KEY_RE = re.compile(r"(?i)(seed|random_state|path|file|dir|output|input|timestamp|session)")
_MAX_CONFIG_KEYS = 100
_MAX_CONFIG_DEPTH = 3
_MAX_CONFIG_LIST = 50
_MAX_CONFIG_TEXT = 200
_MAX_TEXT = 2000
_MAX_CONSULTED = 50
_MAX_CRITERIA = 20
_MAX_CRITERION = 500
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

EVENT_SESSION_START = "session_start"
EVENT_INPUTS = "inputs"
EVENT_SUBTASK = "subtask"
EVENT_SESSION_END = "session_end"
EVENT_KINDS = (EVENT_SESSION_START, EVENT_INPUTS, EVENT_SUBTASK, EVENT_SESSION_END)


class IngestionDataError(ValueError):
    """Dado determinístico inválido (reenviar não adianta): o evento é descartado com aviso."""


# ---------------------------------------------------------------------------
# Contexto e entradas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionContext:
    """Contexto da sessão repetido em todo evento (torna cada operação autossuficiente).

    Attributes:
        project_id: UUID do projeto da sessão.
        session_id: Identificador da sessão mestra (pasta ``outputs/<session_id>/``).
        modo: ``assisted``, ``semi`` ou ``auto``.
        inicio: Instante de início (ISO-8601).
        no_execucao: Identificador do computador (``NODE_ID``).
        continues_session_id: Sessão continuada, quando houver.
    """

    project_id: str
    session_id: str
    modo: str
    inicio: str
    no_execucao: str
    continues_session_id: str | None = None

    @classmethod
    def from_dict(cls, data: object, *, session_id: str) -> "SessionContext":
        """Reconstrói e valida o contexto de um evento da fila (o ``session_id`` vem da pasta)."""
        if not isinstance(data, dict):
            raise IngestionDataError("contexto do evento inválido")
        try:
            project_id = validate_project_id(data.get("project_id"))  # type: ignore[arg-type]
        except GraphStoreError as exc:
            raise IngestionDataError(str(exc)) from exc
        cont = data.get("continues_session_id")
        return cls(
            project_id=project_id,
            session_id=session_id,
            modo=_text_field(data, "modo", 32),
            inicio=_text_field(data, "inicio", 64),
            no_execucao=_text_field(data, "no_execucao", 128),
            continues_session_id=cont if isinstance(cont, str) and _SESSION_ID_RE.fullmatch(cont) else None,
        )


@dataclass(frozen=True)
class SubtaskInput:
    """O que o laço autônomo informa sobre uma subtarefa concluída (serializável para a fila).

    Attributes:
        task_name: Nome da subtarefa (pasta em ``outputs/<sessão>/``).
        subtask_id: ID da subtarefa (chave de idempotência do ``Experimento``).
        agent_id: Agente executor.
        task_type: Tipo da subtarefa no plano.
        hypothesis: Campo ``hypothesis`` do plano.
        scientific_rationale: Campo ``scientific_rationale`` do plano.
        approach: Campo ``approach`` do plano (``nome``, ``tipo``, ``descricao``).
        agent_status: ``success``, ``error`` ou ``timeout`` (resultado final da subtarefa).
        agent_error_category: Categoria estruturada da falha de infraestrutura, quando houver.
        review_status: Parecer do Validator (``pass``, ``fail``, ``divergent_but_documented``) ou ``None``.
        validation_criteria: Critérios de aceite da subtarefa (os quantitativos indicam quais
            métricas o Validator avaliou contra um limiar).
    """

    task_name: str
    subtask_id: str | None = None
    agent_id: str = ""
    task_type: str | None = None
    hypothesis: str = ""
    scientific_rationale: str = ""
    approach: dict[str, str] | None = None
    agent_status: str = "success"
    agent_error_category: str | None = None
    review_status: str | None = None
    validation_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializa para o evento da fila."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "SubtaskInput":
        """Reconstrói com checagem estrita de tipos (a fila é um arquivo não confiável)."""
        if not isinstance(data, dict):
            raise IngestionDataError("dados da subtarefa inválidos")
        approach = data.get("approach")
        if isinstance(approach, dict):
            approach = {
                k: v[:_MAX_TEXT]
                for k, v in approach.items()
                if k in ("nome", "tipo", "descricao") and isinstance(v, str)
            } or None
        else:
            approach = None
        criteria = data.get("validation_criteria")
        return cls(
            task_name=_text_field(data, "task_name", MAX_NAME_CHARS),
            subtask_id=_opt_text(data.get("subtask_id"), 128),
            agent_id=_text_field(data, "agent_id", 64, required=False),
            task_type=_opt_text(data.get("task_type"), 64),
            hypothesis=_text_field(data, "hypothesis", _MAX_TEXT, required=False),
            scientific_rationale=_text_field(data, "scientific_rationale", _MAX_TEXT, required=False),
            approach=approach,
            agent_status=_text_field(data, "agent_status", 32, required=False) or "error",
            agent_error_category=_opt_text(data.get("agent_error_category"), 100),
            review_status=_opt_text(data.get("review_status"), 64),
            validation_criteria=[
                c[:_MAX_CRITERION] for c in (criteria if isinstance(criteria, list) else []) if isinstance(c, str)
            ][:_MAX_CRITERIA],
        )


def _text_field(data: dict[str, Any], key: str, limit: int, *, required: bool = True) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (required and not value.strip()):
        if required:
            raise IngestionDataError(f"campo '{key}' ausente ou inválido")
        return ""
    return value[:limit]


def _opt_text(value: object, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _clean(text: object, limit: int = _MAX_TEXT) -> str:
    """Texto de arquivo/LLM em uma linha, sem controles, com tamanho limitado."""
    return clean_free_text(str(text))[:limit].strip()


# ---------------------------------------------------------------------------
# Mapeamentos puros (design §2, §4)
# ---------------------------------------------------------------------------


def insumo_tipo(filename: str) -> str:
    """``Insumo.tipo`` pela extensão: dataset, artigo ou outro."""
    ext = Path(filename).suffix.lower()
    if ext in _DATASET_EXT:
        return "dataset"
    if ext in _ARTIGO_EXT:
        return "artigo"
    return "outro"


def _json_safe(value: Any, depth: int) -> tuple[bool, Any]:
    """Valor de configuração seguro: escalares, listas curtas e dicionários rasos filtrados."""
    if value is None or isinstance(value, bool):
        return True, value
    if isinstance(value, (int, float)):
        number = finite_number(value)
        return (number is not None), (value if number is not None else None)
    if isinstance(value, str):
        text = _clean(value, _MAX_CONFIG_TEXT)
        looks_like_path = text.startswith(("/", "~", "./", "../")) or "://" in text or "\\" in text
        return (not looks_like_path), text
    if isinstance(value, list) and depth < _MAX_CONFIG_DEPTH:
        items = [v for ok, v in (_json_safe(i, depth + 1) for i in value[:_MAX_CONFIG_LIST]) if ok]
        return True, items
    if isinstance(value, dict) and depth < _MAX_CONFIG_DEPTH:
        return True, normalize_config(value, _depth=depth + 1)
    return False, None


def normalize_config(parameters: object, *, _depth: int = 0) -> dict[str, Any]:
    """``config_normalizada``: só o que descreve o método (design §4).

    Remove chaves que casam ``seed|random_state|path|file|dir|output|input|timestamp|session``
    (sem diferenciar caixa), valores que parecem caminho ou URL, NaN/infinitos e tipos não JSON;
    preserva valores numéricos; ordena as chaves (forma canônica).

    Args:
        parameters: ``params.json["parameters"]``.

    Returns:
        Dicionário com no máximo 100 chaves, de forma canônica.
    """
    if not isinstance(parameters, dict):
        return {}
    kept: dict[str, Any] = {}
    for key in sorted(k for k in parameters if isinstance(k, str)):
        if len(kept) >= _MAX_CONFIG_KEYS:
            break
        clean_key = _clean(key, 100)
        if not clean_key or _NON_METHOD_KEY_RE.search(clean_key):
            continue
        ok, value = _json_safe(parameters[key], _depth)
        if ok:
            kept[clean_key] = value
    return kept


def hash_params(parameters: object) -> str | None:
    """SHA-256 do JSON canônico (chaves ordenadas) de ``params.json["parameters"]``."""
    if not isinstance(parameters, dict):
        return None
    canonical = json.dumps(parameters, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Escrita no grafo
# ---------------------------------------------------------------------------


class _Writer:
    """Operações idempotentes (obter ou criar) sobre um ``GraphStore``, para uma sessão."""

    def __init__(self, store: GraphStore, ctx: SessionContext) -> None:
        self.store = store
        self.ctx = ctx
        self.created = 0

    # -- primitivas -------------------------------------------------------

    def _base(self) -> dict[str, Any]:
        return {"projeto_id": self.ctx.project_id, "sessao_id": self.ctx.session_id}

    def _create(self, label: str, props: dict[str, Any], actor: Actor) -> str:
        if label not in WRITABLE_LABELS:  # defesa em profundidade: a ingestão nunca toca outros rótulos
            raise IngestionDataError(f"rótulo '{label}' não é gravável pela ingestão")
        node_id = self.store.create_node(label, {**self._base(), **props}, actor=actor)
        self.created += 1
        return node_id

    def _edge(self, src: str, rel: str, dst: str, props: dict[str, Any] | None = None, *, fato: bool = True) -> None:
        sub = self.store.neighbors(src, [rel], direction="out", depth=1)
        if any(e.src_id == src and e.rel_type == rel and e.dst_id == dst for e in sub.edges):
            return
        edge_props = {"origem": "fato"} if fato else {}
        edge_props.update(props or {})
        self.store.create_edge(src, rel, dst, edge_props, actor=ACTOR_ORQUESTRADOR)

    def _find(self, label: str, filters: dict[str, Any]) -> Node | None:
        nodes = self.store.find_nodes(label, {"projeto_id": self.ctx.project_id, **filters}, limit=1)
        return nodes[0] if nodes else None

    def project_node(self) -> Node:
        nodes = self.store.find_nodes("Projeto", {"projeto_id": self.ctx.project_id}, limit=1)
        if not nodes:
            raise GraphStoreError(f"Projeto '{self.ctx.project_id}' não encontrado no grafo.")
        return nodes[0]

    # -- sessão -----------------------------------------------------------

    def session(self) -> str:
        """Obtém ou cria a ``Sessao`` (e as arestas ``PERTENCE_A`` e ``CONTINUA``)."""
        ctx = self.ctx
        if ctx.modo not in MODOS:
            raise IngestionDataError(f"modo de sessão inválido: {ctx.modo!r}")
        node = self._find("Sessao", {"sessao_id": ctx.session_id})
        if node is None:
            session_node = self._create(
                "Sessao",
                {"modo": ctx.modo, "inicio": ctx.inicio, "no_execucao": ctx.no_execucao},
                ACTOR_ORQUESTRADOR,
            )
        else:
            session_node = node.id
        self._edge(session_node, "PERTENCE_A", self.project_node().id)
        if ctx.continues_session_id and ctx.continues_session_id != ctx.session_id:
            previous = self._find("Sessao", {"sessao_id": ctx.continues_session_id})
            if previous is not None:
                self._edge(session_node, "CONTINUA", previous.id)
            else:
                logger.warning("Sessão continuada não encontrada no grafo; aresta CONTINUA não criada")
        return session_node

    def end_session(self, fim: str, motivo_parada: str | None, consumo: dict[str, Any] | None) -> None:
        """Grava ``fim``, ``motivo_parada`` e ``consumo`` na ``Sessao``."""
        session_node = self.session()
        changes: dict[str, Any] = {"fim": fim[:64]}
        if motivo_parada is not None:
            if motivo_parada not in MOTIVOS_PARADA:
                raise IngestionDataError(f"motivo_parada inválido: {motivo_parada!r}")
            changes["motivo_parada"] = motivo_parada
        if consumo:
            numbers = {k: v for k, v in consumo.items() if isinstance(k, str) and finite_number(v) is not None}
            if numbers:
                changes["consumo"] = numbers
        self.store.update_node(session_node, changes, actor=ACTOR_ORQUESTRADOR)

    # -- insumos ----------------------------------------------------------

    def insumo(self, session_dir: Path, path: Path, project_node: str) -> str | None:
        """Obtém ou cria um ``Insumo`` (deduplicado por hash no projeto) e liga ao projeto."""
        try:
            digest = sha256_file(path, session_dir)
        except IngestionFileError as exc:
            logger.warning("Insumo ignorado", extra={"extra": {"motivo": str(exc)}})
            return None
        node = self._find("Insumo", {"hash_conteudo": digest})
        if node is None:
            insumo_id = self._create(
                "Insumo",
                {
                    "tipo": insumo_tipo(path.name),
                    "titulo": _clean(path.name, MAX_NAME_CHARS) or "insumo",
                    "hash_conteudo": digest,
                    "caminho": _clean(path.name, MAX_NAME_CHARS),
                },
                ACTOR_ORQUESTRADOR,
            )
        else:
            insumo_id = node.id
        self._edge(project_node, "RECEBEU", insumo_id)
        return insumo_id

    def inputs(self, session_dir: Path) -> int:
        """Um ``Insumo`` por arquivo de ``input_snapshot/`` + ``Projeto-RECEBEU->Insumo``."""
        project_node = self.project_node().id
        count = 0
        for path in list_regular_files(session_dir / "input_snapshot", session_dir):
            if self.insumo(session_dir, path, project_node) is not None:
                count += 1
        return count

    # -- abordagem e hipótese --------------------------------------------

    def abordagem(self, approach: dict[str, str], task_name: str) -> str | None:
        """Resolve (nome normalizado exato) ou cria a ``Abordagem`` declarada no plano."""
        nome = _clean(approach.get("nome", ""), MAX_NAME_CHARS)
        key = normalize_domain_term(nome)
        if not nome or not key:
            return None
        candidates = self.store.find_nodes("Abordagem", {"projeto_id": self.ctx.project_id}, limit=1000)
        for node in candidates:
            if normalize_domain_term(str(node.properties.get("nome", ""))) == key:
                return node.id
        tipo = approach.get("tipo")
        label_task = _clean(task_name, MAX_NAME_CHARS)
        return self._create(
            "Abordagem",
            {
                "nome": nome,
                "tipo": tipo if tipo in TIPOS_ABORDAGEM else "outro",
                "descricao": _clean(
                    approach.get("descricao") or f"Abordagem declarada no plano da subtarefa {label_task}."
                ),
                "justificativa_criacao": f"declarada no plano da subtarefa {label_task}",
                "nos_consultados": [n.id for n in candidates[:_MAX_CONSULTED]],
            },
            ACTOR_RESEARCHER,
        )

    def hipotese(self, sub: SubtaskInput) -> str | None:
        """Hipótese provisória a partir do campo ``hypothesis`` (design §5; substituída na V18)."""
        enunciado = _clean(sub.hypothesis)
        if not enunciado:
            return None
        node = self._find("Hipotese", {"enunciado": enunciado})
        if node is not None:
            return node.id
        return self._create(
            "Hipotese",
            {
                "enunciado": enunciado,
                "justificativa": _clean(sub.scientific_rationale)
                or "Sem justificativa científica declarada no plano da subtarefa.",
                "status": "em_teste",
                "origem": "researcher",
                "justificativa_criacao": f"declarada no plano da subtarefa {_clean(sub.task_name, MAX_NAME_CHARS)}",
                "nos_consultados": [],
            },
            ACTOR_RESEARCHER,
        )

    # -- experimento ------------------------------------------------------

    def subtask(self, session_dir: Path, sub: SubtaskInput) -> str | None:
        """Ingere uma subtarefa concluída; devolve o ``id`` do ``Experimento`` (ou ``None``)."""
        ev = collect_evidence(session_dir, sub.task_name)
        for warning in ev.warnings:
            logger.warning("Leitura de artefato tolerada na ingestão", extra={"extra": {"motivo": warning}})

        failed_run = sub.agent_status != "success" or sub.review_status == "fail"
        experimental_type = sub.agent_id == "developer" or sub.task_type in EXPERIMENTAL_TASK_TYPES
        if not (ev.metrics_status != "ausente" or ev.steps or (failed_run and experimental_type)):
            return None  # subtarefa sem código experimental e sem métricas: nenhum nó (design §1)

        status = self._experiment_status(sub, ev.metrics)
        subtarefa_id = sub.subtask_id or f"{self.ctx.session_id}:{sub.task_name}"
        project_node = self.project_node().id
        session_node = self.session()

        params = ev.params or {}
        parameters = params.get("parameters") if isinstance(params.get("parameters"), dict) else {}
        existing = self._find("Experimento", {"subtarefa_id": subtarefa_id})
        if existing is not None:
            exp_id = existing.id
        else:
            props = self._experiment_props(session_dir, sub, ev, status, subtarefa_id, project_node, parameters)
            exp_id = self._create("Experimento", props, ACTOR_ORQUESTRADOR)

        self._edge(exp_id, "EXECUTADO_EM", session_node)
        self._results(exp_id, sub, ev)
        self._datasets(session_dir, exp_id, project_node, ev)
        if sub.approach:
            abordagem_id = self.abordagem(sub.approach, sub.task_name)
            if abordagem_id is not None:
                edge_props: dict[str, Any] = {"config": normalize_config(parameters)}
                digest = hash_params(parameters) if parameters else None
                if digest:
                    edge_props["hash_params"] = digest
                self._edge(exp_id, "APLICOU", abordagem_id, edge_props, fato=False)
        hipotese_id = self.hipotese(sub)
        if hipotese_id is not None:
            self._edge(exp_id, "TESTA", hipotese_id, fato=False)
        return exp_id

    @staticmethod
    def _experiment_status(sub: SubtaskInput, metrics: dict[str, Any] | None) -> str:
        if sub.agent_status != "success" or sub.review_status == "fail":
            return "falha"
        if sub.review_status == "divergent_but_documented":
            return "divergente_documentado"
        if sub.review_status is None and metrics and metrics.get("divergence_note"):
            return "divergente_documentado"
        return "sucesso"

    def _experiment_props(
        self,
        session_dir: Path,
        sub: SubtaskInput,
        ev: Any,
        status: str,
        subtarefa_id: str,
        project_node: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        props: dict[str, Any] = {
            "subtarefa_id": subtarefa_id,
            "status": status,
            "caminho_artefatos": f"{self.ctx.session_id}/{_clean(sub.task_name, MAX_NAME_CHARS)}",
            "no_execucao": self.ctx.no_execucao,
        }
        if status == "falha":
            cause = classify_failure(
                agent_error_category=sub.agent_error_category,
                last_run=ev.last_run,
                metrics_status=ev.metrics_status,
                review_status=sub.review_status,
            )
            props["causa_falha"] = cause.causa
            props["assinatura_falha"] = cause.assinatura
        digest = hash_params(parameters) if parameters else None
        if digest:
            props["hash_params"] = digest
        seed = (ev.params or {}).get("seed")
        if seed is None:
            seed = (ev.metrics or {}).get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool):
            props["seed"] = seed
        if ev.code_hash:
            props["hash_codigo"] = ev.code_hash
        ambiente = self._ambiente(ev.last_run)
        if ambiente:
            props["ambiente"] = ambiente
        return props

    @staticmethod
    def _ambiente(run: dict[str, Any] | None) -> dict[str, Any]:
        """``ambiente`` do último passo no sandbox: imagem e pacotes (``python`` não é medido no host)."""
        if not run:
            return {}
        ambiente: dict[str, Any] = {}
        image = run.get("imagem_sandbox")
        if isinstance(image, str) and image:
            ambiente["imagem_sandbox"] = _clean(image, 200)
        pacotes = run.get("pacotes")
        if isinstance(pacotes, list):
            ambiente["pacotes"] = [_clean(p, 100) for p in pacotes[:100] if isinstance(p, str)]
        return ambiente

    def _results(self, exp_id: str, sub: SubtaskInput, ev: Any) -> None:
        """Um ``Resultado`` por métrica numérica de ``metrics.json`` + ``PRODUZIU`` + ``MEDE``."""
        metrics = ev.metrics.get("metrics") if ev.metrics else None
        if not isinstance(metrics, dict):
            return
        baselines = ev.metrics.get("baselines")
        baselines = baselines if isinstance(baselines, dict) else {}
        existing = {
            str(n.properties.get("nome_original")): n.id
            for n in self.store.neighbors(exp_id, ["PRODUZIU"], direction="out", depth=1).nodes
            if n.label == "Resultado"
        }
        from src.agents.validator_agent import evaluated_metric_names  # import tardio: módulo pesado

        evaluated = set(evaluated_metric_names(sub.validation_criteria, metrics))
        for raw_name in list(metrics)[:MAX_METRICS]:
            value = finite_number(metrics[raw_name])
            nome = _clean(raw_name, MAX_NAME_CHARS)
            if value is None or not nome:
                continue
            resultado_id = existing.get(nome)
            if resultado_id is None:
                props: dict[str, Any] = {
                    "nome_original": nome,
                    "valor": value,
                    "status_validacao": self._status_validacao(sub, str(raw_name), evaluated),
                    "caminho_metrics": f"{self.ctx.session_id}/{ev.metrics_path or ''}",
                }
                baseline = finite_number(baselines.get(raw_name))
                if baseline is not None:
                    props["baseline"] = baseline
                resultado_id = self._create("Resultado", props, ACTOR_ORQUESTRADOR)
                existing[nome] = resultado_id
            self._edge(exp_id, "PRODUZIU", resultado_id)
            self._mede(resultado_id, nome)

    @staticmethod
    def _status_validacao(sub: SubtaskInput, raw_name: str, evaluated: set[str]) -> str:
        if sub.review_status == "divergent_but_documented":
            return "divergente_documentado"
        if sub.review_status == "pass" or (sub.review_status is not None and raw_name in evaluated):
            return "validado"
        return "nao_validado"

    def _mede(self, resultado_id: str, nome: str) -> None:
        """``Resultado-MEDE->Metrica`` quando a métrica tem forma canônica; nunca cria candidato."""
        try:
            resolution = resolve_metric(
                self.store, nome, actor=ACTOR_ORQUESTRADOR, sessao_id=self.ctx.session_id, semantic_search=None
            )
        except VocabularyError:
            return  # sem canônica conhecida (o sentido, exigido para criar candidato, não é inferido)
        if resolution.node_id is not None and resolution.status != "candidato_criado":
            self._edge(resultado_id, "MEDE", resolution.node_id)

    def _datasets(self, session_dir: Path, exp_id: str, project_node: str, ev: Any) -> None:
        """``Experimento-USOU->Insumo`` por dataset de ``params.json`` e ``dataset_ids``."""
        names = (ev.params or {}).get("datasets")
        if not isinstance(names, list):
            return
        ids: list[str] = []
        for name in names[:MAX_DATASETS]:
            if not (isinstance(name, str) and _is_plain_filename(name)):
                logger.warning("Nome de dataset inválido ignorado na ingestão")
                continue
            insumo_id = self.insumo(session_dir, session_dir / "input_snapshot" / name, project_node)
            if insumo_id is None:
                continue
            self._edge(exp_id, "USOU", insumo_id)
            if insumo_id not in ids:
                ids.append(insumo_id)
        if ids:
            node = self.store.get_node(exp_id)
            if node is not None and sorted(node.properties.get("dataset_ids") or []) != sorted(ids):
                self.store.update_node(exp_id, {"dataset_ids": ids}, actor=ACTOR_ORQUESTRADOR)


def _is_plain_filename(name: str) -> bool:
    """Nome de arquivo de um único componente (aceita espaços e acentos do ``input_context/``)."""
    return (
        0 < len(name) <= 255
        and name not in (".", "..")
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
        and all(ord(c) >= 32 for c in name)
    )


# ---------------------------------------------------------------------------
# Funções de ingestão (task 2.1)
# ---------------------------------------------------------------------------


def ingest_session_start(store: GraphStore, ctx: SessionContext) -> str:
    """Cria a ``Sessao`` (``modo``, ``inicio``, ``no_execucao``), ``PERTENCE_A`` e ``CONTINUA``."""
    return _Writer(store, ctx).session()


def ingest_inputs(store: GraphStore, ctx: SessionContext, session_dir: Path) -> int:
    """Ingere ``input_snapshot/``: um ``Insumo`` por arquivo e ``Projeto-RECEBEU->Insumo``."""
    return _Writer(store, ctx).inputs(session_dir)


def ingest_subtask(store: GraphStore, ctx: SessionContext, session_dir: Path, sub: SubtaskInput) -> str | None:
    """Ingere uma subtarefa concluída (Experimento, Resultados, Abordagem, hipótese provisória)."""
    return _Writer(store, ctx).subtask(session_dir, sub)


def ingest_session_end(
    store: GraphStore,
    ctx: SessionContext,
    *,
    fim: str,
    motivo_parada: str | None,
    consumo: dict[str, Any] | None = None,
) -> None:
    """Grava ``fim``, ``motivo_parada`` e ``consumo`` na ``Sessao``."""
    _Writer(store, ctx).end_session(fim, motivo_parada, consumo)


# ---------------------------------------------------------------------------
# Resiliência: fila local e reenvio (seção 3)
# ---------------------------------------------------------------------------


def replay_event(store: GraphStore, session_dir: Path, event: dict[str, Any]) -> None:
    """Reaplica um evento da fila (idempotente).

    O ``session_id`` vem do nome da pasta, não do evento; o contexto e os dados são revalidados.

    Raises:
        IngestionDataError: Evento malformado (não adianta reenviar).
        Exception: Falha do grafo (o evento continua pendente).
    """
    kind = event.get("kind")
    if kind not in EVENT_KINDS:
        raise IngestionDataError("tipo de evento desconhecido")
    ctx = SessionContext.from_dict(event.get("ctx"), session_id=session_dir.name)
    data = event.get("data")
    data = data if isinstance(data, dict) else {}
    if kind == EVENT_SESSION_START:
        ingest_session_start(store, ctx)
    elif kind == EVENT_INPUTS:
        ingest_inputs(store, ctx, session_dir)
    elif kind == EVENT_SUBTASK:
        ingest_subtask(store, ctx, session_dir, SubtaskInput.from_dict(data))
    else:
        consumo = data.get("consumo")
        ingest_session_end(
            store,
            ctx,
            fim=_text_field(data, "fim", 64),
            motivo_parada=_opt_text(data.get("motivo_parada"), 64),
            consumo=consumo if isinstance(consumo, dict) else None,
        )


@dataclass
class SyncReport:
    """Resultado de ``sync_pending``."""

    applied: int = 0
    pending: int = 0
    dead: int = 0
    ignored_lines: int = 0
    sessions: int = 0


def sync_session(store: GraphStore, session_dir: Path) -> SyncReport:
    """Reprocessa ``knowledge_pending.jsonl`` de uma sessão.

    Eventos aplicados saem da fila; os que falham ficam com ``attempts`` incrementado; ao atingir
    ``MAX_SYNC_ATTEMPTS`` (ou se forem malformados) vão para ``knowledge_pending.dead.jsonl``.
    """
    report = SyncReport(sessions=1)
    queue = PendingQueue(session_dir)
    try:
        events, report.ignored_lines = queue.read()
    except OSError as exc:
        logger.warning("Fila de pendências ilegível; sessão ignorada", extra={"extra": {"error": str(exc)}})
        return report
    remaining: list[dict[str, Any]] = []
    dead: list[dict[str, Any]] = []
    for event in events:
        try:
            replay_event(store, session_dir, event)
            report.applied += 1
            continue
        except IngestionDataError as exc:
            logger.warning("Evento pendente malformado; movido para a fila morta", extra={"extra": {"error": str(exc)}})
            dead.append(event)
            continue
        except Exception as exc:  # noqa: BLE001 - grafo fora do ar ou erro de escrita: segue pendente
            logger.warning("Evento pendente não aplicado", extra={"extra": {"error": type(exc).__name__}})
        attempts = event.get("attempts")
        attempts = (attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0) + 1
        event["attempts"] = attempts
        (dead if attempts >= MAX_SYNC_ATTEMPTS else remaining).append(event)
    for event in dead:
        PendingQueue(session_dir, filename=DEAD_FILENAME).append(event)
    queue.rewrite(remaining)
    report.pending = len(remaining)
    report.dead = len(dead)
    return report


def sync_pending(store: GraphStore, output_base: Path, session_id: str | None = None) -> SyncReport:
    """``geminiclaw knowledge sync``: reprocessa as filas de uma sessão ou de todas.

    Args:
        store: Grafo de conhecimento.
        output_base: Diretório raiz dos outputs (``OUTPUT_BASE_DIR``).
        session_id: Sessão específica; ``None`` varre todas as pastas com fila.

    Raises:
        IngestionDataError: ``session_id`` inválido.
    """
    base = Path(output_base)
    if session_id is not None:
        if not _SESSION_ID_RE.fullmatch(session_id):
            raise IngestionDataError(f"id de sessão inválido: {session_id!r}")
        candidates = [base / session_id]
    else:
        try:
            candidates = sorted(p for p in base.iterdir() if _SESSION_ID_RE.fullmatch(p.name))
        except OSError:
            candidates = []
    total = SyncReport(sessions=0)
    for directory in candidates:
        if directory.is_symlink() or not directory.is_dir() or not (directory / PENDING_FILENAME).exists():
            continue
        part = sync_session(store, directory)
        total.applied += part.applied
        total.pending += part.pending
        total.dead += part.dead
        total.ignored_lines += part.ignored_lines
        total.sessions += 1
    return total


# ---------------------------------------------------------------------------
# Ingestor da sessão (usado pelo orquestrador): nunca interrompe a pesquisa
# ---------------------------------------------------------------------------


class FactIngestor:
    """Ingere os fatos de uma sessão e guarda na fila local o que o grafo não aceitar.

    Todo método público é seguro: erros do grafo são capturados, viram um aviso e um evento em
    ``knowledge_pending.jsonl``. Depois da primeira falha, os eventos seguintes vão direto para a fila
    (sem esperar timeouts); no fim da sessão há uma tentativa de recuperação.
    """

    def __init__(
        self,
        store_factory: Callable[[], GraphStore],
        ctx: SessionContext,
        session_dir: Path,
        *,
        telemetry: Callable[[str, dict[str, Any], int], None] | None = None,
    ) -> None:
        self._factory = store_factory
        self.ctx = ctx
        self._session_dir = Path(session_dir)
        self._queue = PendingQueue(self._session_dir)
        self._telemetry = telemetry
        self._store: GraphStore | None = None
        self._down = False
        self._lock = threading.Lock()

    def _get_store(self) -> GraphStore:
        if self._store is None:
            self._store = self._factory()
        return self._store

    def _envelope(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "v": 1,
            "kind": kind,
            "ctx": {
                "project_id": self.ctx.project_id,
                "modo": self.ctx.modo,
                "inicio": self.ctx.inicio,
                "no_execucao": self.ctx.no_execucao,
                "continues_session_id": self.ctx.continues_session_id,
            },
            "data": data,
            "attempts": 0,
        }

    def _run(self, kind: str, data: dict[str, Any], op: Callable[[GraphStore], None]) -> bool:
        """Executa ``op``; em falha do grafo, enfileira o evento. Devolve ``True`` se aplicou."""
        started = time.monotonic()
        applied = queued = False
        with self._lock:
            try:
                if self._down:
                    raise ConnectionError("grafo indisponível nesta sessão")
                op(self._get_store())
                applied = True
            except IngestionDataError as exc:
                logger.warning(
                    "Evento de ingestão descartado (dado inválido)", extra={"extra": {"kind": kind, "error": str(exc)}}
                )
            except Exception as exc:  # noqa: BLE001 - a pesquisa nunca para por falha do grafo
                self._down = True
                self._store = None
                queued = self._queue.append(self._envelope(kind, data))
                logger.warning(
                    "Grafo indisponível: evento de ingestão guardado em knowledge_pending.jsonl "
                    "(reaplique com `geminiclaw knowledge sync`)",
                    extra={"extra": {"kind": kind, "error": type(exc).__name__, "queued": queued}},
                )
        if self._telemetry is not None:  # só tipo de evento, duração e resultado: nada de dados de pesquisa
            try:
                self._telemetry(kind, {"ok": applied, "queued": queued}, int((time.monotonic() - started) * 1000))
            except Exception as exc:  # noqa: BLE001
                logger.debug("Falha ao registrar telemetria de ingestão", extra={"extra": {"error": str(exc)}})
        return applied

    def session_start(self) -> bool:
        """Início da sessão: ``Sessao``, ``PERTENCE_A`` e ``CONTINUA``."""
        return self._run(EVENT_SESSION_START, {}, lambda s: ingest_session_start(s, self.ctx))

    def inputs(self) -> bool:
        """Snapshot de insumos: um ``Insumo`` por arquivo + ``RECEBEU``."""
        return self._run(EVENT_INPUTS, {}, lambda s: ingest_inputs(s, self.ctx, self._session_dir))

    def subtask(self, sub: SubtaskInput) -> bool:
        """Subtarefa concluída (e revisada): Experimento, Resultados, Abordagem."""
        return self._run(
            EVENT_SUBTASK, sub.to_dict(), lambda s: ingest_subtask(s, self.ctx, self._session_dir, sub)
        )

    def session_end(self, *, fim: str, motivo_parada: str | None, consumo: dict[str, Any] | None = None) -> bool:
        """Fim da sessão; antes, tenta recuperar o grafo e reenviar os pendentes desta sessão."""
        if self._down:
            self._recover()
        data = {"fim": fim, "motivo_parada": motivo_parada, "consumo": consumo or {}}
        return self._run(
            EVENT_SESSION_END,
            data,
            lambda s: ingest_session_end(s, self.ctx, fim=fim, motivo_parada=motivo_parada, consumo=consumo),
        )

    def _recover(self) -> None:
        """Uma tentativa de reabrir o grafo e esvaziar a fila desta sessão."""
        with self._lock:
            try:
                store = self._factory()
                store.list_nodes("Projeto", limit=1)  # sonda: abrir o pool é preguiçoso
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Grafo continua indisponível no fim da sessão", extra={"extra": {"error": type(exc).__name__}}
                )
                return
            self._store = store
            self._down = False
            report = sync_session(store, self._session_dir)
            if report.pending:
                self._down = True
