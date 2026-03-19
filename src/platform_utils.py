import sys

def is_mac() -> bool:
    """Verifica se o sistema operacional atual é Mac OS (Darwin)."""
    return sys.platform == "darwin"

def should_use_tcp_ipc() -> bool:
    """Decide se deve usar TCP para IPC em vez de Unix Sockets.
    
    No Mac OS, bind mounts de Unix Sockets entre host e containers 
    Docker não são suportados nativamente (Errno 95).
    """
    return is_mac()
