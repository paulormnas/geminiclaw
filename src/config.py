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

# --- Configuração LLM (V18) ---

# Provedor e modelo — novos
LLM_PROVIDER = get_env("LLM_PROVIDER", default="google")
LLM_MODEL = get_env("LLM_MODEL") or get_env("DEFAULT_MODEL", default="gemini-3.8-flash")
DEFAULT_MODEL = LLM_MODEL  # Retrocompatibilidade

# Model Router por papel (V14)
RESEARCHER_PROVIDER = get_env("RESEARCHER_PROVIDER", default="google")
RESEARCHER_MODEL = get_env("RESEARCHER_MODEL", default="gemini-3.8-flash")
VALIDATOR_PROVIDER = get_env("VALIDATOR_PROVIDER", default="ollama")
VALIDATOR_MODEL = get_env("VALIDATOR_MODEL", default="qwen3:8b")
DEVELOPER_PROVIDER = get_env("DEVELOPER_PROVIDER", default="google")
DEVELOPER_MODEL = get_env("DEVELOPER_MODEL", default="gemini-3.8-flash")

# Configurações Ollama
OLLAMA_BASE_URL = get_env("OLLAMA_BASE_URL", default="http://localhost:11434")
OLLAMA_NUM_CTX = int(get_env("OLLAMA_NUM_CTX", default="4096"))
OLLAMA_ENABLE_THINKING = get_env("OLLAMA_ENABLE_THINKING", default="false").lower() == "true"

# Google API key: obrigatória APENAS quando provider for google
GEMINI_API_KEY = get_env(
    "GEMINI_API_KEY",
    required=(LLM_PROVIDER == "google"),
)

# Modelo usado quando o principal do Google atinge o limite de requisições (HTTP 429). Vazio desliga o fallback.
GOOGLE_FALLBACK_MODEL = get_env("GOOGLE_FALLBACK_MODEL", default="gemini-3.7-flash")

# Configurações do provedor openai_compatible (V16) — servidores que falam o
# protocolo /v1/chat/completions (llama.cpp server, vLLM, LM Studio, serviços
# hospedados compatíveis). Nomes seguem o padrão já consagrado no ecossistema
# (vLLM, LM Studio, litellm), não o prefixo do nome do provedor no registro.
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

# Validação e rigor (Etapa V22)
STRICT_VALIDATION = get_env_bool("STRICT_VALIDATION", default=True)
if DEPLOYMENT_PROFILE == "pi5" or LLM_PROVIDER == "ollama":
    STRICT_VALIDATION = get_env_bool("STRICT_VALIDATION", default=False)

if DEPLOYMENT_PROFILE == "pi5":
    MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="5"))
    MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="2"))
    # No Pi 5, o Ollama local é o padrão se não especificado
    if not os.environ.get("LLM_PROVIDER"):
        LLM_PROVIDER = "ollama"
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

# --- Grafo de Conhecimento (Roadmap V17 / ADR 009, ADR 015) ---
# Nome do grafo Apache AGE (sem o nome do produto — ADR 011).
KNOWLEDGE_GRAPH_NAME = get_env("KNOWLEDGE_GRAPH_NAME", default="knowledge")
# DSN somente-leitura (papel `knowledge_reader`) usado por GraphStore.read_query
# (Curator, CLI). Obrigatória apenas quando o grafo é efetivamente utilizado —
# a leitura tardia em AgeGraphStore levanta erro explícito se ausente.
KNOWLEDGE_READER_DATABASE_URL = get_env("KNOWLEDGE_READER_DATABASE_URL")
KNOWLEDGE_READ_TIMEOUT_MS = int(get_env("KNOWLEDGE_READ_TIMEOUT_MS", default="5000"))
# Similaridade semântica mínima para um termo livre ser resolvido a um termo
# canônico do vocabulário controlado (faixa de duplicata, v17-controlled-vocabulary).
VOCAB_MATCH_THRESHOLD = float(get_env("VOCAB_MATCH_THRESHOLD", default="0.90"))

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
