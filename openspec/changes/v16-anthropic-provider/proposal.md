# Proposta: Provedor Anthropic (Claude)

**ID:** `v16-anthropic-provider` · **Versão:** V16 · **Capacidade:** `llm-providers`
**ADRs de origem:** [ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md)
**Depende de:** `v16-provider-registry` (já integrada)

## Por quê

O `v16-provider-registry` deixou o provedor nativo Anthropic explicitamente "para depois, pelo
mesmo registro". O pesquisador quer usar o Claude Sonnet 5.5 nos papéis de pesquisa e validação,
mantendo o Gemini no papel de desenvolvimento, e para isso o registro precisa de um provedor
`anthropic`.

## O que muda

- **Novo:** `src/llm/providers/anthropic.py` (`AnthropicProvider`) sobre o SDK oficial
  `anthropic`, registrado como `anthropic` em `src/llm/providers/__init__.py`.
- **Novo:** extra opcional `anthropic` no `pyproject.toml`; importação preguiçosa, como o `google`.
- **Modificado:** `LLMResponse` ganha o campo opaco `provider_data`, que o provedor usa para
  receber de volta no histórico os blocos de pensamento assinados. Os demais provedores o ignoram.
- **Novo em `src/config.py` e `.env.example`:** `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`,
  `ANTHROPIC_EFFORT` e `ANTHROPIC_REFUSAL_FALLBACK`; e os papéis `BASE_*`, `SUMMARIZER_*` e
  `REVIEWER_*`, que já existiam no código e não estavam documentados.
- **Sem mudança:** `src/llm/factory.py`, `src/model_router.py` e `src/model_config.py` (o roteamento
  por papel e o registro já bastam).

## Impacto

- **Código:** `src/llm/base.py`, `src/llm/providers/`, `src/config.py`.
- **Dependência:** `anthropic` (extra opcional), com `httpx2` e outras transitivas no `uv.lock`.
- **Custo:** chamadas ao Claude são pagas e dependem de `ANTHROPIC_API_KEY`; o teste real fica com o
  pesquisador (a suíte automática usa um SDK simulado e não acessa a rede).
