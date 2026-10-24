import os
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

from src.utils.configuration_error import ConfigurationError

# Carrega o arquivo .env se existir
load_dotenv()

# v18.7-background-sessions §6.2: o processo da sessão não herda nomes negados; como o `.env` relido os reintroduziria,
# eles saem de `os.environ` logo depois da carga e antes de qualquer outro import do projeto.
SESSION_PROCESS_MARKER = "GEMINICLAW_SESSION_PROCESS"
if os.environ.get(SESSION_PROCESS_MARKER) == "1":
    for _denied in (n.strip() for n in os.environ.get("SESSION_ENV_DENYLIST", "").split(",")):
        if _denied:
            os.environ.pop(_denied, None)


# Nome do aplicativo — usado, por exemplo, para compor caminhos de cache
# default (ex.: EMBEDDING_CACHE_DIR) sem repetir a string literal.
APP_NAME = "geminiclaw"


class SessionMode(str, Enum):
    """Nível de autonomia da sessão (Roadmap V15.6 / Spec G10).

    ASSISTED: consulta o pesquisador quando o contexto está genuinamente ausente.
    SEMI: nunca bloqueia — documenta suposições e continua.
    AUTO: totalmente autônomo — resolve incertezas via busca web quando possível.
    """

    ASSISTED = "assisted"
    SEMI = "semi"
    AUTO = "auto"

def get_env(key: str, default: str | None = None, required: bool = False) -> str:
    """Obtém uma variável de ambiente com opção de valor padrão ou obrigatoriedade.

    Args:
        key: A chave da variável de ambiente.
        default: O valor padrão caso a variável não exista.
        required: Se True, lança um RuntimeError se a variável não estiver definida.

    Returns:
        O valor da variável de ambiente.

    Raises:
        RuntimeError: Se a variável for obrigatória e não estiver definida.
    """
    value = os.environ.get(key, default)
    if required and value is None:
        raise RuntimeError(f"Variável de ambiente obrigatória '{key}' não está definida.")
    return value  # type: ignore

_PI5_PROFILE_VALUES = (
    "MAX_SUBTASKS_PER_TASK=5, MAX_CONCURRENT_AGENTS=2, AGENT_TIMEOUT_SECONDS=0, "
    "LLM_PROVIDER_PRIORITY=ollama,openai_compatible,google,anthropic,openai"
)


def _deployment_profile_message(value: str) -> str:
    """Mensagem para ``DEPLOYMENT_PROFILE``: só ``default`` e ``pi5`` são distinguidos; o valor não é ecoado."""
    if value == "pi5":
        return (
            "'DEPLOYMENT_PROFILE' foi removida (ADR 023 §1.1): remova a linha e declare no .env os valores que o "
            f"perfil aplicava e que você quer manter: {_PI5_PROFILE_VALUES}."
        )
    return "'DEPLOYMENT_PROFILE' foi removida (ADR 023 §1.1): remova a linha do .env."


_NO_CAP_MESSAGE = (
    "removida pelo ADR 021 §5.1; a exploração não tem teto de hipóteses, ciclos ou execuções; "
    "use os limites de custo, tokens e tempo; remova a linha."
)

# Nomes de configuração removidos: nome -> mensagem fixa ou função do valor. Quem remove uma variável acrescenta
# aqui o nome dela (nunca lê o nome antigo como sinônimo). v18.7-resource-monitor-config.
_REMOVED_VARIABLES: dict[str, str | Callable[[str], str]] = {
    "DEPLOYMENT_PROFILE": _deployment_profile_message,
    "PI_TEMPERATURE_LIMIT": (
        "'PI_TEMPERATURE_LIMIT' foi removida: renomeie para 'TEMPERATURE_LIMIT' "
        "(sem padrão: sem valor, a temperatura não é verificada)."
    ),
    "PI_MIN_AVAILABLE_MEMORY_MB": "'PI_MIN_AVAILABLE_MEMORY_MB' foi removida: renomeie para 'MIN_AVAILABLE_MEMORY_MB'.",
    "OPERATIONAL_THRESHOLD_WAIT_SECONDS": (
        "'OPERATIONAL_THRESHOLD_WAIT_SECONDS' foi removida (v18.7-background-sessions): o processo da sessão não "
        "pergunta no terminal; o aviso de limite operacional só é registrado. Remova a linha do .env."
    ),
    **{
        name: f"'{name}' foi {_NO_CAP_MESSAGE}"
        for name in (
            "HYPOTHESES_PER_CYCLE",
            "MAX_EXPLORATION_CYCLES",
            "MAX_AGENT_RUNS_PER_SESSION",
            "MAX_CONTAINERS_PER_SESSION",
            "MAX_PLANNING_RUNS_PER_SESSION",
            "OPERATIONAL_THRESHOLD_AGENT_RUNS_PCT",
            "OPERATIONAL_THRESHOLD_CONTAINER_COUNT_PCT",
        )
    },
    "SOLUTION_MIN_VERDICT": (
        "'SOLUTION_MIN_VERDICT' foi removida pelo ADR 021 §5.2; a parada usa o objetivo do Problema; "
        "remova a linha."
    ),
    "KNOWLEDGE_SHORTCUT_MIN_VERDICT": (
        "'KNOWLEDGE_SHORTCUT_MIN_VERDICT' foi removida pelo ADR 026 (o veredito deixou de existir; os atalhos "
        "FUNCIONOU_PARA/FALHOU_PARA vêm dos registros de resultado e de HYPOTHESIS_MIN_REPLICAS); remova a linha."
    ),
    "DECISION_EVAL_MIN_VERDICT": (
        "'DECISION_EVAL_MIN_VERDICT' foi removida pelo ADR 026 (o estado da hipótese vem da regra de réplicas: "
        "HYPOTHESIS_MIN_REPLICAS e HYPOTHESIS_MIN_REFUTATIONS); remova a linha."
    ),
    "SIM_CROSS_PROJECT_MIN_CONFIDENCE": (
        "'SIM_CROSS_PROJECT_MIN_CONFIDENCE' foi removida pelo ADR 026 (pares Descoberta->Problema de outro projeto "
        "exigem uma Descoberta baseada em registro de resultado, e não um |veredito| mínimo); remova a linha."
    ),
    "OPERATIONAL_THRESHOLD_COST_USD": (
        "'OPERATIONAL_THRESHOLD_COST_USD' foi substituída por OPERATIONAL_THRESHOLD_COST_USAGE_PCT "
        "(percentual do limite de custo); remova a linha."
    ),
}


# As 21 variáveis ``VERDICT_*`` do modelo v2 do veredito (ADR 015 §9; removidas pelo ADR 026). Lista fechada: outras
# variáveis com o mesmo prefixo, de fora do projeto, não são recusadas.
_REMOVED_VERDICT_VARIABLES: tuple[str, ...] = (
    "VERDICT_Q_VALIDATED_COMPLETE", "VERDICT_Q_VALIDATED_INCOMPLETE", "VERDICT_Q_DIVERGENT",
    "VERDICT_D_NEW_NODE_OR_DATASET", "VERDICT_D_NEW_SESSION", "VERDICT_D_NEW_SEED", "VERDICT_GAMMA",
    "VERDICT_LAMBDA_AMBIGUOUS", "VERDICT_APPROACH_FAILURE_Q", "VERDICT_APPROACH_FAILURE_MIN_REPEATS", "VERDICT_PRIOR",
    "VERDICT_MODEL", "VERDICT_D_VARIATION", "VERDICT_D_REPLICA_NODE", "VERDICT_D_NEW_DATASET",
    "VERDICT_D_VARIATION_NO_GAIN", "VERDICT_D_REPLICA_AGAINST", "VERDICT_USEFUL_VARIATION_EPSILON",
    "VERDICT_M_FLOOR_NO_BASELINE", "VERDICT_REQUIRE_TARGET", "VERDICT_THRESHOLDS",
)


def check_removed_variables(environ: Mapping[str, str]) -> None:
    """Falha se ``environ`` traz algum nome removido, com uma linha por nome encontrado.

    Raises:
        ConfigurationError: Há ao menos um nome removido; a mensagem diz o que fazer com cada um.
    """
    lines = []
    for name, message in _REMOVED_VARIABLES.items():
        if name in environ:
            lines.append(message(environ[name]) if callable(message) else message)
    lines.extend(
        f"'{name}' foi removida pelo ADR 026 (o veredito deixou de existir; ver HYPOTHESIS_MIN_REPLICAS e "
        "HYPOTHESIS_MIN_REFUTATIONS); remova a linha."
        for name in _REMOVED_VERDICT_VARIABLES
        if name in environ
    )
    if lines:
        raise ConfigurationError("Configuração com nomes removidos:\n- " + "\n- ".join(lines))


check_removed_variables(os.environ)  # depois do load_dotenv(): cobre o ambiente e o .env


def _env_number(key: str, default: str | None, kind: type) -> float | int | None:
    """Número de uma variável (``None`` se vazia e sem padrão); texto inválido falha citando a variável."""
    raw = get_env(key, default=default)
    if raw is None or raw.strip() == "":
        return None
    try:
        return kind(raw.strip())
    except ValueError:
        raise ConfigurationError(f"'{key}' deve ser um número ({kind.__name__}); valor inválido.") from None


def get_env_bool(key: str, default: bool = False) -> bool:
    """Obtém uma variável de ambiente convertendo para booleano.
    
    Aceita 'true', '1', 't', 'y', 'yes' como True (case-insensitive).
    """
    value = os.environ.get(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "t", "y", "yes")

# --- Identidade do produto (Roadmap V16 / ADR 011) ---
# Nome exibido nos prompts dos agentes, banners de CLI e mensagens ao
# pesquisador. Centralizado aqui para que o nome do projeto (que será trocado
# no futuro — ADR 011) não fique repetido literalmente em cada módulo.
APP_NAME = get_env("APP_NAME", default="GeminiClaw")

# --- Configuração LLM (ADR 017: catálogo de modelos e roteador por papel) ---
# O modelo de cada papel NÃO é mais configurado por LLM_PROVIDER/LLM_MODEL/DEFAULT_MODEL: o roteador
# (src/llm/routing.py) resolve cada papel a partir do catálogo (src/llm/catalog.yaml), da política
# de dados e da disponibilidade dos provedores. `{PAPEL}_MODEL=provedor/modelo` é um pin opcional.

