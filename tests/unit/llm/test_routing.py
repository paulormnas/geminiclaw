"""Cenários dos requisitos de política, roteador puro, pin e dica do plano (v16-model-catalog-router)."""

import logging

import pytest

from src.llm.availability import Availability
from src.llm.routing import (
    NoEligibleModelError,
    Pin,
    PinError,
    read_pins,
    reset_removed_variables_warning,
    resolve,
    resolve_session,
    validate_hint,
)
from tests.support.catalog_fixtures import all_available, base_document, load, model

pytestmark = pytest.mark.unit

CLAUDE = "anthropic/claude-sonnet-5-5"
GEMINI = "google/gemini-3.8-flash"
QWEN = "ollama/qwen3:8b"


@pytest.fixture
def catalog(tmp_path):
    return load(tmp_path)


def test_chave_de_nuvem_nao_basta(catalog):
    """Cenário: Chave de nuvem não basta (política padrão self_hosted_only)."""
    resolution = resolve("developer", catalog, all_available(catalog), "self_hosted_only")

    assert resolution.id == QWEN
    assert (GEMINI, "politica") in resolution.descartados
    assert (CLAUDE, "politica") in resolution.descartados


def test_nenhum_modelo_sob_a_politica(catalog):
    """Cenário: Nenhum modelo sob a política (nenhum provedor local disponível)."""
    disponiveis = all_available(catalog)
    disponiveis[QWEN] = Availability(False, "sem_endpoint")

    with pytest.raises(NoEligibleModelError) as exc:
        resolve_session(catalog, disponiveis, "self_hosted_only")

    message = str(exc.value)
    assert "developer" in message and "researcher" in message
    assert f"{GEMINI} (politica)" in message
    assert f"{QWEN} (sem_endpoint)" in message
    assert "LLM_DATA_POLICY=third_party_allowed" in message


def test_papel_unico_sem_modelo_cita_o_papel(catalog):
    disponiveis = all_available(catalog)
    disponiveis[QWEN] = Availability(False, "sem_endpoint")

    with pytest.raises(NoEligibleModelError) as exc:
        resolve("validator", catalog, disponiveis, "self_hosted_only")

    assert exc.value.papel == "validator"
    assert "validator" in str(exc.value)


def test_politica_vem_antes_de_qualquer_outra_regra(catalog):
    disponiveis = all_available(catalog)
    disponiveis[GEMINI] = Availability(False, "sem_credencial")

    resolution = resolve("summarizer", catalog, disponiveis, "self_hosted_only")

    # Terceiros são descartados por 'politica', não pelo motivo de disponibilidade.
    assert (GEMINI, "politica") in resolution.descartados


def test_politica_invalida(catalog):
    from src.llm.routing import RoutingError

    with pytest.raises(RoutingError, match="LLM_DATA_POLICY"):
        resolve("developer", catalog, all_available(catalog), "qualquer")


def test_requisito_de_ferramentas(tmp_path):
    """Cenário: Requisito de ferramentas (o primeiro da preferência não tem ferramentas)."""
    doc = base_document()
    doc["modelos"][0] = model(CLAUDE, "third_party", ferramentas=False)
    catalog = load(tmp_path, doc)

    resolution = resolve("researcher", catalog, all_available(catalog), "third_party_allowed")

    assert (CLAUDE, "requisito:ferramentas") in resolution.descartados
    assert resolution.id == GEMINI


def test_requisito_de_janela_de_contexto(tmp_path):
    doc = base_document()
    doc["papeis"]["researcher"]["requisitos"] = {"janela_contexto_min": 200000}
    catalog = load(tmp_path, doc)

    with pytest.raises(NoEligibleModelError) as exc:
        resolve("researcher", catalog, all_available(catalog), "third_party_allowed")

    assert "requisito:janela_contexto" in str(exc.value)


def test_alias_de_papel(catalog):
    """Cenário: Alias de papel (planner == researcher)."""
    disponiveis = all_available(catalog)

    assert resolve("planner", catalog, disponiveis, "third_party_allowed") == resolve(
        "researcher", catalog, disponiveis, "third_party_allowed"
    )


def test_papel_desconhecido(catalog):
    with pytest.raises(ValueError, match="Papel desconhecido"):
        resolve("papel_inexistente", catalog, all_available(catalog), "self_hosted_only")


def test_validator_sem_exigencia_de_trust(catalog):
    """Cenário: Validator sem exigência de trust (Claude vence com third_party_allowed)."""
    resolution = resolve("validator", catalog, all_available(catalog), "third_party_allowed")

    assert resolution.id == CLAUDE
    assert resolution.trust == "third_party"
    assert resolution.origem == "preferencia"


def test_resolve_session_resolve_todos_os_papeis(catalog):
    mapa = resolve_session(catalog, all_available(catalog), "third_party_allowed")

    assert set(mapa) == {"researcher", "developer", "reviewer", "summarizer", "validator", "base"}


def test_modelo_nao_verificado_e_descartado(catalog):
    resolution = resolve("developer", catalog, {QWEN: Availability(True)}, "third_party_allowed")

    assert resolution.id == QWEN
    assert (GEMINI, "nao_verificado") in resolution.descartados


# --------------------------------------------------------------------------- pins


