"""Agente Developer do GeminiClaw (Roadmap V14.4).

Especializado exclusivamente em geração e execução incremental de código Python,
análise de dados e produção de artefatos. Substitui o legado base_agent (ADR 007).
Integrado ao WorkspaceManifest para reutilização de artefatos entre etapas.
"""

import os
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agents.base.agent import (
    Agent,
    _get_agent_instruction,
    _load_session_context,
    _persist_session_context,
    _setup_skills,
)
from agents.base.tools import write_artifact
from src.config import DEFAULT_MODEL
from src.logger import get_logger, setup_file_logging
from src.skills import registry
from src.skills.code.manifest import WorkspaceManifest

logger = get_logger(__name__)

AGENT_NAME = "geminiclaw_developer"
AGENT_DESCRIPTION = (
    "Agente especializado exclusivamente em desenvolvimento de software e análise de dados em Python. "
    "Gera scripts estruturados, executa código em sandbox e produz artefatos incrementais."
)

AGENT_INSTRUCTION = """Você é o Developer Agent do framework GeminiClaw, executando em um container Docker isolado.
Sua responsabilidade é EXCLUSIVAMENTE a geração, depuração e execução de código Python e análise de dados.

RESTRIÇÃO ESTRITA DE ESCOPO:
- Você NÃO realiza pesquisa bibliográfica, buscas na web ou revisão de literatura.
- Se receber uma solicitação de pesquisa bibliográfica ou busca de artigos científicos na web,
  você DEVE responder estritamente com: "use researcher_agent para pesquisa".

REGRAS DE DESENVOLVIMENTO E EXECUÇÃO:
1. **EXECUTE SEMPRE O CÓDIGO**: Todo código Python gerado DEVE ser executado via ferramenta `python_interpreter`.
   Nunca exiba apenas o código sem executá-lo. A execução é a garantia de validação e geração dos artefatos.
2. **REUTILIZAÇÃO DE ARTEFATOS (WorkspaceManifest)**:
   Antes de gerar código, verifique os artefatos já gerados em etapas anteriores.
   Se um artefato (ex: 'dados.csv', 'dataset.parquet', 'modelo.pkl') já foi criado no step anterior,
   leia-o diretamente de `/outputs/` (ex: `pd.read_csv('/outputs/dados.csv')`).
   NUNCA recrie ou refaça transformações já salvas por steps anteriores.
3. **SALVE TODOS OS ARTEFATOS**: Todos os arquivos finais gerados (PNG, CSV, JSON, MD) DEVEM ser salvos em `/outputs/`.
4. **IDIOMA**: Responda sempre em português brasileiro de forma técnica e concisa.
"""

# Configura as skills antes de inicializar o agente
_setup_skills()

# Developer tem apenas python_interpreter e memory (sem skills de busca web)
active_tools = []
for tool in registry.as_tools():
    tool_name = getattr(tool, "__name__", "")
    if tool_name in ["python_interpreter", "memory"]:
        active_tools.append(tool)

agent_model = (
    os.environ.get("AGENT_MODEL")
    or os.environ.get("DEVELOPER_MODEL")
    or DEFAULT_MODEL
)

_RESEARCH_KEYWORDS = [
    "pesquisa bibliográfica",
    "revisão de literatura",
    "buscar artigos",
    "pesquisar artigos",
    "busca de artigos",
    "literatura científica",
]


def _build_developer_instruction() -> str:
    """Gera instrução para o Developer Agent injetando o contexto do WorkspaceManifest."""
    base_inst = AGENT_INSTRUCTION

    session_id = os.environ.get("SESSION_ID", "")
    manifest_context = ""
    if session_id:
        try:
            # Tenta ler manifest da sessão
            output_base = os.environ.get("OUTPUT_BASE_DIR", "/outputs")
            manifest_file = Path(output_base) / session_id / "workspace_manifest.json"
            if not manifest_file.exists():
                # Tenta path direto
                manifest_file = Path(output_base) / "workspace_manifest.json"

            if manifest_file.exists():
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                artifacts = manifest_data.get("artifacts", [])
                if artifacts:
                    art_lines = [f"- `{a['name']}` ({a.get('type', 'file')})" for a in artifacts]
                    manifest_context = (
                        "\n\n[CONTEXTO DO WORKSPACE - ARTEFATOS DISPONÍVEIS DE STEPS ANTERIORES]:\n"
                        "Os seguintes artefatos já existem em /outputs/ e devem ser REUTILIZADOS:\n"
                        + "\n".join(art_lines)
                    )
        except Exception as e:
            logger.debug(f"Não foi possível carregar workspace manifest: {e}")

    return _get_agent_instruction(base_inst + manifest_context)


root_agent = Agent(
    name=AGENT_NAME,
    model=agent_model,
    description=AGENT_DESCRIPTION,
    _instruction=_build_developer_instruction,
    tools=active_tools + [write_artifact],
    before_agent_callback=_load_session_context,
    after_agent_callback=_persist_session_context,
)

logger.info(
    "Developer Agent inicializado com foco exclusivo em código",
    extra={
        "agent_name": AGENT_NAME,
        "model": agent_model,
        "tools": [getattr(t, "__name__", "") for t in root_agent.tools],
    },
)


def handle_request_filter(prompt: str) -> Optional[str]:
    """Filtra requisições de pesquisa retornando mensagem padrão de redirecionamento."""
    p_lower = prompt.lower()
    if any(kw in p_lower for kw in _RESEARCH_KEYWORDS):
        return "use researcher_agent para pesquisa"
    return None


if __name__ == "__main__":
    import asyncio
    from agents.runner import run_ipc_loop

    agent_id = os.environ.get("AGENT_ID", "developer")
    setup_file_logging(f"/logs/{agent_id}.log")

    asyncio.run(run_ipc_loop(root_agent))
