# ADR 011 — Provedores Agnósticos: Registro de Provedores LLM e de Embeddings

**Status:** Aceito em 2026-10-01 (aprovado pelo pesquisador responsável; decisão implementada, texto atualizado na mesma data). A seleção de modelos por papel segue pelo catálogo do ADR 017, ainda pendente
**Data:** 2026-09-28 (revisado em 2026-10-01)
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Substitui:** ADR 006 (a partir de 2026-10-01)
**ADRs relacionados:** ADR 007 (Model Router por papel), ADR 009 (conhecimento), ADR 013 (federação), ADR 017 (catálogo e roteador), ADR 019 (localidade dos dados)

---

## Contexto

O projeto começou com o Google Agent Development Kit (ADK). Com a evolução, o próprio código
substituiu o ADK por uma classe `Agent` interna (`agents/base/agent.py`) e por uma camada
própria de provedores LLM (`src/llm/`). O projeto deve ser **agnóstico a provedor** e não
depender do SDK de agentes do Google.

Levantamento do estado atual (2026-09-28):

- **`google-adk` é dependência morta:** listado no extra opcional `google` do `pyproject.toml`,
  mas nenhum arquivo o importa. Apenas `google.genai` (cliente da API Gemini) é usado, e só em
  `src/llm/providers/google.py`.
- **A interface já é agnóstica:** `LLMProvider` (`src/llm/base.py`) usa formato de tool call no
  estilo OpenAI.
- **Mas a seleção de provedor está duplicada e fechada:** existem dois blocos `if/elif`
  independentes (`src/llm/factory.py` e `src/model_router.py`). Adicionar um provedor exige
  editar ambos.
- **Só há dois provedores:** Google e Ollama. *(Superado: ver "Estado em 2026-10-01".)*
- **Embeddings não são abstraídos:** o modelo local (`all-MiniLM-L6-v2`) e a dimensão (384)
  estão fixos no código dos indexadores, e os vetores não registram qual modelo os gerou.
- **O ADR 006 está desatualizado:** seus trechos de código (`BaseLLMProvider`,
  `GeminiProvider`, `match/case`) não correspondem mais à implementação.

### Estado em 2026-10-01

A maior parte desta decisão já foi implementada (V16 e benchmark de modelos de baixo custo):

| Ponto | Estado |
|---|---|
| Registro único (`src/llm/registry.py`) | Implementado. `factory.py` e `model_router.py` consultam o mesmo registro |
| Provedores | Cinco: `ollama` (alias `local`), `google`, `anthropic`, `openai` e `openai_compatible` |
| Embeddings locais atrás de interface | Implementado (provedor local FastEmbed, metadados de modelo, versão e dimensão em cada vetor) |
| `google-adk` | Removido do `pyproject.toml`; restam referências textuais em documentação e docstrings (limpeza feita junto com esta revisão) |
| Contabilidade de custo | Implementada (§7); não constava da decisão original |
| Catálogo de modelos e roteador por papel (ADR 017) | **Não implementado** |

---

## Decisão

### 1. Registro único de provedores LLM

Substituir os dois blocos `if/elif` por um **registro único de provedores**: cada provedor se
registra por nome, e tanto a seleção global quanto o Model Router por papel (ADR 007) consultam
o mesmo registro. Adicionar um provedor passa a significar implementar a interface e
registrá-lo — sem editar código central.

### 2. Provedores

O registro mantém, hoje, os cinco provedores abaixo; novos entram pelo mesmo mecanismo.

| Provedor | Uso | Observação |
|---|---|---|
| `ollama` | Execução local de LLMs | **Mantido como provedor de primeira classe.** Os testes futuros com modelos locais (hardware próprio do nó) dependem dele; nenhuma decisão deste ADR o rebaixa ou o remove |
| `openai_compatible` | Servidores locais (llama.cpp, vLLM, LM Studio) e serviços hospedados compatíveis | Chave opcional; `OPENAI_COMPATIBLE_BASE_URL` obrigatória |
| `google` | Gemini (API paga ou gratuita) | Fallback automático de modelo em HTTP 429 |
| `anthropic` | Claude | Esforço de raciocínio configurável |
| `openai` | API da OpenAI (modelos de raciocínio, ex.: `gpt-6-luna`) | Chave obrigatória; padrão `https://api.openai.com/v1` |

A escolha por papel continua em `{PAPEL}_PROVIDER` e `{PAPEL}_MODEL` até o catálogo do ADR 017
ser implementado.

### 3. Embeddings são internos e locais

- O modelo de embedding é usado **somente para registrar vetores no banco vetorial interno**
  (Qdrant). Ele roda localmente e é independente do provedor LLM.
- **Nem os vetores nem a geração de embeddings envolvem provedores externos** (Google,
  OpenAI, Anthropic etc.). O registro de provedores LLM (§1) não cobre embeddings.
- O modelo local fica atrás de uma **interface do projeto**, para que possa ser trocado por
  outro modelo local sem reescrever os indexadores.
