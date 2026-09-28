# ADR 009 — Camada de Conhecimento Experimental: Grafo (Apache AGE) + Vetorial (Qdrant)

**Status:** Proposto
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** a definir (sequência pós-V15)
**ADRs relacionados:** ADR 001 (propósito — em revisão), ADR 005 (persistência)

---

## Contexto

O GeminiClaw está sendo redefinido de "harness de execução de pesquisa" (ADR 001) para um
**assistente digital de pesquisa**: um sistema capaz de conduzir experimentos, formular
hipóteses, validar suposições e relatar resultados.

Hoje, o conhecimento produzido por cada sessão se perde entre sessões:

- O Qdrant indexa apenas documentos enviados pelo usuário (`geminiclaw_documents`) e
  resultados de crawl web (`geminiclaw_knowledge`).
- A memória de longo prazo dos agentes (`src/skills/memory/long_term.py`) é chave/valor em
  PostgreSQL, sem busca semântica e sem relações.
- Não existe banco de grafos no projeto.
- Os artefatos científicos introduzidos na V15 (`metrics.json`, `params.json`,
  `divergence_reports`, `researcher_interactions`, `relatorio_final.md`) ficam isolados no
  diretório de cada sessão, sem ligação entre si ou com sessões anteriores.

Consequência: o sistema não aprende com a própria experiência. Se, em uma sessão, uma
arquitetura de rede neural resolveu bem o problema X com determinada configuração — e outra
falhou —, essa informação não está disponível quando o problema Y, semelhante, for
investigado. O mesmo vale para qualquer outra ferramenta usada na pesquisa.

---

## Decisão

### 1. Os agentes constroem ativamente o grafo de conhecimento

A decisão central deste ADR **não é apenas adotar um banco de grafos**, e sim atribuir aos
agentes do projeto a responsabilidade de **criar relações entre descobertas e hipóteses
validadas** ao longo das sessões de pesquisa. O grafo é o registro vivo da experiência
acumulada do assistente.

Os agentes devem ser capazes de registrar e relacionar, entre outros:

- **Quais abordagens funcionaram para qual problema** — ex.: qual arquitetura de rede neural
  resolveu o problema X, e com qual configuração obteve o melhor resultado.
- **O que não funcionou** — resultados negativos são conhecimento de primeira classe e devem
  ser registrados com o mesmo rigor que resultados positivos.
- **O que pode ser transferido** — ligações que indiquem que uma abordagem bem-sucedida no
  problema X é candidata a ser testada no problema Y.
- **Hipóteses validadas e refutadas**, ligadas aos experimentos que as testaram e às
  evidências que sustentam cada conclusão.

Redes neurais são apenas um exemplo. A camada deve ser **agnóstica ao tipo de ferramenta**:
algoritmos clássicos, testes estatísticos, pipelines de pré-processamento, bibliotecas,
protocolos experimentais, instrumentos de medição — qualquer ferramenta ou método usado
durante a pesquisa.

### 2. Apenas conhecimento com evidência entra no grafo

Toda relação criada por um agente deve ter **proveniência rastreável** até a sessão, o
experimento e os artefatos que a sustentam (ex.: `metrics.json` da subtarefa). Relações sem
evidência não são registradas. Isso preserva o princípio de integridade metodológica da V15
(Spec G2): o grafo nunca contém conclusões inventadas ou "otimistas".

### 3. O conhecimento é consumido no planejamento e na formulação de hipóteses

O grafo não é um arquivo morto. Os agentes devem **consultá-lo antes de planejar** e ao
formular novas hipóteses — para reaproveitar o que funcionou, evitar repetir o que falhou e
identificar oportunidades de transferência entre problemas.

### 4. Tecnologia: Apache AGE + Qdrant, atrás de abstrações

- **Grafo: Apache AGE**, extensão do PostgreSQL 16 que adiciona suporte a grafos com
  consultas Cypher. Reutiliza o PostgreSQL já presente na stack — nenhum serviço novo.
