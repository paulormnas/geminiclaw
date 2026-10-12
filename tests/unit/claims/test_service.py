"""ClaimService: determinístico primeiro, lote por conclusão, regras de status e pendências."""

import pytest

from src.claims.model import Conclusao
from src.claims.service import ClaimService
from src.claims.verifier import ClaimVerifierError, NoVerifierModel
from tests.unit.claims.helpers import FakeVerifier, code, evidence_for, make_store, supported

SENSE = {"acuracia": "maior_melhor"}

pytestmark = pytest.mark.asyncio


def conclusion(texto, cid="rel:resultados:1", origem="relatorio", autor="summarizer"):
    return Conclusao(cid, origem, texto, autor)


def service(tmp_path, verifier, **kwargs):
    kwargs.setdefault("verifier_info", lambda role: {
        "provedor_modelo": "ollama/qwen3:8b", "familia_modelo": "qwen", "versao_efetiva": "v1",
        "trust": "self_hosted", "familia_autor": "gemini", "familia_diferente": True,
    })
    kwargs.setdefault("sense_of", lambda name: SENSE.get(name))
    return ClaimService(store=make_store(tmp_path), verifier=verifier, **kwargs)


CODES = {"R1": code("R1", 0.81, "acuracia"), "R2": code("R2", 0.84, "acuracia")}


@pytest.mark.unit
class TestDecomposicaoECobertura:
    async def test_paragrafo_com_tres_afirmacoes(self, tmp_path):
        texto = "A é melhor que B [R1]. O ganho vem do pré-processamento. Faltou testar em outro domínio."
        fake = FakeVerifier(lambda frases, itens: [
            supported("A é melhor", 1), supported("o ganho vem do pré-processamento", 2),
            {"texto": "faltou testar em outro domínio", "frase": 3, "status": "nao_verificavel"},
        ])
        svc = service(tmp_path, fake)
        claims = await svc.verify_conclusion(conclusion(texto), {}, evidence_for("res:e1/a"))
        assert len(claims) == 3
        assert {c.conclusao_id for c in claims} == {"rel:resultados:1"}
        for c in claims:
            assert texto[c.span[0]:c.span[1]] in texto and c.span != (0, 0)
        assert [c.codigo for c in claims] == ["A1", "A2", "A3"]

    async def test_frase_nao_decomposta(self, tmp_path):
        texto = "Primeira frase do relatório. Segunda frase esquecida pelo modelo."
        fake = FakeVerifier(lambda frases, itens: [supported("primeira", 1)])
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion(texto), {}, evidence_for("res:e1/a")
        )
        missing = [c for c in claims if c.status_afirmacao == "nao_verificavel"]
        assert len(missing) == 1
        assert missing[0].motivo_nao_verificavel == "nao_decomposta"
        assert missing[0].texto == "Segunda frase esquecida pelo modelo."


@pytest.mark.unit
class TestDeterministicoPrevalece:
    async def test_refutada_sem_chamar_llm(self, tmp_path):
        fake = FakeVerifier()
        svc = service(tmp_path, fake)
        claims = await svc.verify_conclusion(
            conclusion("A (0,81 [R1]) é melhor que B (0,84 [R2])."), CODES, evidence_for()
        )
        assert [c.status_afirmacao for c in claims] == ["refutada_deterministica"]
        assert claims[0].metodo == "deterministico"
        assert fake.calls == []

    async def test_modelo_contradiz_o_deterministico(self, tmp_path):
        # a frase não é "só de referências" (tem causa), mas a afirmação devolvida pelo modelo é
        fake = FakeVerifier(lambda frases, itens: [
            supported("A (0,81 [R1]) é melhor que B (0,84 [R2])", 1)
        ])
        texto = "A (0,81 [R1]) é melhor que B (0,84 [R2]) porque treinou mais."
        claims = await service(tmp_path, fake).verify_conclusion(conclusion(texto), CODES, evidence_for("res:e/a"))
        assert [c.status_afirmacao for c in claims] == ["refutada_deterministica"]
        assert claims[0].metodo == "deterministico"

    async def test_uma_chamada_por_conclusao(self, tmp_path):
        fake = FakeVerifier(lambda frases, itens: [supported(f, i + 1) for i, f in enumerate(frases)])
        svc = service(tmp_path, fake)
        conclusions = [
            conclusion("A (0,9 [R1]) é maior que B (0,84 [R2]).", "rel:resultados:1"),
            conclusion("Texto interpretativo um. Texto interpretativo dois.", "rel:resultados:2"),
            conclusion("Outra conclusão qualitativa.", "rel:resultados:3"),
            conclusion("Mais uma conclusão sem número.", "rel:resultados:4"),
        ]
        codes = {"R1": code("R1", 0.9), "R2": code("R2", 0.84)}
        await svc.verify_conclusions(conclusions, codes, evidence_for("res:e/a"))
        assert len(fake.calls) == 3
        assert fake.calls[0]["frases"] == ["Texto interpretativo um.", "Texto interpretativo dois."]


