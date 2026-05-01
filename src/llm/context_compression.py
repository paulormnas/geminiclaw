"""Módulo de compressão de contexto para o GeminiClaw.

Implementa compressão em 2 camadas: priorização por tipo e sumarização via LLM.
"""

import os
import json
from typing import List, Dict, Optional, Any, Tuple
from src.logger import get_logger

logger = get_logger(__name__)

# Prioridades de retenção (V6.5)
# Maior valor = maior prioridade (mantém mais tempo)
PRIORITY = {
    "system": 100,      # Nunca descartar
    "user": 90,         # Prompt original e comandos do usuário
    "assistant": 70,    # Respostas do agente
    "tool": 30,         # Resultados de ferramentas (muito verbosos)
}

def estimate_tokens(text: Any) -> int:
    """Estimativa rápida de tokens. Aproximação: 1 token ≈ 4 chars."""
    if isinstance(text, (dict, list)):
        text = json.dumps(text, ensure_ascii=False)
    return len(str(text)) // 4

def _get_priority(message: Dict[str, Any]) -> int:
    """Retorna a prioridade de uma mensagem baseada no seu papel."""
    role = message.get("role", "user")
    return PRIORITY.get(role, 50)

async def compress_messages(
    messages: List[Dict[str, Any]],
    max_tokens: int,
    system: Optional[str] = None,
    provider: Any = None, # LLMProvider opcional para sumarização
) -> List[Dict[str, Any]]:
    """Trunca ou sumariza o histórico preservando informação crítica.
    
    Estratégia V6.5:
    1. Camada 1: Priorização por tipo de mensagem.
    2. Camada 2: Sumarização via LLM se habilitado e necessário.
    """
    from src.config import CONTEXT_COMPRESSION_MODE
    
    if not messages:
        return []

    system_tokens = estimate_tokens(system or "")
    # Margem de segurança de 20%
    safety_margin = max_tokens // 5
    budget = max_tokens - system_tokens - safety_margin

    if budget <= 10: # Budget muito baixo, mantém apenas a última
        return [messages[-1]]

    # Separa mensagens por prioridade
    total_tokens = sum(estimate_tokens(m) for m in messages)
    
    if total_tokens <= budget:
        return messages

    # Se estiver em modo summarize e houver budget suficiente para uma chamada
    if CONTEXT_COMPRESSION_MODE == "summarize" and provider and budget > 100:
        return await _summarize_old_context(messages, budget, provider)
    
    # Caso contrário, fallback para truncagem inteligente
    return _truncate_by_priority(messages, budget)

def _truncate_by_priority(messages: List[Dict[str, Any]], budget: int) -> List[Dict[str, Any]]:
    """Truncagem inteligente baseada em prioridade de trás para frente."""
    kept = []
    
    # Sempre mantemos a última mensagem
    last_msg = dict(messages[-1]) # Cópia para não alterar original
    last_msg_tokens = estimate_tokens(str(last_msg))
    
    if last_msg_tokens > budget:
        # Se a última mensagem sozinha estoura o budget, trunca ela (bruto)
        content = last_msg.get("content", "")
        if isinstance(content, str):
            last_msg["content"] = content[:budget * 4] + "... [truncado]"
        return [last_msg]

    current_budget = budget - last_msg_tokens
    
    # Percorre o resto do histórico (inverso)
    for msg in reversed(messages[:-1]):
        tokens = estimate_tokens(str(msg))
        priority = _get_priority(msg)
        
        # Heurística: se for baixa prioridade e o budget está acabando, descarta antes
        if priority <= 30 and current_budget < (budget * 0.3):
            continue
            
        if current_budget - tokens >= 0:
            kept.insert(0, msg)
            current_budget -= tokens
        else:
            # Se for alta prioridade (user), tentamos manter mesmo que estoure um pouco?
            # Não, limite é limite.
            break
            
    return kept + [last_msg]

async def _summarize_old_context(
    messages: List[Dict[str, Any]], 
    budget: int, 
    provider: Any
) -> List[Dict[str, Any]]:
    """Divide o contexto e sumariza a parte descartada."""
    # Mantém os últimos 40% do budget para mensagens brutas (mensagens recentes)
    recent_budget = int(budget * 0.4)
    old_budget = budget - recent_budget
    
    # Divide mensagens
    recent_messages = []
    old_messages = []
    
    curr_recent_tokens = 0
    for msg in reversed(messages):
        t = estimate_tokens(str(msg))
        if curr_recent_tokens + t <= recent_budget:
            recent_messages.insert(0, msg)
            curr_recent_tokens += t
        else:
            # O resto vai para "old" para ser sumarizado
            # Mas limitamos o "old" também para não sobrecarregar o sumarizador
            old_messages.insert(0, msg)
    
    if not old_messages:
        return recent_messages

    # Sumariza mensagens antigas
    logger.info(f"Sumarizando {len(old_messages)} mensagens antigas para comprimir contexto")
    
    summary_prompt = (
        "Resuma as interações anteriores deste agente de IA, focando em: "
        "1. Descobertas de pesquisa feitas.\n"
        "2. Decisões tomadas.\n"
        "3. Erros encontrados e resolvidos.\n"
        "Seja extremamente conciso. Responda em português brasileiro."
    )
    
    try:
        # Usamos o provider passado para gerar o resumo
        # Nota: Idealmente usar um modelo rápido/barato para isso
        summary_resp = await provider.generate(
            messages=[
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": f"Histórico a sumarizar:\n{json.dumps(old_messages, ensure_ascii=False)}"}
            ],
            max_tokens=500
        )
        
        summary_text = summary_resp.text or "Histórico anterior processado."
        summary_msg = {
            "role": "system", 
            "content": f"[RESUMO DO HISTÓRICO ANTERIOR]: {summary_text}"
        }
        
        return [summary_msg] + recent_messages
    except Exception as e:
        logger.warning(f"Falha na sumarização de contexto: {e}, caindo para truncagem")
        return _truncate_by_priority(messages, budget)
