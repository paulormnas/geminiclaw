"""Invariantes do design §7: o status da afirmação não toca veredito, validação nem admissão no grafo."""

import itertools
import re
from pathlib import Path

import pytest

from src.claims.model import STATUSES, Afirmacao
from src.knowledge import schema
from src.knowledge.verdict import Attempt, Criterion, VerdictParams, compute_verdict

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3] / "src"


def attempts():
    return [
        Attempt(f"a{i}", f"2026-01-0{i}T00:00:00Z", "A", "s1", i, ("d1",), f"c{i}", "resultado", value=0.8 + i * 0.01,
                baseline=0.7, validation="validado", contract_complete=True)
        for i in range(1, 7)
    ]


def claim(status):
    extra = {}
    if status == "parcial":
        extra["parte_nao_suportada"] = "parte"
    if status == "pendente":
        extra["motivo_pendencia"] = "orcamento_esgotado"
    return Afirmacao("id", "A1", "c", "t", (0, 1), "modelo", status, **extra)


def test_veredito_igual_para_os_seis_status():
    criterion = Criterion(sentido="maior_melhor", delta_min=0.05, alvo=None)
    params = VerdictParams()
    baseline = compute_verdict(attempts(), criterion, params)
    # nenhum campo de Attempt/Criterion carrega o status da afirmação; compute_verdict não recebe afirmações
    for combo in itertools.product(STATUSES, repeat=2):
        _ = [claim(s) for s in combo]
        assert compute_verdict(attempts(), criterion, params) == baseline


def test_attempt_e_criterion_nao_tem_status_afirmacao():
    assert "status_afirmacao" not in Attempt.__dataclass_fields__
    assert "status_afirmacao" not in Criterion.__dataclass_fields__


def test_enumeracoes_preservadas():
    assert schema.NODE_SCHEMAS["Resultado"].properties["status_validacao"].enum == (
        "validado", "divergente_documentado", "nao_validado"
    )
    assert schema.NODE_SCHEMAS["Descoberta"].properties["status"].enum == ("ativa", "contestada", "substituida")
    assert schema.NODE_SCHEMAS["Afirmacao"].properties["status_afirmacao"].enum == STATUSES


def test_ingestao_e_veredito_nao_consultam_o_status_da_afirmacao():
    for relative in ("knowledge/verdict.py", "knowledge/ingestion.py", "knowledge/ingestion_io.py",
                     "knowledge/ingestion_queue.py", "knowledge/service.py", "knowledge/hypothesis_cycle.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "status_afirmacao" not in text and "src.claims" not in text, relative


def test_criterios_de_parada_nao_dependem_das_afirmacoes():
    text = (ROOT / "knowledge/hypothesis_cycle.py").read_text(encoding="utf-8")
    assert not re.search(r"claims|afirmac", text, re.IGNORECASE)


def test_relacoes_do_grafo():
    assert schema.find_relation_schema("Afirmacao", "EXTRAIDA_DE", "Descoberta") is not None
    for target in ("Resultado", "Experimento", "Insumo"):
        assert schema.find_relation_schema("Afirmacao", "CONFERIDA_CONTRA", target) is not None
    assert schema.find_relation_schema("Afirmacao", "EXTRAIDA_DE", "Resultado") is None