# Política de dados: 'self_hosted_only' descarta todo modelo de terceiros (mesmo com chave presente);
# 'third_party_allowed' permite enviar prompts a provedores de nuvem.
LLM_DATA_POLICY = get_env("LLM_DATA_POLICY", default="self_hosted_only").strip().lower()
# 'flexible' registra WARNING e segue a preferência quando um pin/dica não vale; 'strict' torna
# pins e conflitos fatais e ignora a dica de modelo do plano.
LLM_ROUTING = get_env("LLM_ROUTING", default="flexible").strip().lower()
# Independência do julgamento (ADR 020): 'required' | 'preferred' | 'off'. Vazio = padrão pela política de dados
# ('required' com third_party_allowed, 'preferred' com self_hosted_only). Valor inválido impede a inicialização.
LLM_JUDGE_INDEPENDENCE = get_env("LLM_JUDGE_INDEPENDENCE", default="").strip().lower()
# Lista de permissão de provedores (separados por vírgula). Vazio = padrão do perfil de deployment.
LLM_PROVIDER_PRIORITY = get_env("LLM_PROVIDER_PRIORITY", default="")
# Timeout (s) do health check de cada (provedor, modelo) no início da sessão.
LLM_HEALTH_CHECK_TIMEOUT_SECONDS = float(get_env("LLM_HEALTH_CHECK_TIMEOUT_SECONDS", default="5"))
# Timeout (s) de cada requisição ao provedor `openai_compatible`. O padrão cobre serviços hospedados; servidores
# locais lentos (vLLM com raciocínio longo a ~30 tok/s) precisam de mais, senão o cliente desiste e a geração é perdida.
OPENAI_COMPATIBLE_TIMEOUT_SECONDS = float(get_env("OPENAI_COMPATIBLE_TIMEOUT_SECONDS", default="120"))
# Piso (tokens) do `max_tokens` enviado ao `openai_compatible`; 0 = respeita o valor pedido pelo chamador (padrão 4096).
# Planos chegam a ~9 mil tokens e modelos com raciocínio gastam o limite pensando: com 4096 o texto final sai vazio.
OPENAI_COMPATIBLE_MAX_TOKENS = int(get_env("OPENAI_COMPATIBLE_MAX_TOKENS", default="0"))
# Catálogo local opcional (só acrescenta modelos). Vazio = src/llm/catalog.local.yaml.
LLM_CATALOG_LOCAL_PATH = get_env("LLM_CATALOG_LOCAL_PATH", default="")

# Configurações Ollama
OLLAMA_BASE_URL = get_env("OLLAMA_BASE_URL", default="http://localhost:11434")
OLLAMA_NUM_CTX = int(get_env("OLLAMA_NUM_CTX", default="4096"))
OLLAMA_ENABLE_THINKING = get_env("OLLAMA_ENABLE_THINKING", default="false").lower() == "true"

# Google API key: só é exigida se algum papel do mapa resolvido usa o Google; sem a chave o provedor
# simplesmente não fica disponível para o roteador.
GEMINI_API_KEY = get_env("GEMINI_API_KEY")

# Modelo usado quando o principal do Google atinge o limite de requisições (HTTP 429). Vazio desliga o fallback.
# Só é aceito se estiver no catálogo com o mesmo `trust` e atender aos requisitos do papel; desligado em
# LLM_ROUTING=strict.
GOOGLE_FALLBACK_MODEL = get_env("GOOGLE_FALLBACK_MODEL", default="gemini-4-argon")

# Provedor openai_compatible (V16) — servidores que falam o protocolo /v1/chat/completions
# (llama.cpp server, vLLM, LM Studio, serviços hospedados compatíveis). ADR 017 §8: variáveis
# PRÓPRIAS, separadas das do provedor 'openai', para que a chave real da OpenAI nunca seja enviada
# a um servidor compatível. Endpoint fora de loopback/rede privada exige https.
OPENAI_COMPATIBLE_BASE_URL = get_env("OPENAI_COMPATIBLE_BASE_URL")
OPENAI_COMPATIBLE_API_KEY = get_env("OPENAI_COMPATIBLE_API_KEY")
# Provedor openai (API da OpenAI): OPENAI_BASE_URL só deve ser definida para um proxy https.
OPENAI_BASE_URL = get_env("OPENAI_BASE_URL")
OPENAI_API_KEY = get_env("OPENAI_API_KEY")
# Esforço de raciocínio do provedor 'openai'. gpt-6-luna recusa ferramentas em /chat/completions com
# raciocínio ativo ("Function tools with reasoning_effort are not supported"); 'none' as habilita.
# Vazio = não enviar o parâmetro.
OPENAI_REASONING_EFFORT = get_env("OPENAI_REASONING_EFFORT", default="none").lower()

# Configurações do provedor anthropic (ADR 011). A chave é obrigatória apenas quando algum
# papel usa o provedor (verificado na criação do provedor, não na importação).
ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = get_env("ANTHROPIC_BASE_URL")
# Esforço do raciocínio adaptativo: low | medium | high | xhigh | max. Vazio = não enviar
# (modelos sem suporte a effort). 'medium' é o ponto de partida para agentes com ferramentas.
ANTHROPIC_EFFORT = get_env("ANTHROPIC_EFFORT", default="medium").lower()
# Repete no servidor, em outro modelo, um pedido recusado pelos classificadores de segurança.
ANTHROPIC_REFUSAL_FALLBACK = get_env_bool("ANTHROPIC_REFUSAL_FALLBACK", default=True)

# Marcadores de esgotamento de cota/gasto por provedor (v18.7-benchmark-fixes, design §1.2): a mensagem do erro
# (429, 400, 402 ou 403) que contém um deles, sem diferenciar caixa, é cota esgotada; sem marcador, o 429 segue
# transitório.
_DEFAULT_QUOTA_MARKERS = {
    "google": "spending cap",
    "anthropic": "credit balance is too low",
    "openai": "insufficient_quota",
    "openai_compatible": "",
}


def _quota_markers(provider: str) -> tuple[str, ...]:
    variable = f"LLM_QUOTA_MARKERS_{provider.upper()}"
    raw = get_env(variable, default=_DEFAULT_QUOTA_MARKERS[provider])
    markers = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    for marker in markers:
        # Um marcador curto ou só numérico (por exemplo, 429) classificaria todo limite de taxa como cota.
        if len(marker) < 6 or marker.isdigit():
            raise ConfigurationError(
                f"'{variable}' tem o marcador {marker!r}: use texto específico do erro de cota "
                "(mínimo de 6 caracteres, nunca só números)."
            )
    return markers


QUOTA_MARKERS: dict[str, tuple[str, ...]] = {name: _quota_markers(name) for name in _DEFAULT_QUOTA_MARKERS}
LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS = int(get_env("LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS", default="300"))

# Política da mudança de versão do modelo dentro da sessão (v18.7-benchmark-fixes, design §1.7); vale só com
# LLM_ROUTING=strict. ``retomar``: grava checkpoint e continua (versão desconhecida troca o modelo do papel pelo
# próximo elegível da preferência); ``parar``: fecha a sessão com versao_modelo (a bateria usa este valor).
MODEL_VERSION_POLICIES = ("retomar", "parar")
ON_MODEL_VERSION_CHANGE = get_env("ON_MODEL_VERSION_CHANGE", default="retomar").strip().lower()
if ON_MODEL_VERSION_CHANGE not in MODEL_VERSION_POLICIES:
    raise ConfigurationError(
        f"'ON_MODEL_VERSION_CHANGE' inválido: aceita {' ou '.join(repr(v) for v in MODEL_VERSION_POLICIES)}."
    )

# Rate limiting — ler nova variável com fallback para a antiga (retrocompatibilidade)
LLM_REQUESTS_PER_MINUTE = int(
    get_env("LLM_REQUESTS_PER_MINUTE")
    or get_env("GEMINI_REQUESTS_PER_MINUTE", default="15")
)
LLM_RATE_LIMIT_COOLDOWN_SECONDS = int(
    get_env("LLM_RATE_LIMIT_COOLDOWN_SECONDS")
    or get_env("GEMINI_RATE_LIMIT_COOLDOWN_SECONDS", default="30")
)
GEMINI_REQUESTS_PER_MINUTE = LLM_REQUESTS_PER_MINUTE  # Retrocompatibilidade
GEMINI_RATE_LIMIT_COOLDOWN_SECONDS = LLM_RATE_LIMIT_COOLDOWN_SECONDS  # Retrocompatibilidade

# --- Limites gerais (iguais em qualquer máquina; ADR 023 §1.1) ---
MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="10"))
MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="3"))

# Tempo limite do agente (s): 0 = sem limite (vira None); negativo ou não inteiro falha na inicialização.
_agent_timeout = _env_number("AGENT_TIMEOUT_SECONDS", "300", int)
if _agent_timeout is None or _agent_timeout < 0:
    raise ConfigurationError("'AGENT_TIMEOUT_SECONDS' deve ser um inteiro >= 0 (0 = sem tempo limite).")
AGENT_TIMEOUT_SECONDS = _agent_timeout or None

# v18.7-persistent-human-gate: pedidos ao pesquisador e caixa de entrada da sessão (design §3).
GATE_POLL_SECONDS = float(get_env("GATE_POLL_SECONDS", default="5"))
GATE_REMINDER_SECONDS = float(get_env("GATE_REMINDER_SECONDS", default="300"))
GATE_ASK_WAIT_SECONDS = float(get_env("GATE_ASK_WAIT_SECONDS", default="120"))
GATE_QUESTION_MAX_CHARS = int(get_env("GATE_QUESTION_MAX_CHARS", default="1000"))
GATE_ANSWER_MAX_CHARS = int(get_env("GATE_ANSWER_MAX_CHARS", default="2000"))
GATE_MAX_PENDING_PER_SESSION = int(get_env("GATE_MAX_PENDING_PER_SESSION", default="20"))
SESSION_INBOX_MAX_CHARS = int(get_env("SESSION_INBOX_MAX_CHARS", default="2000"))
SESSION_INBOX_MAX_PENDING = int(get_env("SESSION_INBOX_MAX_PENDING", default="20"))
SESSION_INBOX_POLL_SECONDS = float(get_env("SESSION_INBOX_POLL_SECONDS", default="5"))
if not 0 < SESSION_INBOX_MAX_CHARS <= 2000:
    raise ConfigurationError("'SESSION_INBOX_MAX_CHARS' deve estar entre 1 e 2000 (limite do CHECK da tabela).")
if not 0 < GATE_QUESTION_MAX_CHARS <= 1000:
    raise ConfigurationError("'GATE_QUESTION_MAX_CHARS' deve estar entre 1 e 1000 (limite do CHECK da tabela).")
