"""Gate persistente de decisões reservadas ao pesquisador (v18.7-persistent-human-gate, design §1.2 e §2.3).

Os pedidos vivem na tabela ``gate_requests``: a sessão (processo próprio) cria e consome; o terminal responde. Só uma
origem humana (``HUMAN_SOURCES``) resolve um pedido; uma mensagem de agente, de documento, do consultor ou da caixa
de entrada nunca o resolve. A resposta é uma transição condicional (``WHERE estado = 'pendente'``): a segunda
resposta é recusada. O consumo é de uso único e ligado ao objeto (``consume_authorized``).

Garantia (ambiente de desenvolvimento, decisão do pesquisador em 2026-10-16): o código da sessão e os agentes não
resolvem pedidos porque só ``TerminalGate`` tem ``answer`` e a sessão nunca o instancia (teste estático). Isto **não**
protege contra código arbitrário com acesso direto ao banco; o endurecimento (papel de banco separado) é uma mudança
anterior à produção.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from src import config
from src.db import get_connection
from src.gate.catalog import ACOES_NEGATIVAS, GATE_CATALOG, validate_request
from src.gate.types import (
    ESTADO_AUTORIZADA,
    ESTADO_NEGADA,
    ESTADO_PENDENTE,
    HUMAN_SOURCES,
    MAX_REFERENCE_CHARS,
    GateAlreadyResolved,
    GateAuthorizationRefused,
    GateInvalidRequest,
    GatePendingLimitReached,
    GateRequest,
    Source,
)
from src.logger import get_logger
from src.utils.display_text import sanitize_line

logger = get_logger(__name__)

_TEXT_KEYS = ("texto", "motivo", "enunciado", "orientacao")
_HUMAN = [s.value for s in HUMAN_SOURCES]  # "terminal" e "cli"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else value.isoformat()


def _row_to_request(row: Any) -> GateRequest:
    opcoes = row["opcoes"]
    if isinstance(opcoes, str):
        opcoes = json.loads(opcoes)
    resposta = row["resposta"]
    if isinstance(resposta, str):
        resposta = json.loads(resposta)
    return GateRequest(
        id=int(row["id"]),
        decisao=row["decisao"],
        referencia=row["referencia"],
        estado=row["estado"],
        resolvido_por=row["resolvido_por"],
        pergunta=row["pergunta"] or "",
        opcoes=tuple(opcoes or ()),
        motivo=row["motivo"],
        session_id=row["session_id"],
        project_id=row["project_id"],
        resposta=resposta,
        consumido=row["consumido_em"] is not None,
        obsoleto=row["obsoleto_em"] is not None,
        criado_em=_iso(row["criado_em"]),
        resolvido_em=_iso(row["resolvido_em"]),
    )


def clean_answer(decisao: str, opcoes: tuple[str, ...], resposta: dict[str, Any]) -> dict[str, Any]:
    """Valida e normaliza a resposta do pesquisador contra o catálogo e as opções do pedido.

    Raises:
        GateInvalidRequest: ação fora das opções do pedido, texto acima de ``GATE_ANSWER_MAX_CHARS`` ou sem texto
            onde ele é obrigatório. O texto livre nunca é truncado em silêncio.
    """
    kind = GATE_CATALOG[decisao]
    clean: dict[str, Any] = {}
    acao = resposta.get("acao")
    if decisao == "responder_pergunta_agente":
        acao = "responder"
    allowed = opcoes or kind.acoes
    if acao not in allowed:
        raise GateInvalidRequest(f"resposta fora das opções do pedido: use {list(allowed)}.")
    clean["acao"] = acao
    limit = int(config.GATE_ANSWER_MAX_CHARS)
    for key in _TEXT_KEYS:
        value = resposta.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise GateInvalidRequest(f"'{key}' deve ser texto.")
        if len(value) > limit:
            raise GateInvalidRequest(f"'{key}' passa de {limit} caracteres; encurte o texto (não é truncado).")
        clean[key] = sanitize_line(value, 0)
    if decisao == "responder_pergunta_agente" and not clean.get("texto"):
        raise GateInvalidRequest("a resposta à pergunta do agente precisa de 'texto'.")
    return clean


class PersistentGate:
    """Pedidos ao pesquisador no banco: criar, listar, consumir. **Não** responde (ver ``TerminalGate``)."""

    # -- criação ------------------------------------------------------------------------------------

    def request(
        self,
        decisao: str,
        referencia: str = "",
        pergunta: str = "",
        opcoes: Iterable[str] = (),
        *,
        motivo: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> GateRequest:
        """Cria o pedido pendente; idempotente por (sessão, decisão, referência) enquanto não consumido.

        Raises:
            GateInvalidRequest: decisão, motivo ou opções fora do catálogo.
            GatePendingLimitReached: a sessão já tem ``GATE_MAX_PENDING_PER_SESSION`` pendentes (o chamador registra
                o excesso como evento e não cria o pedido).
        """
        options = tuple(opcoes)
        try:
            validate_request(decisao, motivo, options)
        except ValueError as exc:
            raise GateInvalidRequest(str(exc)) from None
        reference = str(referencia)[:MAX_REFERENCE_CHARS]
        text = sanitize_line(pergunta, int(config.GATE_QUESTION_MAX_CHARS))
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM gate_requests WHERE COALESCE(session_id, '') = %s AND decisao = %s AND referencia = %s "
                "AND consumido_em IS NULL AND obsoleto_em IS NULL ORDER BY id DESC LIMIT 1",
                (session_id or "", decisao, reference),
            ).fetchone()
            if existing:
                return _row_to_request(existing)
            if session_id is not None:
                count = conn.execute(
                    "SELECT count(*) AS n FROM gate_requests WHERE session_id = %s AND estado = 'pendente' "
                    "AND obsoleto_em IS NULL",
                    (session_id,),
                ).fetchone()["n"]
                if count >= int(config.GATE_MAX_PENDING_PER_SESSION):
                    raise GatePendingLimitReached(
                        f"a sessão já tem {count} pedidos pendentes (GATE_MAX_PENDING_PER_SESSION)."
                    )
            row = conn.execute(
                "INSERT INTO gate_requests (session_id, project_id, decisao, motivo, referencia, pergunta, opcoes) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING *",
                (session_id, project_id, decisao, motivo, reference, text, json.dumps(list(options))),
            ).fetchone()
        logger.info(
            "Decisão reservada ao pesquisador registrada",
            extra={"extra": {"decisao": decisao, "id": int(row["id"]), "motivo": motivo}},
        )
        return _row_to_request(row)

    # -- consulta -----------------------------------------------------------------------------------

    def get(self, request_id: int) -> GateRequest | None:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM gate_requests WHERE id = %s", (request_id,)).fetchone()
        return _row_to_request(row) if row else None

    def pending(self, session_ids: Iterable[str] | None = None) -> list[GateRequest]:
        """Pedidos sem resposta (e não obsoletos) das sessões dadas; sem ``session_ids``, de todas (terminal)."""
        with get_connection() as conn:
            if session_ids is None:
                rows = conn.execute(
                    "SELECT * FROM gate_requests WHERE estado = 'pendente' AND obsoleto_em IS NULL ORDER BY id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gate_requests WHERE estado = 'pendente' AND obsoleto_em IS NULL "
                    "AND session_id = ANY(%s) ORDER BY id",
                    (list(session_ids),),
                ).fetchall()
        return [_row_to_request(r) for r in rows or []]

    def find_in_chain(self, decisao: str, referencia: str, session_chain: Iterable[str]) -> GateRequest | None:
        """Pedido ainda não consumido nem obsoleto de ``decisao`` + ``referencia`` em qualquer sessão da cadeia (o mais
        recente), ou ``None``. Na retomada, a sessão nova reaproveita o pedido da anterior (pendente ou respondido)."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM gate_requests WHERE decisao = %s AND referencia = %s AND session_id = ANY(%s) "
                "AND consumido_em IS NULL AND obsoleto_em IS NULL ORDER BY id DESC LIMIT 1",
                (decisao, str(referencia)[:MAX_REFERENCE_CHARS], list(session_chain)),
            ).fetchone()
        return _row_to_request(row) if row else None

    def answered_unconsumed(self, session_ids: Iterable[str]) -> list[GateRequest]:
        """Pedidos respondidos e ainda não aplicados pela sessão (inclui os respondidos com a sessão fora)."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM gate_requests WHERE estado <> 'pendente' AND consumido_em IS NULL "
                "AND obsoleto_em IS NULL AND session_id = ANY(%s) ORDER BY id",
                (list(session_ids),),
            ).fetchall()
        return [_row_to_request(r) for r in rows or []]

    def authorized(self, request_id: int) -> bool:
        """``True`` somente se o pesquisador autorizou (pendente e negada falham fechado)."""
        req = self.get(request_id)
        return req is not None and req.estado == ESTADO_AUTORIZADA and req.resolvido_por in _HUMAN

    # -- consumo ------------------------------------------------------------------------------------

    def mark_consumed(self, request_id: int) -> bool:
        """Marca o pedido como aplicado (``consumido_em``); ``False`` se já estava consumido."""
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE gate_requests SET consumido_em = now() WHERE id = %s AND consumido_em IS NULL RETURNING id",
                (request_id,),
            ).fetchone()
        return row is not None

    def mark_obsolete(self, request_id: int) -> bool:
        """Marca o pedido como obsoleto (some das listas; por exemplo, hipótese retirada pelo replanejamento)."""
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE gate_requests SET obsoleto_em = now() WHERE id = %s AND obsoleto_em IS NULL RETURNING id",
                (request_id,),
            ).fetchone()
        return row is not None

    def consume_authorized(self, decisao: str, referencia: str, session_chain: Iterable[str]) -> GateRequest:
        """Confere e consome, de uma vez, a autorização de ``decisao`` + ``referencia`` (uso único; design §1.2).

        Vale só pedido da cadeia da sessão (``session_id`` em ``session_chain``) com ``estado = 'autorizada'`` e
        ``resolvido_por`` humano. Pedido da CLI fora de sessão (``session_id`` nulo) só vale quando ``session_chain``
        é vazia (processo de CLI); nunca para um processo de sessão.

        Raises:
            GateAuthorizationRefused: ``nao_encontrada``, ``outra_sessao``, ``ja_consumida`` ou ``nao_autorizada``.
        """
        chain = list(session_chain)
        human = _HUMAN
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM gate_requests WHERE decisao = %s AND referencia = %s AND obsoleto_em IS NULL "
                "ORDER BY id DESC",
                (decisao, str(referencia)[:MAX_REFERENCE_CHARS]),
            ).fetchall()
            if not rows:
                raise GateAuthorizationRefused("nao_encontrada")
            valid = [r for r in rows if (r["session_id"] in chain if chain else r["session_id"] is None)]
            if not valid:
                raise GateAuthorizationRefused("outra_sessao")
            usable = [
                r for r in valid
                if r["estado"] == ESTADO_AUTORIZADA and r["resolvido_por"] in human and r["consumido_em"] is None
            ]
            if not usable:
                done = [r for r in valid if r["estado"] == ESTADO_AUTORIZADA and r["resolvido_por"] in human]
                raise GateAuthorizationRefused("ja_consumida" if done else "nao_autorizada")
            row = conn.execute(
                "UPDATE gate_requests SET consumido_em = now() WHERE id = %s AND consumido_em IS NULL RETURNING *",
                (usable[0]["id"],),
            ).fetchone()
            if row is None:  # outro consumidor chegou antes
                raise GateAuthorizationRefused("ja_consumida")
        return _row_to_request(row)

    def was_authorized(self, decisao: str, referencia: str, session_chain: Iterable[str]) -> bool:
        """Leitura sem consumo: já existe autorização humana (consumida ou não) deste objeto na cadeia da sessão.

        Lê ``gate_requests``, nunca a trilha de auditoria do grafo (parecer de segurança).
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM gate_requests WHERE decisao = %s AND referencia = %s AND estado = 'autorizada' "
                "AND resolvido_por = ANY(%s) AND session_id = ANY(%s) LIMIT 1",
                (decisao, str(referencia)[:MAX_REFERENCE_CHARS], _HUMAN, list(session_chain)),
            ).fetchone()
        return row is not None

    def authorized_reference(self, decisao: str, referencia: str) -> bool:
        """Leitura **sem consumo**: existe autorização humana para ``decisao`` + ``referencia`` (qualquer sessão).

        Só para ``ativar_adendo_regimento``, cuja referência é o sha256 dos bytes do adendo (a autorização vale para
        aquele conteúdo, em qualquer sessão, e não é consumida).
        """
        if decisao != "ativar_adendo_regimento":
            raise GateInvalidRequest("leitura sem consumo só existe para 'ativar_adendo_regimento'.")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM gate_requests WHERE decisao = %s AND referencia = %s AND estado = 'autorizada' "
                "AND resolvido_por = ANY(%s) LIMIT 1",
                (decisao, str(referencia)[:MAX_REFERENCE_CHARS], _HUMAN),
            ).fetchone()
        return row is not None


