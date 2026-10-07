# ruff: noqa: F811 — a fixture make_sandbox é reexportada e usada como argumento
"""Achados da revisão de segurança do PR #111 (v18.5-sandbox-phases): um grupo de testes por achado."""

import pytest
from test_sandbox_slim import FakeDaemon, _run, make_sandbox  # noqa: F401 — fixture reexportada


# --- A1: a rede exige autorização explícita do classificador ---------------------------------------

@pytest.mark.unit
def test_a1_sem_insumos_e_classificador_padrao_nao_libera_rede(make_sandbox, tmp_path):
    """Sem insumos, ``all([])`` não pode liberar a rede: o classificador padrão não autoriza nada."""
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, needs_network=True)

    assert daemon.run_kwargs["network_disabled"] is True
    assert result.rede_na_execucao is False
    assert "classificador" in result.nota_rede


@pytest.mark.unit
def test_a1_classificador_sem_autorizacao_explicita_nega_antes_de_outras_regras(make_sandbox, tmp_path):
    """Um classificador que só implementa ``is_shareable`` (sem ``network_allowed``) é fail-closed."""

    class SoShareable:
        def is_shareable(self, path):
            return True

    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=SoShareable()), tmp_path, needs_network=True)

    assert result.rede_na_execucao is False and "classificador" in result.nota_rede


@pytest.mark.unit
def test_a1_classificador_que_autoriza_sem_insumos_libera_a_rede(make_sandbox, tmp_path):
    class Autoriza:
        def network_allowed(self):
            return True

        def is_shareable(self, path):
            return True

    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=Autoriza()), tmp_path, needs_network=True)

    assert result.rede_na_execucao is True