@pytest.mark.unit
class TestRegrasDoOrquestrador:
    async def test_suporte_sem_evidencia(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [
            {"texto": "x", "frase": 1, "status": "suportada", "evidencias": []},
        ])
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("Uma conclusão."), {}, evidence_for("res:e/a")
        )
        assert claims[0].status_afirmacao == "nao_verificavel"
        assert claims[0].motivo_nao_verificavel == "sem_evidencia"

    async def test_evidencia_fora_do_pacote(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [supported("x", 1, ["ev99"])])
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("Uma conclusão."), {}, evidence_for("res:e/a")
        )
        assert claims[0].status_afirmacao == "nao_verificavel"
        assert claims[0].motivo_nao_verificavel == "sem_evidencia"

    async def test_refutada_pelo_modelo_vira_contestada(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [
            {"texto": "o ganho vem de X", "frase": 1, "status": "refutada", "evidencias": ["ev1"]},
        ])
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("O ganho vem de X."), {}, evidence_for("res:e/a")
        )
        assert claims[0].status_afirmacao == "contestada"
        assert claims[0].metodo == "modelo"

    async def test_parcial_com_parte_nao_suportada(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [{
            "texto": "A e B melhoram", "frase": 1, "status": "parcial", "evidencias": ["ev1"],
            "parte_nao_suportada": "B não melhora",
        }])
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("A e B melhoram."), {}, evidence_for("res:e/a")
        )
        assert claims[0].status_afirmacao == "parcial"
        assert claims[0].parte_nao_suportada == "B não melhora"

    async def test_parcial_sem_parte_vira_nao_verificavel(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [
            {"texto": "x", "frase": 1, "status": "parcial", "evidencias": ["ev1"]},
        ])
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("Uma conclusão."), {}, evidence_for("res:e/a")
        )
        assert claims[0].status_afirmacao == "nao_verificavel"

    async def test_verificador_registrado(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [supported("x", 1)])
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("Uma conclusão."), {}, evidence_for("res:e/a")
        )
        info = claims[0].verificador
        assert info["familia_autor"] == "gemini" and info["familia_modelo"] == "qwen"
        assert info["familia_diferente"] is True
        assert info["versao_efetiva"] == "v1"

    async def test_mesma_familia_registrada(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [supported("x", 1)])
        svc = service(tmp_path, fake, verifier_info=lambda role: {
            "provedor_modelo": "google/gemini", "familia_modelo": "gemini", "versao_efetiva": "d",
            "trust": "third_party", "familia_autor": "gemini", "familia_diferente": False,
        })
        claims = await svc.verify_conclusion(conclusion("Uma conclusão."), {}, evidence_for("res:e/a"))
        assert claims[0].verificador["familia_diferente"] is False


