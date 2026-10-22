"""Ferramentas de escrita tipada do Curator (descobertas, oportunidades, caminhos, fusões e sinalizações)."""

from __future__ import annotations

from typing import Any

from src import config
from src.knowledge.curator_common import (
    _MAX_AUDIT_REASON,
    _MAX_ROWS,
    _STATUS_DISCOVERY,
    DISCOVERY_TYPES,
    FLAG_DECISIONS,
    SOBRE_LABELS,
    CuratorToolError,
)
from src.knowledge.curator_flags import (
    ESTADO_DESCARTADA,
    FlagError,
)
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import Node
from src.knowledge.result_records import QUALIFICACOES, holds_fails, holds_works
from src.knowledge.semantic_index import IGNORED_STATUSES, canonical_text
from src.knowledge.service import KnowledgeServiceError
from src.logger import get_logger
from src.utils.normalization import clean_free_text

logger = get_logger(__name__)


class CuratorWrites:
    def create_discovery(
        self,
        tipo: str,
        enunciado: str,
        condicoes: str,
        sobre_ids: list[str],
        evidencia_ids: list[str],
        justificativa: str,
        filtro_condicoes: dict[str, Any] | None = None,
        variacao_de: str | None = None,
        diferenca: str | None = None,
    ) -> dict[str, Any]:
        """Cria uma ``Descoberta`` após revisar o que já existe (ADR 015 §10). Ver o docstring do módulo."""
        if tipo == "caminho_sem_conclusao":
            return self._refuse("caminho sem conclusão é registrado por register_open_path.")
        if tipo not in DISCOVERY_TYPES:
            return self._refuse(f"tipo inválido; use um de {list(DISCOVERY_TYPES)}.")
        enunciado_c = self._text("enunciado", enunciado)
        condicoes_c = self._text("condicoes", condicoes, required=tipo == "condicional")
        justificativa_c = self._text("justificativa", justificativa)
        diferenca_c = self._text("diferenca", diferenca, required=False)
        filtro = self._filter(filtro_condicoes)
        sobre = self._ids("sobre_ids", sobre_ids, required=True)
        evidencias = self._ids("evidencia_ids", evidencia_ids)
        if not evidencias:
            return self._refuse(
                "toda descoberta exige evidência ligada (evidencia_ids: Resultado, Experimento ou Decisao); "
                "especulação sem evidência não vira nó."
            )
        sobre_nodes = [self._node("sobre_ids", i, SOBRE_LABELS) for i in sobre]
        bad_evidence = self._check_evidence(self._evidence_nodes(evidencias), sobre_nodes)
        if bad_evidence is not None:
            return self._refuse(bad_evidence)
        variacao = self._id("variacao_de", variacao_de) if variacao_de else None
        record_ids: list[str] = []
        if tipo in ("funciona", "nao_funciona") or (tipo == "condicional" and filtro):
            blocked, record_ids = self._gate_records(tipo, sobre_nodes, filtro)
            if blocked is not None:
                return blocked
        evidencias = list(dict.fromkeys([*evidencias, *record_ids]))
        props = {
            "tipo": tipo,
            "enunciado": enunciado_c,
            "condicoes": condicoes_c or None,
        }
        review = self._review(
            "Descoberta", {k: v for k, v in props.items() if v}, sobre=sobre, extra_consulted=evidencias
        )
        refusal = self._check_duplicates(review, variacao, diferenca_c, "Descoberta")
        if refusal is not None:
            return refusal
        self._spend_write()
        justificativa_final = justificativa_c + (
            f" | Variação de {variacao}: {diferenca_c}" if variacao and diferenca_c else ""
        )
        node_props: dict[str, Any] = {
            **self._base_props(),
            "tipo": tipo,
            "enunciado": enunciado_c,
            "n_evidencias": len(evidencias),
            "status": "ativa",
            "justificativa_criacao": justificativa_final[: self.limits.max_text_chars * 2],
            "nos_consultados": list(dict.fromkeys(review.consultados))[:100],
        }
        if condicoes_c:
            node_props["condicoes"] = condicoes_c
        if filtro:
            node_props["filtro_condicoes"] = filtro
        new_id = self.store.create_node("Descoberta", node_props, actor=self.actor)
        self._created.add(new_id)
        self.touched_discoveries.append(new_id)
        self._wire_discovery(new_id, sobre, evidencias)
        linked = self._link_related(new_id, review, variacao) if review.relacionados else []
        self.stats.criados += 1
        self._audit("create_discovery", id=new_id, tipo=tipo, sobre=sobre, evidencias=evidencias, variacao_de=variacao)
        return {
            "ok": True, "id": new_id, "ligada_a": linked, "nos_consultados": len(node_props["nos_consultados"]),
            **self._take_warnings(),
        }

    def _gate_records(
        self, tipo: str, sobre_nodes: list[Node], filtro: dict[str, Any] | None
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """Impede ``funciona``/``nao_funciona`` sem registro de resultado que cumpra a regra de réplicas (ADR 026 §4).

        Returns:
            ``(recusa ou None, ids dos registros do escopo que sustentam a descoberta)``; os registros entram
            como ``BASEADA_EM`` da descoberta.
        """
        try:
            scope = self.service.scope_facts(sobre_nodes, filtro)
        except KnowledgeServiceError as exc:
            return self._refuse(f"registro de resultado indisponível: {exc}"), []
        if scope is None:
            if tipo == "condicional":
                return None, []
            return (
                self._refuse(
                    "funciona/nao_funciona exigem sobre_ids com uma Hipotese, ou Abordagem + Problema, para o registro "
                    "de resultado ser conferido; sem isso use licao_de_caminho."
                ),
                [],
            )
        facts = scope[0]
        min_rep, min_ref = config.HYPOTHESIS_MIN_REPLICAS, config.HYPOTHESIS_MIN_REFUTATIONS
        if tipo == "funciona" and not holds_works(facts, min_replicas=min_rep):
            return self._refuse(
                f"{facts.n_atingiu_alvo} réplica(s) independente(s) atingiram o alvo; 'funciona' exige {min_rep}."
            ), []
        if tipo == "nao_funciona" and not holds_fails(facts, min_refutations=min_ref):
            return self._refuse(
                f"{facts.n_abaixo_alvo} réplica(s) independente(s) abaixo do alvo e {facts.n_atingiu_alvo} acima; "
                f"'nao_funciona' exige {min_ref} abaixo e nenhuma acima."
            ), []
        records = self.service.records_in_scope(sobre_nodes)
        if tipo == "nao_funciona":
            chosen = [r for r in records if (r.properties.get("n_abaixo_alvo") or 0) >= 1]
        else:
            chosen = [r for r in records if (r.properties.get("n_atingiu_alvo") or 0) >= 1]
        if not chosen:
            return self._refuse("nenhum registro de resultado do escopo sustenta a descoberta."), []
        return None, [r.id for r in chosen[:5]]

    def _wire_discovery(self, new_id: str, sobre: list[str], evidencias: list[str]) -> None:
        for target in evidencias:
            self._edge(new_id, "BASEADA_EM", target, [target])
        for target in sobre:
            self._edge(new_id, "SOBRE", target)

    def reinforce_discovery(
        self, id: str, evidencia_ids: list[str], condicoes_extra: str | None = None  # noqa: A002
    ) -> dict[str, Any]:
        """Reforça uma ``Descoberta`` ativa: novas evidências (``BASEADA_EM``) e condições ampliadas."""
        node = self._mutable("id", id, ("Descoberta",))
        if node.properties.get("status") != "ativa":
            return self._refuse("só descobertas ativas são reforçadas.")
        evidencias = self._ids("evidencia_ids", evidencia_ids, required=True)
        scope_nodes = [n for n in self._neighbors_out(id, "SOBRE")]
        bad_evidence = self._check_evidence(self._evidence_nodes(evidencias), scope_nodes)
        if bad_evidence is not None:
            return self._refuse(bad_evidence)
        extra = self._text("condicoes_extra", condicoes_extra, required=False)
        fresh = [e for e in evidencias if not self._has_edge(id, "BASEADA_EM", e)]
        if not fresh and not extra:
            return self._refuse("nenhuma evidência nova nem condição a acrescentar.")
        self._spend_write()
        for target in fresh:
            self._edge(id, "BASEADA_EM", target, [target])
        changes: dict[str, Any] = {"n_evidencias": int(node.properties.get("n_evidencias") or 0) + len(fresh)}
        if extra:
            merged = f"{node.properties.get('condicoes') or ''} | {extra}".strip(" |")
            if len(merged) > self.limits.max_text_chars * 2:
                return self._refuse("condições acumuladas longas demais; consolide antes de ampliar.")
            changes["condicoes"] = merged
        self.store.update_node(id, changes, actor=self.actor)
        self.stats.reforcados += 1
        if id not in self.touched_discoveries:
            self.touched_discoveries.append(id)
        self._audit("reinforce_discovery", id=id, novas=fresh)
        return {"ok": True, "id": id, "evidencias_novas": len(fresh), **self._take_warnings()}

    def qualify_record(
        self,
        registro_id: str,
        qualificacao: str,
        limite_aplicabilidade: str,
        evidencia_ids: list[str],
        licao: str | None = None,
    ) -> dict[str, Any]:
        """Qualifica um ``RegistroResultado`` do projeto como reparo, restrição ou retido (ADR 026 §4).

        Só ``qualificacao``, ``limite_aplicabilidade`` e ``licao`` mudam; os fatos medidos são do orquestrador (a porta
        do grafo recusa qualquer outro campo). A qualificação precisa de evidência: ao menos um ``Resultado`` do próprio
        registro em ``evidencia_ids``. ``reparo`` exige efeito medido (alvo atingido ou ``delta_pai`` positivo) e
        ``restricao`` exige tentativa abaixo do alvo ou falha atribuída à abordagem.
        """
        node = self._mutable("registro_id", registro_id, ("RegistroResultado",))
        if qualificacao not in QUALIFICACOES or qualificacao == "pendente":
            return self._refuse("qualificacao inválida; use reparo, restricao ou retido.")
        limite = self._text("limite_aplicabilidade", limite_aplicabilidade)
        licao_c = self._text("licao", licao, required=False)
        evidencias = self._ids("evidencia_ids", evidencia_ids, required=True)
        linked = {n.id for n in self._neighbors_out(registro_id, "BASEADA_EM")}
        if not linked & set(evidencias):
            return self._refuse("evidencia_ids deve citar ao menos um Resultado do próprio registro (BASEADA_EM).")
        props = node.properties
        if qualificacao == "reparo":
            delta = props.get("delta_pai")
            positive = isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta > 0
            if not props.get("atingiu_alvo") and not positive:
                return self._refuse("reparo exige efeito medido: alvo atingido ou delta_pai positivo.")
        if qualificacao == "restricao" and not (
            (props.get("n_abaixo_alvo") or 0) >= 1 or self._approach_failed(registro_id)
        ):
            return self._refuse("restricao exige tentativa abaixo do alvo ou falha atribuída à abordagem.")
        self._spend_write()
        changes: dict[str, Any] = {"qualificacao": qualificacao, "limite_aplicabilidade": limite}
        if licao_c:
            changes["licao"] = licao_c
        self.store.update_node(registro_id, changes, actor=self.actor)
        self._audit(
            "qualify_record", id=registro_id, qualificacao=qualificacao,
            qualificacao_anterior=props.get("qualificacao"), evidencias=evidencias,
        )
        return {"ok": True, "id": registro_id, "qualificacao": qualificacao}

    def _approach_failed(self, registro_id: str) -> bool:
        """A abordagem do registro tem experimento com falha atribuída a ela (``causa_falha = abordagem``)."""
        for approach in self._neighbors_out(registro_id, "REGISTRA"):
            sub = self.store.neighbors(approach.id, ["APLICOU"], direction="in", depth=1)
            if any(n.label == "Experimento" and n.properties.get("causa_falha") == "abordagem" for n in sub.nodes):
                return True
        return False

    def set_discovery_status(
        self,
        id: str,  # noqa: A002
        status: str,
        motivo: str,
        substituida_por: str | None = None,
        evidencia_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Marca uma ``Descoberta`` como ``contestada`` ou ``substituida`` (mudança durável: regras estritas).

        Revisão do PR #106 (uma injeção não pode apagar o conhecimento legítimo): há teto de mudanças de status por
        execução (``CURATOR_MAX_STATUS_CHANGES_PER_RUN``); ``contestada`` exige ``evidencia_ids`` **novas** (ainda não
        ligadas à descoberta), validadas e do escopo dela; ``substituida`` exige ``substituida_por`` **criada em
        execução anterior**, ativa, do mesmo escopo (``SOBRE`` em comum) e com evidência que a descoberta antiga
        ainda não tinha. O estado anterior vai para a auditoria e a aresta ``SUBSTITUI`` preserva a origem; reativar
        é decisão do pesquisador (``update_node`` com autoria ``pesquisador``).
        """
        node = self._mutable("id", id, ("Descoberta",))
        if status not in _STATUS_DISCOVERY:
            return self._refuse(f"status inválido; use um de {list(_STATUS_DISCOVERY)}.")
        reason = self._text("motivo", motivo, max_chars=_MAX_AUDIT_REASON)
        if node.properties.get("status") != "ativa":
            return self._refuse("só descobertas ativas mudam de status.")
        if self.stats.mudancas_de_status >= config.CURATOR_MAX_STATUS_CHANGES_PER_RUN:
            return self._refuse(
                f"limite de {config.CURATOR_MAX_STATUS_CHANGES_PER_RUN} mudanças de status por execução atingido."
            )
        scope = self._neighbors_out(id, "SOBRE")
        linked = {n.id for n in self._neighbors_out(id, "BASEADA_EM")}
        replacement: Node | None = None
        if status == "contestada":
            fresh_ids = [e for e in self._ids("evidencia_ids", evidencia_ids, required=True) if e not in linked]
            if not fresh_ids:
                return self._refuse("contestar exige evidência nova (ainda não ligada à descoberta).")
            bad = self._check_evidence(self._evidence_nodes(fresh_ids), scope)
            if bad is not None:
                return self._refuse(bad)
        else:
            if not substituida_por:
                return self._refuse("'substituida' exige 'substituida_por' (a descoberta que a substitui).")
            replacement = self._mutable("substituida_por", substituida_por, ("Descoberta",))
            if replacement.id == id or replacement.properties.get("status") != "ativa":
                return self._refuse("'substituida_por' deve ser outra descoberta ativa.")
            if replacement.id in self._created:
                return self._refuse("a substituta foi criada nesta execução: só vale uma já existente de antes.")
            if not {n.id for n in self._neighbors_out(replacement.id, "SOBRE")} & {n.id for n in scope}:
                return self._refuse("a substituta deve estar ligada ao mesmo escopo (SOBRE) da descoberta.")
            if not {n.id for n in self._neighbors_out(replacement.id, "BASEADA_EM")} - linked:
                return self._refuse("a substituta deve ter evidência que a descoberta antiga não tinha.")
        self._spend_write()
        self.stats.mudancas_de_status += 1
        changes: dict[str, Any] = {"status": status}
        if node.properties.get("tipo") != "caminho_sem_conclusao":
            changes["motivo"] = reason
        self.store.update_node(id, changes, actor=self.actor)
        if replacement is not None and not self._has_edge(replacement.id, "SUBSTITUI", id):
            self._edge(replacement.id, "SUBSTITUI", id, [id])
        self._audit(
            "set_discovery_status", id=id, status=status, status_anterior=node.properties.get("status"),
            motivo=reason, substituida_por=substituida_por,
        )
        return {"ok": True, "id": id, "status": status}

    def link_contradiction(self, a_id: str, b_id: str, motivo: str) -> dict[str, Any]:
        """Liga duas descobertas do projeto por ``CONTRADIZ`` (``a`` contradiz ``b``)."""
        a = self._mutable("a_id", a_id, ("Descoberta",))
        b = self._node("b_id", b_id, ("Descoberta",))
        if a.id == b.id:
            return self._refuse("uma descoberta não contradiz a si mesma.")
        reason = self._text("motivo", motivo, max_chars=_MAX_AUDIT_REASON)
        if self._has_edge(a.id, "CONTRADIZ", b.id):
            return self._refuse("a contradição já está registrada.")
        self._spend_write()
        self._edge(a.id, "CONTRADIZ", b.id)
        self._audit("link_contradiction", a=a.id, b=b.id, motivo=reason)
        return {"ok": True}

    def create_opportunity(
        self,
        enunciado: str,
        justificativa: str,
        origem_descoberta_id: str,
        para_problema_id: str,
        sugere_ids: list[str] | None = None,
        variacao_de: str | None = None,
        diferenca: str | None = None,
    ) -> dict[str, Any]:
        """Cria uma ``Oportunidade`` **sempre** ``documentada`` (aprovar é do pesquisador), sem duplicar."""
        enunciado_c = self._text("enunciado", enunciado)
        justificativa_c = self._text("justificativa", justificativa)
        diferenca_c = self._text("diferenca", diferenca, required=False)
        origem = self._node("origem_descoberta_id", origem_descoberta_id, ("Descoberta",))
        problema = self._node("para_problema_id", para_problema_id, ("Problema",))
        sugere = [self._node("sugere_ids", i, ("Abordagem", "Hipotese")) for i in self._ids("sugere_ids", sugere_ids)]
        if origem.properties.get("status") != "ativa":
            return self._refuse("a oportunidade deve nascer de uma descoberta ativa.")
        key = clean_free_text(enunciado_c).lower()
        for old in self.store.find_nodes(
            "Oportunidade", {"projeto_id": self.project_id, "status": "rejeitada"}, limit=_MAX_ROWS
        ):
            if clean_free_text(str(old.properties.get("enunciado", ""))).lower() == key:
                return self._refuse(
                    "o pesquisador já rejeitou esta oportunidade; ela não é recriada.", id_existente=old.id
                )
        paraphrase = self._rejected_paraphrase(enunciado_c, justificativa_c)
        if paraphrase is not None:
            return self._refuse(
                "o pesquisador já rejeitou uma oportunidade equivalente (similaridade alta); ela não é recriada.",
                id_existente=paraphrase,
            )
        variacao = self._id("variacao_de", variacao_de) if variacao_de else None
        review = self._review(
            "Oportunidade",
            {"enunciado": enunciado_c, "justificativa": justificativa_c},
            sobre=[], extra_consulted=[origem.id, problema.id, *[s.id for s in sugere]],
        )
        refusal = self._check_duplicates(review, variacao, diferenca_c, "Oportunidade")
        if refusal is not None:
            return refusal
        self._spend_write()
        new_id = self.store.create_node(
            "Oportunidade",
            {
                **self._base_props(),
                "enunciado": enunciado_c,
                "justificativa": justificativa_c,
                "status": "documentada",
                "justificativa_criacao": justificativa_c
                + (f" | Variação de {variacao}: {diferenca_c}" if variacao and diferenca_c else ""),
                "nos_consultados": list(dict.fromkeys(review.consultados))[:100],
            },
            actor=self.actor,
        )
        self._created.add(new_id)
        self._edge(new_id, "ORIGINADA_DE", origem.id)
        self._edge(new_id, "PARA", problema.id)
        for target in sugere:
            self._edge(new_id, "SUGERE", target.id)
        self.stats.criados += 1
        self._audit("create_opportunity", id=new_id, origem=origem.id, problema=problema.id)
        return {"ok": True, "id": new_id, "status": "documentada", **self._take_warnings()}

    def _rejected_paraphrase(self, enunciado: str, justificativa: str) -> str | None:
        """ID de uma ``Oportunidade`` rejeitada semanticamente equivalente (>= ``SIM_DUPLICATE_MIN``), se houver.

        A busca do índice ignora nós rejeitados; por isso compara-se o vetor do texto novo com o dos rejeitados.
        Índice indisponível = falha fechada (nada é criado).
        """
        rejected = self.store.find_nodes(
            "Oportunidade", {"projeto_id": self.project_id, "status": "rejeitada"}, limit=_MAX_ROWS
        )
        if not rejected:
            return None
        if self.index is None:
            raise CuratorToolError("revisão contra oportunidades rejeitadas indisponível (índice semântico).")
        text = canonical_text("Oportunidade", {"enunciado": enunciado, "justificativa": justificativa})
        try:
            scores = self.index.similarity_to(text or enunciado, [n.id for n in rejected])
        except Exception as exc:  # noqa: BLE001
            raise CuratorToolError("revisão contra oportunidades rejeitadas indisponível (índice semântico).") from exc
        hits = [(score, node_id) for node_id, score in scores.items() if score >= config.SIM_DUPLICATE_MIN]
        return max(hits)[1] if hits else None

    def register_open_path(
        self,
        ponto_de_parada: str,
        motivo: str,
        proximo_passo_sugerido: str,
        hipotese_id: str | None = None,
        sessao_id: str | None = None,
        variacao_de: str | None = None,
        diferenca: str | None = None,
    ) -> dict[str, Any]:
        """Registra um caminho sem conclusão (``Descoberta`` ``caminho_sem_conclusao``) de uma hipótese ou sessão."""
        if (hipotese_id is None) == (sessao_id is None):
            raise CuratorToolError("informe exatamente um entre 'hipotese_id' e 'sessao_id'.")
        stop = self._text("ponto_de_parada", ponto_de_parada)
        reason = self._text("motivo", motivo)
        proximo = self._text("proximo_passo_sugerido", proximo_passo_sugerido)
        diferenca_c = self._text("diferenca", diferenca, required=False)
        variacao = self._id("variacao_de", variacao_de) if variacao_de else None
        if hipotese_id is not None:
            anchor = self._mutable("hipotese_id", hipotese_id, ("Hipotese",))
            experiments = [n for n in self._neighbors_in(anchor.id, "TESTA") if n.label == "Experimento"]
        else:
            anchor = self._node("sessao_id", sessao_id or "", ("Sessao",), own=True)
            experiments = [n for n in self._neighbors_in(anchor.id, "EXECUTADO_EM") if n.label == "Experimento"]
        if not experiments:
            return self._refuse("sem Experimento ligado: não há ponto de parada a registrar.")
        last = max(experiments, key=lambda n: str(n.properties.get("criado_em", "")))
        props = {"tipo": "caminho_sem_conclusao", "enunciado": f"Caminho sem conclusão: {stop}", "condicoes": reason}
        review = self._review(
            "Descoberta", props, sobre=[anchor.id] if anchor.label != "Sessao" else [], extra_consulted=[last.id]
        )
        refusal = self._check_duplicates(review, variacao, diferenca_c, "Descoberta")
        if refusal is not None:
            return refusal
        self._spend_write()
        new_id = self.store.create_node(
            "Descoberta",
            {
                **self._base_props(),
                **props,
                "ponto_de_parada": stop,
                "motivo": reason,
                "proximo_passo_sugerido": proximo,
                "n_evidencias": 1,
                "status": "ativa",
                "justificativa_criacao": f"Caminho sem conclusão registrado ao fim da sessão: {reason}"[
                    : self.limits.max_text_chars * 2
                ],
                "nos_consultados": list(dict.fromkeys(review.consultados))[:100],
            },
            actor=self.actor,
        )
        self._created.add(new_id)
        self._edge(new_id, "BASEADA_EM", last.id, [last.id])
        if anchor.label == "Hipotese":
            self._edge(new_id, "SOBRE", anchor.id)
        if review.relacionados:
            self._link_related(new_id, review, variacao)
        self.stats.criados += 1
        self._audit("register_open_path", id=new_id, ancora=anchor.id, experimento=last.id)
        return {"ok": True, "id": new_id, **self._take_warnings()}

    def _neighbors_out(self, node_id: str, rel: str) -> list[Node]:
        sub = self.store.neighbors(node_id, [rel], direction="out", depth=1)
        by_id = {n.id: n for n in sub.nodes}
        return [by_id[e.dst_id] for e in sub.edges if e.src_id == node_id and e.rel_type == rel and e.dst_id in by_id]

    def _neighbors_in(self, node_id: str, rel: str) -> list[Node]:
        sub = self.store.neighbors(node_id, [rel], direction="in", depth=1)
        by_id = {n.id: n for n in sub.nodes}
        return [by_id[e.src_id] for e in sub.edges if e.dst_id == node_id and e.rel_type == rel and e.src_id in by_id]

    # ------------------------------------------------------------------ escrita: fila, fusão, sinalizações

    def review_similarity(
        self, queue_id: int, decisao: str, motivo: str, gerar: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Revisa um par do lote corrente: ``confirmar`` cria ``SEMELHANTE_A``; ``descartar`` só marca a fila.

        ``gerar`` (opcional, só com ``confirmar``): ``{"kind": "oportunidade"|"descoberta", ...argumentos da
        ferramenta correspondente}``; passa pelas mesmas regras (duplicata, evidência, ``documentada``).
        """
        if self.queue is None:
            raise CuratorToolError("fila de similaridade indisponível.")
        if decisao not in ("confirmar", "descartar"):
            raise CuratorToolError("'decisao' deve ser confirmar ou descartar.")
        reason = self._text("motivo", motivo, max_chars=_MAX_AUDIT_REASON)
        if not isinstance(queue_id, int) or isinstance(queue_id, bool):
            raise CuratorToolError("'queue_id' deve ser um inteiro.")
        item = self._batch.get(queue_id)
        if item is None:
            return self._refuse("o par não está no lote desta execução; use next_similarity_batch.")
        if self.stats.pares_revisados >= self.limits.queue_batch:
            return self._refuse(f"limite de {self.limits.queue_batch} pares revisados por execução atingido.")
        if gerar is not None and decisao != "confirmar":
            return self._refuse("'gerar' só vale com 'confirmar'.")
        cand = item.candidate
        if decisao == "descartar":
            self.queue.mark_discarded(queue_id, by=self.actor.criado_por, motivo=reason)
            self._batch.pop(queue_id, None)
            self.stats.pares_revisados += 1
            self.stats.descartados += 1
            self._audit("review_similarity", queue_id=queue_id, decisao="descartar", motivo=reason)
            return {"ok": True, "decisao": "descartar"}
        a, b = self.store.get_node(cand.node_a), self.store.get_node(cand.node_b)
        if a is None or b is None or any(n.properties.get("status") in IGNORED_STATUSES for n in (a, b)):
            self.queue.mark_discarded(queue_id, by=self.actor.criado_por, motivo="nó inexistente ou inativo")
            self._batch.pop(queue_id, None)
            self.stats.pares_revisados += 1
            self.stats.descartados += 1
            return self._refuse("par obsoleto (nó inexistente ou inativo): descartado.")
        self._spend_write()
        if not self._has_edge(a.id, "SEMELHANTE_A", b.id):
            try:
                self._edge(
                    a.id, "SEMELHANTE_A", b.id,
                    score=cand.score, modelo=cand.embedding_model, versao=cand.embedding_version,
                )
            except GraphStoreError as exc:
                self.stats.escritas -= 1
                return self._refuse(f"relação não permitida para este par: {exc}")
        self.queue.mark_confirmed(queue_id, by=self.actor.criado_por, motivo=reason)
        self._batch.pop(queue_id, None)
        self.stats.pares_revisados += 1
        self._audit("review_similarity", queue_id=queue_id, decisao="confirmar", motivo=reason, a=a.id, b=b.id)
        out: dict[str, Any] = {"ok": True, "decisao": "confirmar", "a": a.id, "b": b.id}
        if cand.tipo == "duplicata" and a.label == b.label == "Abordagem":
            out["sugestao"] = "duplicata de Abordagem: considere merge_approaches(duplicada_id, canonica_id, motivo)."
        if gerar is not None:
            out["gerado"] = self._generate_from_pair(gerar, [a.id, b.id])
        return out

    def _generate_from_pair(self, gerar: dict[str, Any], pair: list[str]) -> dict[str, Any]:
        if not isinstance(gerar, dict):
            return self._refuse("'gerar' deve ser um objeto.")
        args = {k: v for k, v in gerar.items() if k != "kind"}
        try:
            if gerar.get("kind") == "oportunidade":
                return self.create_opportunity(**args)
            if gerar.get("kind") == "descoberta":
                return self.create_discovery(**args)
        except (CuratorToolError, TypeError) as exc:
            return self._refuse(str(exc) if isinstance(exc, CuratorToolError) else "argumentos inválidos em 'gerar'.")
        return self._refuse("'gerar.kind' deve ser oportunidade ou descoberta.")

    def merge_approaches(self, duplicada_id: str, canonica_id: str, motivo: str) -> dict[str, Any]:
        """Funde uma ``Abordagem`` duplicada na canônica: ``status="fundida"`` + ``FUNDIDA_EM``. Nada é apagado.

        A fusão não tem "desfazer" nas ferramentas, então vale a condição mais estrita (revisão do PR #106): as duas
        abordagens são do **projeto da sessão**, têm o mesmo ``tipo``, e existe uma aresta ``SEMELHANTE_A`` com
        ``score >= SIM_DUPLICATE_MIN`` (par ``duplicata``) **confirmada em execução anterior** do Curator (nunca na
        mesma execução em que o modelo pede a fusão). O nome da duplicada continua resolvendo: a ingestão e as
        consultas passam a seguir ``FUNDIDA_EM``. A fusão fica no ``knowledge_audit`` do grafo (``update_node``) e em
        ``curator_audit.jsonl`` (com o score); reverter é decisão do pesquisador (``status`` da duplicada).
        """
        dup = self._mutable("duplicada_id", duplicada_id, ("Abordagem",))
        canon = self._mutable("canonica_id", canonica_id, ("Abordagem",))
        reason = self._text("motivo", motivo, max_chars=_MAX_AUDIT_REASON)
        if dup.id == canon.id:
            return self._refuse("a duplicada e a canônica devem ser diferentes.")
        if dup.properties.get("tipo") != canon.properties.get("tipo"):
            return self._refuse("só se fundem abordagens do mesmo tipo.")
        if dup.properties.get("status") == "fundida" or canon.properties.get("status") == "fundida":
            return self._refuse("abordagem já fundida; use a canônica final.")
        if self.service.canonical_approach(canon.id) != canon.id:
            return self._refuse("a canônica indicada já foi fundida em outra.")
        if dup.id in self.service.merged_approaches(canon.id) or canon.id in self.service.merged_approaches(dup.id):
            return self._refuse("a fusão formaria um ciclo.")
        score, why = self._confirmed_duplicate(dup, canon)
        if score is None:
            return self._refuse(why)
        self._spend_write()
        self.store.update_node(dup.id, {"status": "fundida"}, actor=self.actor)
        self._edge(dup.id, "FUNDIDA_EM", canon.id, [dup.id, canon.id])
        try:
            self.service.recompute_approach(canon.id)
        except GraphStoreError as exc:
            logger.info("Recálculo após a fusão indisponível", extra={"extra": {"motivo": type(exc).__name__}})
        self._audit("merge_approaches", duplicada=dup.id, canonica=canon.id, motivo=reason, score=round(score, 4))
        return {"ok": True, "duplicada": dup.id, "canonica": canon.id}

    def _confirmed_duplicate(self, a: Node, b: Node) -> tuple[float | None, str]:
        """``(score, "")`` se o par é duplicata confirmada em execução anterior; senão ``(None, motivo)``."""
        edges = []
        for src, dst in ((a.id, b.id), (b.id, a.id)):
            sub = self.store.neighbors(src, ["SEMELHANTE_A"], direction="out", depth=1)
            edges += [e for e in sub.edges if e.src_id == src and e.rel_type == "SEMELHANTE_A" and e.dst_id == dst]
        if not edges:
            return None, "as abordagens não têm SEMELHANTE_A confirmado: revise o par na fila (review_similarity)."
        strong = [e for e in edges if float(e.properties.get("score") or 0) >= config.SIM_DUPLICATE_MIN]
        if not strong:
            return None, f"o par não é duplicata (score < {config.SIM_DUPLICATE_MIN}): só pares 'duplicata' se fundem."
        older = [e for e in strong if str(e.properties.get("criado_em", "")) < self._started]
        if not older:
            return None, "duplicata confirmada nesta execução: a fusão só vale em execução anterior à confirmação."
        return max(float(e.properties.get("score") or 0) for e in older), ""

    def resolve_flag(
        self, id: str, estado: str, motivo: str, no_id: str | None = None  # noqa: A002
    ) -> dict[str, Any]:
        """Marca uma sinalização pendente como ``registrada`` (com o ``no_id``) ou ``descartada`` (com motivo)."""
        if self._flags is None:
            raise CuratorToolError("sinalizações indisponíveis nesta sessão.")
        if estado not in FLAG_DECISIONS:
            raise CuratorToolError(f"'estado' deve ser um de {list(FLAG_DECISIONS)}.")
        if no_id:
            self._node("no_id", no_id)
        try:
            self._flags.resolve(self._id("id", id), estado, motivo, no_id)
        except FlagError as exc:
            return self._refuse(str(exc))
        if estado == ESTADO_DESCARTADA:
            self.stats.descartados += 1
        self._audit("resolve_flag", id=id, estado=estado, no_id=no_id, motivo=motivo)
        return {"ok": True}

    # ------------------------------------------------------------------ despacho para o laço do modelo

