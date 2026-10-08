"""Juiz LLM das perguntas de ``ask_researcher`` e calibração humana (``v16-agent-communication-eval`` §5 e §6).

O modelo do juiz é selecionado automaticamente: diferente dos modelos de ``developer`` e
``researcher`` (planejamento) da sessão e do agente que perguntou. O texto enviado ao juiz passa
por redação (ADR 019 §3). Nada daqui é executado dentro da sessão, e nada é gravado nela.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from src import config
from src.egress.fragments import ContentOrigin, PromptFragment, labeled
from src.llm.pricing import estimate_cost, get_price
from src.utils.json_parser import extract_json

RUBRIC_VERSION = "1"
CRITERIA = ("necessidade", "clareza", "resposta", "efeito")
EXCLUDED_ROLES = ("developer", "researcher")
POOL_ROLES = ("reviewer", "validator", "summarizer", "base")
CALIBRATION_DIR = Path("docs/benchmarks/calibracao")
LABELS_PATH = CALIBRATION_DIR / "ask_researcher.jsonl"
CALIBRATION_RESULT_PATH = CALIBRATION_DIR / "resultado.json"
LOCAL_PROVIDERS = frozenset({"ollama"})

RUBRIC = "\n".join([
    "Escala de 1 a 3 para cada critério.",
    "necessidade: 1 = o contexto da própria pergunta já permitia decidir; "
    "2 = decisão razoável sem ajuda, mas com risco; "
    "3 = só o pesquisador (ou uma fonte externa) poderia decidir.",
    "clareza: 1 = pergunta ambígua ou sem contexto suficiente; 2 = compreensível, falta detalhe; "
    "3 = objetiva, com contexto e opções.",
    "resposta (apenas se houver resposta): 1 = não responde ou contradiz o contexto; "
    "2 = responde parcialmente; 3 = responde e é utilizável.",
    "efeito (apenas se pedido): 1 = o agente ignorou a resposta; 2 = uso parcial; "
    "3 = o agente passou a agir conforme a resposta.",
])


class JudgeUnavailable(RuntimeError):
    """O juiz não pode ser usado (configuração ausente, política de dados ou preço desconhecido)."""


@dataclass(frozen=True)
class JudgeSelection:
    """Modelo escolhido para o juiz e o motivo."""

    provider: str
    model: str
    reason: str
    excluded: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


# --------------------------------------------------------------------------------------------
# Redação e eventos
# --------------------------------------------------------------------------------------------

_URL_RE = re.compile(r"(?i)\b(?:(?:https?|ftp|file)://|www\.)\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d+)?")
_DECIMAL_RE = re.compile(r"\d+[.,]\d+")
_LONG_DIGITS_RE = re.compile(r"\d{6,}")
_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")


def _fold(text: str) -> str:
    """NFKC e remoção de caracteres invisíveis, para que a redação não seja contornada por Unicode."""
    return _INVISIBLE_RE.sub("", unicodedata.normalize("NFKC", text))


def redact_for_judge(text: str, protected_names: tuple[str, ...] | list[str] = (), max_chars: int | None = None) -> str:
    """Remove do texto o que não pode sair do nó (ADR 019 §3).

    O texto passa por NFKC e perde caracteres invisíveis. Decimais, números com separador de milhar e
    sequências de 6 ou mais dígitos viram ``<num>``; nomes de arquivos de entrada e de artefatos (sem
    diferenciar caixa) viram ``<arquivo>``; URLs (``http``, ``https``, ``ftp``, ``file``, ``www.``) e
    e-mails viram ``<url>`` e ``<email>``. O resultado é truncado em ``max_chars``
    (``COMM_EVAL_JUDGE_CONTEXT_CHARS`` quando omitido). Números escritos por extenso não são
    reconhecidos: é uma limitação conhecida, e o juiz externo continua exigindo opt-in.
    """
    out = _fold(text or "")
    out = _EMAIL_RE.sub("<email>", out)
    out = _URL_RE.sub("<url>", out)
    for name in sorted({_fold(n) for n in protected_names if n}, key=len, reverse=True):
        out = re.sub(re.escape(name), "<arquivo>", out, flags=re.IGNORECASE)
    out = _THOUSANDS_RE.sub("<num>", out)
    out = _DECIMAL_RE.sub("<num>", out)
    out = _LONG_DIGITS_RE.sub("<num>", out)
    limit = config.COMM_EVAL_JUDGE_CONTEXT_CHARS if max_chars is None else max_chars
    return out[:limit]


def protected_file_names(plan: dict[str, dict[str, Any]] | None, session_dir: Path | None) -> list[str]:
    """Nomes de arquivo que nunca saem do nó: artefatos esperados no plano e arquivos da sessão."""
    names: set[str] = set()
    for task in (plan or {}).values():
        for expected in task.get("expected_artifacts") or []:
            if isinstance(expected, str) and expected.strip():
                names.add(Path(expected).name)
    if session_dir and Path(session_dir).is_dir():
        for i, path in enumerate(Path(session_dir).rglob("*")):
            if i >= 2000:
                break
            if path.is_file() and path.name not in ("script.py", "scientific_helpers.py"):
                names.add(path.name)
    return sorted(n for n in names if len(n) >= 3)


def event_ref(session_id: str, ts: float, question: str) -> str:
    """Identificador estável de um evento ``ask_researcher``."""
    return hashlib.sha1(f"{session_id}|{ts:.3f}|{question}".encode("utf-8")).hexdigest()[:12]


def ask_events(session_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Eventos ``ask_researcher`` da sessão, com o modelo do agente que perguntou."""
    models = data.get("models_by_role", {})
    out = []
    for e in data["events"]:
        if e["event_type"] != "ask_researcher":
            continue
        p = e["payload"]
        out.append({
            "ref": event_ref(session_id, e["ts"], str(p.get("question", ""))), "session_id": session_id,
            "agent_id": e["agent_id"], "task_name": e.get("task_name"), "ts": e["ts"], "payload": p,
            "asker_model": models.get(e["agent_id"]),
        })
    return out


