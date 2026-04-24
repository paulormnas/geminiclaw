"""Utilitários para formatação e exibição no terminal."""

# Códigos ANSI para cores e estilos
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"

# Cores
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Ícones de status
STATUS_ICONS: dict[str, str] = {
    "waiting": "⏳",
    "running": "🔄",
    "success": "✅",
    "error": "❌",
    "timeout": "⏰",
    "info": "ℹ️",
    "warning": "⚠️",
    "network": "🌐",
    "package": "📦",
    "search": "🔍",
    "find": "🔎",
}

# Versão e Banner
VERSION = "0.1.0"
BANNER = f"""{CYAN}{BOLD}
  ╔═══════════════════════════════════════╗
  ║          🔮 GeminiClaw v{VERSION}          ║
  ║   Framework de Orquestração de IA     ║
  ╚═══════════════════════════════════════╝
{RESET}"""

def color_text(text: str, color_code: str) -> str:
    """Aplica uma cor ao texto e reseta ao final.

    Args:
        text: O texto a ser colorido.
        color_code: O código ANSI da cor.

    Returns:
        O texto formatado com a cor.
    """
    return f"{color_code}{text}{RESET}"

def print_status(status: str, message: str, color: str = "") -> None:
    """Exibe uma mensagem com ícone de status.

    Args:
        status: Chave para o ícone em STATUS_ICONS.
        message: Mensagem a ser exibida.
        color: Cor opcional para a mensagem.
    """
    icon = STATUS_ICONS.get(status, "•")
    if color:
        print(f"  {icon} {color}{message}{RESET}")
    else:
        print(f"  {icon} {message}")
