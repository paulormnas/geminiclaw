# Design: Localidade, Família e Versão Efetiva dos Modelos no Catálogo

## 0. Estado atual (verificado no código em 2026-09-29)

| Ponto | Onde | Situação |
|---|---|---|
| Seleção por papel | `src/model_config.py:22-50`, `:80-81`; `src/model_router.py:26-67` | Mapa fixo papel → provedor/modelo por variável de ambiente. O catálogo `src/llm/catalog.yaml` e o roteador `resolve(...)` do ADR 017 **ainda não existem** em `dev`; esta mudança pressupõe que existam. |
| Criação de provedor | `src/llm/registry.py:102-127` | `ProviderSettings(name, model, base_url, api_key)`; nenhum dado de localidade. |
| Resposta do provedor | `src/llm/base.py:11-17` | `LLMResponse` sem versão do modelo; `model_name` (`:65-69`) é o nome pedido, não o servido. |
| OpenAI compatível | `src/llm/providers/openai_compatible.py:79-93` | Lê só `usage`; ignora `data["model"]` e `system_fingerprint`. |
| Google | `src/llm/providers/google.py:160-176` | Não lê `response.model_version`. |
| Ollama | `src/llm/providers/ollama.py:104-135` | `/api/chat` não devolve digest; `/api/tags` só é usado no `health_check`. |
| Telemetria por chamada | `src/llm/agent_loop.py:302-317`; `scripts/init_db.sql:154-171` | `token_usage` guarda `llm_provider` e `llm_model`; sem versão. |
| Banner e payload | `src/cli.py:729-760`; `src/orchestrator.py:312` | Banner mostra modo, contexto e orçamento; payload guarda `budget`. |
| Motivos de parada | `src/usage.py:25-31` | `StopReason` com tokens, tempo, retentativas, conexão. |

## 1. Campos novos do catálogo

```yaml
# src/llm/catalog.yaml (trecho; demais campos conforme ADR 017)
modelos:
  - id: ollama/qwen3:8b
    provedor: ollama
    trust: self_hosted
    localidade: no_no            # no_no | fora_do_no (padrão fora_do_no)
    aceita_dados_brutos: true    # implícito em no_no; declarar false aqui é erro
    familia_modelo: qwen
  - id: openai_compatible/llama-3.3-70b
    provedor: openai_compatible
    trust: self_hosted
    localidade: fora_do_no       # servidor de GPU da instituição
    aceita_dados_brutos: true    # declaração explícita do operador
    familia_modelo: llama
  - id: google/gemini-2.5-pro
    provedor: google
    trust: third_party
    familia_modelo: gemini       # localidade e aceita_dados_brutos nos padrões
```

Regras de validação (esquema estrito do ADR 017 §9; qualquer violação **para a
inicialização** com mensagem que cita o arquivo e o `id`):

| Regra | Resultado |
|---|---|
| `aceita_dados_brutos: true` com `trust: third_party` | erro |
| `localidade: no_no` com `trust: third_party` | erro |
| `localidade: no_no` com `aceita_dados_brutos: false` explícito | erro (declaração contraditória) |
| `localidade: no_no` sem `aceita_dados_brutos` | valor efetivo `true` |
| `familia_modelo` ausente, vazio ou fora de `^[a-z0-9][a-z0-9_-]*$` | erro |
| valor de `localidade` fora do enum | erro |

`catalog.local.yaml` continua só podendo **acrescentar** entradas (ADR 017 §8). Cada entrada
local com `aceita_dados_brutos` efetivo `true` gera um `WARNING` próprio, com o `id`, além do
aviso com o hash do arquivo.

**Coerência com o endpoint (não inferência):** na inicialização, para cada entrada elegível
com endpoint conhecido, o validador compara a `localidade` declarada com o host:

