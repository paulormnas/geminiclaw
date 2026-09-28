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
- **Embeddings não são abstraídos:** o modelo (`all-MiniLM-L6-v2`) e a dimensão (384) estão
  fixos no código dos indexadores.
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

### 3. Abstração de embeddings

Criar uma **interface de provedor de embeddings**, independente do provedor LLM. Cada vetor
armazenado deve registrar **qual modelo e versão** o gerou, e o texto de origem deve ser
preservado para permitir reindexação. Isso é pré-requisito para a camada de conhecimento
(ADR 009) e para a federação (ADR 013), em que nós diferentes podem usar modelos diferentes.

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

### Negativas / Trade-offs

- **Paridade de tool calling:** cada provedor tem particularidades; o adaptador precisa
  normalizá-las e testes de contrato por provedor são necessários.
- **Reindexação:** trocar o modelo de embedding exige reindexar as coleções existentes no
  Qdrant.
- **Nome do projeto:** "GeminiClaw" remete a um único fornecedor. A mudança de nome não é
  decidida aqui, mas fica registrada como questão em aberto.

---

## Revisão

Este ADR deve ser revisado quando:
- O número de provedores tornar o registro próprio mais custoso que uma biblioteca externa.
- A federação (ADR 013) exigir um modelo de embedding comum entre nós.