if GATE_ASK_WAIT_SECONDS < 0 or (AGENT_TIMEOUT_SECONDS is not None and AGENT_TIMEOUT_SECONDS <= GATE_ASK_WAIT_SECONDS):
    raise ConfigurationError(
        "'GATE_ASK_WAIT_SECONDS' deve ser >= 0 e menor que 'AGENT_TIMEOUT_SECONDS' (a subtarefa que pergunta ao "
        "pesquisador não pode esperar mais que o tempo limite do agente)."
    )

# v18.7-session-events-terminal: eventos de progresso da sessão e acompanhamento pelo terminal (design §3).
SESSION_EVENTS_POLL_SECONDS = float(get_env("SESSION_EVENTS_POLL_SECONDS", default="2"))
SESSION_EVENT_SUMMARY_MAX_CHARS = int(get_env("SESSION_EVENT_SUMMARY_MAX_CHARS", default="300"))
SESSION_EVENTS_RETENTION_DAYS = int(get_env("SESSION_EVENTS_RETENTION_DAYS", default="0"))
TERMINAL_EVENT_DETAIL = get_env("TERMINAL_EVENT_DETAIL", default="resumo").strip().lower()
TERMINAL_FOLLOW_HISTORY = int(get_env("TERMINAL_FOLLOW_HISTORY", default="20"))
TERMINAL_CONSULT_ENABLED = get_env_bool("TERMINAL_CONSULT_ENABLED", default=True)
TERMINAL_CONSULT_CONTEXT_MAX_CHARS = int(get_env("TERMINAL_CONSULT_CONTEXT_MAX_CHARS", default="12000"))
TERMINAL_CONSULT_MAX_TOKENS = int(get_env("TERMINAL_CONSULT_MAX_TOKENS", default="20000"))
if SESSION_EVENTS_POLL_SECONDS <= 0:
    raise ConfigurationError("'SESSION_EVENTS_POLL_SECONDS' deve ser maior que 0.")
if not 1 <= SESSION_EVENT_SUMMARY_MAX_CHARS <= 300:
    raise ConfigurationError("'SESSION_EVENT_SUMMARY_MAX_CHARS' deve estar entre 1 e 300 (limite do CHECK da tabela).")
if SESSION_EVENTS_RETENTION_DAYS < 0:
    raise ConfigurationError("'SESSION_EVENTS_RETENTION_DAYS' deve ser >= 0 (0 nunca apaga).")
if TERMINAL_EVENT_DETAIL not in ("silencioso", "resumo", "detalhado"):
    raise ConfigurationError("'TERMINAL_EVENT_DETAIL' deve ser 'silencioso', 'resumo' ou 'detalhado'.")
if TERMINAL_FOLLOW_HISTORY < 0 or TERMINAL_CONSULT_CONTEXT_MAX_CHARS < 1 or TERMINAL_CONSULT_MAX_TOKENS < 1:
    raise ConfigurationError(
        "'TERMINAL_FOLLOW_HISTORY' deve ser >= 0; 'TERMINAL_CONSULT_CONTEXT_MAX_CHARS' e 'TERMINAL_CONSULT_MAX_TOKENS' "
        "devem ser >= 1."
    )

# Limites de planejamento (Roadmap V4)
MAX_PLANNING_ITERATIONS = int(get_env("MAX_PLANNING_ITERATIONS", default="10"))
MAX_PLAN_RETRIES = int(get_env("MAX_PLAN_RETRIES", default="5"))

# v16-pipeline-robustness — robustez do planejamento, da revisão e do disjuntor.
PLAN_NORMALIZER_ENABLED = get_env_bool("PLAN_NORMALIZER_ENABLED", default=True)
PLAN_REJECTION_STALL_LIMIT = int(get_env("PLAN_REJECTION_STALL_LIMIT", default="2"))
PLAN_LLM_REJECTION_LIMIT = int(get_env("PLAN_LLM_REJECTION_LIMIT", default="3"))
ARTIFACT_MATCH_MODE = get_env("ARTIFACT_MATCH_MODE", default="tolerant").lower()  # tolerant | strict
CIRCUIT_BREAKER_STALL_CYCLES = int(get_env("CIRCUIT_BREAKER_STALL_CYCLES", default="2"))

# v18.6-review-evidence — evidência e tolerância na revisão de subtarefas.
REVIEW_METRIC_QUALIFIERS = get_env_bool("REVIEW_METRIC_QUALIFIERS", default=True)
REVIEW_ARTIFACT_PROFILE = get_env_bool("REVIEW_ARTIFACT_PROFILE", default=True)
REVIEW_PROFILE_MAX_BYTES = int(get_env("REVIEW_PROFILE_MAX_BYTES", default="5242880"))
REVIEW_PROFILE_MAX_CHARS = int(get_env("REVIEW_PROFILE_MAX_CHARS", default="1200"))
# v18.6-profile-hardening — limites estruturais do perfil (NC-PERFIL-5).
REVIEW_PROFILE_MAX_COLUMNS = int(get_env("REVIEW_PROFILE_MAX_COLUMNS", default="200"))
REVIEW_PROFILE_MAX_ROWS = int(get_env("REVIEW_PROFILE_MAX_ROWS", default="100000"))
REVIEW_PROFILE_MAX_SECONDS = float(get_env("REVIEW_PROFILE_MAX_SECONDS", default="5"))
REVIEW_PROFILE_MAX_JSON_LINES = int(get_env("REVIEW_PROFILE_MAX_JSON_LINES", default="200"))

# v18.7-subtask-contract (ADR 022) — contrato da subtarefa, revisão tipada e colisão de artefatos.
SUBTASK_CONTRACT_ENABLED = get_env_bool("SUBTASK_CONTRACT_ENABLED", default=True)
CONTRACT_TASK_MAX_CHARS = int(get_env("CONTRACT_TASK_MAX_CHARS", default="4000"))
CONTRACT_FIELD_MAX_CHARS = int(get_env("CONTRACT_FIELD_MAX_CHARS", default="1500"))
REVIEW_INTEGRITY_ALWAYS = get_env_bool("REVIEW_INTEGRITY_ALWAYS", default=True)
REVIEW_SCRIPT_MAX_CHARS = int(get_env("REVIEW_SCRIPT_MAX_CHARS", default="6000"))
REVIEW_OBSERVATIONS_MAX = int(get_env("REVIEW_OBSERVATIONS_MAX", default="10"))
PLAN_ARTIFACT_COLLISION_CHECK = get_env_bool("PLAN_ARTIFACT_COLLISION_CHECK", default=True)

# v18.7-dependency-artifacts (ADR 022 §9) — saídas das dependências montadas somente leitura no sandbox.
DEPENDENCY_ARTIFACTS_ENABLED = get_env_bool("DEPENDENCY_ARTIFACTS_ENABLED", default=True)
DEPENDENCY_ARTIFACTS_SCOPE = get_env("DEPENDENCY_ARTIFACTS_SCOPE", default="transitivas").strip().lower()
if DEPENDENCY_ARTIFACTS_SCOPE not in ("transitivas", "diretas"):
    raise ValueError(
        f"DEPENDENCY_ARTIFACTS_SCOPE inválido: '{DEPENDENCY_ARTIFACTS_SCOPE}'. Valores aceitos: transitivas, diretas."
    )
DEPENDENCY_ARTIFACTS_MAX_MOUNTS = int(get_env("DEPENDENCY_ARTIFACTS_MAX_MOUNTS", default="16"))
DEPENDENCY_ARTIFACTS_LIST_MAX = int(get_env("DEPENDENCY_ARTIFACTS_LIST_MAX", default="20"))

# v18.7-exploration-metrics — itens de listas nas métricas de operação e no relatório (ex.: retiradas por similaridade).
OPERATION_METRICS_LIST_MAX_ITEMS = int(get_env("OPERATION_METRICS_LIST_MAX_ITEMS", default="50"))
if OPERATION_METRICS_LIST_MAX_ITEMS < 1:
    raise ValueError("OPERATION_METRICS_LIST_MAX_ITEMS deve ser um inteiro >= 1.")
if DEPENDENCY_ARTIFACTS_MAX_MOUNTS < 1 or DEPENDENCY_ARTIFACTS_LIST_MAX < 1:
    raise ValueError("DEPENDENCY_ARTIFACTS_MAX_MOUNTS e DEPENDENCY_ARTIFACTS_LIST_MAX devem ser inteiros >= 1.")

# v18.7-agent-system-prompts — regimento da pesquisa. Teto do recorte injetado em cada chamada de papel (por combinação
# de tipo de objetivo e modo) e da saída de ``ler_regimento``; protege o custo de entrada contra crescimento do texto.
REGIMENTO_EXCERPT_MAX_CHARS = int(get_env("REGIMENTO_EXCERPT_MAX_CHARS", default="16000"))
if REGIMENTO_EXCERPT_MAX_CHARS < 1:
    raise ValueError("REGIMENTO_EXCERPT_MAX_CHARS deve ser um inteiro >= 1.")
# Adendo de projeto: arquivo procurado nos insumos do pesquisador; só vale com a aprovação do hash pelo gate.
REGIMENTO_ADDENDUM_FILE = get_env("REGIMENTO_ADDENDUM_FILE", default="regimento_adendo.yaml")
if not REGIMENTO_ADDENDUM_FILE or "/" in REGIMENTO_ADDENDUM_FILE or REGIMENTO_ADDENDUM_FILE.startswith("."):
    raise ValueError("REGIMENTO_ADDENDUM_FILE deve ser um nome de arquivo simples, sem caminho.")

# v18.6-hypothesis-closure — resultado científico negativo (hipótese refutada por limiar) é progresso, não falha.
NEGATIVE_RESULT_AS_PROGRESS = get_env_bool("NEGATIVE_RESULT_AS_PROGRESS", default=True)

# v16-agent-communication-eval — avaliação pós-execução da comunicação entre agentes.
# O modelo do juiz é selecionado automaticamente (design §5.3); PROVIDER/MODEL são sobrescrita opcional.
COMM_EVAL_JUDGE_PROVIDER = get_env("COMM_EVAL_JUDGE_PROVIDER", default="").lower()
COMM_EVAL_JUDGE_MODEL = get_env("COMM_EVAL_JUDGE_MODEL", default="")
COMM_EVAL_JUDGE_CANDIDATES = get_env("COMM_EVAL_JUDGE_CANDIDATES", default="")  # "provedor/modelo,..."
COMM_EVAL_ALLOW_EXTERNAL_JUDGE = get_env_bool("COMM_EVAL_ALLOW_EXTERNAL_JUDGE", default=False)
COMM_EVAL_MAX_USD = float(get_env("COMM_EVAL_MAX_USD", default="0"))
COMM_EVAL_JUDGE_CONTEXT_CHARS = int(get_env("COMM_EVAL_JUDGE_CONTEXT_CHARS", default="400"))
COMM_EVAL_CALIBRATION_SIZE = int(get_env("COMM_EVAL_CALIBRATION_SIZE", default="20"))
COMM_EVAL_MIN_KAPPA = float(get_env("COMM_EVAL_MIN_KAPPA", default="0.6"))
COMM_EVAL_LOOP_MIN_LENGTH = int(get_env("COMM_EVAL_LOOP_MIN_LENGTH", default="3"))