- **Similaridade semântica: Qdrant** (já presente), para encontrar descobertas, problemas e
  hipóteses semanticamente próximos, complementando as relações explícitas do grafo.
- O acesso ao grafo e ao índice vetorial deve ocorrer por **interfaces do projeto**, não por
  chamadas diretas espalhadas pelo código, permitindo trocar o backend sem reescrever os
  agentes.
- A camada é também o **substrato para o compartilhamento de conhecimento entre nós**
  (Raspberry Pis e outros computadores rodando o projeto), a ser decidido em ADR próprio.

### 5. Fora do escopo deste ADR

**O modelo de dados do grafo não é definido aqui.** Os tipos de nós, os tipos de relações e
as propriedades de cada um serão discutidos e definidos posteriormente, em ADR ou spec
dedicada. Este ADR estabelece apenas a responsabilidade dos agentes, o princípio de
evidência, o uso no planejamento e a tecnologia de armazenamento.

Também ficam para specs futuras: qual papel de agente executa a extração e a vinculação, em
que momento do ciclo da sessão isso ocorre, e a estratégia de deduplicação de entidades.

---

## Alternativas Consideradas

### Alternativa A: Neo4j

Banco de grafos mais maduro, com o melhor ecossistema de ferramentas.

**Descartado porque:** é baseado em JVM e consome memória significativa. No Raspberry Pi 5
(8 GB), competiria por RAM com PostgreSQL, Qdrant e os containers de agentes.

### Alternativa B: Memgraph

Compatível com Cypher, escrito em C++, mais leve que o Neo4j.

**Descartado porque:** adiciona mais um serviço para operar e exige que todo o grafo caiba em
memória — uma restrição arriscada à medida que o conhecimento acumulado cresce.

### Alternativa C: Somente Qdrant (relações em payload)

Guardar relações como metadados nos pontos vetoriais.

**Descartado porque:** um índice vetorial não oferece travessia de relações ("quais
abordagens falharam em problemas semelhantes a X que tiveram sucesso em Y?"). Similaridade
semântica e relações explícitas são complementares, não substitutas.

### Alternativa D: Tabelas relacionais simples no PostgreSQL

Modelar nós e arestas como tabelas e consultar com CTEs recursivas.

**Descartado porque:** consultas de múltiplos saltos ficam verbosas e difíceis de manter. O
Apache AGE oferece Cypher sobre o mesmo PostgreSQL, sem custo operacional adicional.

---

## Consequências

### Positivas

- O assistente passa a **aprender com a própria experiência**, inclusive com resultados
  negativos.
- Base concreta para **formulação de hipóteses por transferência** entre problemas.
- Nenhum serviço novo em execução — footprint adequado ao Pi 5.
- Proveniência obrigatória torna cada conclusão auditável até o experimento de origem.

### Negativas / Trade-offs

- **Imagem do PostgreSQL:** a imagem atual precisa incluir a extensão Apache AGE, o que
  altera a infraestrutura base (`docker-compose` / Dockerfile). Pela governança do projeto
  (AGENTS.md), essa mudança exige aprovação explícita antes de ser implementada.
- **Mudança de schema:** criar o grafo é uma alteração de banco que também exige aprovação
  explícita.
- **Compatibilidade de versões:** a versão do Apache AGE deve ser compatível com o
  PostgreSQL 16 e com ARM64; verificar antes da implementação.
- **Maturidade:** o ecossistema do Apache AGE é menor que o do Neo4j; a abstração de acesso
  mitiga o risco de uma troca futura.
- **Qualidade do grafo:** relações incorretas criadas por agentes podem "poluir" o
  conhecimento e induzir hipóteses ruins. O princípio de evidência obrigatória reduz esse
  risco; mecanismos de validação e correção das relações serão definidos nas specs.

---

## Revisão

Este ADR deve ser revisado quando:
- O modelo de dados do grafo (nós, relações e propriedades) for definido.
- O ADR de compartilhamento de conhecimento entre nós for escrito.
- O Apache AGE se mostrar inadequado em desempenho ou manutenção no Raspberry Pi 5.
