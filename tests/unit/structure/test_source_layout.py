"""Estrutura do código por responsabilidade (ADR 024 §2 e §6; ``v18.7-source-layout``)."""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.structure.helpers import ROOT

pytestmark = pytest.mark.unit

# Módulos antigos (relativos a ``src``), com ``.`` como separador; ``skills.document_processor.extractors`` por prefixo.
_OLD_MODULES = (
    "agent_runtime.context",
    "agents.validator_agent",
    "artifact_match",
    "artifact_profile",
    "autonomous_loop",
    "claims.report",
    "cli",
    "cli_claims",
    "cli_graph",
    "cli_opportunities",
    "cli_project",
    "cli_provenance",
    "context_loader",
    "continuity",
    "egress.fragments",
    "embeddings.reindex",
    "exploration",
    "health",
    "heartbeat",
    "history",
    "human_gate",
    "infrastructure",
    "knowledge.normalization",
    "llm_cache",
    "metrics_file",
    "model_config",
    "model_router",
    "operation_metrics",
    "orchestrator",
    "output_manager",
    "pipeline_errors",
    "plan_normalizer",
    "platform_images",
    "platform_info",
    "project_session",
    "prompts",
    "rate_limiter",
    "reserved_files",
    "resume",
    "session",
    "skills.code.manifest",
    "skills.document_processor.chunker",
    "skills.document_processor.descriptors",
    "skills.document_processor.enrichment",
    "skills.document_processor.indexer",
    "skills.document_processor.pipeline",
    "skills.document_processor.registry_store",
    "subtask_output",
    "task_scheduler",
    "telemetry",
    "triage",
    "unlimited_mode",
    "usage",
    "skills.document_processor.extractors",
)
_OLD_AGENT_PACKAGES = "base|curator|developer|researcher|summarizer|validator|planner|reviewer"
_SCANNED = ("src", "scripts", "tests", ".agents")
_SELF = Path(__file__).resolve()

# (módulo de origem depois da movimentação, definição) das definições movidas sem alterar o corpo (design §2.2).
_MOVED_DEFINITIONS = (
    *(("src.agents.validator.agent", name) for name in (
        "_METRIC_ALIASES", "_metric_key", "MetricCriterion", "_comparisons", "_metric_criteria", "_OPERATORS",
        "_compare", "_group_named", "_evaluate_comparison", "_evaluate_comparison_found",
        "_evaluate_metric_criteria", "evaluated_metric_names", "Comparison",
    )),
    *(("src.session.continuity", name) for name in (
        "ST_CONCLUIDA", "ST_EM_ANDAMENTO", "ST_PENDENTE", "ST_ABANDONADA", "ST_FALHOU",
    )),
    ("src.documents.reindex", "_make_client"),
    *(("src.knowledge.ids", name) for name in (
        "get_or_create_node_id", "generate_node_id", "_node_id_config_dir", "uuid7",
    )),
    ("src.knowledge.ingestion", "insumo_tipo"),
    ("src.knowledge.ingestion_io", "sha256_file"),
    ("src.knowledge.ingestion_io", "MAX_HASH_BYTES"),
    ("src.orchestration.orchestrator", "AgentResult"),
    ("src.orchestration.orchestrator", "AgentTask"),
)


def _text_files() -> list[Path]:
    files: list[Path] = []
    for base in _SCANNED:
        for path in (ROOT / base).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.resolve() == _SELF:
                continue
            if path.suffix in {".py", ".md", ".sh", ".yaml", ".yml", ".toml"}:
                files.append(path)
    return files


def test_raiz_de_src_so_com_modulos_transversais() -> None:
    names = sorted(p.name for p in (ROOT / "src").glob("*.py"))
    assert names == ["__init__.py", "config.py", "db.py", "logger.py"]


def test_agentes_num_so_pacote() -> None:
    assert not (ROOT / "agents").exists()
    assert (ROOT / "src" / "agents" / "validator" / "agent.py").is_file()


