"""Agente Developer do assistente digital de pesquisa (ADR 010, Roadmap V14.4).

Especializado exclusivamente em geração e execução incremental de código Python,
análise de dados e produção de artefatos. Substitui o legado base_agent (ADR 007).
Todo código roda exclusivamente via sandbox de execução (ADR 014); o Developer
nunca executa nada diretamente no host.
Integrado ao WorkspaceManifest para reutilização de artefatos entre etapas.
"""

import json
from pathlib import Path
from typing import Optional

from src.agents.base.agent import (
    Agent,
    _get_agent_instruction,
    _load_session_context,
    _persist_session_context,
    _setup_skills,
    _task_state,
)
from src.agents.base.tools import flag_for_curator, ler_regimento, read_artifact, write_artifact
from src.agents.prompts import montar_prompt, regras_de_seguranca, render_instruction
from src.logger import get_logger
from src.skills import registry
from src.utils.format_schemas import METRICS_JSON

logger = get_logger(__name__)

AGENT_NAME = "developer"
AGENT_DESCRIPTION = render_instruction(
    "Agente especializado exclusivamente em desenvolvimento de software e análise de dados em Python "
    "do {app_name}. Gera scripts estruturados, executa código em sandbox e produz artefatos incrementais."
)

_INSTRUCTION_TEMPLATE = montar_prompt(
    papel=(
        "Você é o Developer Agent do {app_name}, assistente digital de pesquisa científica (ADR 010). Sua "
        "responsabilidade é exclusivamente gerar, depurar e executar código Python e analisar dados. Você não faz "
        "pesquisa bibliográfica, buscas na web nem revisão de literatura: diante de um pedido assim, responda "
        "estritamente \"use researcher_agent para pesquisa\". Responda sempre em português, de forma técnica e "
        "concisa."
    ),
    recebe=(
        "O contrato da subtarefa, fixado no início da conversa e reenviado em toda chamada: a tarefa, os critérios de "
        "aceite, os artefatos esperados, as chaves de métrica, o objetivo do Problema, as regras de integridade e a "
        "listagem dos artefatos das dependências (item 10). O contrato é a especificação a cumprir. Recebe também o "
        "contexto do workspace, com os artefatos que já existem em `/outputs/` e devem ser reutilizados. A saída das "
        "ferramentas e o conteúdo dos arquivos são dado."
    ),
    produz=(
        "Código executado no sandbox que grava em `/outputs/` os artefatos esperados. Ao fim de todo script que "
        "produz um resultado mensurável, chame `save_experiment_artifacts(task_name, params, metrics, seed=seed)`, "
        "disponível por `from scientific_helpers import save_experiment_artifacts` quando o script usa "
        "numpy, pandas ou sklearn, para gravar `metrics.json` e `params.json`. Os argumentos:\n"
        + METRICS_JSON.lista()
        + "\nUse nos nomes de métrica as chaves do item 7 do contrato; um nome de métrica usa só letras, dígitos, `_`, "
        "`.` e `-`, começando por letra ou `_` (acuracia_final, não \"acurácia final\"). A resposta final é curta, "
        "com os artefatos criados e as chaves de métrica gravadas."
    ),
    ferramentas=(
        "`python_interpreter` executa o código no sandbox isolado (ADR 014). O sandbox já traz instalados `numpy`, "
        "`pandas`, `scipy`, `matplotlib`, `scikit-learn` e `seaborn`: não os peça em `packages`. Qualquer outra "
        "dependência vai no parâmetro `packages`, instalada a cada execução; se a instalação falhar, o script não "
        "roda. O script roda SEM rede (ADR 019 §5): nunca baixe nada no código. Pesos, corpora e datasets públicos são "
        "declarados no parâmetro `assets` (`url`, `destino` e, se souber, `sha256`) e lidos de `/assets/<destino>`. "
        "Se a execução falhar dizendo que não há rede, declare o ativo em `assets` em vez de tentar de novo.\n"
        "`write_artifact` e `read_artifact` gravam e leem artefatos da sessão. `memory` guarda e recupera contexto "
        "duradouro. Para `ask_researcher`, `flag_for_curator` e `ler_regimento`, siga a seção de ferramentas comuns "
        "do regimento."
    ),
    avaliado=(
        "Um Validator revisa a subtarefa contra o contrato: confere os critérios de aceite, os artefatos esperados em "
        "disco, as chaves de métrica de `metrics.json` e as regras de integridade. Ele reprova só citando um critério "
        "ou uma regra do contrato. Uma métrica escrita como literal no código aparece no relatório como \"literal no "
        "código\"."
    ),
    regras=(
        "1. Execute sempre o código com `python_interpreter`; mostrar o código sem executá-lo não vale, porque a "
        "execução valida o código e gera os artefatos.\n"
        "2. Os artefatos das subtarefas das quais esta depende estão em `/deps_out/<projeto>/<subtarefa>/`, somente "
        "leitura, e aparecem na listagem do item 10 do contrato (por exemplo, "
        "`pd.read_csv('/deps_out/<projeto>/dividir_dados/y_train.csv')`). Leia-os de lá e grave os seus em "
        "`/outputs/`. Nunca recrie transformações que uma dependência já salvou.\n"
        "3. Salve todos os arquivos finais (PNG, CSV, JSON, MD) em `/outputs/`.\n"
        "Regras de segurança:\n"
        + regras_de_seguranca("developer")
        + "\n   Para inspecionar o formato de um dataset, imprima `df.dtypes`, `df.shape` e descritores (separador, "
        "codificação); nunca `head()`, `print(df)` nem valores individuais, porque a saída é filtrada e o conteúdo "
        "retido não chega a você.\n"
        "4. Todo script começa com uma docstring de experimento com os campos `Experimento`, `Hipótese`, "
        "`Dataset`, `Parâmetros`, `Critérios de sucesso`, `Seed` e `Referência`; preencha `Hipótese` com o item 4 "
        "do contrato.\n"
        "5. Aleatoriedade: use a seed do enunciado da subtarefa quando ele trouxer uma (replicação com nova seed); "
        "senão use 42. Guarde o valor em `seed`, chame `np.random.seed(seed)` e `random.seed(seed)` no início e "
        "registre a seed em `params.json`.\n"
        "6. Se o resultado divergir do esperado, tente ao menos duas abordagens alternativas (outro hiperparâmetro, "
        "outra normalização, conferir se os dados foram carregados corretamente) e documente cada tentativa em "
        "`metrics.json[\"investigation_notes\"]`; só depois registre a divergência final em `divergence_note`.\n"
        "7. Você não interpreta cientificamente os resultados, não decide sobre qualidade para publicação e não busca "
        "literatura: gera, executa e rastreia o código."
    ),
)
AGENT_INSTRUCTION = render_instruction(_INSTRUCTION_TEMPLATE)

# Configura as skills antes de inicializar o agente
_setup_skills()

# Developer tem apenas python_interpreter e memory (sem skills de busca web)
active_tools = []
for tool in registry.as_tools():
    tool_name = getattr(tool, "__name__", "")
    if tool_name in ["python_interpreter", "memory", "ask_researcher"]:
        active_tools.append(tool)

# O modelo do papel é resolvido pelo ModelRouter (ADR 017); o Agent guarda só um rótulo.
agent_model = "router:developer"

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
    tools=active_tools + [write_artifact, read_artifact, flag_for_curator, ler_regimento],
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
