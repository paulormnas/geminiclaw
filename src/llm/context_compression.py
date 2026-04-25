# src/llm/context_compression.py
# Roadmap V4 - Etapa V21.1

def estimate_tokens(text: str) -> int:
    """Estimativa rápida de tokens sem tokenizer. Aproximação: 1 token ≈ 4 chars.
    
    Esta estimativa é conservadora (superestima levemente em português) para 
    evitar estourar o limite de contexto do Ollama no Pi 5.
    """
    return len(str(text)) // 4

def compress_messages(
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
) -> list[dict]:
    """Trunca o histórico preservando: system prompt + mensagens recentes.

    Estratégia:
    1. Sempre preservar: system prompt (se houver) + última mensagem do usuário.
    2. Preservar mensagens recentes de trás para frente até atingir o budget.
    3. Descartar mensagens antigas do meio/início da conversa se necessário.
    
    Args:
        messages: Lista de mensagens no formato {"role": "...", "content": "..."}.
        max_tokens: Limite máximo de tokens permitido (ex: OLLAMA_NUM_CTX).
        system: String opcional do system prompt.
        
    Returns:
        Lista de mensagens truncada e segura para inferência.
    """
    if not messages:
        return []

    system_tokens = estimate_tokens(system or "")
    # Margem de segurança de 25% ou 500 tokens para a resposta do modelo
    safety_margin = min(500, max_tokens // 4)
    budget = max_tokens - system_tokens - safety_margin

    if budget <= 0:
        # Budget insuficiente até para o system prompt, mantém apenas a última mensagem
        return [messages[-1]]

    # Sempre incluir a última mensagem (é a mais importante para a continuidade)
    last_msg = messages[-1]
    last_msg_tokens = estimate_tokens(last_msg.get("content", ""))
    
    if last_msg_tokens > budget:
        # Se a última mensagem sozinha estoura o budget, trunca ela (bruto)
        # 1 token ≈ 4 chars, então mantemos budget * 4 caracteres
        content = last_msg.get("content", "")
        last_msg["content"] = content[:budget * 4] + "... [truncado]"
        return [last_msg]

    remaining_budget = budget - last_msg_tokens
    kept_history = []

    # Adicionar mensagens mais recentes primeiro (percorrendo de trás para frente)
    # Ignora a última que já foi incluída
    for msg in reversed(messages[:-1]):
        tokens = estimate_tokens(str(msg))
        if remaining_budget - tokens > 0:
            kept_history.insert(0, msg)
            remaining_budget -= tokens
        else:
            # Histórico antigo descartado por falta de espaço
            break

    return kept_history + [last_msg]
