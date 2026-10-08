import os
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

# Carrega o arquivo .env se existir
load_dotenv()


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
# Lista de permissão de provedores (separados por vírgula). Vazio = padrão do perfil de deployment.
LLM_PROVIDER_PRIORITY = get_env("LLM_PROVIDER_PRIORITY", default="")
# Timeout (s) do health check de cada (provedor, modelo) no início da sessão.
LLM_HEALTH_CHECK_TIMEOUT_SECONDS = float(get_env("LLM_HEALTH_CHECK_TIMEOUT_SECONDS", default="5"))
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
GOOGLE_FALLBACK_MODEL = get_env("GOOGLE_FALLBACK_MODEL", default="gemini-3.7-flash")

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

# --- Perfil de Deployment (V18.1) ---
DEPLOYMENT_PROFILE = get_env("DEPLOYMENT_PROFILE", default="default")

if DEPLOYMENT_PROFILE == "pi5":
    MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="5"))
    MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="2"))
else:
    MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="10"))
    MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="3"))

# Prioridade para variável de ambiente explícita para o timeout do agente
env_timeout = get_env("AGENT_TIMEOUT_SECONDS")
if env_timeout is not None:
    AGENT_TIMEOUT_SECONDS = int(env_timeout)
else:
    # Fallback para perfil
    if DEPLOYMENT_PROFILE == "pi5":
        AGENT_TIMEOUT_SECONDS = None  # Infinito por padrão no Pi 5
    else:
        AGENT_TIMEOUT_SECONDS = 300   # Default 5min

# Limites de planejamento (Roadmap V4)
MAX_PLANNING_ITERATIONS = int(get_env("MAX_PLANNING_ITERATIONS", default="10"))
MAX_PLAN_RETRIES = int(get_env("MAX_PLAN_RETRIES", default="5"))

# Roadmap V16/ADR 014 — circuit breaker de execuções de agente por sessão.
# MAX_CONTAINERS_PER_SESSION (nome da época dos agentes em container) segue aceito como alias.
MAX_AGENT_RUNS_PER_SESSION = int(
    get_env("MAX_AGENT_RUNS_PER_SESSION") or get_env("MAX_CONTAINERS_PER_SESSION", default="30")
)
# Piso do limite de execuções de subtarefa; o limite efetivo cresce com o plano aprovado
# (v16-pipeline-robustness, design §5). Execuções de planejamento têm limite próprio.
MAX_PLANNING_RUNS_PER_SESSION = int(get_env("MAX_PLANNING_RUNS_PER_SESSION", default="20"))

# v16-pipeline-robustness — robustez do planejamento, da revisão e do disjuntor.
PLAN_NORMALIZER_ENABLED = get_env_bool("PLAN_NORMALIZER_ENABLED", default=True)
PLAN_REJECTION_STALL_LIMIT = int(get_env("PLAN_REJECTION_STALL_LIMIT", default="2"))
ARTIFACT_MATCH_MODE = get_env("ARTIFACT_MATCH_MODE", default="tolerant").lower()  # tolerant | strict
CIRCUIT_BREAKER_STALL_CYCLES = int(get_env("CIRCUIT_BREAKER_STALL_CYCLES", default="2"))

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
# UsageBudget/UsageTracker (src/usage.py) transformam estes limites em condições de
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
# Estratégia de OCR para imagens: 'local' (pytesseract) ou 'gemini' (Gemini Vision).
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
# openspec/changes/v17-knowledge-semantic-index). Coleção Qdrant com um ponto
# por nó vetorizável (ID do ponto = ID do nó) e limiares das faixas de
# similaridade. Os limiares dependem do modelo de embedding e são calibrados
# pelo pesquisador (`geminiclaw knowledge stats` apenas sugere ajustes).
KNOWLEDGE_COLLECTION = get_env("KNOWLEDGE_COLLECTION", default="knowledge_nodes")
SIM_DUPLICATE_MIN = float(get_env("SIM_DUPLICATE_MIN", default="0.90"))
SIM_RELATED_MIN_SAME_DOMAIN = float(get_env("SIM_RELATED_MIN_SAME_DOMAIN", default="0.70"))
SIM_RELATED_MIN_CROSS = float(get_env("SIM_RELATED_MIN_CROSS", default="0.60"))
SIM_CROSS_PROJECT_MIN_CONFIDENCE = float(get_env("SIM_CROSS_PROJECT_MIN_CONFIDENCE", default="0.30"))
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
SANDBOX_PIDS_LIMIT = int(get_env("SANDBOX_PIDS_LIMIT", default="256"))
SANDBOX_TMPFS_SIZE = get_env("SANDBOX_TMPFS_SIZE", default="256m")
SANDBOX_INSTALL_LOG_TAIL_LINES = int(get_env("SANDBOX_INSTALL_LOG_TAIL_LINES", default="40"))
# v18.5-sandbox-phases — fases de rede e dados do sandbox (ADR 019 §5).
SANDBOX_INSTALL_TIMEOUT_SECONDS = int(get_env("SANDBOX_INSTALL_TIMEOUT_SECONDS", default=str(CODE_SANDBOX_SETUP_TIMEOUT_SECONDS)))
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
PI_TEMPERATURE_LIMIT = float(get_env("PI_TEMPERATURE_LIMIT", default="75.0"))
PI_MIN_AVAILABLE_MEMORY_MB = float(get_env("PI_MIN_AVAILABLE_MEMORY_MB", default="512.0"))

