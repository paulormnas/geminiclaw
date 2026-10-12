"""Regras do orquestrador para a verificação das conclusões (v18.5-claim-verification, design §3, §5, §6, §7 e §11).

O fluxo por conclusão: segmenta em frases → conferência determinística (sem LLM) → uma chamada ao Validator com
as frases restantes (dividida só se o pacote passar de ``CLAIM_EVIDENCE_MAX_CHARS``) → regras de status aplicadas
aqui, nunca pelo modelo → cobertura (toda frase sem afirmação vira ``nao_verificavel``). Falha do
verificador, orçamento esgotado e ausência de modelo geram ``pendente`` com motivo, sem bloquear a sessão.

Este módulo não altera ``Resultado.status_validacao``, ``Attempt.validation`` nem ``Descoberta.status`` e não é
consultado por ``compute_verdict`` (invariantes 1–3 do design §7).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from src import config
from src.claims.decompose import Sentence, split_sentences
from src.claims.deterministic import CODE_RE, CodeValue, DeterministicResult, evaluate_sentence
from src.claims.model import (
    ATOR_ORQUESTRADOR,
    METODO_DETERMINISTICO,
    METODO_MODELO,
    ORIGEM_DESCOBERTA,
    Afirmacao,
    Conclusao,
)
from src.claims.store import ClaimStore
from src.claims.verifier import (
    MOTIVO_NAO_DECOMPOSTA,
    MOTIVO_RESPOSTA_INVALIDA,
    ClaimDraft,
    ClaimVerifierError,
    ClaimVerifierPort,
    EvidenceItem,
    NoVerifierModel,
    apply_response,
    split_batches,
)
from src.knowledge.ids import generate_node_id
from src.logger import get_logger

logger = get_logger(__name__)

EvidenceBuilder = Callable[[Conclusao, list[Sentence]], list[EvidenceItem]]
VerifierInfo = Callable[[str], dict[str, Any] | None]
FlagSink = Callable[[Conclusao, Afirmacao], None]


def verifier_info_from_allocation(author_role: str) -> dict[str, Any] | None:
    """Registro do verificador (design §6): modelo do papel ``validator`` e família do autor da conclusão."""
    try:
        from src.llm.allocation import current_allocation

        verifier = current_allocation("validator")
        author = current_allocation(author_role)
    except Exception as exc:  # noqa: BLE001 - sem alocação resolvida o registro fica incompleto, mas explícito
        logger.warning("Alocação do verificador indisponível", extra={"erro": type(exc).__name__})
        return None
    return {
        "provedor_modelo": f"{verifier.provedor}/{verifier.modelo}",
        "familia_modelo": verifier.familia_modelo,
        "versao_efetiva": verifier.versao_efetiva,
        "trust": verifier.trust,
        "familia_autor": author.familia_modelo,
        "familia_diferente": verifier.familia_modelo != author.familia_modelo,
    }


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class ClaimService:
    """Verifica conclusões e grava as afirmações no ``ClaimStore``.

    Args:
        store: Armazenamento da sessão (``afirmacoes.json``).
        verifier: Quem julga o lote (o ``ValidatorAgent``); ``None`` deixa as afirmações não determinísticas pendentes.
        budget_exhausted: ``True`` quando o limite de tokens ou de tempo foi atingido (``UsageTracker.check()``).
        verifier_info: Registro do verificador por papel do autor.
        sense_of: ``Metrica.sentido`` por nome de métrica.
        known_metrics: Nomes de métricas conhecidas (atribuição à métrica errada).
        aliases_of: Sinônimos do vocabulário por métrica.
        flag_sink: Recebe a sinalização ao Curator de ``refutada_deterministica`` em ``Descoberta``.
    """

    store: ClaimStore
    verifier: ClaimVerifierPort | None = None
    budget_exhausted: Callable[[], bool] = lambda: False
    verifier_info: VerifierInfo = verifier_info_from_allocation
    sense_of: Callable[[str], str | None] = lambda _name: None
    known_metrics: Callable[[], Iterable[str]] = lambda: ()
    aliases_of: Callable[[str], Iterable[str]] = lambda _name: ()
    flag_sink: FlagSink | None = None
    approx_rel_tol: float | None = None
    evidence_max_chars: int | None = None
    # Provedor do verificador indisponível: as chamadas seguintes desta execução não são tentadas (evita esperar as
    # retentativas do provedor a cada conclusão); as afirmações ficam pendentes e são reverificadas na retomada.
    _verifier_down: bool = False

    # --- entrada pública -------------------------------------------------------------------------------------------

    async def verify_conclusions(
        self,
        conclusoes: Sequence[Conclusao],
        codes: dict[str, CodeValue],
        evidence: EvidenceBuilder,
    ) -> dict[str, list[Afirmacao]]:
        """Verifica cada conclusão (ver ``verify_conclusion``) e grava o arquivo ao final de cada uma."""
        out: dict[str, list[Afirmacao]] = {}
        for conclusao in conclusoes:
            out[conclusao.conclusao_id] = await self.verify_conclusion(conclusao, codes, evidence)
            self.store.save()
        return out

    async def verify_conclusion(
        self, conclusao: Conclusao, codes: dict[str, CodeValue], evidence: EvidenceBuilder
    ) -> list[Afirmacao]:
        """Verifica uma conclusão e devolve as afirmações vigentes dela.

        Texto igual ao já verificado e sem pendências: reaproveita as afirmações (nova execução do pipeline). Texto
        diferente: as afirmações antigas ficam no arquivo com ``substituida_por`` (nada é apagado).
        """
        digest = text_hash(conclusao.texto)
        known = self.store.conclusoes.get(conclusao.conclusao_id)
        current = self.store.for_conclusion(conclusao.conclusao_id)
        if known and known.get("texto_hash") == digest and current and not any(
            c.status_afirmacao == "pendente" for c in current
        ):
            return current
        sentences = split_sentences(conclusao.texto)
        fresh: list[Afirmacao] = []
        undecided: list[Sentence] = []
        for sentence in sentences:
            result = self._deterministic(sentence.texto, codes)
            if result is None:
                undecided.append(sentence)
            else:
                fresh.append(self._from_deterministic(conclusao, sentence, result))
        if undecided:
            fresh.extend(await self._verify_with_model(conclusao, sentences, undecided, codes, evidence))
        self._commit(conclusao, fresh, digest, replaced=current)
        return self.store.for_conclusion(conclusao.conclusao_id)

    async def reverify_pending(
        self,
        pending: Sequence[Afirmacao],
        conclusao_texto: Callable[[str], str | None],
        codes: dict[str, CodeValue],
        evidence: EvidenceBuilder,
        ator: str = ATOR_ORQUESTRADOR,
        session_id: str | None = None,
    ) -> list[Afirmacao]:
        """Reverifica afirmações ``pendente`` de sessões anteriores (retomada, design §11).

        Cada afirmação pendente é reconferida isoladamente; o novo status entra no histórico (por acréscimo) e nada
        muda no veredito nem nas hipóteses.
        """
        done: list[Afirmacao] = []
        for claim in pending:
            if claim.status_afirmacao != "pendente":
                continue
            texto = conclusao_texto(claim.conclusao_id) or claim.texto
            conclusao = Conclusao(
                claim.conclusao_id,
                ORIGEM_DESCOBERTA if claim.conclusao_id.startswith("desc:") else "relatorio",
                texto,
                "curator" if claim.conclusao_id.startswith("desc:") else "summarizer",
            )
            sentence = Sentence(0, claim.texto, (0, len(claim.texto)))
            result = self._deterministic(claim.texto, codes)
            if result is not None:
                self._apply_result(claim, result, ator, session_id)
            else:
                drafts = await self._call_verifier(conclusao, [sentence], codes, evidence)
                self._apply_draft(claim, drafts, conclusao, ator, session_id)
            done.append(claim)
        return done

    # --- determinístico ---------------------------------------------------------------------------------------------

    def _deterministic(self, sentence: str, codes: dict[str, CodeValue]) -> DeterministicResult | None:
        tol = self.approx_rel_tol if self.approx_rel_tol is not None else config.CLAIM_APPROX_REL_TOL
        return evaluate_sentence(
            sentence, codes, approx_rel_tol=tol, sense_of=self.sense_of,
            known_metrics=self.known_metrics, aliases_of=self.aliases_of,
        )

    def _from_deterministic(self, conclusao: Conclusao, sentence: Sentence, result: DeterministicResult) -> Afirmacao:
        return Afirmacao(
            afirmacao_id=generate_node_id(),
            codigo="",
            conclusao_id=conclusao.conclusao_id,
            texto=sentence.texto,
            span=sentence.span,
            metodo=METODO_DETERMINISTICO,
            status_afirmacao=result.status,
            valores_registrados=result.valores,
            justificativa=result.justificativa,
        )

    # --- modelo -----------------------------------------------------------------------------------------------------

    async def _verify_with_model(
        self,
        conclusao: Conclusao,
        sentences: list[Sentence],
        undecided: list[Sentence],
        codes: dict[str, CodeValue],
        evidence: EvidenceBuilder,
    ) -> list[Afirmacao]:
        drafts = await self._call_verifier(conclusao, undecided, codes, evidence)
        by_index = {s.indice: s for s in sentences}
        claims: list[Afirmacao] = []
        covered: set[int] = set()
        info = self.verifier_info(conclusao.autor)
        for draft in drafts:
            claims.append(self._from_draft(conclusao, draft, by_index, codes, info))
            if isinstance(draft, _Pending):
                covered.add(draft.sentence.indice)
            elif draft.frase is not None:
                covered.add(draft.frase)
        for sentence in undecided:
            if sentence.indice not in covered:
                claims.append(
                    Afirmacao(
                        afirmacao_id=generate_node_id(), codigo="", conclusao_id=conclusao.conclusao_id,
                        texto=sentence.texto, span=sentence.span, metodo=METODO_MODELO,
                        status_afirmacao="nao_verificavel", motivo_nao_verificavel=MOTIVO_NAO_DECOMPOSTA,
                        justificativa="frase da conclusão sem afirmação devolvida pelo verificador", verificador=info,
                    )
                )
        return claims

    async def _call_verifier(
        self,
        conclusao: Conclusao,
        undecided: list[Sentence],
        codes: dict[str, CodeValue],
        evidence: EvidenceBuilder,
    ) -> list[Any]:
        indices = [s.indice for s in undecided]
        by_index = {s.indice: s for s in undecided}
        if self.verifier is None:
            return self._pending(conclusao, undecided, "sem_modelo_verificador")
        all_items = evidence(conclusao, undecided)
        max_chars = self.evidence_max_chars or config.CLAIM_EVIDENCE_MAX_CHARS
        batches = split_batches(indices, all_items, max_chars, {i: len(s.texto) for i, s in by_index.items()})
        drafts: list[Any] = []
        stopped: str | None = None
        for batch_indices, items in batches:
            batch_sentences = [by_index[i] for i in batch_indices]
            if stopped is None and self.budget_exhausted():
                stopped = "orcamento_esgotado"
            if stopped is None and self._verifier_down:
                stopped = "falha_verificador"
            if stopped is not None:
                drafts.extend(self._pending(conclusao, batch_sentences, stopped))
                continue
            try:
                result = await self.verifier.verify_claims(
                    conclusao.conclusao_id, conclusao.autor, [s.texto for s in batch_sentences], items
                )
            except NoVerifierModel as exc:
                logger.warning("Sem modelo elegível para o verificador", extra={"erro": str(exc)[:200]})
                stopped = "sem_modelo_verificador"
                drafts.extend(self._pending(conclusao, batch_sentences, stopped))
                continue
            except ClaimVerifierError as exc:
                self._verifier_down = self._verifier_down or exc.fatal
                logger.warning(
                    "Verificador sem resposta utilizável; afirmações ficam pendentes",
                    extra={"conclusao_id": conclusao.conclusao_id, "erro": str(exc)[:200]},
                )
                drafts.extend(self._pending(conclusao, batch_sentences, "falha_verificador"))
                continue
            drafts.extend(apply_response(result, batch_indices, items))
        return drafts

    @staticmethod
    def _pending(conclusao: Conclusao, sentences: list[Sentence], motivo: str) -> list[Any]:
        return [_Pending(s, motivo) for s in sentences]

    def _from_draft(
        self,
        conclusao: Conclusao,
        draft: Any,
        by_index: dict[int, Sentence],
        codes: dict[str, CodeValue],
        info: dict[str, Any] | None,
    ) -> Afirmacao:
        if isinstance(draft, _Pending):
            return Afirmacao(
                afirmacao_id=generate_node_id(), codigo="", conclusao_id=conclusao.conclusao_id,
                texto=draft.sentence.texto, span=draft.sentence.span, metodo=None, status_afirmacao="pendente",
                motivo_pendencia=draft.motivo, justificativa=f"verificação adiada: {draft.motivo}",
            )
        assert isinstance(draft, ClaimDraft)
        sentence = by_index.get(draft.frase) if draft.frase is not None else None
        span = sentence.span if sentence is not None else (0, len(conclusao.texto))
        claim = Afirmacao(
            afirmacao_id=generate_node_id(), codigo="", conclusao_id=conclusao.conclusao_id, texto=draft.texto,
            span=span, metodo=METODO_MODELO, status_afirmacao=draft.status,
            parte_nao_suportada=draft.parte_nao_suportada, evidencias=list(draft.evidencias),
            justificativa=draft.justificativa, verificador=info, motivo_nao_verificavel=draft.motivo_nao_verificavel,
        )
        # O determinístico prevalece: afirmação só de referências que a conferência refuta ou confirma.
        if CODE_RE.search(draft.texto):
            override = self._deterministic(draft.texto, codes)
            if override is not None:
                claim.metodo = METODO_DETERMINISTICO
                claim.status_afirmacao = override.status
                claim.valores_registrados = override.valores
                claim.justificativa = override.justificativa
                claim.parte_nao_suportada = None
                claim.motivo_nao_verificavel = None
        return claim

    # --- gravação e efeitos ------------------------------------------------------------------------------------------

    def _commit(
        self, conclusao: Conclusao, fresh: list[Afirmacao], digest: str, replaced: list[Afirmacao]
    ) -> None:
        for claim in fresh:
            claim.codigo = self.store.next_code()
            self.store.add(claim)
        if replaced and fresh:
            for old in replaced:
                old.substituida_por = fresh[0].afirmacao_id
                old.historico.append(
                    {"status": old.status_afirmacao, "substituida_por": fresh[0].afirmacao_id,
                     "session_id": self.store.session_id, "ator": ATOR_ORQUESTRADOR}
                )
        conclusao.aprovada = not any(c.status_afirmacao == "refutada_deterministica" for c in fresh)
        previous = self.store.conclusoes.get(conclusao.conclusao_id, {})
        conclusao.ciclos = int(previous.get("ciclos", conclusao.ciclos))
        entry = conclusao.to_dict()
        entry["texto"] = conclusao.texto
        entry["texto_hash"] = digest
        self.store.conclusoes[conclusao.conclusao_id] = entry
        for claim in fresh:
            if claim.status_afirmacao == "refutada_deterministica" and conclusao.origem == ORIGEM_DESCOBERTA:
                self._flag(conclusao, claim)

    def _flag(self, conclusao: Conclusao, claim: Afirmacao) -> None:
        if self.flag_sink is None:
            return
        try:
            self.flag_sink(conclusao, claim)
        except Exception as exc:  # noqa: BLE001 - a sinalização nunca derruba a verificação
            logger.warning("Sinalização ao Curator falhou", extra={"erro": type(exc).__name__})

    def _apply_result(self, claim: Afirmacao, result: DeterministicResult, ator: str, session_id: str | None) -> None:
        claim.metodo = METODO_DETERMINISTICO
        claim.valores_registrados = result.valores
        claim.justificativa = result.justificativa
        claim.motivo_pendencia = None
        self.store.change_status(claim, result.status, ator, session_id, reverificacao=True)

    def _apply_draft(
        self, claim: Afirmacao, drafts: list[Any], conclusao: Conclusao, ator: str, session_id: str | None
    ) -> None:
        draft = drafts[0] if drafts else None
        if draft is None or isinstance(draft, _Pending):
            if isinstance(draft, _Pending):
                claim.motivo_pendencia = draft.motivo
            return  # continua pendente (mesmo motivo ou novo); nada a registrar
        claim.metodo = METODO_MODELO
        claim.parte_nao_suportada = draft.parte_nao_suportada
        claim.evidencias = list(draft.evidencias)
        claim.justificativa = draft.justificativa
        claim.motivo_pendencia = None
        claim.motivo_nao_verificavel = draft.motivo_nao_verificavel
        claim.verificador = self.verifier_info(conclusao.autor)
        self.store.change_status(claim, draft.status, ator, session_id, reverificacao=True)


@dataclass(frozen=True)
class _Pending:
    sentence: Sentence
    motivo: str


__all__ = [
    "ClaimService",
    "MOTIVO_RESPOSTA_INVALIDA",
    "text_hash",
    "verifier_info_from_allocation",
]