# --- Orçamento de Uso da Sessão (V18 / Spec usage-limits) ---
# UsageBudget/UsageTracker (src/orchestration/usage.py) transformam estes limites em condições de
# parada reais (não apenas avisos — ver OPERATIONAL_THRESHOLDS abaixo). Fonte única:
# o AutonomousLoop lê estes limites exclusivamente daqui, nunca de os.environ direto.
#
# SESSION_MAX_TOKENS substitui MAX_SESSION_TOKENS (definida abaixo como alias de
# retrocompatibilidade — ambos os nomes de variável de ambiente são aceitos).
SESSION_MAX_TOKENS = int(
    get_env("SESSION_MAX_TOKENS") or get_env("MAX_SESSION_TOKENS", default="500000")
)
# Limite de tempo de relógio (wall-clock) da sessão, em minutos.
SESSION_MAX_MINUTES = float(get_env("SESSION_MAX_MINUTES", default="120"))
# SESSION_MAX_TASK_RETRIES substitui MAX_RETRY_PER_SUBTASK (alias de retrocompatibilidade
# abaixo). MUDANÇA DE COMPORTAMENTO: antes desta spec, o AutonomousLoop lia
# MAX_RETRY_PER_SUBTASK diretamente de os.environ com default 10 (inconsistente com o
# default 3 já documentado aqui); agora o loop lê exclusivamente este valor — o default
# efetivo de retentativas por tarefa passa de 10 para 3.
SESSION_MAX_TASK_RETRIES = int(
    get_env("SESSION_MAX_TASK_RETRIES") or get_env("MAX_RETRY_PER_SUBTASK", default="3")
)
# Retentativas de conexão acumuladas na sessão inteira (provedores LLM + sandbox Docker).
SESSION_MAX_CONNECTION_RETRIES = int(get_env("SESSION_MAX_CONNECTION_RETRIES", default="20"))
# Fração de SESSION_MAX_TOKENS reservada para o fechamento (checkpoint + consolidação
# final) após o limite de exploração ser atingido.
SESSION_CLOSING_RESERVE_PCT = float(get_env("SESSION_CLOSING_RESERVE_PCT", default="0.05"))
# Tempo de carência (segundos) para que subtarefas em andamento terminem após o limite
# de tempo da sessão ser atingido, antes de serem canceladas.
LIMIT_GRACE_SECONDS = int(get_env("LIMIT_GRACE_SECONDS", default="120"))

# --- Continuidade da pesquisa (V18 / mudança v18-research-continuity) ---
# Batimento da sessão mestra e detecção de paradas inesperadas (queda de energia, erro fatal): a sessão `active`
# sem batimento há mais de SESSION_STALE_SECONDS é marcada `interrompida` na próxima inicialização.
SESSION_HEARTBEAT_SECONDS = float(get_env("SESSION_HEARTBEAT_SECONDS", default="30"))
SESSION_STALE_SECONDS = float(get_env("SESSION_STALE_SECONDS", default="300"))
# v18.7-background-sessions: sessões terminadas há mais de N dias saem do registro (`agent_sessions`); as com
# trabalho por terminar e as antecessoras de uma cadeia viva ficam. 0 desliga a purga; `outputs/` nunca é tocado.
SESSION_RETENTION_DAYS = float(get_env("SESSION_RETENTION_DAYS", default="30"))
# v18.7-background-sessions: cada pesquisa roda em processo próprio (ADR 023); o terminal só lança, acompanha e decide.
SESSION_LAUNCH_TIMEOUT_SECONDS = float(get_env("SESSION_LAUNCH_TIMEOUT_SECONDS", default="60"))
SESSION_LOG_DIR = get_env("SESSION_LOG_DIR", default="logs/sessions")
SESSION_LOOP_TICK_SECONDS = float(get_env("SESSION_LOOP_TICK_SECONDS", default="10"))
SESSION_LOOP_STALE_SECONDS = float(get_env("SESSION_LOOP_STALE_SECONDS", default="900"))
TERMINAL_PRESENCE_HEARTBEAT_SECONDS = float(get_env("TERMINAL_PRESENCE_HEARTBEAT_SECONDS", default="10"))
TERMINAL_PRESENCE_STALE_SECONDS = float(get_env("TERMINAL_PRESENCE_STALE_SECONDS", default="60"))
SESSION_PRESENCE_CHECK_SECONDS = float(get_env("SESSION_PRESENCE_CHECK_SECONDS", default="15"))
TERMINAL_STALE_CHECK_SECONDS = float(get_env("TERMINAL_STALE_CHECK_SECONDS", default="60"))
SESSION_LOST_EXIT_GRACE_SECONDS = float(get_env("SESSION_LOST_EXIT_GRACE_SECONDS", default="30"))
# Nomes extras retirados do ambiente do processo da sessão (separados por vírgula).
SESSION_ENV_DENYLIST = tuple(n.strip() for n in get_env("SESSION_ENV_DENYLIST", default="").split(",") if n.strip())
if TERMINAL_PRESENCE_STALE_SECONDS <= 2 * TERMINAL_PRESENCE_HEARTBEAT_SECONDS:
    raise ConfigurationError(
        "'TERMINAL_PRESENCE_STALE_SECONDS' deve ser maior que o dobro de 'TERMINAL_PRESENCE_HEARTBEAT_SECONDS' "
        "(uma pausa curta do banco não pode contar como ausência do terminal)."
    )
if SESSION_LOOP_STALE_SECONDS <= SESSION_LOOP_TICK_SECONDS:
    raise ConfigurationError("'SESSION_LOOP_STALE_SECONDS' deve ser maior que 'SESSION_LOOP_TICK_SECONDS'.")
# `checkpoint.json` é dado não confiável na leitura: tamanho máximo aceito (bytes) e teto de subtarefas.
CHECKPOINT_MAX_BYTES = int(get_env("CHECKPOINT_MAX_BYTES", default=str(2 * 1024 * 1024)))
CHECKPOINT_MAX_SUBTASKS = int(get_env("CHECKPOINT_MAX_SUBTASKS", default="200"))
# Profundidade máxima da cadeia de sessões continuadas lida na retomada (anti-ciclo e anti-custo).
RESUME_MAX_CHAIN_DEPTH = int(get_env("RESUME_MAX_CHAIN_DEPTH", default="20"))
# Teto opcional de tokens acumulados da cadeia de sessões continuadas (0 = sem teto; só exibe o acumulado).
RESUME_MAX_CHAIN_TOKENS = int(get_env("RESUME_MAX_CHAIN_TOKENS", default="0"))
# Bloco de contexto de retomada do Researcher (caracteres) e leitura de artefatos de sessões anteriores (bytes).
RESUME_CONTEXT_MAX_CHARS = int(get_env("RESUME_CONTEXT_MAX_CHARS", default="12000"))
RESUME_ARTIFACT_MAX_READ_BYTES = int(get_env("RESUME_ARTIFACT_MAX_READ_BYTES", default=str(256 * 1024)))

# --- Perfil de Sessão (Roadmap V15.6 / Spec G10) ---
# Nível de autonomia padrão quando nenhuma flag --mode é fornecida.
# Ambientes headless (ex: servidores sem pesquisador disponível) podem usar 'semi' ou 'auto'.
_session_default_mode_raw = get_env("SESSION_DEFAULT_MODE", default=SessionMode.ASSISTED.value).lower()
try:
    SESSION_DEFAULT_MODE = SessionMode(_session_default_mode_raw).value
except ValueError:
    SESSION_DEFAULT_MODE = SessionMode.ASSISTED.value


# --- Outras Configurações ---
# Banco de dados PostgreSQL (Roadmap V8) — única config de banco necessária
DATABASE_URL = get_env(
    "DATABASE_URL",
    default="postgresql://geminiclaw:geminiclaw_secret@localhost:5432/geminiclaw",
)

OUTPUT_BASE_DIR = get_env("OUTPUT_BASE_DIR", default="outputs")
LOGS_BASE_DIR = get_env("LOGS_BASE_DIR", default="logs")
SEARCH_CACHE_TTL_SECONDS = int(get_env("SEARCH_CACHE_TTL_SECONDS", default="3600"))

# --- Pipeline de Contexto de Entrada (Roadmap V15.5 / Spec G9) ---
INPUT_CONTEXT_DIR = get_env("INPUT_CONTEXT_DIR", default="./input_context")
# Acima deste total estimado de tokens, a CLI avisa o pesquisador antes de prosseguir.
CONTEXT_TOKEN_WARNING_THRESHOLD = int(get_env("CONTEXT_TOKEN_WARNING_THRESHOLD", default="100000"))
# Descrição de imagens por modelo de visão (v18.5-research-data-ingestion): ``provedor/modelo``, entrada do catálogo
# de modelos. Vazio = sem visão (OCR local).
VISION_MODEL = get_env("VISION_MODEL", default="")
# Obsoleto: ``gemini`` vira alias de ``VISION_MODEL=google/gemini-4-argon`` (com aviso); ``local`` = sem visão.
OCR_PROVIDER = get_env("OCR_PROVIDER", default="local")

# Docker settings

# Deep Search Skill (S2)
SKILL_DEEP_SEARCH_ENABLED = get_env_bool("SKILL_DEEP_SEARCH_ENABLED", default=False)
DEEP_SEARCH_DOMAINS = get_env("DEEP_SEARCH_DOMAINS", default="docs.python.org,arxiv.org")
DEEP_SEARCH_MAX_PAGES_PER_DOMAIN = int(get_env("DEEP_SEARCH_MAX_PAGES_PER_DOMAIN", default="50"))
DEEP_SEARCH_CACHE_TTL_SECONDS = int(get_env("DEEP_SEARCH_CACHE_TTL_SECONDS", default="86400"))
QDRANT_URL = get_env("QDRANT_URL", default="http://localhost:6333")
QDRANT_CHECK_COMPATIBILITY = get_env_bool("QDRANT_CHECK_COMPATIBILITY", default=True)
EMBEDDING_MODEL = get_env("EMBEDDING_MODEL", default="sentence-transformers/all-MiniLM-L6-v2")

