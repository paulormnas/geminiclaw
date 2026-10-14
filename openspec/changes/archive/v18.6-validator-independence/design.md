# Design: v18.6-validator-independence

> **Nota (2026-10-13, `v18.6-remove-unused-agents`, #155):** os papéis `reviewer` e `base` citados abaixo como juiz e julgado foram removidos da regra. O juiz é só o `validator` e o julgado é só o `developer`; os pontos de conferência de despacho de `base`/`reviewer` e `check_dispatch` deixaram de existir. O texto abaixo é o histórico da proposta original; a verdade atual está em `openspec/specs/llm-providers/spec.md` e no ADR 020.

## 1. Conceitos

- **Juízes:** `validator`, `reviewer` (`JUDGE_ROLES`).
- **Julgados:** `developer`, `base` (`JUDGED_ROLES`).
- **Modelo efetivo:** o modelo que de fato atende uma chamada: resolvido, pin, dica aceita ou
  reserva do 429.
- **Família:** `ModelEntry.familia_modelo` do catálogo (linhagem de treinamento), com a origem
  (`versionado` ou `local`) registrada.

## 2. Modo efetivo

```python
def effective_judge_mode(env_value: str | None, data_policy: str) -> tuple[str, str]:
    """(modo, origem): valor explícito vence; sem ele, 'required' em third_party_allowed e 'preferred' em self_hosted_only."""
```

Valor inválido faz a inicialização falhar com mensagem que lista os valores aceitos.

## 3. Resolução na inicialização (`resolve_session`)

Ordem:

1. Papéis com pin (qualquer papel), na ordem do catálogo.
2. Julgados sem pin (`developer`, `base`), descartando as famílias dos juízes com pin.
3. Demais papéis sem pin, exceto juízes.
4. Juízes sem pin, descartando as famílias dos julgados resolvidos e mantendo o desempate do ADR
   019 §6 pelas famílias de `AUTHOR_ROLES`.

`resolve()` ganha o parâmetro `familias_proibidas: frozenset[str]` (separado de `familias_autor`,
que segue só para o desempate). O descarte usa `MOTIVO_MESMA_FAMILIA = "mesma_familia_julgamento"`
e vale também no ramo do pin.

Conflito entre dois pins (juiz e julgado da mesma família):

| `LLM_ROUTING` | Modo `required` | Modo `preferred` | Modo `off` |
|---|---|---|---|
| `strict` | `PinError` | pin do juiz mantido, `WARNING`, `atendida=false` | sem conferência |
| `flexible` | pin do juiz ignorado com `WARNING`; juiz pela preferência sem a família | igual a `required` se houver elegível; senão pin mantido com `atendida=false` | sem conferência |

Sem modelo elegível para o `validator` em `required`: `NoEligibleModelError` com a sugestão do ADR
020 §2; `_suggestion` (`routing.py:141-156`) ganha o ramo de `mesma_familia_julgamento`.

Na inicialização, todos os papéis **evitam** conflito (pulam as famílias proibidas quando há
alternativa na preferência), mas só o par `validator`/`developer` é exigência: sem alternativa,
`reviewer` e `base` ficam com o preferido e o conflito é tratado no despacho (§4). A tabela de pins
acima vale só para o par `validator`/`developer` (ADR 020 §4).

## 4. Conferência no despacho

`JudgeIndependenceGuard` (estado da sessão):

```python
class JudgeIndependenceGuard:
    def check(self, role: str, model_id: str, *, origem: str, subtarefa: str | None) -> Decision: ...
```

- Mantém as famílias efetivas em uso por juízes e por julgados.
- `check` é chamado ao aceitar dica (`apply_hint`, `src/orchestrator.py:1909`), ao despachar subtarefa
  para `base` ou `reviewer` e ao trocar para a reserva do 429 (`fallback_for`).
- Despacho de `base`/`reviewer` em conflito: primeiro tenta o próximo modelo elegível de outra
  família na preferência do papel (`substituido`); sem nenhum, aplica o modo. Um `base`/`reviewer`
  com pin só é substituído com `LLM_ROUTING=flexible`; com `strict` não tem alternativa e vai direto
  ao modo (ADR 020 §3).
- Decisões: `aceito`, `substituido`, `rejeitado` (dica volta ao modelo resolvido; reserva não é
  usada; despacho de `base`/`reviewer` em `required` falha **só a subtarefa** com
  `mesma_familia_julgamento` e a sugestão, e a sessão continua), `aceito_preferred` (modo `preferred`).
- Cada chamada grava o evento `independencia_julgamento`.

## 5. Registro

Payload da sessão:

```json
"independencia_julgamento": {
  "modo": "required", "origem_modo": "padrao_politica",
  "validator": {"modelo": "google/gemini-3.8-flash", "familia": "gemini", "origem_familia": "versionado"},
  "developer": {"modelo": "anthropic/claude-sonnet-5-5", "familia": "claude", "origem_familia": "versionado"},
  "atendida": true
}
```

Evento por conferência: `{papel, modelo, familia, origem, subtarefa, decisao, motivo}`.
Banner: uma linha "Julgamento: gemini (validator) ≠ claude (developer)" ou o aviso com
`atendida=false`. Relatório final: seção de metadados ganha a mesma linha. Métricas de operação:
`independencia_julgamento_atendida` e contagem de rejeições.

## 6. Egresso (para o Analista de Segurança)

A nova ordem do catálogo pode levar o juiz a um provedor de nuvem antes não usado. O envio continua
sujeito a `LLM_DATA_POLICY`, a `LLM_PROVIDER_PRIORITY` (lista de permissão) e ao `EgressGate`
(ADR 019 §3). Nada muda no que o juiz recebe.

### Parecer de segurança (STRIDE curto, 2026-10-13)

Escopo: efeito da nova ordem do catálogo e da regra R1 sobre o egresso e sobre a superfície de ataque.

| Ameaça | Avaliação | Mitigação / requisito |
|---|---|---|
| **Information disclosure** (juiz em provedor de nuvem antes não usado) | O catálogo só traz modelos de nuvem na preferência; sob `self_hosted_only` (padrão) a política os descarta antes de qualquer outra regra, então a mudança não abre egresso nessa política. Sob `third_party_allowed` o juiz pode ir a um provedor novo. | **Requisito S1:** a elegibilidade de um modelo de outra família continua passando por `_discard_reason` (política, lista `LLM_PROVIDER_PRIORITY`, disponibilidade); nenhum caminho de substituição, de despacho ou de reserva contorna esse filtro. **S2:** todo envio ao juiz segue pelo `EgressGate`/`GatedProvider` com o destino do modelo efetivo (inclusive o substituído). **S3:** o banner e o evento mostram o provedor/modelo escolhido. |
| **Tampering** (dica de plano gerada pelo LLM tenta trocar o juiz ou forçar família) | A dica já é superfície de injeção (ADR 017 §7). R1 só a restringe mais: dica na família do juiz é rejeitada; o juiz nunca muda no meio da sessão. | **S4:** a dica nunca altera o modelo de um juiz nem sobrepõe pin; `required` e `preferred` rejeitam a dica em conflito. |
| **Spoofing** (família declarada em `catalog.local.yaml`) | O operador pode declarar qualquer família; é confiança no operador, não ameaça externa. | **S5:** a origem da família (`versionado`/`local`) é registrada no payload (design §5). |
| **Repudiation** | Conferências e descartes não deixariam rastro sem registro. | **S6:** evento `independencia_julgamento` por conferência e `atendida` no payload; nenhum modo desliga a conferência em silêncio. |
| **Denial of service** (sessão não inicia em `required`) | Falha explícita e acionável é desejada (fail-fast); a instalação padrão usa `preferred`. | Mensagem com sugestão (`LLM_JUDGE_INDEPENDENCE=preferred`). |
| **Elevation of privilege** | Nenhuma: não há novo prompt, ferramenta, sandbox ou segredo; o juiz recebe o mesmo conteúdo. | Segredos continuam só em `.env`; os eventos não gravam credenciais nem texto de prompt. |

Conclusão: sem bloqueio. Os requisitos S1 a S6 passam a valer na implementação e nos testes.

## 7. Retomada

Na retomada, as famílias julgadas de todos os eventos `independencia_julgamento` da sessão original
e do payload são carregadas no `JudgeIndependenceGuard` antes de reverificar afirmações pendentes;
o juiz resolvido agora passa pela mesma conferência e pelo modo.

## 8. Avaliação de comunicação

`select_judge` (`scripts/benchmark/comm_judge.py:183-190`) exclui modelos das famílias de `developer`
e `base` da sessão avaliada (lidas do payload) e do modelo que perguntou; a família do Researcher é
desempate.

## 9. Análise de impacto nos 6 eixos

| Eixo | Impacto |
|---|---|
| Orquestrador e loop | Conferência no despacho; dica pode ser rejeitada |
| Agentes e prompts | Nenhum prompt muda |
| Sandbox | Nenhum |
| Persistência | Evento e campo de payload novos, sem schema |
| Segurança | Possível provedor novo para o juiz (§6) |
| Testes e telemetria | Rótulo de papel da revisão corrigido; testes do roteador puros |

## 10. Questões em aberto (decididas em 2026-10-13: dica descartada e padrão `preferred`; Claude segue primeiro no catálogo)

1. As duas divergências do ADR 020 (dica do Developer na família do juiz; padrão por política).
2. Ordem de preferência dos juízes no catálogo: manter Claude Sonnet primeiro (com o Developer em
   Gemini, como hoje) ou pôr Gemini/GPT primeiro para deixar Claude livre para dicas do Developer
   (divergência 1 do ADR 020).

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Instalações existentes param de iniciar | Padrão por política; mensagem acionável; `.env.example` com exemplo |
| Rótulo de telemetria muda e quebra relatórios por papel | Tarefa 6.2 confere consumidores (`report.py`, `communication.py`, métricas de operação) |
| Família declarada errada no catálogo local | Origem da família registrada e exibida |
