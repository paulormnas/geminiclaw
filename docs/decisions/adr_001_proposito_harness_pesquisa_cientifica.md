# ADR 001 — Propósito: Harness de Execução de Pesquisa Científica

**Status:** Aceito
**Data:** 2026-09-22
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap.md`, `roadmaps/roadmap_V6_research_autonomy.md`, `roadmaps/roadmap_V14.md`

---

## Contexto

O GeminiClaw surgiu como um framework genérico de orquestração de agentes Gemini para Raspberry Pi 5. Com a evolução do projeto, ficou claro que o caso de uso principal é ser um **assistente de pesquisa científica** operando ao lado de um pesquisador humano.

Precisava-se definir com precisão o **escopo de atuação do sistema** para evitar que ele tentasse resolver problemas que pertencem a outros domínios (como busca bibliográfica) enquanto os problemas centrais (execução de experimentos, código, análise) ficassem subdesenvolvidos.

---

## Decisão

O GeminiClaw é um **harness de execução** — não um motor de busca bibliográfica.

### O que o sistema FAZ:

1. **Recebe contexto pré-curado:** O sistema assume que o pesquisador ou um agente externo especializado já realizou a fase de busca bibliográfica (Scopus, PubMed, IEEE Xplore, arXiv, etc.) e proveu o contexto relevante (artigos, datasets, hipóteses) como input da sessão.

2. **Executa análises e experimentos:** O sistema decompõe a tarefa de pesquisa em subtarefas executáveis — análise de dados, implementação de algoritmos, experimentos estatísticos, geração de visualizações.

3. **Desenvolve código:** O Developer Agent gera, itera e valida código Python em um sandbox isolado (PythonSandbox), construindo incrementalmente sobre o trabalho anterior dentro da sessão.

4. **Valida resultados:** O Validator Agent avalia se os outputs produzidos satisfazem os critérios definidos na tarefa — verificando artefatos em disco, não apenas o texto da resposta.

5. **Elabora relatórios:** O Summarizer Agent consolida resultados, artefatos e métricas de execução em um relatório estruturado com rastreabilidade (objetivo, metodologia, resultados, limitações, próximos passos).

6. **Busca na web para suporte técnico:** Web search (QuickSearch, WebReader) é usada **exclusivamente** para necessidades técnicas das tasks em execução — por exemplo, documentação de bibliotecas, exemplos de código, soluções para erros específicos. **Não** deve ser usada para pesquisa bibliográfica ou revisão de literatura.

### O que o sistema NÃO FAZ:

- ❌ Busca em bases bibliográficas científicas (Scopus, PubMed, IEEE Xplore, Semantic Scholar, etc.)
- ❌ Revisão sistemática de literatura de forma autônoma
- ❌ Avaliação de qualidade de fontes científicas primárias (peer-review status, fator de impacto)
- ❌ Geração de hipóteses científicas sem orientação humana

---

## Alternativas Consideradas

### Alternativa A: Sistema all-in-one com busca bibliográfica integrada

Integrar clientes de Scopus API, PubMed Entrez, arXiv API diretamente no Researcher Agent.

**Descartado porque:**
- Aumenta enormemente a complexidade e o número de dependências externas
- Credenciais de acesso a bases pagas são um problema operacional
- A qualidade da busca bibliográfica requer heurísticas específicas de domínio que vão além do escopo deste projeto
- Viola o princípio de responsabilidade única: um sistema que faz busca bibliográfica E executa experimentos E valida resultados tende a fazer todos mal

### Alternativa B: Agente especializado de revisão bibliográfica como módulo interno

Criar um agente `bibliographer` interno ao GeminiClaw responsável pela fase de busca.

**Descartado porque:**
- A fase bibliográfica tem requisitos muito distintos (acesso a APIs externas pagas, critérios PRISMA, gerenciamento de referências)
- É mais adequado desenvolvê-la como um sistema separado que alimenta o GeminiClaw com contexto estruturado

---

## Consequências

### Positivas

- **Foco claro:** O sistema pode ser otimizado para execução de experimentos sem comprometer qualidade em busca bibliográfica.
- **Interface bem definida:** O pesquisador sabe exatamente o que precisa fornecer como input (contexto de artigos, datasets, hipóteses) e o que vai receber como output (código, artefatos, relatório).
- **Menor superfície de ataque:** Sem acesso a APIs de bases bibliográficas externas, há menos vetores de vazamento de credenciais.
- **Composabilidade:** O GeminiClaw pode ser orquestrado por um sistema externo de revisão bibliográfica, funcionando como o estágio de "execução" em um pipeline de pesquisa maior.

### Negativas / Trade-offs

- O pesquisador precisa preparar o contexto antes de cada sessão — não há zero-shot desde a ideia até o experimento sem intervenção humana.
- Para pesquisas exploratórias sem artigos de referência, o sistema tem utilidade limitada sem contexto pré-curado.

---

## Conformidade com Prompts dos Agentes

Todos os system prompts dos agentes devem refletir esta decisão:

- **Researcher Agent:** Instrução explícita de que o contexto de artigos é fornecido como input; web search é para resolução de dúvidas técnicas, não para descoberta de literatura.
- **Developer Agent:** Web search para documentação de bibliotecas e exemplos de código, não para buscar artigos científicos.
- **Summarizer Agent:** Relatório deve referenciar apenas as fontes fornecidas como contexto ou produzidas durante a sessão.

---

## Revisão

Este ADR deve ser revisado se:
- O projeto evoluir para incluir um módulo de revisão bibliográfica
- A interface de input do sistema mudar significativamente
- O caso de uso principal for redefinido pelo pesquisador