# Embeddings locais (Roadmap V16 / ADR 011 §3) — ver src/embeddings/
EMBEDDING_CACHE_DIR = get_env(
    "EMBEDDING_CACHE_DIR",
    default=str(Path.home() / ".cache" / APP_NAME / "embeddings"),
)
EMBEDDING_BATCH_SIZE = int(get_env("EMBEDDING_BATCH_SIZE", default="32"))
# Quando true, nenhum download do modelo é tentado (modelo deve já estar em
# EMBEDDING_CACHE_DIR — ver scripts/setup_pi.sh). Usado em produção no Pi 5.
EMBEDDING_OFFLINE = get_env_bool("EMBEDDING_OFFLINE", default=False)

# Índice semântico do grafo de conhecimento (Roadmap V17 / ADR 015 §6,
# openspec/changes/archive/v17-knowledge-semantic-index). Coleção Qdrant com um ponto
# por nó vetorizável (ID do ponto = ID do nó) e limiares das faixas de
# similaridade. Os limiares dependem do modelo de embedding e são calibrados
# pelo pesquisador (`geminiclaw knowledge stats` apenas sugere ajustes).
KNOWLEDGE_COLLECTION = get_env("KNOWLEDGE_COLLECTION", default="knowledge_nodes")
SIM_DUPLICATE_MIN = float(get_env("SIM_DUPLICATE_MIN", default="0.90"))
SIM_RELATED_MIN_SAME_DOMAIN = float(get_env("SIM_RELATED_MIN_SAME_DOMAIN", default="0.70"))
SIM_RELATED_MIN_CROSS = float(get_env("SIM_RELATED_MIN_CROSS", default="0.60"))
SIM_CROSS_DOMAIN_BOOST = float(get_env("SIM_CROSS_DOMAIN_BOOST", default="1.5"))
SIM_CANDIDATE_SCAN_LIMIT = int(get_env("SIM_CANDIDATE_SCAN_LIMIT", default="200"))
SIM_CALIBRATION_WINDOW_DAYS = int(get_env("SIM_CALIBRATION_WINDOW_DAYS", default="30"))
RECENCY_HALF_LIFE_DAYS = float(get_env("RECENCY_HALF_LIFE_DAYS", default="365"))
CONFIDENCE_FLOOR = float(get_env("CONFIDENCE_FLOOR", default="0.05"))
# Nós lidos do grafo por página na reconciliação (limita a memória no Pi 5).
SIM_RECONCILE_BATCH_SIZE = int(get_env("SIM_RECONCILE_BATCH_SIZE", default="200"))
# Amostra mínima (pares revisados na faixa) para sugerir ajuste de limiar.
SIM_CALIBRATION_MIN_SAMPLES = int(get_env("SIM_CALIBRATION_MIN_SAMPLES", default="10"))
# Liga o índice semântico ao GraphStore de produção (factory.open_graph_store).
KNOWLEDGE_SEMANTIC_INDEX_ENABLED = get_env_bool("KNOWLEDGE_SEMANTIC_INDEX_ENABLED", default=True)

# v17-research-project: contorno explícito para grafo fora do ar. Desligado (padrão), toda sessão exige o
# grafo. Ligado, e SOMENTE se o grafo não abrir, a sessão roda sem projeto (payload project_mode="sem_grafo");
# com o grafo acessível a confirmação humana do Problema continua obrigatória.
RESEARCH_PROJECT_GRAPH_OPTIONAL = get_env_bool("RESEARCH_PROJECT_GRAPH_OPTIONAL", default=False)

# v17-graph-cli: acesso do pesquisador ao grafo pela CLI (visualizar sem LLM; alterar só pelo Curator, com confirmação).
GRAPH_SHOW_MAX_NODES = int(get_env("GRAPH_SHOW_MAX_NODES", default="200"))
GRAPH_SHOW_MAX_TEXT_CHARS = int(get_env("GRAPH_SHOW_MAX_TEXT_CHARS", default="200"))
GRAPH_EDIT_MAX_ROUNDS = int(get_env("GRAPH_EDIT_MAX_ROUNDS", default="3"))
GRAPH_EDIT_MAX_OPS = int(get_env("GRAPH_EDIT_MAX_OPS", default="20"))
GRAPH_EDIT_MAX_REQUEST_CHARS = int(get_env("GRAPH_EDIT_MAX_REQUEST_CHARS", default="2000"))
GRAPH_EDIT_MAX_DISPLAY_CHARS = int(get_env("GRAPH_EDIT_MAX_DISPLAY_CHARS", default="8000"))

# Quick Search Fallback
QUICK_SEARCH_STRATEGY = get_env("QUICK_SEARCH_STRATEGY", default="ddg,ddg_lite,brave")
BRAVE_API_KEY = get_env("BRAVE_API_KEY", default="")

# Web Reader Skill (S5)
SKILL_WEB_READER_ENABLED = get_env_bool("SKILL_WEB_READER_ENABLED", default=True)

# Document Processor Skill (V7)
SKILL_DOCUMENT_PROCESSOR_ENABLED = get_env_bool("SKILL_DOCUMENT_PROCESSOR_ENABLED", default=False)


# Code Execution Skill (S3)
SKILL_CODE_ENABLED = get_env_bool("SKILL_CODE_ENABLED", default=True)
CODE_SANDBOX_TIMEOUT_SECONDS = int(get_env("CODE_SANDBOX_TIMEOUT_SECONDS", default="60"))
CODE_SANDBOX_MEMORY_LIMIT = get_env("CODE_SANDBOX_MEMORY_LIMIT", default="256m")
# Limite da instalação de pacotes sob demanda no sandbox; ao estourar, a execução falha.
CODE_SANDBOX_SETUP_TIMEOUT_SECONDS = int(get_env("CODE_SANDBOX_SETUP_TIMEOUT_SECONDS", default="300"))

# Sandbox de código (v16-sandbox-slim-image / ADR 018)
SANDBOX_IMAGE = get_env("SANDBOX_IMAGE", default="code-sandbox:latest")
# Diretórios temporários por execução (ex.: /deps dos pacotes instalados sob demanda).
SANDBOX_WORK_DIR = get_env("SANDBOX_WORK_DIR", default="store/sandbox_work")
# Diretórios de trabalho de execuções do sandbox mais velhos que isto são órfãos (encerramento abrupto) e a partida
# os remove. Deve ficar bem acima do maior tempo de execução do sandbox, para nunca apagar execução em andamento.
SANDBOX_WORK_ORPHAN_MAX_HOURS = float(get_env("SANDBOX_WORK_ORPHAN_MAX_HOURS", default="24"))
SANDBOX_PIDS_LIMIT = int(get_env("SANDBOX_PIDS_LIMIT", default="256"))
SANDBOX_TMPFS_SIZE = get_env("SANDBOX_TMPFS_SIZE", default="256m")
SANDBOX_INSTALL_LOG_TAIL_LINES = int(get_env("SANDBOX_INSTALL_LOG_TAIL_LINES", default="40"))
# v18.5-sandbox-phases — fases de rede e dados do sandbox (ADR 019 §5).
SANDBOX_INSTALL_TIMEOUT_SECONDS = int(
    get_env("SANDBOX_INSTALL_TIMEOUT_SECONDS", default=str(CODE_SANDBOX_SETUP_TIMEOUT_SECONDS))
)
SANDBOX_FETCH_TIMEOUT_SECONDS = int(get_env("SANDBOX_FETCH_TIMEOUT_SECONDS", default="600"))
SANDBOX_ASSET_MAX_BYTES = int(get_env("SANDBOX_ASSET_MAX_BYTES", default="536870912"))  # 512 MiB por ativo
# 2 GiB por execução
SANDBOX_ASSET_TOTAL_MAX_BYTES = int(get_env("SANDBOX_ASSET_TOTAL_MAX_BYTES", default="2147483648"))
SANDBOX_MIN_FREE_BYTES = int(get_env("SANDBOX_MIN_FREE_BYTES", default="1073741824"))  # 1 GiB livre para iniciar
SANDBOX_ASSET_CACHE_DIR = get_env("SANDBOX_ASSET_CACHE_DIR", default="store/assets")
SANDBOX_INPUT_DELIVERY = get_env("SANDBOX_INPUT_DELIVERY", default="mount")  # mount | copy
# stdout/stderr do script devolvidos ao orquestrador (cada)
SANDBOX_OUTPUT_MAX_BYTES = int(get_env("SANDBOX_OUTPUT_MAX_BYTES", default="1048576"))
SANDBOX_COPY_MAX_BYTES = int(get_env("SANDBOX_COPY_MAX_BYTES", default="67108864"))  # 64 MiB: tmpfs conta na memória

# Health Monitoring (S7)
HEALTH_CHECK_ENABLED = get_env_bool("HEALTH_CHECK_ENABLED", default=True)
# Mínimo de memória disponível para iniciar um agente (e uma pesquisa, v18.7-background-sessions).
MIN_AVAILABLE_MEMORY_MB = float(get_env("MIN_AVAILABLE_MEMORY_MB", default="512"))
# Limite de temperatura (°C): sem valor, a temperatura não entra nas verificações (sem padrão).
TEMPERATURE_LIMIT = _env_number("TEMPERATURE_LIMIT", None, float)
if TEMPERATURE_LIMIT is not None and TEMPERATURE_LIMIT <= 0:
    raise ConfigurationError("'TEMPERATURE_LIMIT' deve ser um número maior que zero (°C).")
TEMPERATURE_WARNING_MARGIN_C = _env_number("TEMPERATURE_WARNING_MARGIN_C", "5.0", float)
if TEMPERATURE_WARNING_MARGIN_C is None or TEMPERATURE_WARNING_MARGIN_C < 0:
    raise ConfigurationError("'TEMPERATURE_WARNING_MARGIN_C' deve ser um número >= 0.")
# Sensor de temperatura (nome em psutil.sensors_temperatures()); vazio = maior leitura entre os sensores.
TEMPERATURE_SENSOR = get_env("TEMPERATURE_SENSOR", default="").strip()

# Memory (S4 + S5)
SKILL_MEMORY_ENABLED = get_env_bool("SKILL_MEMORY_ENABLED", default=True)
# LONG_TERM_MEMORY_DB removido (Roadmap V8): usa PostgreSQL via DATABASE_URL

