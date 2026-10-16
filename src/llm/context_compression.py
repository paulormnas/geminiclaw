"""Módulo de compressão de contexto para o GeminiClaw.

Implementa compressão em 2 camadas: priorização por tipo e sumarização via LLM.
"""

from typing import Any, Dict, List, Optional

from src.logger import get_logger
from src.utils.egress_fragments import (
    ContentOrigin,
    PromptFragment,
    dumps_messages,
    labeled,
    message_to_fragments,
    truncate_message,
)

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

def _tool_call_ids(message: Dict[str, Any]) -> list[str]:
    """IDs das chamadas de ferramenta de uma mensagem do assistente (vazio nas demais)."""
    if message.get("role") != "assistant":
        return []
    return [str(tc.get("id")) for tc in (message.get("tool_calls") or []) if isinstance(tc, dict) and tc.get("id")]


def _blocks(messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Agrupa o histórico em blocos atômicos: o assistente com ``tool_calls`` e as respostas de ferramenta que o seguem.

    Descartar só uma das pontas deixa uma resposta de ferramenta sem a chamada (a API Responses e o chat da OpenAI
    recusam com 400, "No tool call found for function call output"; observado no benchmark de 2026-10-12).
    """
    blocks: List[List[Dict[str, Any]]] = []
    for message in messages:
        if message.get("role") == "tool" and blocks and _tool_call_ids(blocks[-1][0]):
            blocks[-1].append(message)
        else:
            blocks.append([message])
    return blocks


def drop_orphan_tool_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove respostas sem a chamada correspondente e chamadas sem resposta (rede de segurança)."""
    open_ids: set[str] = set()
    answered: set[str] = set()
    for message in messages:
        open_ids.update(_tool_call_ids(message))
        if message.get("role") == "tool" and str(message.get("tool_call_id")) in open_ids:
            answered.add(str(message.get("tool_call_id")))
    kept: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages:
        ids = _tool_call_ids(message)
        if ids:
            if not all(i in answered for i in ids):
                continue  # chamada sem resposta (ou meio-respondida): sai o bloco inteiro
            seen.update(ids)
        elif message.get("role") == "tool" and str(message.get("tool_call_id")) not in seen:
            continue
        kept.append(message)
    return kept or messages[-1:]


async def _compress_messages(
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

    if budget <= 10: # Budget muito baixo, mantém apenas a última (com a chamada de ferramenta que ela responde)
        return _blocks(messages)[-1]

    # Separa mensagens por prioridade
    total_tokens = sum(estimate_tokens(m) for m in messages)
    
    if total_tokens <= budget:
        return messages

    # Se estiver em modo summarize e houver budget suficiente para uma chamada
    if CONTEXT_COMPRESSION_MODE == "summarize" and provider and budget > 100:
        return await _summarize_old_context(messages, budget, provider)
    
    # Caso contrário, fallback para truncagem inteligente
    return _truncate_by_priority(messages, budget)

async def compress_messages(
    messages: List[Dict[str, Any]],
    max_tokens: int,
    system: Optional[str] = None,
    provider: Any = None,
) -> List[Dict[str, Any]]:
    """Trunca ou sumariza o histórico preservando informação crítica e os pares chamada/resposta de ferramenta."""
    result = await _compress_messages(messages, max_tokens, system, provider)
    return result if result is messages else drop_orphan_tool_messages(result)


def _truncate_by_priority(messages: List[Dict[str, Any]], budget: int) -> List[Dict[str, Any]]:
    """Truncagem inteligente baseada em prioridade de trás para frente, em blocos atômicos de chamada de ferramenta."""
    blocks = _blocks(messages)
    last_block = [dict(m) for m in blocks[-1]]  # cópia para não alterar o original
    last_tokens = sum(estimate_tokens(str(m)) for m in last_block)

    if last_tokens > budget:
        # Se o último bloco sozinho estoura o budget, trunca a última mensagem dele (bruto), mantendo a origem dos
        # trechos que sobram (v18.5-egress-gate: a camada de saída lê os trechos, não o ``content``).
        other = sum(estimate_tokens(str(m)) for m in last_block[:-1])
        return last_block[:-1] + [truncate_message(last_block[-1], max(budget - other, 1) * 4)]

    current_budget = budget - last_tokens
    kept: List[List[Dict[str, Any]]] = []

    # Percorre o resto do histórico (inverso)
    for block in reversed(blocks[:-1]):
        tokens = sum(estimate_tokens(str(m)) for m in block)
        priority = _get_priority(block[0])

        # Heurística: se for baixa prioridade e o budget está acabando, descarta antes
        if priority <= 30 and current_budget < (budget * 0.3):
            continue

        if current_budget - tokens >= 0:
            kept.insert(0, block)
            current_budget -= tokens
        else:
            break  # limite é limite

    return [m for block in kept for m in block] + last_block


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