# Memory (S4 + S5)
SKILL_MEMORY_ENABLED = get_env_bool("SKILL_MEMORY_ENABLED", default=True)
# LONG_TERM_MEMORY_DB removido (Roadmap V8): usa PostgreSQL via DATABASE_URL

# Human-in-the-Loop (Roadmap V15.3 / Spec G5)
SKILL_HUMAN_FEEDBACK_ENABLED = get_env_bool("SKILL_HUMAN_FEEDBACK_ENABLED", default=True)
# Limites operacionais monitorados a cada ciclo de planejamento (não-bloqueantes por padrão;
# apenas o modo 'assisted' pausa e pergunta se o pesquisador quer suspender a sessão).
# V18/usage-limits — os avisos agora são percentuais dos limites reais de UsageBudget
# (SESSION_MAX_TOKENS, SESSION_MAX_MINUTES), que passam a ser condições de parada
# (ver src/usage.py). session_duration_min (antigo, em minutos absolutos) vira alias:
# se definido, é convertido para percentual de SESSION_MAX_MINUTES.
_session_duration_min_env = get_env("OPERATIONAL_THRESHOLD_SESSION_DURATION_MIN")
if _session_duration_min_env is not None and SESSION_MAX_MINUTES:
    _session_duration_pct_default = float(_session_duration_min_env) / SESSION_MAX_MINUTES
else:
    _session_duration_pct_default = 0.5
OPERATIONAL_THRESHOLDS: dict[str, float] = {
    "token_usage_pct": float(get_env("OPERATIONAL_THRESHOLD_TOKEN_USAGE_PCT", default="0.80")),
    "cost_usd": float(get_env("OPERATIONAL_THRESHOLD_COST_USD", default="5.0")),
    "session_duration_pct": float(
        get_env(
            "OPERATIONAL_THRESHOLD_SESSION_DURATION_PCT",
            default=str(_session_duration_pct_default),
        )
    ),
    # OPERATIONAL_THRESHOLD_CONTAINER_COUNT_PCT (nome antigo) segue aceito como alias.
    "agent_runs_pct": float(
        get_env("OPERATIONAL_THRESHOLD_AGENT_RUNS_PCT")
        or get_env("OPERATIONAL_THRESHOLD_CONTAINER_COUNT_PCT", default="0.85")
    ),
}
# Alias de retrocompatibilidade: MAX_SESSION_TOKENS é o nome antigo de SESSION_MAX_TOKENS.
MAX_SESSION_TOKENS = SESSION_MAX_TOKENS
# Tempo que a CLI aguarda a resposta do pesquisador ao aviso de limite antes de continuar.
OPERATIONAL_THRESHOLD_WAIT_SECONDS = int(get_env("OPERATIONAL_THRESHOLD_WAIT_SECONDS", default="30"))
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

# Reviewer (V6.3)
REVIEW_ENABLED = get_env_bool("REVIEW_ENABLED", default=True)
REVIEW_MODE = get_env("REVIEW_MODE", default="per_subtask") # per_subtask | end_only | disabled

# Context Compression (V6.5)
CONTEXT_COMPRESSION_MODE = get_env("CONTEXT_COMPRESSION_MODE", default="truncate") # truncate | summarize

# Concurrency Control (V6.6)
MAX_LOCAL_LLM_CONCURRENT = int(get_env("MAX_LOCAL_LLM_CONCURRENT", default="2"))

# Triage
TRIAGE_MODE = get_env("TRIAGE_MODE", default="hybrid")
TRIAGE_CONFIDENCE_THRESHOLD = float(get_env("TRIAGE_CONFIDENCE_THRESHOLD", default="0.7"))