# --------------------------------------------------------------------------------------------
# Seleção do juiz
# --------------------------------------------------------------------------------------------

def parse_candidates(raw: str) -> list[str]:
    """Lista ``provedor/modelo`` separada por vírgula (entradas inválidas são recusadas)."""
    items = [c.strip() for c in (raw or "").split(",") if c.strip()]
    for item in items:
        if "/" not in item:
            raise JudgeUnavailable(f"Candidato a juiz inválido '{item}': use provedor/modelo.")
    return items


def canon_model(key: str) -> str:
    """Forma canônica de ``provedor/modelo`` para comparar exclusões (caixa, espaços e prefixo ``models/``)."""
    provider, _, model = (key or "").strip().partition("/")
    model = model.strip().lower()
    for prefix in ("models/", "publishers/google/models/"):
        if model.startswith(prefix):
            model = model[len(prefix):]
    return f"{provider.strip().lower()}/{model}"


def is_local_provider(provider: str) -> bool:
    """``ollama`` só é local quando ``OLLAMA_BASE_URL`` aponta para o próprio computador."""
    if provider not in LOCAL_PROVIDERS:
        return False
    host = (urlparse(config.OLLAMA_BASE_URL).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def _split(key: str) -> tuple[str, str]:
    provider, _, model = key.partition("/")
    return provider.lower(), model


def _price_rank(key: str) -> float:
    price = get_price(*_split(key))
    return float("inf") if price is None else price.input + price.output


def select_judge(
    models_by_role: dict[str, str],
    candidates: list[str] | None = None,
    asking_model: str | None = None,
    override: str | None = None,
) -> JudgeSelection | None:
    """Escolhe o modelo do juiz, diferente dos de ``developer`` e ``researcher`` e do que perguntou.

    Args:
        models_by_role: ``{papel: "provedor/modelo"}`` da sessão (de ``token_usage``).
        candidates: Candidatos extras (``COMM_EVAL_JUDGE_CANDIDATES``).
        asking_model: Modelo do agente que fez a pergunta (excluído por evento).
        override: ``provedor/modelo`` informado pelo pesquisador (sobrescrita opcional).

    Returns:
        A seleção, ou ``None`` se o único candidato válido for o modelo de quem perguntou
        (evento fica ``judge_skipped: same_model``).

    Raises:
        JudgeUnavailable: Se não houver candidato válido (a mensagem lista os excluídos).
    """
    excluded = sorted({models_by_role[r] for r in EXCLUDED_ROLES if r in models_by_role})
    excluded_canon = {canon_model(m) for m in excluded}
    excluded_providers = {canon_model(m).partition('/')[0] for m in excluded}
    if override:
        pool = [override]
    else:
        pool = []
        for key in [models_by_role[r] for r in POOL_ROLES if r in models_by_role] + list(candidates or []):
            if key not in pool:
                pool.append(key)
    valid = [m for m in pool if canon_model(m) not in excluded_canon]
    if not valid:
        raise JudgeUnavailable(
            "Nenhum candidato válido para o juiz. Modelos excluídos (developer e researcher): "
            f"{', '.join(excluded) or 'nenhum'}. Informe candidatos em COMM_EVAL_JUDGE_CANDIDATES."
        )
    asking = canon_model(asking_model) if asking_model else None
    allowed = [m for m in valid if canon_model(m) != asking]
    if not allowed:
        return None
    order = {m: i for i, m in enumerate(allowed)}
    best = min(
        allowed,
        key=lambda m: (canon_model(m).partition("/")[0] in excluded_providers, _price_rank(m), order[m]),
    )
    if override:
        reason = "sobrescrita do pesquisador"
    elif canon_model(best).partition('/')[0] not in excluded_providers:
        reason = "provedor diferente do desenvolvimento e do planejamento"
    else:
        reason = "menor preço entre os candidatos válidos"
    provider, model = _split(best)
    return JudgeSelection(provider.lower(), model, reason, excluded)


# --------------------------------------------------------------------------------------------
# Juiz
# --------------------------------------------------------------------------------------------

def deterministic_effect(answer: str | None, options: list[str], texts: list[str]) -> int | None:
    """Efeito resolvido por código: a opção escolhida aparece nos textos posteriores do agente.

    Returns:
        3 se a opção escolhida aparece em algum dos textos; ``None`` quando o código não decide.
    """
    if not answer:
        return None
    chosen = next((o for o in options if o and o.lower() in answer.lower()), None)
    if chosen is None:
        return None
    return 3 if any(chosen.lower() in (t or "").lower() for t in texts) else None


def _build_prompt(event: dict[str, Any], protected: list[str], texts: list[str], need_effect: bool) -> str:
    p = event["payload"]
    answer = _answer(p)
    redacted = lambda value: redact_for_judge(str(value or ""), protected)  # noqa: E731
    parts = [
        f"PERGUNTA: {redacted(p.get('question'))}",
        f"POR QUE NÃO PODE PROSSEGUIR: {redacted(p.get('why_cant_proceed'))}",
        f"OPÇÕES: {redacted('; '.join(str(o) for o in (p.get('options') or [])))}",
        f"CONTEXTO: {redacted(p.get('context'))}",
    ]
    wanted = ["necessidade", "clareza"]
    if answer:
        parts.append(f"RESPOSTA: {redacted(answer)}")
        wanted.append("resposta")
        if need_effect:
            parts.append("TEXTOS POSTERIORES DO AGENTE: " + redacted(" | ".join(texts)))
            wanted.append("efeito")
    parts.append("Avalie com a rubrica e responda SOMENTE com JSON: "
                 + json.dumps({k: "1-3" for k in wanted} | {"justificativa": "texto curto"}, ensure_ascii=False))
    return "\n".join(parts)


def _answer(payload: dict[str, Any]) -> str | None:
    value = payload.get("resposta") or payload.get("answer") or payload.get("researcher_response")
    return str(value) if value else None


def _parse_scores(text: str, wanted: list[str]) -> dict[str, Any] | None:
    data = extract_json(text or "")
    if not isinstance(data, dict):
        return None
    scores: dict[str, Any] = {}
    for key in wanted:
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value not in (1, 2, 3):
            return None
        scores[key] = value
    scores["justificativa"] = str(data.get("justificativa", ""))[:400]
    return scores


def judge_events(
    events: list[dict[str, Any]],
    models_by_role: dict[str, str],
    *,
    provider_factory: Callable[[str, str], Any],
    texts_by_task: dict[str, list[str]] | None = None,
    protected_names: list[str] | None = None,
    candidates: list[str] | None = None,
    override: str | None = None,
    allow_external: bool | None = None,
    max_usd: float | None = None,
) -> dict[str, Any]:
    """Avalia os eventos com o juiz selecionado e devolve notas, ignorados e custo.

    Nenhuma chamada é feita sem juiz válido; a avaliação do juiz termina com erro explícito
    (``error``) quando a configuração não permite, e o restante da avaliação segue.
    """
    allow_external = config.COMM_EVAL_ALLOW_EXTERNAL_JUDGE if allow_external is None else allow_external
    max_usd = config.COMM_EVAL_MAX_USD if max_usd is None else max_usd
    texts_by_task = texts_by_task or {}
    results: list[dict[str, Any]] = []
    spent = 0.0

    try:
        first = select_judge(models_by_role, candidates, None, override)
    except JudgeUnavailable as exc:
        return {"events": [], "error": str(exc), "skipped": {}, "cost_usd": 0.0}
    selection_info = {"selected": first.key if first else None, "excluded": first.excluded if first else [],
                      "reason": first.reason if first else None}

    for event in events:
        base = {"event_ref": event["ref"], "task_name": event.get("task_name"),
                "asker_model": event.get("asker_model")}
        selection = select_judge(models_by_role, candidates, event.get("asker_model"), override)
        if selection is None:
            results.append({**base, "status": "judge_skipped", "reason": "same_model"})
            continue
        external = not is_local_provider(selection.provider)
        if external and not allow_external:
            return {"events": results, "skipped": _count_skips(results), "cost_usd": round(spent, 6),
                    "error": "Juiz externo recusado: COMM_EVAL_ALLOW_EXTERNAL_JUDGE é falso e o modelo "
                             f"selecionado ({selection.key}) está fora do nó."}
        if external and get_price(selection.provider, selection.model) is None:
            return {"events": results, "skipped": _count_skips(results), "cost_usd": round(spent, 6),
                    "error": f"Preço desconhecido para {selection.key}: configure LLM_PRICING_OVERRIDES "
                             "para que o teto de custo possa ser aplicado."}
        if external and spent >= max_usd:
            results.append({**base, "status": "judge_skipped", "reason": "budget"})
            continue

        answer = _answer(event["payload"])
        texts = texts_by_task.get(event.get("task_name") or "", [])
        effect = deterministic_effect(answer, [str(o) for o in (event["payload"].get("options") or [])], texts)
        need_effect = bool(answer) and effect is None
        wanted = ["necessidade", "clareza"] + (["resposta"] if answer else []) + (["efeito"] if need_effect else [])
        prompt = _build_prompt(event, protected_names or [], texts, need_effect)

        try:
            provider = provider_factory(selection.provider, selection.model)
        except JudgeUnavailable as exc:
            return {"events": results, "skipped": _count_skips(results), "cost_usd": round(spent, 6),
                    "error": str(exc)}
        scores = None
        budget_stop = False
        for _ in range(2):  # uma nova tentativa
            if external and spent >= max_usd:  # o teto vale também para a nova tentativa
                budget_stop = True
                break
            response = _generate(provider, prompt)
            usage = response.usage or {}
            cost = estimate_cost(selection.provider, selection.model, usage.get("prompt_tokens", 0) or 0,
                                 usage.get("completion_tokens", 0) or 0)
            spent += cost or 0.0
            scores = _parse_scores(response.text or "", wanted)
            if scores is not None:
                break
        if scores is None:
            if budget_stop:
                results.append({**base, "status": "judge_skipped", "reason": "budget"})
            else:
                results.append({**base, "status": "judge_error", "judge": selection.key})
            continue
        if effect is not None:
            scores["efeito"] = effect
            scores["efeito_origem"] = "codigo"
        results.append({**base, "status": "judged", "judge": selection.key, "judge_reason": selection.reason,
                        "rubric_version": RUBRIC_VERSION, "scores": scores})

    return {"events": results, "skipped": _count_skips(results), "cost_usd": round(spent, 6),
            "selection": selection_info}


def _generate(provider: Any, prompt: str) -> Any:
    """Chamada síncrona ao provedor do juiz (a avaliação roda fora do event loop da sessão)."""
    import asyncio

    return asyncio.run(provider.generate(
        # O prompt do juiz é texto de agentes (já redigido pela guarda): trecho contaminado, para a camada de saída.
        messages=[labeled("user", PromptFragment(prompt, ContentOrigin.INSTRUCAO, tainted=True, source="juiz"))],
        system="Você é um avaliador independente de perguntas feitas por agentes de pesquisa. " + RUBRIC,
        temperature=0.0, max_tokens=600,
    ))


def _count_skips(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for r in results:
        if r["status"] == "judge_skipped":
            counts[r["reason"]] += 1
        elif r["status"] == "judge_error":
            counts["judge_error"] += 1
    return dict(counts)


def routed_provider_factory(provider: str, model: str) -> Any:
    """Cria o provedor do juiz passando pelo catálogo, pela política de dados e pelas regras de endpoint.

    O juiz não pode contornar o roteador (ADR 017): o modelo precisa estar no catálogo efetivo e,
    sob ``LLM_DATA_POLICY=self_hosted_only``, ser ``self_hosted``, mesmo com
    ``COMM_EVAL_ALLOW_EXTERNAL_JUDGE`` verdadeiro. ``create_provider`` ainda recusa endpoint
    remoto sem ``https``.

    Raises:
        JudgeUnavailable: Modelo fora do catálogo, recusado pela política ou endpoint inseguro.
    """
    from src.egress.gate import Destination, GatedProvider
    from src.llm.catalog import CatalogError
    from src.llm.endpoints import EndpointError
    from src.llm.registry import create_provider
    from src.llm.session import get_catalog

    key = f"{provider}/{model}"
    try:
        entry = get_catalog().modelos.get(key)
    except CatalogError as exc:  # inclui endpoint remoto sem https
        raise JudgeUnavailable(str(exc)) from exc
    if entry is None:
        raise JudgeUnavailable(
            f"Juiz {key} fora do catálogo de modelos: declare-o em catalog.local.yaml (ADR 017)."
        )
    if config.LLM_DATA_POLICY == "self_hosted_only" and entry.trust != "self_hosted":
        raise JudgeUnavailable(
            f"Juiz {key} é de terceiros e LLM_DATA_POLICY=self_hosted_only o recusa "
            "(defina LLM_DATA_POLICY=third_party_allowed para usá-lo)."
        )
    try:
        # Todo envio do juiz passa pela camada de saída (v18.5-egress-gate): registrado e filtrado pelo destino.
        return GatedProvider(
            create_provider(provider, model),
            Destination(
                canal="llm", provedor=entry.provedor, modelo=entry.modelo, trust=entry.trust,
                localidade=entry.localidade, aceita_dados_brutos=entry.aceita_dados_brutos, papel="juiz",
            ),
        )
    except EndpointError as exc:
        raise JudgeUnavailable(str(exc)) from exc


def judge_session(
    session_id: str,
    data: dict[str, Any],
    plan: dict[str, dict] | None = None,
    session_dir: Path | None = None,
) -> dict[str, Any]:
    """Juiz de uma sessão com a configuração de ``src/config.py`` e o provedor real.

    Os nomes de arquivo do plano e da pasta da sessão são protegidos na redação (ADR 019 §3).
    """
    events = ask_events(session_id, data)
    override = f"{config.COMM_EVAL_JUDGE_PROVIDER}/{config.COMM_EVAL_JUDGE_MODEL}" if (
        config.COMM_EVAL_JUDGE_PROVIDER and config.COMM_EVAL_JUDGE_MODEL) else None
    texts = {name: [t.get("prompt", ""), t.get("scientific_rationale", "")] for name, t in (plan or {}).items()}
    result = judge_events(
        events, data.get("models_by_role", {}), provider_factory=routed_provider_factory, texts_by_task=texts,
        protected_names=protected_file_names(plan, session_dir),
        candidates=parse_candidates(config.COMM_EVAL_JUDGE_CANDIDATES), override=override,
    )
    judged = [e for e in result["events"] if e["status"] == "judged"]
    by_judge: dict[str, dict[str, Any]] = {}
    for model in sorted({e["judge"] for e in judged}):
        mine = [e for e in judged if e["judge"] == model]
        calibration = calibration_status(CALIBRATION_RESULT_PATH, model, RUBRIC_VERSION)
        by_judge[model] = {"events": len(mine), "mean_scores": _mean_scores(mine), "calibration": calibration,
                           "scores_label": "calibrado" if calibration["calibrated"] else "não calibrado"}
    result["by_judge"] = by_judge
    single = next(iter(by_judge.values())) if len(by_judge) == 1 else None
    result["calibration"] = single["calibration"] if single else calibration_status(
        CALIBRATION_RESULT_PATH, None, RUBRIC_VERSION)
    result["scores_label"] = single["scores_label"] if single else "não calibrado"
    result["mean_scores"] = single["mean_scores"] if single else {}
    return result


def _mean_scores(judged: list[dict[str, Any]]) -> dict[str, float]:
    by: dict[str, list[int]] = defaultdict(list)
    for e in judged:
        for key in CRITERIA:
            if key in e["scores"]:
                by[key].append(e["scores"][key])
    return {k: round(sum(v) / len(v), 3) for k, v in by.items()}


# --------------------------------------------------------------------------------------------
# Calibração humana
# --------------------------------------------------------------------------------------------

def weighted_kappa(a: list[int], b: list[int], categories: tuple[int, ...] = (1, 2, 3)) -> float:
    """Kappa de Cohen ponderado (pesos quadráticos) entre duas listas de notas ordinais."""
    if len(a) != len(b) or not a:
        raise ValueError("As listas de notas precisam ter o mesmo tamanho, e não ser vazias.")
    k = len(categories)
    index = {c: i for i, c in enumerate(categories)}
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        observed[index[x]][index[y]] += 1
    n = float(len(a))
    row = [sum(observed[i]) for i in range(k)]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    weight = lambda i, j: ((i - j) / (k - 1)) ** 2  # noqa: E731
    num = sum(weight(i, j) * observed[i][j] for i in range(k) for j in range(k))
    den = sum(weight(i, j) * row[i] * col[j] / n for i in range(k) for j in range(k))
    if math.isclose(den, 0.0):
        return 1.0 if math.isclose(num, 0.0) else 0.0
    return round(1.0 - num / den, 4)


def calibration_sample(events: list[dict[str, Any]], size: int, seed: int) -> list[dict[str, Any]]:
    """Amostra determinística, estratificada por sessão e papel que perguntou (round-robin)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in sorted(events, key=lambda x: x["ref"]):
        groups[(e["session_id"], e["agent_id"])].append(e)
    rng = random.Random(seed)
    queues = []
    for key in sorted(groups):
        items = groups[key]
        rng.shuffle(items)
        queues.append(items)
    sample: list[dict[str, Any]] = []
    while len(sample) < size and any(queues):
        for queue in queues:
            if queue and len(sample) < size:
                sample.append(queue.pop(0))
    return sample


def write_sheet(sample: list[dict[str, Any]], out: Path) -> None:
    """Grava a planilha em branco para rotulagem humana (uma linha JSON por evento)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for e in sample:
        p = e["payload"]
        lines.append(json.dumps({
            "event_ref": e["ref"], "session_id": e["session_id"], "agent_id": e["agent_id"],
            "task_name": e.get("task_name"), "question": p.get("question"),
            "why_cant_proceed": p.get("why_cant_proceed"), "options": p.get("options"),
            "context": p.get("context"), "necessidade": None, "clareza": None, "rotulador": None,
            "rotulado_em": None,
        }, ensure_ascii=False))
    out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_labels(path: Path) -> dict[str, dict[str, Any]]:
    """Lê e valida os rótulos humanos (``necessidade`` e ``clareza`` de 1 a 3)."""
    labels: dict[str, dict[str, Any]] = {}
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        for key in ("necessidade", "clareza"):
            if row.get(key) is None:
                break
            if row[key] not in (1, 2, 3):
                raise ValueError(f"{path}:{n}: '{key}' deve ser 1, 2 ou 3 (veio {row[key]!r}).")
        else:
            labels[row["event_ref"]] = row
    return labels


def calibrate(judgments_path: Path, labels_path: Path) -> dict[str, Any]:
    """Kappa ponderado entre o juiz e os rótulos humanos, por critério.

    Args:
        judgments_path: JSON com a lista de eventos julgados (``ask_researcher.events`` do resultado).
        labels_path: Rótulos humanos (JSONL).
    """
    raw = json.loads(Path(judgments_path).read_text(encoding="utf-8"))
    events = raw.get("events", []) if isinstance(raw, dict) else raw
    judged = {e["event_ref"]: e for e in events if e.get("status") == "judged"}
    labels = read_labels(labels_path)
    common = sorted(set(judged) & set(labels))
    models = {judged[r]["judge"] for r in common}
    versions = {judged[r]["rubric_version"] for r in common}
    if len(models) > 1 or len(versions) > 1:
        raise ValueError("Os eventos calibrados foram julgados por mais de um modelo ou versão de rubrica.")
    kappa = {c: weighted_kappa([judged[r]["scores"][c] for r in common], [labels[r][c] for r in common])
             for c in ("necessidade", "clareza")} if common else {}
    return {"n": len(common), "kappa": kappa, "judge_model": next(iter(models), None),
            "rubric_version": next(iter(versions), None)}


def calibration_status(result_path: Path, judge_model: str | None, rubric_version: str) -> dict[str, Any]:
    """Diz se as notas do juiz estão calibradas (modelo, rubrica, tamanho e kappa batem)."""
    size, min_kappa = config.COMM_EVAL_CALIBRATION_SIZE, config.COMM_EVAL_MIN_KAPPA
    path = Path(result_path)
    if not path.exists():
        return {"calibrated": False, "kappa": None, "n": 0, "reason": "sem calibração registrada"}
    data = json.loads(path.read_text(encoding="utf-8"))
    base = {"kappa": data.get("kappa"), "n": data.get("n", 0)}
    if data.get("judge_model") != judge_model or data.get("rubric_version") != rubric_version:
        return {**base, "calibrated": False, "reason": "modelo do juiz ou versão da rubrica mudou"}
    if data.get("n", 0) < size:
        return {**base, "calibrated": False, "reason": f"menos de {size} eventos rotulados"}
    if not data.get("kappa") or any(k < min_kappa for k in data["kappa"].values()):
        return {**base, "calibrated": False, "reason": f"kappa abaixo de {min_kappa}"}
    return {**base, "calibrated": True, "reason": "ok"}