def test_pin_em_conflito_com_a_politica_flexivel(catalog, caplog):
    """Cenário: Pin em conflito com a política (flexível)."""
    pins = {"researcher": Pin(CLAUDE)}

    with caplog.at_level(logging.WARNING, logger="src.llm.routing"):
        resolution = resolve("researcher", catalog, all_available(catalog), "self_hosted_only", pins, "flexible")

    assert resolution.id == QWEN
    assert resolution.origem == "preferencia"
    warning = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert CLAUDE in warning and "politica" in warning
    assert (CLAUDE, "pin:politica") in resolution.descartados


def test_pin_em_conflito_estrito(catalog):
    """Cenário: Pin em conflito (estrito)."""
    pins = {"researcher": Pin(CLAUDE)}

    with pytest.raises(PinError) as exc:
        resolve("researcher", catalog, all_available(catalog), "self_hosted_only", pins, "strict")

    assert CLAUDE in str(exc.value) and "politica" in str(exc.value)


def test_pin_valido_vence_a_preferencia(catalog):
    resolution = resolve(
        "researcher", catalog, all_available(catalog), "third_party_allowed", {"researcher": Pin(QWEN)}, "strict"
    )

    assert resolution.id == QWEN
    assert resolution.origem == "pin"


def test_pin_fora_do_catalogo_e_indisponivel(catalog):
    with pytest.raises(PinError, match="fora_do_catalogo"):
        resolve("developer", catalog, all_available(catalog), "third_party_allowed",
                {"developer": Pin("google/nao-existe")}, "strict")
    disponiveis = all_available(catalog)
    disponiveis[GEMINI] = Availability(False, "sem_credencial")
    with pytest.raises(PinError, match="sem_credencial"):
        resolve("developer", catalog, disponiveis, "third_party_allowed", {"developer": Pin(GEMINI)}, "strict")


def test_variaveis_legadas(catalog, caplog):
    """Cenário: Variáveis legadas ({PAPEL}_PROVIDER + {PAPEL}_MODEL sem barra)."""
    env = {"DEVELOPER_PROVIDER": "google", "DEVELOPER_MODEL": "gemini-3.8-flash"}

    with caplog.at_level(logging.WARNING, logger="src.llm.routing"):
        pins = read_pins(catalog, env)
    resolution = resolve("developer", catalog, all_available(catalog), "third_party_allowed", pins)

    assert resolution.id == GEMINI
    assert resolution.origem == "pin_legado"
    assert any("obsoletas" in r.getMessage() for r in caplog.records)


def test_pin_novo_formato_e_erro_sem_provedor(catalog):
    assert read_pins(catalog, {"RESEARCHER_MODEL": QWEN}) == {"researcher": Pin(QWEN)}

    with pytest.raises(PinError, match="provedor/modelo"):
        read_pins(catalog, {"RESEARCHER_MODEL": "qwen3:8b"})


def test_pin_da_cli_vence_o_ambiente(catalog):
    pins = read_pins(catalog, {"RESEARCHER_MODEL": GEMINI}, cli_pins={"researcher": QWEN})

    assert pins["researcher"] == Pin(QWEN)
    with pytest.raises(PinError, match="provedor/modelo"):
        read_pins(catalog, {}, cli_pins={"researcher": "qwen3:8b"})


def test_variaveis_removidas_geram_um_unico_warning(catalog, caplog):
    """Cenário: Variável removida presente (LLM_PROVIDER é ignorada, mapa inalterado)."""
    reset_removed_variables_warning()
    env = {"LLM_PROVIDER": "ollama", "LLM_MODEL": "x", "DEFAULT_MODEL": "y"}

    with caplog.at_level(logging.WARNING, logger="src.llm.routing"):
        pins1 = read_pins(catalog, env)
        pins2 = read_pins(catalog, env)

    assert pins1 == pins2 == {}
    avisos = [r for r in caplog.records if getattr(r, "variaveis", None)]
    assert len(avisos) == 1
    assert avisos[0].variaveis == ["LLM_PROVIDER", "LLM_MODEL", "DEFAULT_MODEL"]
    mapa = resolve_session(catalog, all_available(catalog), "third_party_allowed", pins1)
    assert mapa == resolve_session(catalog, all_available(catalog), "third_party_allowed")


# --------------------------------------------------------------------------- dica do plano


def test_dica_sem_provedor(catalog, caplog):
    """Cenário: Dica sem provedor (ignorada com WARNING)."""
    with caplog.at_level(logging.WARNING, logger="src.llm.routing"):
        accepted = validate_hint(
            "developer", "qwen3:8b", catalog, all_available(catalog), "third_party_allowed", "flexible"
        )

    assert accepted is None
    assert any("provedor/modelo" in r.getMessage() for r in caplog.records)


def test_dica_valida(catalog):
    """Cenário: Dica válida (ollama/qwen3:8b disponível e com ferramentas)."""
    accepted = validate_hint("developer", QWEN, catalog, all_available(catalog), "self_hosted_only", "flexible")

    assert accepted == QWEN


def test_dica_invalida_por_politica_catalogo_ou_estrito(catalog):
    disponiveis = all_available(catalog)
    assert validate_hint("developer", GEMINI, catalog, disponiveis, "self_hosted_only", "flexible") is None
    inexistente = validate_hint(
        "developer", "google/nao-existe", catalog, disponiveis, "third_party_allowed", "flexible"
    )
    assert inexistente is None
    assert validate_hint("developer", QWEN, catalog, disponiveis, "third_party_allowed", "strict") is None
    assert validate_hint("developer", None, catalog, disponiveis, "third_party_allowed", "flexible") is None
