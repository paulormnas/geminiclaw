"""Módulo de compressão de contexto para o GeminiClaw.

Implementa compressão em 2 camadas: priorização por tipo e sumarização via LLM.
"""

from typing import Any, Dict, List, Optional

from src.egress.fragments import (
    ContentOrigin,
    PromptFragment,
    dumps_messages,
    labeled,
    message_to_fragments,
    truncate_message,
)
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
        text = dumps_messages(text)
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
        # Se a última mensagem sozinha estoura o budget, trunca ela (bruto), mantendo a origem dos trechos
        # que sobram (v18.5-egress-gate: a camada de saída lê os trechos, não o ``content``).
        return [truncate_message(last_msg, budget * 4)]

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
        import time as _time

        from src.llm.metering import record_llm_call

        _t0 = _time.monotonic()
        # O histórico vai como trechos que mantêm a origem de cada mensagem: a camada de saída reaplica as regras
        # de egresso ao destino do resumo (v18.5-egress-gate, ADR 019 §3.8).
        history_fragments: list[PromptFragment] = [
            PromptFragment("Histórico a sumarizar:", ContentOrigin.INSTRUCAO, source="compressao")
        ]
        for old in old_messages:
            label = f"[{old.get('role', 'user')}{' ' + old['name'] if old.get('name') else ''}]"
            history_fragments.append(PromptFragment(label, ContentOrigin.INSTRUCAO, source="compressao"))
            history_fragments.extend(message_to_fragments(old))
        summary_resp = await provider.generate(
            messages=[
                labeled("system", PromptFragment(summary_prompt, ContentOrigin.INSTRUCAO, source="compressao")),
                labeled("user", *history_fragments),
            ],
            max_tokens=500
        )
        record_llm_call(provider, summary_resp, int((_time.monotonic() - _t0) * 1000), "context_compression")
        
        summary_text = summary_resp.text or "Histórico anterior processado."
        summary_msg = labeled(
            "system",
            PromptFragment(
                f"[RESUMO DO HISTÓRICO ANTERIOR]: {summary_text}",
                ContentOrigin.INSTRUCAO,
                tainted=bool(getattr(summary_resp, "tainted", False)),
                produced_by=getattr(summary_resp, "produced_by", None) or None,
                source="resumo_compressao",
            ),
        )
        
        return [summary_msg] + recent_messages
    except Exception as e:
        logger.warning(f"Falha na sumarização de contexto: {e}, caindo para truncagem")
        return _truncate_by_priority(messages, budget)