# --- Veredito de Evidência (Roadmap V17 / ADR 015 §9) ---
# Parâmetros calibráveis da equação de confiança usada por src/knowledge/verdict.py.
# Ver ADR 015 §9.8 para a tabela de referência e o significado de cada peso.
VERDICT_Q_VALIDATED_COMPLETE = float(get_env("VERDICT_Q_VALIDATED_COMPLETE", default="1.0"))
VERDICT_Q_VALIDATED_INCOMPLETE = float(get_env("VERDICT_Q_VALIDATED_INCOMPLETE", default="0.7"))
VERDICT_Q_DIVERGENT = float(get_env("VERDICT_Q_DIVERGENT", default="0.3"))
VERDICT_D_NEW_NODE_OR_DATASET = float(get_env("VERDICT_D_NEW_NODE_OR_DATASET", default="1.0"))
VERDICT_D_NEW_SESSION = float(get_env("VERDICT_D_NEW_SESSION", default="0.5"))
VERDICT_D_NEW_SEED = float(get_env("VERDICT_D_NEW_SEED", default="0.2"))
VERDICT_GAMMA = float(get_env("VERDICT_GAMMA", default="0.5"))
VERDICT_LAMBDA_AMBIGUOUS = float(get_env("VERDICT_LAMBDA_AMBIGUOUS", default="0.5"))
VERDICT_APPROACH_FAILURE_Q = float(get_env("VERDICT_APPROACH_FAILURE_Q", default="0.3"))
VERDICT_APPROACH_FAILURE_MIN_REPEATS = int(get_env("VERDICT_APPROACH_FAILURE_MIN_REPEATS", default="2"))
VERDICT_PRIOR = float(get_env("VERDICT_PRIOR", default="1.0"))
_verdict_thresholds_raw = get_env("VERDICT_THRESHOLDS", default="0.1,0.3,0.5")
VERDICT_THRESHOLDS: tuple[float, float, float] = tuple(
    float(x) for x in _verdict_thresholds_raw.split(",")
)  # type: ignore[assignment]

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
# Menor |veredito| que mantém os atalhos FUNCIONOU_PARA/FALHOU_PARA (a faixa "insuficiente" começa abaixo dele).
KNOWLEDGE_SHORTCUT_MIN_VERDICT = float(get_env("KNOWLEDGE_SHORTCUT_MIN_VERDICT", default="0.1"))
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
# Hipóteses executadas por ciclo nos modos `semi`/`auto` (as de maior prioridade); `assisted` executa as aprovadas.
HYPOTHESES_PER_CYCLE = max(int(get_env("HYPOTHESES_PER_CYCLE", default="2")), 1)
# Similaridade semântica a partir da qual uma hipótese nova reutiliza a existente do projeto.
HYPOTHESIS_DEDUP_SIMILARITY = float(get_env("HYPOTHESIS_DEDUP_SIMILARITY", default="0.90"))
# |veredito| a partir do qual a hipótese escolhida avalia a `Decisao` ("acertada"/"nao_acertada") e a hipótese
# passa a `validada`/`refutada`.
DECISION_EVAL_MIN_VERDICT = float(get_env("DECISION_EVAL_MIN_VERDICT", default="0.3"))
# Sugestões do Curator ao Researcher por ciclo.
CURATOR_MAX_SUGGESTIONS = max(int(get_env("CURATOR_MAX_SUGGESTIONS", default="3")), 0)
# Menor veredito de uma hipótese sobre o Problema para a solução ser considerada encontrada (evidência moderada).
SOLUTION_MIN_VERDICT = float(get_env("SOLUTION_MIN_VERDICT", default="0.3"))
# Ciclos de exploração por sessão (planejar -> executar -> consolidar -> sugerir): teto de iteração à prova de laço
# infinito, além dos limites de uso (tokens, tempo, retentativas, execuções) e do circuito de progresso zero.
MAX_EXPLORATION_CYCLES = max(int(get_env("MAX_EXPLORATION_CYCLES", default="20")), 1)
# Tamanho máximo (caracteres) dos textos de hipótese, decisão e sugestão aceitos do plano (recusa, não trunca) e
# quantidades máximas por plano.
HYPOTHESIS_TEXT_MAX_CHARS = int(get_env("HYPOTHESIS_TEXT_MAX_CHARS", default="1000"))
HYPOTHESES_MAX_PER_PLAN = int(get_env("HYPOTHESES_MAX_PER_PLAN", default="10"))
DECISIONS_MAX_PER_PLAN = int(get_env("DECISIONS_MAX_PER_PLAN", default="10"))

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
    from src.knowledge.ids import get_or_create_node_id
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
