"""Decomposição das conclusões em frases e extração das conclusões do relatório (spec: conclusões decompostas)."""

import pytest

from src.claims.decompose import (
    conclusion_from_discovery,
    extract_report_conclusions,
    normalize_heading,
    split_sentences,
)

SECTIONS = ("Resumo Executivo", "Resultados", "Análise das Divergências", "Limitações Identificadas")


@pytest.mark.unit
class TestSplitSentences:
    def test_divide_em_frases_com_span(self):
        text = "A acurácia foi 0,81 [R1]. O modelo B é melhor. Não houve divergência."
        sentences = split_sentences(text)
        assert [s.texto for s in sentences] == [
            "A acurácia foi 0,81 [R1].", "O modelo B é melhor.", "Não houve divergência.",
        ]
        for s in sentences:
            assert text[s.span[0]:s.span[1]] == s.texto

    def test_nao_quebra_em_decimal_nem_abreviacao(self):
        text = "Ver Fig. 3 para o valor 0,84 [R2] e outros, etc. Depois segue o texto."
        assert [s.texto for s in split_sentences(text)] == [
            "Ver Fig. 3 para o valor 0,84 [R2] e outros, etc.", "Depois segue o texto.",
        ]

    def test_texto_vazio(self):
        assert split_sentences("   ") == []


@pytest.mark.unit
class TestExtractReportConclusions:
    REPORT = (
        "# Relatório\n\n"
        "## 1. Resumo Executivo\n\nO modelo A superou B em 0,81 [R1].\nSegunda linha do mesmo parágrafo.\n\n"
        "- Item de lista com conclusão própria.\n\n"
        "## Metodologia\n\nTexto fora das seções verificadas.\n\n"
        "## Resultados\n\n| Métrica | Valor |\n|---|---|\n| acurácia | 0,81 [R1] |\n"
        "| observação | o desempenho caiu bastante no conjunto de teste |\n\n"
        "<!-- numeric-provenance:begin -->\n## Origem dos números\nTexto do orquestrador sem conclusão.\n"
        "<!-- numeric-provenance:end -->\n\n"
        "```\ncódigo não é conclusão\n```\n"
    )

    def test_conclusoes_so_das_secoes_verificadas(self):
        found = extract_report_conclusions(self.REPORT, SECTIONS)
        ids = [c.conclusao_id for c in found]
        assert ids == [
            "rel:resumo executivo:1", "rel:resumo executivo:2", "rel:resultados:1",
        ]
        assert "Segunda linha" in found[0].texto
        assert all(c.autor == "summarizer" for c in found)

    def test_inicio_aponta_para_o_texto_no_relatorio(self):
        for c in extract_report_conclusions(self.REPORT, SECTIONS):
            assert self.REPORT[c.inicio:c.inicio + len(c.texto)] == c.texto

    def test_tabela_so_de_referencias_nao_e_conclusao(self):
        found = extract_report_conclusions(self.REPORT, SECTIONS)
        assert not any("0,81 [R1] |" in c.texto for c in found)

    def test_ids_iguais_no_texto_fonte_e_no_renderizado(self):
        source = "## Resultados\n\nO F1 {{res:exec_00000000-0000-4000-8000-000000000000/f1}} foi alto.\n\n{{calc:1+1}}\n"
        rendered = "## Resultados\n\nO F1 0,9 [R1] foi alto.\n\n2 [C1]\n"
        assert [c.conclusao_id for c in extract_report_conclusions(source, SECTIONS)] == [
            c.conclusao_id for c in extract_report_conclusions(rendered, SECTIONS)
        ] == ["rel:resultados:1"]

    def test_normalize_heading(self):
        assert normalize_heading("3. Análise das Divergências") == "analise das divergencias"


@pytest.mark.unit
def test_conclusao_de_descoberta():
    conclusao = conclusion_from_discovery("n1", "O método X funciona", "em dados limpos")
    assert conclusao.conclusao_id == "desc:n1"
    assert conclusao.autor == "curator"
    assert conclusao.texto == "O método X funciona. Condições: em dados limpos"
