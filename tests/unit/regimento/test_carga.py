"""Carga, recorte e leitura do regimento (v18.7-agent-system-prompts, requisitos de agent-prompts e agent-runtime)."""

import shutil
from pathlib import Path

import pytest

from src.agents.regimento import REGIMENTO_DIR, RegimentoError, cabecalho, carregar_regimento, recorte, secao

pytestmark = pytest.mark.unit


def _copia(tmp_path: Path) -> Path:
    destino = tmp_path / "regimento"
    destino.mkdir()
    for nome in ("regimento.md", "regimento.yaml"):
        shutil.copy(REGIMENTO_DIR / nome, destino / nome)
    return destino


def test_carga_do_regimento():
    reg = carregar_regimento()
    ids = {s.id for s in reg.secoes}
    assert reg.versao == 1
    assert {
        "fluxo", "exploracao", "paradas", "integridade", "objetivo_limiar", "objetivo_discriminacao",
        "objetivo_cobertura", "objetivo_fronteira", "modo_assisted", "modo_semi", "modo_auto",
    } <= ids
    assert len(reg.sha256) == 64 and int(reg.sha256, 16) >= 0


def test_hash_muda_com_o_conteudo(tmp_path):
    base = _copia(tmp_path)
    antes = carregar_regimento(base).sha256
    (base / "regimento.md").write_text((base / "regimento.md").read_text() + "\nMais uma frase.\n")
    assert carregar_regimento(base).sha256 != antes


def test_metadados_invalidos_citam_o_titulo(tmp_path):
    base = _copia(tmp_path)
    md = (base / "regimento.md").read_text().replace("<!-- secao: paradas; aplica: comum -->\n", "", 1)
    (base / "regimento.md").write_text(md)
    with pytest.raises(RegimentoError, match="Paradas e retiradas"):
        carregar_regimento(base)


def test_aplica_invalido(tmp_path):
    base = _copia(tmp_path)
    md = (base / "regimento.md").read_text().replace("aplica: modo:semi", "aplica: modo:inexistente")
    (base / "regimento.md").write_text(md)
    with pytest.raises(RegimentoError, match="aplica"):
        carregar_regimento(base)


def test_discriminacao_no_auto_so_tem_o_que_vale_para_a_combinacao():
    reg = carregar_regimento()
    rec = recorte(reg, "discriminacao", "auto")
    assert cabecalho(reg, rec) == "REGIMENTO DA PESQUISA (versão 1; objetivo discriminacao; modo auto)"
    assert "## Objetivo do tipo discriminação" in rec.texto
    for fora in ("Objetivo do tipo limiar", "Objetivo do tipo fronteira", "Objetivo do tipo cobertura", "## Modo assisted", "## Modo semi"):
        assert fora not in rec.texto
    assert "`uma_compativel`" in rec.texto
    assert "`aprovar_hipotese`" in rec.texto


def test_sem_projeto_so_secoes_comuns_e_do_modo():
    reg = carregar_regimento()
    rec = recorte(reg, None, "assisted")
    assert "## Modo assisted" in rec.texto and "## Como o sistema funciona" in rec.texto
    assert "Objetivo do tipo" not in rec.texto and "Critérios do tipo de objetivo" not in rec.texto
    assert rec.tipo_objetivo == ""
    assert cabecalho(reg, rec) == "REGIMENTO DA PESQUISA (versão 1; sem objetivo; modo assisted)"


def test_modo_filtra_motivos_de_parada():
    reg = carregar_regimento()
    assert "`suspensa_sem_pesquisador`" in recorte(reg, None, "assisted").texto
    assert "`suspensa_sem_pesquisador`" not in recorte(reg, None, "auto").texto
    assert "`aguarda_pesquisador`" in recorte(reg, None, "auto").texto


def test_recorte_e_estavel_e_tem_hash_proprio():
    reg = carregar_regimento()
    a, b = recorte(reg, "limiar", "semi"), recorte(reg, "limiar", "semi")
    assert a == b and len(a.sha256) == 64
    assert a.sha256 != recorte(reg, "limiar", "auto").sha256


def test_recorte_grande_demais_cita_a_primeira_combinacao():
    with pytest.raises(RegimentoError, match=r"sem objetivo; modo assisted.*REGIMENTO_EXCERPT_MAX_CHARS=100"):
        carregar_regimento(max_chars=100)


def test_teto_padrao_vem_da_configuracao(monkeypatch):
    monkeypatch.setattr("src.config.REGIMENTO_EXCERPT_MAX_CHARS", 100)
    with pytest.raises(RegimentoError, match="tem .* caracteres"):
        carregar_regimento()


def test_tipo_ou_modo_desconhecido_falha():
    reg = carregar_regimento()
    with pytest.raises(RegimentoError):
        recorte(reg, "inventado", "auto")
    with pytest.raises(RegimentoError):
        recorte(reg, "limiar", "inventado")


def test_secao_devolve_texto_e_listas_citadas():
    reg = carregar_regimento()
    texto = secao(reg, "objetivo_discriminacao")
    assert "Objetivo do tipo discriminação" in texto and "`todas_contrariadas`" in texto
    assert "`hipotese_direcao_restrita`" in secao(reg, "paradas")


@pytest.mark.parametrize("pedido", ["", "../../.env", "nao_existe"])
def test_secao_desconhecida_devolve_a_lista_de_ids(pedido):
    reg = carregar_regimento()
    resposta = secao(reg, pedido)
    assert "- fluxo:" in resposta and "- modo_auto:" in resposta
    assert ".env" not in resposta
