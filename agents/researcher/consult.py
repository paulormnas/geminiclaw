"""Researcher consultor: responde ``ask_researcher`` nos modos ``semi`` e ``auto``.

V18 — Spec `researcher-consult` (ADR 012 §8). Uma chamada de LLM do papel ``researcher``, com
prompt e ferramentas próprios: somente ``quick_search`` e ``web_reader``, embrulhadas pela guarda
de consulta (``src/research_consult/query_guard.py``) e por limites de uso por consulta. Não há
``ask_researcher``, sandbox, escrita de arquivos ou escrita no grafo, logo não há recursão.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from src.llm.base import LLMProvider
from src.llm.metering import record_llm_call
from src.logger import get_logger
from src.research_consult.query_guard import DEFAULT_QUERY_MAX_CHARS, Ok, check_query
from src.utils.json_parser import extract_json

logger = get_logger(__name__)

TOOL_QUICK_SEARCH = "quick_search"
TOOL_WEB_READER = "web_reader"
FORMAT_RETRIES = 2
# Trecho de cada resultado devolvido ao modelo (não vai para o registro nem para a telemetria).
_TOOL_OUTPUT_MAX_CHARS = 6000

CONSULT_SYSTEM_PROMPT = """Você é o Researcher consultor do GeminiClaw. Outro agente do pipeline \
de pesquisa fez uma pergunta e não há pesquisador humano disponível; você responde no lugar dele.

REGRAS:
- Responda de forma curta e verificável. Diga quando não sabe; não invente.
- Prefira documentação oficial. Use `quick_search` para achar a página e `web_reader` para ler.
- NÃO faça busca bibliográfica (artigos, revisões de literatura). Só documentação técnica,
  definições e valores usuais de prática.
- NUNCA inclua na busca valores, números de medições, nomes de arquivos ou trechos de dados do
  projeto. Busque o conceito geral (ex.: "sklearn train_test_split stratify"), não os dados.
  Buscas com números decimais, números longos ou nomes de arquivo são recusadas.
- Você NÃO decide: aprovar Oportunidade, confirmar Problema, aprovar termo de vocabulário,
  autorizar escrita em instrumento e ativar o modo sem limite são decisões do pesquisador. Se a
  pergunta pedir uma delas, responda apenas {"reservada": true}.

SAÍDA FINAL: um único objeto JSON, sem texto fora dele:
{"resposta": "...", "confianca": "alta|media|baixa",
 "fontes": [{"url": "https://...", "titulo": "..."}],
 "suposicoes": ["..."], "recomendacao": "..."}
