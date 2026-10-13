"""``v18.6-review-evidence``: o filtro de localidade não retém o perfil estrutural enviado ao revisor."""

from __future__ import annotations

import pytest

from src.agents.validator_agent import build_artifact_evidence_fragments
from src.egress.fragments import ContentOrigin, PromptFragment, labeled

pytestmark = pytest.mark.unit


def test_gate_nao_retem_o_perfil_do_csv_mas_retem_o_trecho(gate, third_party, tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.LOCALITY_MIN_GROUP_SIZE", 10)
    (tmp_path / "dados.csv").write_text("idade,especie\n31,rara_xyz\n42,rara_xyz\n", encoding="utf-8")

    perfil = build_artifact_evidence_fragments(tmp_path, [])
    msg = labeled("user", PromptFragment("EVIDÊNCIA:", ContentOrigin.INSTRUCAO), *perfil)
    saida = gate.prepare_llm([msg], None, third_party).messages[0]["content"]
    assert "2 linhas de dados, 2 colunas" in saida and "idade (numérica, 0 nulos)" in saida
    assert "retido" not in saida and "rara_xyz" not in saida

    monkeypatch.setattr("src.config.REVIEW_ARTIFACT_PROFILE", False)
    antes = build_artifact_evidence_fragments(tmp_path, [])
    msg = labeled("user", PromptFragment("EVIDÊNCIA:", ContentOrigin.INSTRUCAO), *antes)
    saida = gate.prepare_llm([msg], None, third_party).messages[0]["content"]
    assert "[dado de pesquisa retido:" in saida