- **O versionamento do embedding é registrado como metadado** de cada vetor (modelo, versão e
  dimensão), e o texto de origem é preservado para permitir reindexação.

Isso é pré-requisito para a camada de conhecimento (ADR 009). Na federação (ADR 013), os
vetores também não são compartilhados: cada nó gera os seus a partir dos registros recebidos.

### 4. Remoção do Google ADK

Remover `google-adk` do `pyproject.toml` (feito) e atualizar as referências a "Google ADK" na
documentação (AGENTS.md, regras de papéis, README, docstrings), o que passa a constar desta
revisão.

### 5. Sem frameworks de abstração pesados

A decisão do ADR 006 de **não usar LangChain** (ou equivalentes) permanece: footprint no Pi 5 e
depuração mais difícil continuam sendo motivos válidos. Com cinco provedores o registro próprio
segue mais barato que uma biblioteca externa.

### 6. Particularidades dos provedores ficam nos adaptadores

Cada provedor tem regras próprias da API, e o adaptador as normaliza para a interface comum
(`LLMProvider`), de modo que agentes e orquestrador não as conheçam. As regras abaixo vieram
de erros reais da API e têm testes com SDK ou HTTP simulados.

- **Google (Gemini 3.x):** resultados de ferramenta voltam em turno `user`; a `thought_signature`
  da resposta é reenviada no histórico; o cliente é assíncrono; tokens de pensamento são
  cobrados como saída e contam em `max_output_tokens`, então há um piso para esse limite.
- **Anthropic:** sem `temperature`, `thinking` nem `tool_choice` forçado nos modelos atuais;
  `effort` e o fallback do servidor só vão a modelos que os aceitam; blocos de pensamento
  assinados voltam intactos; piso para `max_tokens`.
- **OpenAI:** `max_completion_tokens` em vez de `max_tokens` (com piso, pois inclui o
  raciocínio); sem `temperature`; `reasoning_effort` configurável (padrão `none`, necessário
  para usar ferramentas em `/chat/completions` no `gpt-6-luna`); histórico normalizado ao
  esquema estrito (`arguments` como texto JSON).
- **Todos:** o corpo da resposta de erro HTTP entra na mensagem, para diagnosticar recusas da API.

### 7. Contabilidade de uso e custo por chamada

Toda chamada LLM é registrada num único ponto (`src/llm/metering.py`): tokens de entrada e
saída, tokens em cache, latência e custo estimado. Os preços ficam em `src/llm/pricing.py`
(USD por milhão de tokens), sobrescrevíveis por `LLM_PRICING_OVERRIDES`. **Modelo sem preço
conhecido tem custo `n/d`, nunca zero**, para não esconder gasto. Testes nunca acessam a API de
provedores pagos (um fixture do `conftest.py` falha o teste que tentar); créditos servem apenas
ao benchmark.

---

## Alternativas Consideradas

### Alternativa A: Manter os dois blocos `if/elif`

**Descartado porque:** cada novo provedor exige mudanças em dois lugares, com risco de
divergência — já aconteceu entre o ADR 006 e o código.

### Alternativa B: Adotar LangChain / LiteLLM como camada de abstração

**Descartado porque:** mantém-se o motivo do ADR 006 — muitas dependências para o Pi 5 e erros
de API ocultados pela abstração. Pode ser reconsiderado se o número de provedores crescer
muito.

---

## Consequências

### Positivas

- O projeto deixa de depender de qualquer SDK de agentes de um único fornecedor.
- Adicionar provedores vira uma mudança local e testável.
- Embeddings versionados tornam a camada de conhecimento e a federação viáveis.
- Nenhum conteúdo de pesquisa é enviado a terceiros para indexação.

### Negativas / Trade-offs

- **Paridade de tool calling:** cada provedor tem particularidades; o adaptador precisa
  normalizá-las e testes de contrato por provedor são necessários.
- **Reindexação:** trocar o modelo de embedding exige reindexar as coleções existentes no
  Qdrant.
- **Nome do projeto:** "GeminiClaw" remete a um único fornecedor e **será alterado no
  futuro** (o novo nome ainda não foi definido). Até lá, código novo deve evitar acoplar
  identificadores ao nome atual (ex.: centralizar o nome em configuração, não repeti-lo em
  módulos, tabelas ou coleções novas), para facilitar a renomeação.
- **Modelo de embedding limitado ao hardware local:** como os embeddings não usam provedores
  externos, o modelo precisa caber no Pi 5.

---

## Revisão

Este ADR deve ser revisado quando:
- O catálogo e o roteador do ADR 017 forem implementados (a seleção por variáveis `{PAPEL}_*` muda).
- Os testes com LLMs locais (Ollama ou `openai_compatible`) começarem, para registrar os
  resultados e eventuais particularidades dos adaptadores.
- O número de provedores tornar o registro próprio mais custoso que uma biblioteca externa.
- A federação (ADR 013) exigir um modelo de embedding comum entre nós.
- O novo nome do projeto for definido.