# Human-in-the-Loop (Roadmap V15.3 / Spec G5)
SKILL_HUMAN_FEEDBACK_ENABLED = get_env_bool("SKILL_HUMAN_FEEDBACK_ENABLED", default=True)
# Limites operacionais monitorados a cada ciclo de planejamento (não-bloqueantes por padrão;
# apenas o modo 'assisted' pausa e pergunta se o pesquisador quer suspender a sessão).
# V18/usage-limits — os avisos agora são percentuais dos limites reais de UsageBudget
# (SESSION_MAX_TOKENS, SESSION_MAX_MINUTES), que passam a ser condições de parada
# (ver src/orchestration/usage.py). session_duration_min (antigo, em minutos absolutos) vira alias:
# se definido, é convertido para percentual de SESSION_MAX_MINUTES.
_session_duration_min_env = get_env("OPERATIONAL_THRESHOLD_SESSION_DURATION_MIN")
if _session_duration_min_env is not None and SESSION_MAX_MINUTES:
    _session_duration_pct_default = float(_session_duration_min_env) / SESSION_MAX_MINUTES
else:
    _session_duration_pct_default = 0.5
OPERATIONAL_THRESHOLDS: dict[str, float] = {
    "token_usage_pct": float(get_env("OPERATIONAL_THRESHOLD_TOKEN_USAGE_PCT", default="0.80")),
    "session_duration_pct": float(
        get_env(
            "OPERATIONAL_THRESHOLD_SESSION_DURATION_PCT",
            default=str(_session_duration_pct_default),
        )
    ),
}
# Alias de retrocompatibilidade: MAX_SESSION_TOKENS é o nome antigo de SESSION_MAX_TOKENS.
MAX_SESSION_TOKENS = SESSION_MAX_TOKENS

# --- Limites da exploração (v18.7-exploration-limits, ADR 021; design §13) ---
# Valores provisórios: só mudam depois de testados em bateria. Valor inválido falha na inicialização.


def _bounded_number(key: str, default: str, kind: type, rule: str, valid: Callable[[float], bool]) -> float | int:
    """Número de ``key`` que cumpre ``valid``; vazio, inválido ou fora da regra falha citando a variável."""
    value = _env_number(key, default, kind)
    if value is None or not valid(value):
        raise ConfigurationError(f"'{key}' deve ser {rule}.")
    return value


def _provider_costs(raw: str) -> dict[str, float]:
    """``provedor=valor,...`` com valores > 0; vazio resulta em ``{}`` (só o total vale)."""
    limits: dict[str, float] = {}
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        provider, _, amount = item.partition("=")
        try:
            value = float(amount)
        except ValueError:
            value = 0.0
        if not provider.strip() or value <= 0:
            raise ConfigurationError(
                "'SESSION_MAX_COST_USD_BY_PROVIDER' deve ser 'provedor=valor,...' com valores maiores que zero."
            )
        limits[provider.strip()] = value
    return limits


# Custo estimado da sessão (US$): o único jeito de desligar o limite é o modo sem limite, nunca um valor <= 0.
_cost_limit = _env_number("SESSION_MAX_COST_USD", "20.0", float)
if _cost_limit is None or _cost_limit <= 0:
    raise ConfigurationError(
        "'SESSION_MAX_COST_USD' deve ser um número maior que zero; para rodar sem limite use o modo sem limite "
        "(--unlimited), não um valor <= 0 ou vazio."
    )
SESSION_MAX_COST_USD: float = _cost_limit
SESSION_MAX_COST_USD_BY_PROVIDER: dict[str, float] = _provider_costs(
    get_env("SESSION_MAX_COST_USD_BY_PROVIDER", default="")
)
OPERATIONAL_THRESHOLD_COST_USAGE_PCT = float(
    _bounded_number("OPERATIONAL_THRESHOLD_COST_USAGE_PCT", "0.80", float, "um número em (0, 1]", lambda v: 0 < v <= 1)
)
OPERATIONAL_THRESHOLDS["cost_usage_pct"] = OPERATIONAL_THRESHOLD_COST_USAGE_PCT
# Estagnação, intervenção do Curator e saturação (0 em EXPLORATION_STALL_CYCLES desliga as três).
EXPLORATION_STALL_CYCLES = int(
    _bounded_number("EXPLORATION_STALL_CYCLES", "5", int, "um inteiro >= 0 (0 desliga)", lambda v: v >= 0)
)
EXPLORATION_MAX_INTERVENTIONS = int(
    _bounded_number("EXPLORATION_MAX_INTERVENTIONS", "3", int, "um inteiro >= 1", lambda v: v >= 1)
)
EXPLORATION_PATIENCE_GROWTH = float(
    _bounded_number("EXPLORATION_PATIENCE_GROWTH", "0.5", float, "um número >= 0", lambda v: v >= 0)
)
SATURATION_MIN_REPLICATES = int(
    _bounded_number("SATURATION_MIN_REPLICATES", "3", int, "um inteiro >= 2", lambda v: v >= 2)
)
SATURATION_SE_MULTIPLIER = float(
    _bounded_number("SATURATION_SE_MULTIPLIER", "1.0", float, "um número maior que zero", lambda v: v > 0)
)
COVERAGE_NOVELTY_WINDOW = int(
    _bounded_number("COVERAGE_NOVELTY_WINDOW", "5", int, "um inteiro >= 1", lambda v: v >= 1)
)
COVERAGE_NOVELTY_MIN_RATE = float(
    _bounded_number("COVERAGE_NOVELTY_MIN_RATE", "0.2", float, "um número >= 0", lambda v: v >= 0)
)
RESTRICTION_SIMILARITY = float(
    _bounded_number("RESTRICTION_SIMILARITY", "0.80", float, "um número em (0, 1]", lambda v: 0 < v <= 1)
)
# Política dos planos rejeitados em sequência (design §9.3): explorar (Curator intervém) ou parar.
ON_PLAN_REJECTIONS = get_env("ON_PLAN_REJECTIONS", default="explorar").strip().lower()
if ON_PLAN_REJECTIONS not in ("explorar", "parar"):
    raise ConfigurationError("'ON_PLAN_REJECTIONS' deve ser 'explorar' ou 'parar'.")

# v18.5-operation-metrics: avisos periódicos do modo sem limite (sem como desligá-los: valores <= 0 falham).
UNLIMITED_NOTICE_INTERVAL_MINUTES = float(get_env("UNLIMITED_NOTICE_INTERVAL_MINUTES", default="15"))
UNLIMITED_NOTICE_TOKEN_STEP = int(get_env("UNLIMITED_NOTICE_TOKEN_STEP", default="500000"))
if UNLIMITED_NOTICE_INTERVAL_MINUTES <= 0:
    raise ValueError("UNLIMITED_NOTICE_INTERVAL_MINUTES deve ser positivo (os avisos não se desligam).")
if UNLIMITED_NOTICE_TOKEN_STEP <= 0:
    raise ValueError("UNLIMITED_NOTICE_TOKEN_STEP deve ser positivo (os avisos não se desligam).")
# Similaridade textual mínima (0-1, via difflib) para considerar duas perguntas ao
# pesquisador "a mesma dúvida" e reutilizar a resposta anterior sem perguntar de novo.
ASK_RESEARCHER_DEDUP_SIMILARITY = float(get_env("ASK_RESEARCHER_DEDUP_SIMILARITY", default="0.85"))

# V18/researcher-consult — Researcher consultor nos modos `semi`/`auto` (ADR 012 §8).
# Desligado, `ask_researcher` volta a devolver a suposição documentada.
RESEARCHER_CONSULT_ENABLED = get_env_bool("RESEARCHER_CONSULT_ENABLED", default=True)
# Desliga só as ferramentas web do consultor (ele responde com o que sabe).
RESEARCHER_CONSULT_WEB_ENABLED = get_env_bool("RESEARCHER_CONSULT_WEB_ENABLED", default=True)
RESEARCHER_CONSULT_MAX_PER_SESSION = int(get_env("RESEARCHER_CONSULT_MAX_PER_SESSION", default="10"))
RESEARCHER_CONSULT_MAX_SEARCHES = int(get_env("RESEARCHER_CONSULT_MAX_SEARCHES", default="3"))
RESEARCHER_CONSULT_MAX_READS = int(get_env("RESEARCHER_CONSULT_MAX_READS", default="2"))
RESEARCHER_CONSULT_TIMEOUT_SECONDS = float(get_env("RESEARCHER_CONSULT_TIMEOUT_SECONDS", default="120"))
# Tamanho máximo do texto enviado a um buscador público (guarda de consulta).
RESEARCHER_CONSULT_QUERY_MAX_CHARS = int(get_env("RESEARCHER_CONSULT_QUERY_MAX_CHARS", default="120"))
# Hosts (sufixos de domínio, separados por vírgula) que `web_reader` pode ler nas consultas.
# Vazio = sem lista estática (padrão); a allowlist por consulta é a de hosts vistos na busca (abaixo).
RESEARCHER_CONSULT_ALLOWED_HOSTS = tuple(
    h.strip().lower() for h in (get_env("RESEARCHER_CONSULT_ALLOWED_HOSTS", default="") or "").split(",") if h.strip()
)
# Allowlist de hosts por consulta (v18.5-egress-gate, tarefa 7.6): `web_reader` só lê hosts que apareceram em resultado
# de `quick_search` da mesma consulta (fecha o canal de saída por URL pós-injeção). Padrão LIGADO.
RESEARCHER_CONSULT_READ_ONLY_SEARCHED_HOSTS = get_env_bool("RESEARCHER_CONSULT_READ_ONLY_SEARCHED_HOSTS", default=True)

# LLM Response Cache
LLM_CACHE_ENABLED = get_env_bool("LLM_CACHE_ENABLED", default=True)
LLM_CACHE_TTL_SECONDS = int(get_env("LLM_CACHE_TTL_SECONDS", default="3600"))
LLM_CACHE_MAX_ENTRIES = int(get_env("LLM_CACHE_MAX_ENTRIES", default="1000"))

# Autonomous Loop — alias de retrocompatibilidade: MAX_RETRY_PER_SUBTASK é o nome antigo
# de SESSION_MAX_TASK_RETRIES (definida acima, junto ao orçamento de uso da sessão).
MAX_RETRY_PER_SUBTASK = SESSION_MAX_TASK_RETRIES

# V13.4.2 — Limite de linhas de código do step anterior injetadas no contexto do LLM.
# Para qwen3:8b com 8192 tokens, 150 linhas de Python cabem com espaço para o restante.
MAX_CODE_CONTEXT_LINES = int(get_env("MAX_CODE_CONTEXT_LINES", default="150"))

# Revisão de subtarefa pelo Validator (V6.3)
REVIEW_ENABLED = get_env_bool("REVIEW_ENABLED", default=True)
REVIEW_MODE = get_env("REVIEW_MODE", default="per_subtask") # per_subtask | disabled
if REVIEW_MODE not in ("per_subtask", "disabled"):
    raise ValueError(f"REVIEW_MODE inválido: '{REVIEW_MODE}'. Valores aceitos: per_subtask, disabled.")