- loopback = `localhost`, `127.0.0.0/8`, `::1` ou socket Unix;
- `no_no` com host fora de loopback → `WARNING` ("declarada no nó, endpoint em `<host>`");
- `fora_do_no` com host em loopback → `WARNING` ("pode ser túnel ou proxy; mantida como
  declarada").

A declaração nunca é alterada pelo aviso. Provedores de nuvem (sem `base_url`) não são
checados.

## 2. Preferência com empate e desempate por família

A lista `preferencia` de cada papel (ADR 017 §2) passa a aceitar, em cada posição, um `id` ou
uma **lista de `id`s** (mesma posição):

```yaml
papeis:
  validator:                                # sem exigência de trust (ADR 017 §2, 2026-10-01)
    preferencia:
      - [ollama/qwen3:8b, ollama/gemma3:12b]   # mesma posição
      - google/gemini-3.8-flash
```

`resolve(papel, ...)` continua puro. Algoritmo para cada papel:

1. filtra por política, requisitos e lista de permissão (ADR 017 §5);
2. percorre as posições em ordem e para na primeira que tiver ao menos um elegível;
3. se a posição tiver mais de um elegível **e** o papel for `validator`, prefere os de
   `familia_modelo` diferente de todas as `familias_autor`; se nenhum for diferente, ou se o
   papel não for `validator`, usa a ordem da lista dentro da posição.

`familias_autor` = famílias resolvidas para os papéis que escrevem afirmações verificadas:
`researcher`, `developer`, `summarizer` e `curator` (`v18.5-claim-verification`). Por isso o
roteador resolve os papéis na ordem `planner, researcher, developer, reviewer, summarizer,
curator, base` e **por último** `validator`. Um modelo de outra família em posição inferior **nunca** substitui
o da primeira posição elegível. O pin `VALIDATOR_MODEL` (ADR 017 §7) tem precedência e
desliga o desempate.

A decisão é registrada em `allocation_profile.papeis.validator.desempate`:
`{"aplicado": bool, "familias_autor": [...], "candidatos": [...], "escolhido": "<id>"}`.

## 3. Perfil de alocação (`allocation_profile`)

Gravado em `agent_sessions.payload["allocation_profile"]` logo após a resolução, antes do
primeiro envio:

```json
{
  "catalogo": {"versao": "…", "hash": "sha256:…", "local_hash": null},
  "papeis": {
    "researcher": {"provedor_modelo": "google/gemini-2.5-pro", "trust": "third_party",
                   "localidade": "fora_do_no", "aceita_dados_brutos": false,
                   "familia_modelo": "gemini", "versao_efetiva": "gemini-2.5-pro-002"},
    "developer":  {"…": "…"},
    "validator":  {"…": "…", "desempate": {"…": "…"}}
  }
}
```

> **Nota de alinhamento (tarefa 0.b.1):** `v16-model-catalog-router` implementou o bloco `catalogo` como `{versao, hash, local: bool}` (`payload["llm_routing"]`); este design usa `local_hash`. Os dois precisam ser alinhados antes da implementação.


- `versao_efetiva` por papel começa com o valor conhecido no início (Ollama) ou
  `desconhecida`, e é atualizada com a primeira versão observada.
- Os valores são **como declarados** no catálogo (ADR 019 §1), com `aceita_dados_brutos`
  **efetivo** (após a regra do `no_no`).
- O banner (`print_session_banner`) ganha um bloco "Alocação" com uma linha por papel:
  `papel → provedor/modelo · trust · localidade · dados brutos: sim/não`.
- O relatório final e o registro da sessão leem o perfil deste payload; o aviso de perfil
  misto (§3.8 do ADR) é da mudança `v18.5-egress-gate`.

API pública para as demais mudanças (sem acesso direto ao YAML):

```python
# src/llm/allocation.py
@dataclass(frozen=True)
class RoleAllocation:
    papel: str
    provedor: str
    modelo: str
    trust: str                 # "self_hosted" | "third_party"
    localidade: str            # "no_no" | "fora_do_no"
    aceita_dados_brutos: bool  # valor efetivo
    familia_modelo: str
    versao_efetiva: str        # "desconhecida" até ser observada

def current_allocation(papel: str) -> RoleAllocation: ...
```

## 4. Versão efetiva por chamada

`LLMResponse` ganha `versao_efetiva: str = "desconhecida"`. Fonte por provedor:

| Provedor | Fonte | Momento |
|---|---|---|
| `google` | `response.model_version` do `google-genai` | cada chamada |
| `openai_compatible` | `data["model"]`; se houver `system_fingerprint`, `"<model>@<fingerprint>"` | cada chamada |
| `ollama` | `digest` do modelo em `GET /api/tags` | início da sessão (no health check do ADR 017 §4) e a cada gravação de checkpoint (`v18-research-continuity`); cada resposta usa o último digest conhecido |

Campo vazio, ausente ou não textual → `desconhecida`. O valor nunca é inventado a partir do
nome pedido.

**Registro:** `record_token_usage` recebe `versao_efetiva` e grava na coluna nova de
`token_usage`. O mesmo valor vai ao `egress_log` quando a `v18.5-egress-gate` existir.

**Mudança dentro da sessão:** um `VersionTracker` por sessão guarda a última versão por
`provedor/modelo`. Quando uma versão conhecida muda para outra (inclusive para
`desconhecida`):

- grava evento `versao_modelo_alterada` em `agent_events` (`payload_json` com papel,
  `provedor/modelo`, anterior, nova);
- acrescenta o evento a `payload["eventos_versao_modelo"]` e registra `WARNING`;
- o relatório final lista os eventos (leitura do payload).

**`LLM_ROUTING=strict`:** versão `desconhecida` após a primeira chamada de um papel, ou versão
alterada, marca `parada_pendente = "versao_modelo"`. O `AutonomousLoop` verifica essa marca no
mesmo ponto em que verifica os limites de uso (antes de cada despacho) e entra em
**fechamento** (checkpoint + Curator, como em `v18-usage-limits` §3), com
`motivo_parada="versao_modelo"` (novo valor de `StopReason`). A sessão pode ser retomada; na
retomada, o perfil é resolvido de novo e as versões são reavaliadas. Fora de `strict`, só há
evento e aviso.

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Ordem de resolução dos papéis; verificação de `parada_pendente` junto aos limites; novo `StopReason`. |
| Agentes & Prompts | Nenhum prompt muda. O Validator pode passar a usar outro modelo quando houver empate. |
| Sandboxes & Containers | Nenhum. |
| Persistência | Coluna `token_usage.versao_efetiva` (schema, exige aprovação); `allocation_profile` e `eventos_versao_modelo` no payload JSONB. |
| Segurança | Declarações novas e coerência validada; `aceita_dados_brutos` impossível com `third_party`; avisos para entradas locais que aceitam dados brutos. Base para a `v18.5-egress-gate`. |
| Testes & Telemetria | Versão efetiva por chamada; eventos de troca de versão; testes de esquema, roteador e provedores com respostas simuladas. |

## 6. Riscos e limites

- As declarações `localidade` e `aceita_dados_brutos` dependem do operador. O aviso de
  coerência com o endpoint reduz erros óbvios, mas não os impede (ADR 019 §1).
- A versão informada pelo provedor pode ser só um alias estável. O registro guarda o que o
  provedor informa; a garantia é "registrado como informado", não "imutável".
- No Ollama, uma troca de modelo entre dois checkpoints só é detectada no checkpoint seguinte.
