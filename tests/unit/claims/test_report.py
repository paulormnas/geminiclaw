"""Relatório com marcas inline, seção do orquestrador e conversores (spec: relatório com todas as afirmações)."""

import asyncio
import threading

import pytest

from src.claims.service import ClaimService
from src.claims.verifier import ClaimVerifierError
from src.report.base_converter import CLAIM_MARK_RE, split_marks
from src.report.claims_report import ClaimsRunner, claims_section, format_mark, insert_marks, register_claims
from src.report.pipeline import ReportState, build_default_pipeline
from tests.unit.claims.helpers import FakeVerifier, make_store, supported

pytestmark = pytest.mark.unit

SOURCE = (
    "# Relatório\n\n## Resultados\n\n"
    "Primeira conclusão qualitativa sobre o experimento. Segunda frase da primeira conclusão.\n\n"
    "Outra conclusão independente do relatório final.\n"
)


def run_stage(tmp_path, responder, source=SOURCE):
    """Roda o pipeline completo com o estágio de afirmações num laço de eventos em outra thread."""
    from src.numeric_refs.resolver import ReferenceResolver

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        fake = FakeVerifier(responder)
        session_dir = tmp_path / "s1"
        session_dir.mkdir()
        runner = ClaimsRunner(
            loop=loop,
            make_service=lambda state: ClaimService(
                store=make_store(tmp_path, "s1"), verifier=fake,
                verifier_info=lambda role: {"provedor_modelo": "ollama/q", "familia_modelo": "qwen",
                                            "versao_efetiva": "v", "trust": "self_hosted",
                                            "familia_autor": "gemini", "familia_diferente": True},
            ),
            sections=("Resultados",),
        )
        pipeline = build_default_pipeline()
        register_claims(pipeline, runner)
        resolver = ReferenceResolver(ledger=None, output_dir=tmp_path)  # sem referências no texto de teste
        state = ReportState("s1", session_dir, source, source, resolver)
        pipeline.build(state)
        return (session_dir / "relatorio_final.md").read_text(encoding="utf-8"), state, fake
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


def test_marcas_inline_e_tabela_com_todas_as_afirmacoes(tmp_path):
    def responder(frases, itens):
        return [
            supported("primeira", 1),
            {"texto": "segunda", "frase": 2, "status": "parcial", "evidencias": ["ev1"], "parte_nao_suportada": "p"},
        ] if len(frases) == 2 else [
            {"texto": "outra", "frase": 1, "status": "refutada", "evidencias": ["ev1"]},
        ]

    # o pacote precisa existir: sem referências no texto, o modelo "cita" ev1 inexistente -> sem_evidencia
    report, state, fake = run_stage(tmp_path, responder)
    assert "<!-- claims:begin -->" in report and "<!-- claims:end -->" in report
    assert "## Verificação das afirmações" in report
    assert "Primeira conclusão qualitativa sobre o experimento." in report  # texto preservado
    store = state.extras["claims"]["store"]
    rows = [line for line in report.split("<!-- claims:begin -->")[1].splitlines() if line.startswith("| A")]
    assert len(rows) == len(store.active())


def test_sem_evidencia_no_pacote_marca_nao_verificavel(tmp_path):
    report, state, _ = run_stage(tmp_path, lambda f, i: [supported(x, n + 1) for n, x in enumerate(f)])
    assert "[A1 · não verificável]" in report
    assert report.count("· não verificável]") == 3  # as três frases do texto de teste


def test_suportada_nao_tem_marca():
    assert format_mark(_claim("suportada")) is None


def test_falha_do_verificador_aparece_no_relatorio(tmp_path):
    report, _, _ = run_stage(tmp_path, lambda f, i: ClaimVerifierError("x", fatal=True))
    assert "· pendente]" in report
    assert "pendência: falha_verificador" in report


def test_falha_do_estagio_e_explicita(tmp_path):
    state = ReportState.__new__(ReportState)
    state.extras = {"claims_error": "RuntimeError: boom"}
    assert "NÃO foi conferido" in claims_section(state)


def test_marcas_sao_reconhecidas_pelos_conversores():
    text = "A frase. [A3 · parcial] Outra [A4 · não verificável] fim."
    kinds = [m.kind for m in split_marks(text)]
    assert kinds.count("claim") == 2
    assert CLAIM_MARK_RE.fullmatch("[A10 · contestada]")


def test_conversor_html_destaca_por_status(tmp_path):
    pytest.importorskip("markdown")
    from src.report.html_converter import HTMLConverter

    md = tmp_path / "r.md"
    md.write_text("# T\n\nTexto [A1 · refutada] e [A2 · pendente].\n", encoding="utf-8")
    out = tmp_path / "r.html"
    HTMLConverter().convert(md, out)
    html = out.read_text(encoding="utf-8")
    assert 'class="claim status-refutada"' in html and 'class="claim status-pendente"' in html


def test_conversor_latex_destaca_por_status(tmp_path):
    from src.report.latex_converter import LaTeXConverter

    md = tmp_path / "r.md"
    md.write_text("# T\n\nTexto [A1 · contestada].\n", encoding="utf-8")
    out = tmp_path / "r.tex"
    LaTeXConverter().convert(md, out)
    assert r"\colorbox{violet!30}" in out.read_text(encoding="utf-8")


def test_conversor_docx_destaca_marca(tmp_path):
    docx = pytest.importorskip("docx")
    from src.report.docx_converter import DOCXConverter

    md = tmp_path / "r.md"
    md.write_text("# T\n\nTexto [A1 · parcial].\n", encoding="utf-8")
    out = tmp_path / "r.docx"
    DOCXConverter().convert(md, out)
    runs = [r for p in docx.Document(out).paragraphs for r in p.runs if r.text == "[A1 · parcial]"]
    assert runs and runs[0].font.highlight_color is not None


def _claim(status):
    from src.claims.model import Afirmacao

    extra = {"parte_nao_suportada": "x"} if status == "parcial" else {}
    return Afirmacao("i", "A1", "c", "t", (0, 1), "modelo", status, **extra)


def test_insert_marks_preserva_o_texto(tmp_path):
    from src.claims.model import Conclusao

    store = make_store(tmp_path)
    text = "Antes. Primeira frase. Depois."
    start = text.index("Primeira")
    conclusao = Conclusao("c", "relatorio", "Primeira frase.", "summarizer", inicio=start)
    claim = _claim("contestada")
    claim.conclusao_id = "c"
    claim.span = (0, len(conclusao.texto))
    store.add(claim)
    out = insert_marks(text, [conclusao], store)
    assert out == "Antes. Primeira frase. [A1 · contestada] Depois."
    assert out.replace(" [A1 · contestada]", "") == text