# Context Compression (V6.5)
CONTEXT_COMPRESSION_MODE = get_env("CONTEXT_COMPRESSION_MODE", default="truncate") # truncate | summarize

# Concurrency Control (V6.6)
MAX_LOCAL_LLM_CONCURRENT = int(get_env("MAX_LOCAL_LLM_CONCURRENT", default="2"))

# Triage
TRIAGE_MODE = get_env("TRIAGE_MODE", default="hybrid")
TRIAGE_CONFIDENCE_THRESHOLD = float(get_env("TRIAGE_CONFIDENCE_THRESHOLD", default="0.7"))

# --- Regra de estado da hipótese (ADR 026 §3; substitui o veredito do ADR 015 §9) ---
# Tentativas válidas e independentes (configuração, semente ou conjunto de dados distintos) que atingem o alvo e
# validam a hipótese.
HYPOTHESIS_MIN_REPLICAS = int(
    _bounded_number("HYPOTHESIS_MIN_REPLICAS", "2", int, "um inteiro >= 1", lambda v: v >= 1)
)
# Tentativas válidas e independentes abaixo do alvo, sem nenhuma que o atinja, que refutam a hipótese.
HYPOTHESIS_MIN_REFUTATIONS = int(
    _bounded_number("HYPOTHESIS_MIN_REFUTATIONS", "2", int, "um inteiro >= 1", lambda v: v >= 1)
)

# --- Candidatos estruturais (ADR 026 §6; v18.9-memory-evaluation) ---
# Semelhança mínima entre Problemas para uma abordagem de um virar candidata de transferência no outro.
CANDIDATE_MIN_SIMILARITY = float(
    _bounded_number("CANDIDATE_MIN_SIMILARITY", "0.60", float, "um número em [0, 1]", lambda v: 0 <= v <= 1)
)
# Descendentes no máximo para uma abordagem com ganho contar como pouco explorada.
CANDIDATE_MAX_DESCENDANTS = int(
    _bounded_number("CANDIDATE_MAX_DESCENDANTS", "2", int, "um inteiro >= 0", lambda v: v >= 0)
)

# --- Experiência de problemas semelhantes (ADR 026 §6; v18.9-cross-project-context) ---
# Problemas de outros projetos cujos registros entram no bloco do plano (e quantos).
RELATED_RECORDS_K = int(_bounded_number("RELATED_RECORDS_K", "5", int, "um inteiro >= 1", lambda v: v >= 1))
# Teto de caracteres do bloco ``experiencia_de_problemas_semelhantes``.
RELATED_RECORDS_MAX_CHARS = int(
    _bounded_number("RELATED_RECORDS_MAX_CHARS", "2500", int, "um inteiro >= 200", lambda v: v >= 200)
)
# Peso do cosseno do texto na semelhança de Problemas; o resto é a semelhança de ``caracteristicas_dados``.
RELATED_TEXT_WEIGHT = float(
    _bounded_number("RELATED_TEXT_WEIGHT", "0.5", float, "um número em [0, 1]", lambda v: 0 <= v <= 1)
)
# Candidatos vindos de outro projeto viram ``Oportunidade`` (``origem = "grafo"``). Desligado até a regra do E0.
CROSS_PROJECT_CANDIDATES = get_env_bool("CROSS_PROJECT_CANDIDATES", default=False)

# --- Memória de falhas (ADR 026 §5; v18.9-failure-memory) ---
# Teto de caracteres do bloco "NÃO / USE" que o Developer recebe antes de cada subtarefa de código (0 desliga).
FAILURE_MEMORY_MAX_CHARS = int(
    _bounded_number("FAILURE_MEMORY_MAX_CHARS", "1500", int, "um inteiro >= 0 (0 desliga)", lambda v: v >= 0)
)

# --- Agente Curator (Roadmap V17 / ADR 012 §1-§2, ADR 015 §10; mudança v17-curator-agent) ---
# O modelo do papel `curator` vem do catálogo (src/llm/catalog.yaml, ADR 017); para fixar um modelo use
# `CURATOR_MODEL=provedor/modelo`. Os limites abaixo valem POR EXECUÇÃO do Curator (consolidate/close_session).
CURATOR_ENABLED = get_env_bool("CURATOR_ENABLED", default=True)
CURATOR_MAX_ITERATIONS = int(get_env("CURATOR_MAX_ITERATIONS", default="20"))
CURATOR_MAX_TOKENS_PER_RUN = int(get_env("CURATOR_MAX_TOKENS_PER_RUN", default="30000"))
CURATOR_QUEUE_BATCH = int(get_env("CURATOR_QUEUE_BATCH", default="20"))
# Escritas no grafo por execução (criar/reforçar/ligar/mudar status) e consultas livres (read_query).
CURATOR_MAX_WRITES_PER_RUN = int(get_env("CURATOR_MAX_WRITES_PER_RUN", default="30"))
CURATOR_MAX_READ_QUERIES_PER_RUN = int(get_env("CURATOR_MAX_READ_QUERIES_PER_RUN", default="5"))
# Mudanças de status de descobertas (contestar/substituir) por execução: ações duráveis, com teto baixo.
CURATOR_MAX_STATUS_CHANGES_PER_RUN = int(get_env("CURATOR_MAX_STATUS_CHANGES_PER_RUN", default="3"))
# Tamanho máximo de cada campo de texto aceito pelas ferramentas de escrita (recusa, não trunca).
CURATOR_MAX_TEXT_CHARS = int(get_env("CURATOR_MAX_TEXT_CHARS", default="1000"))
# Tamanho máximo da saída de uma ferramenta devolvida ao modelo (dado não confiável) e do resumo de entrada.
CURATOR_MAX_TOOL_OUTPUT_CHARS = int(get_env("CURATOR_MAX_TOOL_OUTPUT_CHARS", default="6000"))
CURATOR_TIMEOUT_SECONDS = int(get_env("CURATOR_TIMEOUT_SECONDS", default="300"))
# Sinalizações (flag_for_curator): máximo por sessão e tamanho do texto.
CURATOR_MAX_FLAGS_PER_SESSION = int(get_env("CURATOR_MAX_FLAGS_PER_SESSION", default="100"))
CURATOR_FLAG_MAX_CHARS = int(get_env("CURATOR_FLAG_MAX_CHARS", default="1000"))
# Promoção de configuração a Abordagem(tipo="configuracao"): positivos validados e projetos distintos.
PROMOTION_MIN_POSITIVES = int(get_env("PROMOTION_MIN_POSITIVES", default="3"))
PROMOTION_MIN_PROJECTS = int(get_env("PROMOTION_MIN_PROJECTS", default="2"))

# --- Ciclo de hipóteses e exploração ativa (V18 / mudança v18-hypothesis-loop; ADR 012 §3-§4, ADR 015) ---
# Desliga o ciclo de exploração (volta ao laço de ciclo único da V17) sem apagar nada do grafo.
HYPOTHESIS_LOOP_ENABLED = get_env_bool("HYPOTHESIS_LOOP_ENABLED", default=True)
# Pesos da prioridade de hipóteses, na ordem: relevância, apoio prévio, novidade, (1 - custo). Devem somar 1.
HYPOTHESIS_PRIORITY_WEIGHTS: tuple[float, float, float, float] = tuple(  # type: ignore[assignment]
    float(x) for x in get_env("HYPOTHESIS_PRIORITY_WEIGHTS", default="0.35,0.30,0.20,0.15").split(",")
)
if len(HYPOTHESIS_PRIORITY_WEIGHTS) != 4 or any(w < 0 for w in HYPOTHESIS_PRIORITY_WEIGHTS) or not (
    abs(sum(HYPOTHESIS_PRIORITY_WEIGHTS) - 1.0) < 1e-6
):
    raise ValueError("HYPOTHESIS_PRIORITY_WEIGHTS deve ter 4 pesos não negativos que somam 1 (0.35,0.30,0.20,0.15).")
# Similaridade semântica a partir da qual uma hipótese nova reutiliza a existente do projeto.
HYPOTHESIS_DEDUP_SIMILARITY = float(get_env("HYPOTHESIS_DEDUP_SIMILARITY", default="0.90"))
# Sugestões do Curator ao Researcher por ciclo.
CURATOR_MAX_SUGGESTIONS = max(int(get_env("CURATOR_MAX_SUGGESTIONS", default="3")), 0)
# Tamanho máximo (caracteres) dos textos de hipótese, decisão e sugestão aceitos do plano (recusa, não trunca) e
# quantidades máximas por plano.
HYPOTHESIS_TEXT_MAX_CHARS = int(get_env("HYPOTHESIS_TEXT_MAX_CHARS", default="1000"))
HYPOTHESES_MAX_PER_PLAN = int(get_env("HYPOTHESES_MAX_PER_PLAN", default="10"))
DECISIONS_MAX_PER_PLAN = int(get_env("DECISIONS_MAX_PER_PLAN", default="10"))
# v18.6-auto-metrics-and-stop-reasons: máximo de métricas que o Researcher pode definir no plano (modo auto).
METRICS_MAX_PER_PLAN = max(int(get_env("METRICS_MAX_PER_PLAN", default="3")), 1)
# v18.7-hypothesis-linking: máximo de itens do retorno ao Researcher sobre ligações e retiradas do ciclo anterior, e
# primeiras palavras (normalizadas, sem acento) que tornam o texto livre ``hypothesis`` não afirmativo.
LINKAGE_FEEDBACK_MAX_ITEMS = max(int(get_env("LINKAGE_FEEDBACK_MAX_ITEMS", default="30")), 1)
HYPOTHESIS_TEXT_NEGATION_PREFIXES = tuple(
    item.strip().lower()
    for item in get_env("HYPOTHESIS_TEXT_NEGATION_PREFIXES", default="nao,sem,nenhum,nenhuma,nunca").split(",")
    if item.strip()
)

