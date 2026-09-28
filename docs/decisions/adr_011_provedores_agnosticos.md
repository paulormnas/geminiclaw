# ADR 011 — Provedores Agnósticos: Registro de Provedores LLM e de Embeddings

**Status:** Proposto
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Substitui:** ADR 006 (quando aceito)
**ADRs relacionados:** ADR 007 (Model Router por papel), ADR 009 (conhecimento), ADR 013 (federação)

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
- **Só há dois provedores:** Google e Ollama.
- **Embeddings não são abstraídos:** o modelo local (`all-MiniLM-L6-v2`) e a dimensão (384)
  estão fixos no código dos indexadores, e os vetores não registram qual modelo os gerou.
- **O ADR 006 está desatualizado:** seus trechos de código (`BaseLLMProvider`,
  `GeminiProvider`, `match/case`) não correspondem mais à implementação.

---

## Decisão

### 1. Registro único de provedores LLM

Substituir os dois blocos `if/elif` por um **registro único de provedores**: cada provedor se
registra por nome, e tanto a seleção global quanto o Model Router por papel (ADR 007) consultam
o mesmo registro. Adicionar um provedor passa a significar implementar a interface e
registrá-lo — sem editar código central.

### 2. Novos provedores

Adicionar ao menos um adaptador **compatível com a API da OpenAI**, que cobre servidores locais
(llama.cpp, vLLM, LM Studio) e diversos serviços hospedados com uma única implementação.
Provedores nativos adicionais (ex.: Anthropic) podem ser adicionados pelo mesmo mecanismo. A
escolha exata fica para a spec da V16.

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

Remover `google-adk` do `pyproject.toml` e atualizar as referências a "Google ADK" na
documentação (AGENTS.md, regras de papéis, docstrings).

### 5. Sem frameworks de abstração pesados

A decisão do ADR 006 de **não usar LangChain** (ou equivalentes) permanece: footprint no Pi 5 e
depuração mais difícil continuam sendo motivos válidos.

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
- O número de provedores tornar o registro próprio mais custoso que uma biblioteca externa.
- A federação (ADR 013) exigir um modelo de embedding comum entre nós.
- O novo nome do projeto for definido.