"""


class ConsultError(Exception):
    """O consultor não produziu uma resposta válida (formato, laço sem fim, etc.)."""


@dataclass
class ConsultResult:
    """Resultado de uma consulta ao Researcher."""

    resposta: dict[str, Any] = field(default_factory=dict)
    reservada: bool = False
    buscas_realizadas: list[dict[str, Any]] = field(default_factory=list)
    leituras: list[str] = field(default_factory=list)
    recusas: list[dict[str, str]] = field(default_factory=list)
    modelo: str = ""
    tokens: int = 0
    duracao_s: float = 0.0


def consult_tools(web_enabled: bool) -> list[dict[str, Any]]:
    """Ferramentas expostas ao modelo (formato OpenAI): só ``quick_search`` e ``web_reader``.

    Args:
        web_enabled: Se ``False``, nenhuma ferramenta é exposta.

    Returns:
        Lista de definições de ferramenta (vazia com a web desligada).
    """
    if not web_enabled:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": TOOL_QUICK_SEARCH,
                "description": "Busca curta na web (documentação técnica, definições).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Termos de busca gerais."},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_WEB_READER,
                "description": "Lê o texto de uma página (URL http/https).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer", "default": 4000},
                    },
                    "required": ["url"],
                },
            },
        },
    ]


def build_consult_prompt(
    *,
    question: str,
    context: str,
    why_cant_proceed: str,
    options: list[str],
    agent_role: str,
    subtask_name: str,
    plan_summary: str,
) -> str:
    """Monta a mensagem do usuário para o consultor (sem o histórico do agente que perguntou)."""
    parts = [
        f"Agente que perguntou: {agent_role or 'desconhecido'} (subtarefa: {subtask_name or '-'})",
        f"Pergunta: {question}",
    ]
    if context:
        parts.append(f"Contexto: {context}")
    if why_cant_proceed:
        parts.append(f"Por que não pôde decidir sozinho: {why_cant_proceed}")
    if options:
        parts.append("Opções: " + " | ".join(f"[{i}] {o}" for i, o in enumerate(options, 1)))
    if plan_summary:
        parts.append(f"Resumo do plano corrente:\n{plan_summary}")
    return "\n".join(parts)


def format_answer(parsed: dict[str, Any]) -> str:
    """Texto devolvido ao agente que perguntou.

    Args:
        parsed: JSON validado do consultor (``resposta``, ``confianca``, ``fontes``, ...).

    Returns:
        ``[Resposta do Researcher (consultor), confiança <c>] <resposta>`` mais fontes numeradas e
        suposições.
    """
    confianca = parsed.get("confianca") or "baixa"
    lines = [f"[Resposta do Researcher (consultor), confiança {confianca}] {parsed.get('resposta', '')}"]
    if parsed.get("recomendacao"):
        lines.append(f"Recomendação: {parsed['recomendacao']}")
    fontes = parsed.get("fontes") or []
    if fontes:
        lines.append("Fontes:")
        for i, f in enumerate(fontes, 1):
            url = f.get("url", "") if isinstance(f, dict) else str(f)
            titulo = f.get("titulo", "") if isinstance(f, dict) else ""
            lines.append(f"{i}. {titulo} {url}".rstrip())
    suposicoes = parsed.get("suposicoes") or []
    if suposicoes:
        lines.append("Suposições:")
        lines.extend(f"- {s}" for s in suposicoes)
    lines.append("Registre em 'scientific_rationale' que usou esta consulta.")
    return "\n".join(lines)


def _clip(output: Any) -> str:
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    return text[:_TOOL_OUTPUT_MAX_CHARS]


class _ConsultRun:
    """Estado de uma consulta: contadores de ferramentas e registros para auditoria."""

    def __init__(
        self,
        *,
        search_skill: Any,
        reader_skill: Any,
        protected_names: Iterable[str],
        max_searches: int,
        max_reads: int,
        query_max_chars: int,
    ) -> None:
        self.search_skill = search_skill
        self.reader_skill = reader_skill
        self.protected = list(protected_names)
        self.max_searches = max_searches
        self.max_reads = max_reads
        self.query_max_chars = query_max_chars
        self.searches_used = 0
        self.reads_used = 0
        self.buscas: list[dict[str, Any]] = []
        self.leituras: list[str] = []
        self.recusas: list[dict[str, str]] = []

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        """Executa uma chamada de ferramenta do modelo, aplicando limites e guarda."""
        if name == TOOL_QUICK_SEARCH:
            return await self._search(str(args.get("query", "")), args.get("max_results", 5))
        if name == TOOL_WEB_READER:
            return await self._read(str(args.get("url", "")), args.get("max_chars", 4000))
        return f"Erro: ferramenta '{name}' não disponível para o consultor."

    async def _search(self, query: str, max_results: Any) -> str:
        if self.searches_used >= self.max_searches:
            return f"Erro: limite de {self.max_searches} buscas por consulta atingido."
        self.searches_used += 1  # recusa também conta no limite (design §4)
        verdict = check_query(query, self.protected, self.query_max_chars)
        if not isinstance(verdict, Ok):
            self.recusas.append({"ferramenta": TOOL_QUICK_SEARCH, "texto": query, "motivo": verdict.motivo})
            return f"Busca recusada pela guarda de consulta (motivo: {verdict.motivo}). Reformule sem dados do projeto."
        try:
            result = await self.search_skill.run(query=query, max_results=int(max_results or 5))
        except Exception as exc:  # falha de rede/backend vira resposta ao modelo, não erro da consulta
            self.buscas.append({"query": query, "backend": None, "erro": str(exc)[:200]})
            return f"Erro na busca: {exc}"
        backend = (result.metadata or {}).get("source")
        self.buscas.append({"query": query, "backend": backend})
        if not result.success:
            return f"Erro na busca: {result.error}"
        return _clip(result.output)

    async def _read(self, url: str, max_chars: Any) -> str:
        if self.reads_used >= self.max_reads:
            return f"Erro: limite de {self.max_reads} leituras por consulta atingido."
        self.reads_used += 1
        verdict = check_query(url, self.protected, max(self.query_max_chars, 300))
        if not isinstance(verdict, Ok):
            self.recusas.append({"ferramenta": TOOL_WEB_READER, "texto": url, "motivo": verdict.motivo})
            return f"Leitura recusada pela guarda de consulta (motivo: {verdict.motivo})."
        self.leituras.append(url)
        try:
            result = await self.reader_skill.run(url=url, max_chars=int(max_chars or 4000))
        except Exception as exc:
            return f"Erro na leitura: {exc}"
        if not result.success:
            return f"Erro na leitura: {result.error}"
        return _clip(result.output)


async def run_consult(
    provider: LLMProvider,
    *,
    question: str,
    context: str = "",
    why_cant_proceed: str = "",
    options: list[str] | None = None,
    agent_role: str = "",
    subtask_name: str = "",
    plan_summary: str = "",
    protected_names: Iterable[str] = (),
    web_enabled: bool = True,
    search_skill: Any = None,
    reader_skill: Any = None,
    max_searches: int = 3,
    max_reads: int = 2,
    query_max_chars: int = DEFAULT_QUERY_MAX_CHARS,
) -> ConsultResult:
    """Executa uma consulta ao Researcher (laço de ferramentas curto + resposta JSON validada).

    Args:
        provider: Provedor LLM do papel ``researcher``.
        question, context, why_cant_proceed, options: Pergunta do agente (``ask_researcher``).
        agent_role, subtask_name: Quem perguntou.
        plan_summary: Resumo do plano corrente.
        protected_names: Nomes de arquivo da sessão que não podem sair em buscas.
        web_enabled: Se ``False``, nenhuma ferramenta é exposta.
        search_skill, reader_skill: Skills ``quick_search`` e ``web_reader`` (qualquer objeto com
            ``run`` assíncrono compatível).
        max_searches, max_reads: Limites de ferramentas por consulta.
        query_max_chars: Tamanho máximo de uma consulta.

    Returns:
        ``ConsultResult``. Com ``reservada=True`` quando o modelo classificou a pergunta como
        decisão reservada ao pesquisador.

    Raises:
        ConsultError: Se o modelo não devolver um JSON válido após as correções de formato.
    """
    started = time.monotonic()
    tools = consult_tools(web_enabled)
    state = _ConsultRun(
        search_skill=search_skill,
        reader_skill=reader_skill,
        protected_names=protected_names,
        max_searches=max_searches,
        max_reads=max_reads,
        query_max_chars=query_max_chars,
    )
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": build_consult_prompt(
                question=question,
                context=context,
                why_cant_proceed=why_cant_proceed,
                options=options or [],
                agent_role=agent_role,
                subtask_name=subtask_name,
                plan_summary=plan_summary,
            ),
        }
    ]
    tokens = 0
    format_failures = 0
    max_turns = (max_searches + max_reads + 1 if tools else 1) + FORMAT_RETRIES + 1
    result = ConsultResult(modelo=provider.model_name or "")

    for _ in range(max_turns):
        t0 = time.monotonic()
        response = await provider.generate(
            messages=messages, tools=tools or None, system=CONSULT_SYSTEM_PROMPT, temperature=0.2
        )
        record_llm_call(provider, response, int((time.monotonic() - t0) * 1000), agent_id="researcher")
        usage = response.usage or {}
        tokens += (usage.get("prompt_tokens", 0) or 0) + (usage.get("completion_tokens", 0) or 0)
        messages.append(response.to_message())

        if response.tool_calls:
            for call in response.tool_calls:
                out = await state.execute(call.name, call.arguments) if tools else (
                    f"Erro: ferramenta '{call.name}' não disponível para o consultor."
                )
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": out})
            continue

        parsed = extract_json(response.text or "")
        if isinstance(parsed, dict) and parsed.get("reservada") is True:
            result.reservada = True
            break
        if isinstance(parsed, dict) and isinstance(parsed.get("resposta"), str) and parsed["resposta"].strip():
            result.resposta = {
                "resposta": parsed["resposta"],
                "confianca": (
                    parsed["confianca"] if parsed.get("confianca") in ("alta", "media", "baixa") else "baixa"
                ),
                "fontes": parsed.get("fontes") if isinstance(parsed.get("fontes"), list) else [],
                "suposicoes": parsed.get("suposicoes") if isinstance(parsed.get("suposicoes"), list) else [],
                "recomendacao": parsed.get("recomendacao") or "",
            }
            break
        format_failures += 1
        if format_failures > FORMAT_RETRIES:
            raise ConsultError("o consultor não devolveu JSON válido com 'resposta'")
        messages.append(
            {
                "role": "user",
                "content": 'Formato inválido. Responda somente com o objeto JSON pedido ("resposta", '
                '"confianca", "fontes", "suposicoes", "recomendacao") ou {"reservada": true}.',
            }
        )
    else:
        raise ConsultError("o consultor não concluiu a resposta no limite de turnos")

    result.buscas_realizadas = state.buscas
    result.leituras = state.leituras
    result.recusas = state.recusas
    result.tokens = tokens
    result.duracao_s = round(time.monotonic() - started, 3)
    return result
