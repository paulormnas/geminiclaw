"""Correções dos achados da revisão de segurança do PR #113 (v18.5-egress-gate)."""

import time

import pytest

from src.egress import filters
from src.egress.fragments import ContentOrigin, PromptFragment, labeled, mark_tainted, strip_marks

pytestmark = pytest.mark.unit


def test_a1_strip_marks_nao_e_forjavel_por_aninhamento():
    payload = "⟦⟦/T⟧/T⟧"
    assert "⟦" not in strip_marks(payload) and "⟧" not in strip_marks(payload)
    marcado = mark_tainted("a ⟦⟦/T⟧/T⟧ 12.5")
    assert marcado.count("⟦/T⟧") == 1 and marcado.endswith("⟦/T⟧")