# --- Grafo de Conhecimento (Roadmap V17 / ADR 009, ADR 015) ---
# Nome do grafo Apache AGE (sem o nome do produto — ADR 011).
KNOWLEDGE_GRAPH_NAME = get_env("KNOWLEDGE_GRAPH_NAME", default="knowledge")
# DSN somente-leitura (papel `knowledge_reader`) usado por GraphStore.read_query
# (Curator, CLI). Obrigatória apenas quando o grafo é efetivamente utilizado —
# a leitura tardia em AgeGraphStore levanta erro explícito se ausente.
KNOWLEDGE_READER_DATABASE_URL = get_env("KNOWLEDGE_READER_DATABASE_URL")
KNOWLEDGE_READ_TIMEOUT_MS = int(get_env("KNOWLEDGE_READ_TIMEOUT_MS", default="5000"))
# v17-structural-fact-ingestion — limites de I/O da ingestão de insumos (contenção no Pi 5):
# maior arquivo que será hasheado e total de bytes hasheados por chamada de ingestão (subtarefa/insumos).
INGESTION_MAX_FILE_BYTES = int(get_env("INGESTION_MAX_FILE_BYTES", default=str(256 * 1024 * 1024)))
INGESTION_MAX_HASH_BYTES_PER_CALL = int(
    get_env("INGESTION_MAX_HASH_BYTES_PER_CALL", default=str(1024 * 1024 * 1024))
)
# v17-input-document-index — indexação automática dos insumos de input_snapshot/ (sem LLM, antes do planejamento).
INPUT_INDEX_ENABLED = get_env_bool("INPUT_INDEX_ENABLED", default=True)
# Tempo máximo (s) da indexação no início da sessão; o que sobrar fica pendente para a próxima sessão.
INPUT_INDEX_MAX_SECONDS = int(get_env("INPUT_INDEX_MAX_SECONDS", default="300"))
# Arquivos acima deste tamanho (MB) são registrados só com descritor (artigos não são extraídos).
INPUT_INDEX_MAX_FILE_MB = int(get_env("INPUT_INDEX_MAX_FILE_MB", default="20"))
# Conjuntos de dados em JSON/JSONL/xlsx/xls/ods/parquet acima deste tamanho (MB) não são lidos por inteiro
# (parse em memória): só descritor mínimo e WARNING. CSV/TSV são lidos em fluxo e seguem o limite geral.
INPUT_INDEX_MAX_DATASET_MB = int(get_env("INPUT_INDEX_MAX_DATASET_MB", default="10"))
# Tamanho máximo (caracteres) do cabeçalho enriquecido de cada trecho.
INPUT_INDEX_HEADER_MAX_CHARS = int(get_env("INPUT_INDEX_HEADER_MAX_CHARS", default="400"))
# Similaridade semântica mínima para um termo livre ser resolvido a um termo
# canônico do vocabulário controlado (faixa de duplicata, v17-controlled-vocabulary).
VOCAB_MATCH_THRESHOLD = float(get_env("VOCAB_MATCH_THRESHOLD", default="0.90"))

# Busca de domínio com embeddings hierárquicos (v17-domain-search §7).
# Resultados devolvidos por padrão (teto fixo de 10 aplicado pela busca).
DOMAIN_SEARCH_LIMIT = int(get_env("DOMAIN_SEARCH_LIMIT", default="5"))
# Escore mínimo de um domínio para ser devolvido (depende do modelo de embedding).
DOMAIN_SEARCH_MIN_SCORE = float(get_env("DOMAIN_SEARCH_MIN_SCORE", default="0.35"))
# Margem de escore em que o nível mais específico passa à frente do mais amplo.
DOMAIN_SPECIFICITY_MARGIN = float(get_env("DOMAIN_SPECIFICITY_MARGIN", default="0.03"))
# Tamanho máximo (caracteres) da consulta e do contexto da busca de domínio.
DOMAIN_SEARCH_MAX_QUERY_CHARS = int(get_env("DOMAIN_SEARCH_MAX_QUERY_CHARS", default="300"))
# Descendentes marcados como pendentes por lote quando um ancestral muda.
DOMAIN_REINDEX_BATCH = int(get_env("DOMAIN_REINDEX_BATCH", default="200"))
# Tamanho máximo (caracteres) de um termo livre de vocabulário que vira candidato. Termos
# maiores são recusados: texto de agente não deve voltar ao prompt de outro sem limite.
VOCAB_TERM_MAX_CHARS = int(get_env("VOCAB_TERM_MAX_CHARS", default="120"))

# v18.5-egress-gate (ADR 019 §3) — camada única de saída com filtro de egresso.
def _optional_positive_int(key: str) -> int | None:
    """Lê um inteiro positivo opcional do ambiente; ausente/vazio -> ``None``; inválido falha de forma acionável."""
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{key} inválida: '{raw}'. Informe um inteiro positivo (ex.: {key}=10).") from None
    if value <= 0:
        raise RuntimeError(f"{key} inválida: '{raw}'. Informe um inteiro positivo (ex.: {key}=10).")
    return value


# Tamanho mínimo de grupo (k) das estatísticas impressas enviadas a modelos sem dados brutos. O valor é
# decisão do pesquisador (não há default no código); sem valor, a sessão não inicia (ver o requisito abaixo).
LOCALITY_MIN_GROUP_SIZE: int | None = _optional_positive_int("LOCALITY_MIN_GROUP_SIZE")
# Saídas de execução não tabulares acima deste tamanho (caracteres) vão com início, fim e marcador de elisão.
EGRESS_OUTPUT_MAX_CHARS = int(get_env("EGRESS_OUTPUT_MAX_CHARS", default="4000"))
# Limite de volume (bytes) de saídas de execução, após o filtro, enviadas a destinos fora do nó por sessão.
EGRESS_SESSION_MAX_BYTES = int(get_env("EGRESS_SESSION_MAX_BYTES", default="2000000"))
# Linhas consecutivas com o mesmo número de campos que caracterizam um bloco tabular; também o limite
# (exclusivo) de elementos numéricos de uma lista para retê-la.
EGRESS_TABLE_MIN_ROWS = int(get_env("EGRESS_TABLE_MIN_ROWS", default="3"))

# --- Referências numéricas rastreáveis (v18.5-numeric-references, ADR 019 §2) ---
NUMREF_DISPLAY_MAX_SIG_DIGITS = int(get_env("NUMREF_DISPLAY_MAX_SIG_DIGITS", default="6"))
NUMREF_CALC_SIG_DIGITS = int(get_env("NUMREF_CALC_SIG_DIGITS", default="4"))
NUMREF_CALC_MAX_CHARS = int(get_env("NUMREF_CALC_MAX_CHARS", default="400"))
NUMREF_CALC_MAX_NODES = int(get_env("NUMREF_CALC_MAX_NODES", default="64"))
NUMREF_CALC_MAX_POW = int(get_env("NUMREF_CALC_MAX_POW", default="4"))
NUMREF_YEAR_MIN = int(get_env("NUMREF_YEAR_MIN", default="1900"))
NUMREF_YEAR_MAX = int(get_env("NUMREF_YEAR_MAX", default="2100"))
NUMREF_STATIC_CHECK_ENABLED = get_env_bool("NUMREF_STATIC_CHECK_ENABLED", default=True)

# --- Verificação das conclusões por afirmações (v18.5-claim-verification, ADR 019 §6) ---
CLAIM_VERIFY_ENABLED = get_env_bool("CLAIM_VERIFY_ENABLED", default=True)
# Seções do relatório cujas conclusões são conferidas (títulos separados por vírgula; sem numeração).
CLAIM_VERIFY_SECTIONS = tuple(
    s.strip()
    for s in get_env(
        "CLAIM_VERIFY_SECTIONS",
        default="Resumo Executivo,Resultados,Análise das Divergências,Limitações Identificadas",
    ).split(",")
    if s.strip()
)
# Tamanho máximo (caracteres) do pacote de evidência de uma chamada; acima disso a conclusão é dividida em lotes.
CLAIM_EVIDENCE_MAX_CHARS = int(get_env("CLAIM_EVIDENCE_MAX_CHARS", default="12000"))
# Tolerância relativa de "aproximadamente", "próximo de" e "cerca de" na conferência determinística.
CLAIM_APPROX_REL_TOL = float(get_env("CLAIM_APPROX_REL_TOL", default="0.05"))
# Ciclos de correção do relatório pelo Summarizer (0 desliga).
CLAIM_REVISION_MAX_CYCLES = int(get_env("CLAIM_REVISION_MAX_CYCLES", default="1"))
if CLAIM_EVIDENCE_MAX_CHARS <= 0 or CLAIM_APPROX_REL_TOL < 0 or CLAIM_REVISION_MAX_CYCLES < 0:
    raise ValueError(
        "CLAIM_EVIDENCE_MAX_CHARS deve ser > 0 e CLAIM_APPROX_REL_TOL e CLAIM_REVISION_MAX_CYCLES, >= 0."
    )

# --- Registro de execuções encadeado por hash (v18.5-execution-provenance, ADR 019 §4) ---
# Cache SQLite dos hashes de arquivos grandes (chave: caminho, dispositivo, inode, tamanho, mtime_ns).
PROVENANCE_HASH_CACHE_PATH = get_env("PROVENANCE_HASH_CACHE_PATH", default="store/hash_cache.db")
# Tamanho mínimo (bytes) para um arquivo usar o cache de hash.
PROVENANCE_HASH_CACHE_MIN_BYTES = int(get_env("PROVENANCE_HASH_CACHE_MIN_BYTES", default="8388608"))


def require_locality_min_group_size() -> int:
    """Devolve ``LOCALITY_MIN_GROUP_SIZE`` ou falha de forma acionável quando não foi definido.

    Raises:
        RuntimeError: Se a variável não está definida (decisão do pesquisador; ver ``.env.example``).
    """
    if LOCALITY_MIN_GROUP_SIZE is None:
        raise RuntimeError(
            "LOCALITY_MIN_GROUP_SIZE não definida: o filtro de egresso precisa do tamanho mínimo de grupo (k) das "
            "estatísticas enviadas a modelos sem dados brutos (ADR 019 §3). Defina no .env, por exemplo "
            "LOCALITY_MIN_GROUP_SIZE=10 (veja .env.example)."
        )
    return LOCALITY_MIN_GROUP_SIZE


# Identificador estável deste computador (fator de independência, ADR 015 §9).
# Gerado uma vez e persistido em ~/.config/geminiclaw/node_id (ou $XDG_CONFIG_HOME).
_node_id_env = get_env("NODE_ID")
if _node_id_env:
    NODE_ID = _node_id_env
else:
    from src.utils.node_id import get_or_create_node_id
    NODE_ID = get_or_create_node_id()


from src.logger import get_logger

logger = get_logger(__name__)

for directory in [OUTPUT_BASE_DIR, LOGS_BASE_DIR]:
    try:
        if directory.startswith("/"):
             if not Path(directory).exists():
                 logger.warning(f"Diretório de volume {directory} não encontrado no container.")
             continue
        Path(directory).mkdir(parents=True, exist_ok=True)
    except PermissionError:
        if not Path(directory).exists():
            raise