def test_busca_textual_pelos_caminhos_antigos() -> None:
    # ``cli`` e ``session`` viraram pacotes: o caminho antigo é o nome sem submódulo.
    packages = {"cli", "session"}
    dotted = re.compile(
        r"(?<![\w.])src\.(?:"
        + "|".join(re.escape(m) + (r"(?![\w.])" if m in packages else r"(?![\w])") for m in _OLD_MODULES)
        + ")"
    )
    slashed = re.compile(
        r"(?<![\w/.])src/(?:" + "|".join(re.escape(m.replace(".", "/")) + r"\.py" for m in _OLD_MODULES[:-1]) + r")(?![\w])"
    )
    agents_pkg = re.compile(
        r"(?<![\w.])agents\.(?:" + _OLD_AGENT_PACKAGES + r")(?![\w])|(?<![\w/.])agents/(?:" + _OLD_AGENT_PACKAGES + r")(?![\w])"
    )
    found = []
    for path in _text_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if dotted.search(line) or slashed.search(line) or agents_pkg.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}")
    assert not found, f"caminhos antigos sobreviventes: {found[:20]}"


def test_importacao_antiga_falha() -> None:
    for old in ("src.orchestrator", "src.cli_graph", "src.model_router", "agents.base"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(old)


def test_alvo_de_patch_de_definicao_movida_aponta_para_o_modulo_novo() -> None:
    patterns = [
        (module, name, re.compile(r"[\"']" + re.escape(module) + r"\." + re.escape(name) + r"(?![\w])"))
        for module, name in _MOVED_DEFINITIONS
    ]
    found = []
    for path in (ROOT / "tests").rglob("*.py"):
        if path.resolve() == _SELF or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for module, name, pattern in patterns:
            if pattern.search(text):
                found.append(f"{path.relative_to(ROOT)}: {module}.{name}")
    assert not found, found


def test_test_wiring_cita_os_caminhos_novos() -> None:
    text = (ROOT / "tests" / "unit" / "egress" / "test_wiring.py").read_text(encoding="utf-8")
    for new in ("src/research_data/context_loader.py", "src/llm/model_router.py"):
        assert new in text and (ROOT / new).is_file()
    for old in ("src/context_loader.py", "src/model_router.py"):
        assert old not in text


def test_arquivos_de_dados_apontados_por_caminhos_calculados_existem() -> None:
    from src.host.platform_images import PROJECT_ROOT
    from src.knowledge import vocabulary
    from src.llm import catalog
    from src.skills.code import sandbox, skill

    assert (vocabulary.DEFAULT_VOCABULARY_DIR / "metrics.yaml").is_file()
    assert catalog.CATALOG_PATH.is_file()
    assert (PROJECT_ROOT / "containers" / "images.yaml").is_file()
    assert skill._SCIENTIFIC_HELPERS_PATH.is_file()
    assert (Path(sandbox.__file__).resolve().parents[3] / "pyproject.toml").is_file()


def test_raiz_do_projeto_nos_caminhos_calculados() -> None:
    from src.host import platform_images
    from src.skills.code import sandbox

    assert platform_images.PROJECT_ROOT == ROOT
    assert Path(sandbox.__file__).resolve().parents[3] == ROOT


def test_sys_path_sem_src() -> None:
    code = (
        "import importlib, sys\n"
        "from src.cli import main\n"
        "assert main.root_path == sys.argv[1], main.root_path\n"
        "assert sys.argv[2] not in sys.path\n"
        "for name in ('egress', 'agents'):\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except ModuleNotFoundError:\n"
        "        continue\n"
        "    raise SystemExit(f'{name} importavel sem o prefixo src')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT), str(ROOT / "src")], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ponto_de_entrada_da_cli() -> None:
    import tomllib

    entry = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]["geminiclaw"]
    assert entry == "src.cli.main:main"
    module, _, attribute = entry.partition(":")
    assert callable(getattr(importlib.import_module(module), attribute))
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.main", "--help"], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GeminiClaw" in result.stdout
