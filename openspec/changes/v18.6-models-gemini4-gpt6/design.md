# Design: v18.6-models-gemini4-gpt6

## 1. Fontes dos dados (conferidos em 2026-10-14)

| Modelo | ID | Preço por 1M tokens (entrada / saída / cache) | Fonte |
|---|---|---|---|
| Gemini 4 Argon | `gemini-4-argon` | US$ 2,00 / 10,00 / 0,10 até 2026-11-30; US$ 4,00 / 20,00 / 0,20 a partir de 2026-12-01 | ai.google.dev/gemini-api/docs/pricing |
| GPT-6.1 Sol | `gpt-6.1-sol` | Standard ≤ 272K: 2,00 / 10,00 / 0,10; > 272K: 4,00 / 15,00 / 0,20 | developers.openai.com/api/docs/pricing |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2,00 / 10,00 / 0,20 (já na tabela) | platform.claude.com/docs/en/about-claude/pricing |
| Claude Haiku 5.5 | `claude-haiku-5-5` | já na tabela | idem |

Os quatro IDs aparecem nas listas de modelos das contas (API de cada provedor, lida no Pi). `gpt-6-sol` também existe, mas
`gpt-6.1-sol` é o mais novo da linha com o mesmo preço de lista e metade do preço de cache.

## 2. Catálogo versão 5

Remover `google/gemini-3.8-flash` e `openai/gpt-5.6-terra`; incluir `google/gemini-4-argon` (`familia_modelo: gemini`,
`janela_contexto: 1048576`, ferramentas e saída estruturada) e `openai/gpt-6.1-sol` (`familia_modelo: gpt`,
`janela_contexto: 1050000`). As listas de preferência por papel trocam um pelo outro na mesma posição, preservando a regra
do ADR 020 (uma família de cada nas listas do `validator`). O número `versao` do catálogo sobe para 5, e o validador de
catálogo local continua recusando ID desconhecido.

## 3. Preço com vigência

```python
@dataclass(frozen=True)
class Price:
    input: float; output: float; cached_input: float
    long_threshold: int | None = None; long_price: "Price | None" = None
    promo_until: date | None = None      # último dia (UTC) do preço promocional
    after_promo: "Price | None" = None   # preço a partir do dia seguinte
```

`estimate_cost` escolhe o preço pela data UTC da chamada. `gemini-4-argon` declara `promo_until = 2026-11-30` e
`after_promo = Price(4.0, 20.0, 0.20)`. Uma chamada depois da vigência sem `after_promo` usa o preço promocional e emite
`WARNING` (nunca inventa preço). `LLM_PRICING_OVERRIDES` continua vencendo.

## 4. Versão dos modelos no benchmark

Origem do dado: `Session.payload["allocation_profile"]["papeis"][<papel>]` (`provedor_modelo`, `familia_modelo`,
`versao_efetiva`), que o orquestrador atualiza quando o provedor informa a versão (`src/orchestrator.py`, sink de versões).
O runner lê esse payload ao fim da execução e grava, em cada resultado:

```json
"modelos": {
  "developer": {"pedido": "google/gemini-4-argon", "familia": "gemini", "versao_efetiva": "gemini-4-argon-..."},
  "validator": {"pedido": "anthropic/claude-sonnet-5-5", "familia": "claude", "versao_efetiva": "desconhecida"}
},
"precos": {"google/gemini-4-argon": {"entrada": 2.0, "saida": 10.0, "cache": 0.1, "vigencia_ate": "2026-11-30"}},
"data_execucao": "2026-10-15"
```

`versao_efetiva` é o literal `desconhecida` quando o provedor não informa (regra de `src/llm/versions.py`); nunca se deduz do
nome pedido. `desconhecida` entra no placar como aviso `versao_desconhecida` (não é erro nem anomalia de parada). O
relatório ganha a tabela "Modelos e versões" por combinação, com a data e os preços; o relatório de comparação entre
rodadas passa a avisar quando a mesma combinação teve versões efetivas diferentes.

## 5. Orçamento

`budget_usd` já é um mapa por provedor, avaliado antes de cada execução (`run_benchmark.py:577-598`). A matriz passa a
declarar `anthropic`, `openai` e `google` com US$ 14 cada. Uma combinação mista soma o gasto de cada provedor no seu próprio teto.

## 6. Qdrant compartilhado

O reset apaga as coleções do sistema (`geminiclaw_documents`, `geminiclaw_knowledge` e `KNOWLEDGE_COLLECTION`) do Qdrant
alvo (`reset_stores._drop_qdrant`). As coleções são criadas de novo sob demanda: o índice semântico por
`SemanticIndex.ensure_collection()` e os indexadores de documentos por `_ensure_collection()`. Esta mudança só acrescenta o
teste que prova isso e remove a ambiguidade da spec ("recriar" o banco, "apagar" as coleções). As coleções de desenvolvimento
do mesmo Qdrant também são apagadas quando `BENCHMARK_QDRANT_URL` é igual a `QDRANT_URL`; o pesquisador aceitou
(2026-10-14), pois o ambiente é de desenvolvimento.

## 7. Impacto nos 6 eixos

| Eixo | Efeito |
|---|---|
| Arquitetura | Nenhum contrato novo; `Price` ganha dois campos opcionais; resultados do benchmark ganham campos aditivos. |
| Segurança | Os dois modelos são `third_party`, como os que substituem; a política `self_hosted_only` os descarta igual. Sem segredo novo. |
| Dados | Nenhuma mudança de schema. O JSON de resultados antigos continua legível (campos novos ausentes). |
| Desempenho | Argon é modelo de raciocínio: latência e tokens de saída maiores que o Flash; medir na matriz. |
| Custo | Argon custa cerca de 2,7× o 3.8 Flash na entrada e na saída; promoção até 2026-11-30. Teto de US$ 14 por provedor. |
| Testabilidade | Sem chamada paga: provedores simulados e relógio injetado nos cenários. |

## 8. Segurança

Sem superfície nova de egresso: os provedores e a política de dados são os mesmos; o runner continua sem imprimir chaves. A
tabela "Modelos e versões" não inclui URL nem credencial.

## 9. Riscos e mitigações

- **Preço sobe em 2026-12-01:** a vigência é explícita e o relatório mostra a data e o preço aplicado.
- **Provedor não informa a versão:** registrada como `desconhecida`, com aviso; a reprodutibilidade fica sinalizada, não escondida.
- **Argon mais caro/lento que o esperado:** o teto de US$ 14 por provedor interrompe a matriz; a combinação afetada fica `skipped` com o motivo.

## 10. Questões em aberto

1. **Esforço de raciocínio do Gemini 4 Argon:** o provedor Google não configura `thinking` hoje. Adotado: usar o padrão do
   provedor e medir; se o custo de saída (tokens de raciocínio) estourar, abrir mudança própria com um `GOOGLE_THINKING_*`.
2. **Escolha do `gpt-6.1-sol`** em vez do `gpt-6-astra` (5× o preço) ou do `gpt-6-luna` (já no catálogo, barato demais para
   Validator): adotado o Sol, a confirmar pelo pesquisador na aprovação.