class TerminalGate(PersistentGate):
    """Gate do processo do terminal (REPL, comando direto e comandos de CLI): o único que responde pedidos.

    A sessão e os agentes nunca instanciam esta classe (teste estático ``test_gate_guarantees``).
    """

    def resolve(
        self,
        decisao: str,
        referencia: str = "",
        *,
        source: Source,
        approved: bool,
        pergunta: str = "",
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> GateRequest:
        """Pede e resolve de uma vez uma decisão que o pesquisador toma no próprio terminal (confirmar o Problema,
        ``vocab approve``, ``opportunities approve``...). Idempotente: se o pedido já foi resolvido, devolve-o como está
        (a decisão anterior do pesquisador vale; nada é sobrescrito).

        Raises:
            GateInvalidRequest: decisão ou subtipo fora do catálogo.
        """
        request = self.request(
            decisao, referencia, pergunta, session_id=session_id, project_id=project_id,
            opcoes=GATE_CATALOG[decisao].acoes if decisao in GATE_CATALOG else (),
        )
        if request.estado != ESTADO_PENDENTE:
            return request
        try:
            return self.answer(request.id, source=source, approved=approved)
        except GateAlreadyResolved:  # outro terminal chegou antes
            return self.get(request.id) or request

    def answer(
        self,
        request_id: int,
        *,
        source: Source,
        approved: bool | None = None,
        resposta: dict[str, Any] | None = None,
    ) -> GateRequest:
        """Resolve o pedido (transição condicional ``pendente -> autorizada/negada``).

        Fonte que não seja ``HUMAN_SOURCES`` é ignorada e o pedido segue pendente. ``approved`` serve às decisões
        autorizar/negar; as demais levam ``resposta`` com ``acao`` (e texto, quando o tipo pede).

        Raises:
            KeyError: pedido inexistente.
            GateInvalidRequest: resposta fora das opções do pedido ou texto acima do limite.
            GateAlreadyResolved: o pedido já foi resolvido.
        """
        current = self.get(request_id)
        if current is None:
            raise KeyError(request_id)
        if not isinstance(source, Source) or source not in HUMAN_SOURCES:
            logger.warning(
                "Resposta de fonte não humana ignorada: a decisão continua pendente para o pesquisador",
                extra={"extra": {"decisao": current.decisao, "origem": str(getattr(source, "value", source))[:40]}},
            )
            return current
        if current.estado != ESTADO_PENDENTE:
            raise GateAlreadyResolved(f"o pedido {request_id} já foi resolvido ({current.estado}).")
        if resposta is None:
            if approved is None:
                raise GateInvalidRequest("informe 'approved' ou 'resposta'.")
            resposta = {"acao": "autorizar" if approved else "negar"}
        answer = clean_answer(current.decisao, current.opcoes, resposta)
        estado = ESTADO_NEGADA if answer["acao"] in ACOES_NEGATIVAS else ESTADO_AUTORIZADA
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE gate_requests SET estado = %s, resposta = %s::jsonb, resolvido_por = %s, resolvido_em = now() "
                "WHERE id = %s AND estado = 'pendente' RETURNING *",
                (estado, json.dumps(answer), source.value, request_id),
            ).fetchone()
        if row is None:
            raise GateAlreadyResolved(f"o pedido {request_id} já foi resolvido.")
        return _row_to_request(row)