@pytest.mark.unit
class TestPendencias:
    async def test_resposta_invalida_deixa_pendente(self, tmp_path):
        fake = FakeVerifier(lambda f, i: ClaimVerifierError("resposta inválida"))
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("Uma conclusão."), {}, evidence_for("res:e/a")
        )
        assert claims[0].status_afirmacao == "pendente"
        assert claims[0].motivo_pendencia == "falha_verificador"

    async def test_sem_modelo_elegivel(self, tmp_path):
        fake = FakeVerifier(lambda f, i: NoVerifierModel("sem modelo"))
        claims = await service(tmp_path, fake).verify_conclusion(
            conclusion("Uma conclusão."), {}, evidence_for("res:e/a")
        )
        assert claims[0].motivo_pendencia == "sem_modelo_verificador"

    async def test_sem_verificador_configurado(self, tmp_path):
        claims = await service(tmp_path, None).verify_conclusion(
            conclusion("Uma conclusão."), {}, evidence_for("res:e/a")
        )
        assert claims[0].motivo_pendencia == "sem_modelo_verificador"

    async def test_falha_do_provedor_nao_repete_chamadas(self, tmp_path):
        fake = FakeVerifier(lambda f, i: ClaimVerifierError("conexão", fatal=True))
        svc = service(tmp_path, fake)
        conclusions = [conclusion(f"Conclusão número {n}.", f"rel:resultados:{n}") for n in range(1, 4)]
        await svc.verify_conclusions(conclusions, {}, evidence_for("res:e/a"))
        assert len(fake.calls) == 1
        assert all(c.motivo_pendencia == "falha_verificador" for c in svc.store.active())

    async def test_orcamento_esgotado_depois_de_duas_de_cinco(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [supported(x, n + 1) for n, x in enumerate(f)])
        state = {"done": 0}

        def exhausted():
            return state["done"] >= 2

        svc = service(tmp_path, fake, budget_exhausted=exhausted)
        conclusions = [conclusion(f"Conclusão qualitativa {n}.", f"rel:resultados:{n}") for n in range(1, 6)]
        det = conclusion("A (0,9 [R1]) é maior que B (0,84 [R2]).", "rel:resultados:6")
        codes = {"R1": code("R1", 0.9), "R2": code("R2", 0.84)}
        for c in conclusions + [det]:
            await svc.verify_conclusion(c, codes, evidence_for("res:e/a"))
            state["done"] = len(fake.calls)
        pending = svc.store.pending()
        assert len(fake.calls) == 2 and len(pending) == 3
        assert {p.motivo_pendencia for p in pending} == {"orcamento_esgotado"}
        det_claims = svc.store.for_conclusion("rel:resultados:6")
        assert det_claims[0].status_afirmacao == "suportada"  # o determinístico roda sempre

    async def test_reverificacao_registra_no_historico(self, tmp_path):
        fake = FakeVerifier(lambda f, i: ClaimVerifierError("x"))
        svc = service(tmp_path, fake)
        claims = await svc.verify_conclusion(conclusion("Uma conclusão."), {}, evidence_for("res:e/a"))
        claim = claims[0]
        assert claim.status_afirmacao == "pendente"
        svc.verifier = FakeVerifier(lambda f, i: [supported("Uma conclusão.", 1)])
        done = await svc.reverify_pending(
            [claim], lambda cid: "Uma conclusão.", {}, evidence_for("res:e/a"), session_id="s2"
        )
        assert done[0].status_afirmacao == "suportada"
        assert [h["status"] for h in done[0].historico] == ["pendente", "suportada"]
        assert done[0].historico[-1]["session_id"] == "s2"


@pytest.mark.unit
class TestEfeitos:
    async def test_refutacao_deterministica_de_descoberta_sinaliza_o_curator(self, tmp_path):
        flags = []
        svc = service(tmp_path, FakeVerifier(), flag_sink=lambda con, claim: flags.append((con, claim)))
        con = conclusion("A (0,81 [R1]) é melhor que B (0,84 [R2]).", "desc:n1", "descoberta", "curator")
        await svc.verify_conclusion(con, CODES, evidence_for())
        assert len(flags) == 1
        assert flags[0][1].valores_registrados["R1"]["valor"] == 0.81

    async def test_refutacao_de_relatorio_nao_sinaliza(self, tmp_path):
        flags = []
        svc = service(tmp_path, FakeVerifier(), flag_sink=lambda con, claim: flags.append(claim))
        await svc.verify_conclusion(conclusion("A (0,81 [R1]) é melhor que B (0,84 [R2])."), CODES, evidence_for())
        assert flags == []

    async def test_texto_igual_reaproveita_afirmacoes(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [supported("x", 1)])
        svc = service(tmp_path, fake)
        await svc.verify_conclusion(conclusion("Uma conclusão."), {}, evidence_for("res:e/a"))
        await svc.verify_conclusion(conclusion("Uma conclusão."), {}, evidence_for("res:e/a"))
        assert len(fake.calls) == 1

    async def test_texto_novo_substitui_sem_apagar(self, tmp_path):
        fake = FakeVerifier(lambda f, i: [supported("x", 1)])
        svc = service(tmp_path, fake)
        first = await svc.verify_conclusion(conclusion("Uma conclusão."), {}, evidence_for("res:e/a"))
        second = await svc.verify_conclusion(conclusion("Outra conclusão."), {}, evidence_for("res:e/a"))
        assert svc.store.get(first[0].afirmacao_id).substituida_por == second[0].afirmacao_id
        assert len(svc.store.afirmacoes) == 2
        assert svc.store.active() == second
