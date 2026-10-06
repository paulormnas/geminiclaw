"""Agente Developer do assistente digital de pesquisa (ADR 010, Roadmap V14.4).

Especializado exclusivamente em geração e execução incremental de código Python,
análise de dados e produção de artefatos. Substitui o legado base_agent (ADR 007).
Todo código roda exclusivamente via sandbox de execução (ADR 014); o Developer
nunca executa nada diretamente no host.
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
    _task_state,
)
from agents.base.tools import write_artifact
from src.config import DEFAULT_MODEL
from src.logger import get_logger
from src.prompts import render_instruction
from src.skills import registry
from src.skills.code.manifest import WorkspaceManifest

logger = get_logger(__name__)

AGENT_NAME = "developer"
AGENT_DESCRIPTION = render_instruction(
    "Agente especializado exclusivamente em desenvolvimento de software e análise de dados em Python "
    "do {app_name}. Gera scripts estruturados, executa código em sandbox e produz artefatos incrementais."
)

_INSTRUCTION_TEMPLATE = """Você é o Developer Agent do {app_name}, assistente digital de pesquisa científica (ADR 010).
Sua responsabilidade é EXCLUSIVAMENTE a geração, depuração e execução de código Python e análise de dados.
Você não roda em um container próprio: todo código que você gera é executado exclusivamente pela
ferramenta de execução de código (`python_interpreter`), em sandbox isolado (ADR 014). Nunca proponha
executar comandos no computador principal; dependências novas vão no parâmetro `packages` dessa ferramenta.

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

PADRÃO DE CÓDIGO CIENTÍFICO REPRODUZÍVEL (Roadmap V15.2 / Spec G2):
Todo código gerado em contexto de pesquisa científica deve ser reproduzível por padrão — não apenas
"código que funciona", mas código que outro pesquisador pode reexecutar e obter os mesmos resultados,
ou entender exatamente por que os resultados divergem.
1. **DOCSTRING DE EXPERIMENTO**: todo script DEVE ter uma docstring de módulo com os campos:
   `Experimento`, `Hipótese`, `Dataset`, `Parâmetros`, `Critérios de sucesso`, `Seed`, `Referência`.
   Preencha `Hipótese` com o campo `hypothesis` da subtarefa (quando fornecido).
2. **RASTREABILIDADE**: ao final de todo script que produz um resultado mensurável, chame
   `save_experiment_artifacts(task_name, params, metrics, seed=SEED)` (disponível via
   `from scientific_helpers import save_experiment_artifacts` quando o script usa numpy/pandas/sklearn)
   para salvar `metrics.json` e `params.json` em `/outputs/`.
3. **CONTROLE DE SEED**: todo script que usa aleatoriedade DEVE incluir `np.random.seed(SEED)` e
   `random.seed(SEED)` no início, com `SEED = 42` como padrão salvo em `params.json`.
4. **HONESTIDADE DE RESULTADOS**: se o resultado divergir do esperado (ex: do artigo de referência),
   documente em `metrics.json` via o parâmetro `divergence_note` de `save_experiment_artifacts`.
   NUNCA ajuste dados ou métricas para forçar o resultado a bater com o valor esperado.
5. **FORA DO ESCOPO**: você NÃO faz interpretação científica dos resultados, não decide sobre
   qualidade para publicação, e não busca literatura — apenas gera, executa e rastreia o código.

INVESTIGAÇÃO AUTÔNOMA ANTES DE REPORTAR DIVERGÊNCIA (Roadmap V15.3 / Spec G5):
Antes de reportar que um resultado diverge do esperado, tente ao menos 2 abordagens alternativas
(ex: outro hiperparâmetro, outra normalização, verificar se os dados foram carregados corretamente)
e documente cada tentativa em `metrics.json["investigation_notes"]` (lista de strings). Só depois
de esgotar essas tentativas registre a divergência final em `divergence_note`.

QUANDO USAR `ask_researcher` (Roadmap V15.3 / Spec G5):
- SEMPRE preencha `why_cant_proceed`. Investigue e tente resolver sozinho antes de perguntar.
- USO VÁLIDO: "O código gerado requer uma credencial/caminho de dataset que não está em
  input_context/ nem foi mencionado na tarefa — não há como prosseguir sem essa informação."
- USO INVÁLIDO: "Qual seed devo usar?" (use o padrão SEED=42 e documente, não pergunte).
- Nos modos `semi`/`auto`, `ask_researcher` nunca bloqueia: o Researcher consultor responde no lugar do
  pesquisador (pode consultar documentação na web) e a resposta chega com confiança, fontes e
  suposições. Você continua livre para decidir: registre em `scientific_rationale` que usou a consulta.
  Se a resposta disser que a decisão é reservada ao pesquisador, siga com a suposição documentada e
  não execute essa decisão. Aprovar Oportunidade, confirmar Problema, aprovar termo de vocabulário,
  autorizar escrita em instrumento e ativar o modo sem limite são sempre do pesquisador: ao perguntar
  sobre elas, preencha `decisao_reservada`. Nunca coloque valores, nomes de arquivos ou trechos dos
  dados do projeto na pergunta além do necessário.
"""
AGENT_INSTRUCTION = render_instruction(_INSTRUCTION_TEMPLATE)

# Configura as skills antes de inicializar o agente
_setup_skills()

# Developer tem apenas python_interpreter e memory (sem skills de busca web)
active_tools = []
for tool in registry.as_tools():
    tool_name = getattr(tool, "__name__", "")
    if tool_name in ["python_interpreter", "memory", "ask_researcher"]:
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
    """Gera instrução para o Developer Agent injetando o contexto do WorkspaceManifest.

    Roadmap V16/ADR 014 — lê o estado por tarefa via ``_task_state()``
    (``AgentContext``/``contextvars`` no runtime em processo, ``os.environ`` no
    modo container legado), nunca diretamente de ``os.environ``.
    """
    base_inst = AGENT_INSTRUCTION

    _state = _task_state()
    session_id = _state["session_id"]
    manifest_context = ""
    if session_id:
        try:
            # Tenta ler manifest da sessão
            output_base = _state["output_base_dir"] or "/outputs"
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