_terminal_gate: "TerminalGate | None" = None
_session_gate: "PersistentGate | None" = None


def terminal_gate() -> "TerminalGate":
    """Gate do processo do terminal (REPL, comando direto e comandos de CLI): o único que responde pedidos."""
    global _terminal_gate
    if _terminal_gate is None:
        _terminal_gate = TerminalGate()
    return _terminal_gate


def session_gate() -> "PersistentGate":
    """Gate do processo da sessão: cria, lista e consome pedidos; nunca responde (não tem ``answer``)."""
    global _session_gate
    if _session_gate is None:
        _session_gate = PersistentGate()
    return _session_gate


def set_gates(terminal: Any | None = None, session: Any | None = None) -> None:
    """Troca os gates do processo (testes de unidade injetam ``FakeGate``); ``None`` volta ao gate de produção."""
    global _terminal_gate, _session_gate
    _terminal_gate, _session_gate = terminal, session


def authorize_from_cli(decisao: str, referencia: str = "", gate: Any | None = None) -> bool:
    """Registra e autoriza uma decisão reservada executada pelo **pesquisador** na CLI (``resolvido_por='cli'``).

    Só deve ser chamado de dentro de um comando de CLI disparado pelo pesquisador (nunca de código que processe
    resposta de agente ou de consultor). A barreira final continua sendo ``validate_human_only`` no ``GraphStore``.
    """
    active = gate or terminal_gate()
    req = active.resolve(decisao, referencia, source=Source.CLI, approved=True)
    return bool(active.authorized(req.id))
