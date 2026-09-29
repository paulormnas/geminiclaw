# Design: Provedor Anthropic

## Restrições dos modelos atuais que moldam o desenho

Válidas para `claude-sonnet-5-5` (e a família Opus 5.x), conforme a documentação da API:

| Restrição | Consequência no provedor |
|---|---|
| Parâmetros de amostragem (`temperature`, `top_p`, `top_k`) com valor não padrão retornam 400 | O `temperature` do contrato `LLMProvider` é ignorado; a qualidade é controlada por `effort`. |
| Raciocínio adaptativo por omissão; `thinking: {type: "disabled"}` retorna 400 | Nunca enviamos `thinking`. |
| `tool_choice` `any`/`tool` retorna 400 | Nunca enviamos `tool_choice` (padrão `auto`). |
| O pensamento conta em `max_tokens` | `max_tokens` tem piso de 16.000 (também o teto recomendado para chamadas sem streaming). |
| Blocos de pensamento são assinados e devem voltar intactos no ciclo de ferramentas | Guardados em `LLMResponse.provider_data` e reenviados (ver abaixo). |
| Esforço padrão `high`; `medium` é o ponto de partida para agentes com ferramentas | `ANTHROPIC_EFFORT=medium`, ajustável. |
| Pedidos podem ser recusados por classificadores (`stop_reason: "refusal"`) | Recusa vira `ProviderRefusalError`; fallback do servidor ligado por padrão. |

## Conversão do histórico

O laço do agente mantém o histórico no formato OpenAI. O provedor converte a cada chamada:

- mensagens `system` viram o parâmetro `system` (sem duplicar o `system` recebido);
- mensagens `tool` e `user` consecutivas formam **um** turno `user`, com os `tool_result` antes do
  texto (exigência da API), em vez de vários turnos;
- ferramentas em formato OpenAI viram `{name, description, input_schema}`;
- mensagens vazias são omitidas (a API rejeita blocos de texto vazios).

## Blocos de pensamento (`provider_data`)

A resposta guarda, em `provider_data["content"]`, os blocos na ordem original com apenas os campos
que a API aceita de volta (`text`, `thinking` + `signature`, `redacted_thinking`, `tool_use`).
`LLMResponse.to_message()` inclui esse campo no histórico. Ao reconstruir o turno do assistente, o
provedor só reutiliza os blocos guardados se o texto e os ids de `tool_use` ainda coincidem com a
mensagem: a compressão de contexto pode reescrever o histórico, e blocos de pensamento de um turno
editado invalidariam a requisição. Se não coincidirem, usa o turno reconstruído sem pensamento.

Quando o fallback do servidor responde em outro modelo (bloco `fallback` no conteúdo), os blocos de
pensamento pertencem a ele e não são guardados.

## Retentativas e telemetria

O cliente é criado com `max_retries=0` e o provedor faz a retentativa (erro de conexão, 429 e 5xx,
com o backoff de `src/llm/retry.py`), emitindo `connection_retry` a cada uma. É esse evento que o
`UsageTracker` (V18) conta contra `SESSION_MAX_CONNECTION_RETRIES`; com as retentativas do SDK, elas
ficariam invisíveis.

## Segurança

- A chave vem só de `ANTHROPIC_API_KEY` (`.env`); nunca aparece em log nem em `repr()`.
- Sem chave, a criação do provedor falha com mensagem acionável (fail-fast), não na importação.
- O `anthropic` é dependência opcional; sem o extra, só a criação desse provedor falha.

## Riscos

- **Não validado contra a API real na suíte automática** (sem chave). Mitigação: SDK simulado nos
  testes e validação manual pelo pesquisador; o `health_check()` consulta o modelo.
- **Fallback do servidor** usa cabeçalho beta (`server-side-fallback-2026-07-01`). Se a API o rejeitar,
  `ANTHROPIC_REFUSAL_FALLBACK=false` o desliga sem alterar código.
- **Nome do modelo** definido pelo pesquisador (`claude-sonnet-5-5`); um id inválido retorna 404 do
  provedor na primeira chamada.
