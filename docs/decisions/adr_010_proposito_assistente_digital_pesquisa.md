# ADR 010 — Propósito: Assistente Digital de Pesquisa Científica

**Status:** Proposto
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Substitui:** ADR 001 (quando aceito)
**ADRs relacionados:** ADR 009 (conhecimento experimental), ADR 011 (provedores), ADR 012 (Curator), ADR 013 (federação)

---

## Contexto

O ADR 001 definiu o GeminiClaw como um **harness de execução**: o sistema recebia contexto
pré-curado e executava tarefas, sendo explicitamente proibido de gerar hipóteses sem
orientação humana. Com a V15 concluída (modos de sessão, pipeline `input_context/`,
epistemologia científica do Researcher, contratos de código reproduzível, human-in-the-loop e
relatório científico), o sistema já executa experimentos com rigor.

O pesquisador responsável redefiniu o caso de uso principal — gatilho de revisão previsto no
próprio ADR 001. O objetivo passa a ser um **assistente digital de pesquisa**: um sistema que
não apenas executa, mas conduz a investigação.

---

## Decisão

O GeminiClaw é um **assistente digital de pesquisa científica** capaz de conduzir
experimentos, formular hipóteses, validar suposições e relatar resultados.

### O que o sistema FAZ

1. **Parte de insumos fornecidos pelo pesquisador responsável:** artigos, dados e demais
   materiais que dão início a uma pesquisa (via `input_context/`, Spec G9).
2. **Formula hipóteses** a partir desses insumos, dos resultados de seus próprios experimentos
   e do conhecimento experimental acumulado (ADR 009) — inclusive por transferência: o que
   funcionou no problema X como candidato para o problema Y.
3. **Conduz experimentos** decompostos em DAG, executados em sandbox isolado, com contratos de
   reprodutibilidade (Spec G2).
4. **Valida suposições e resultados** contra evidências em disco (`metrics.json`), nunca contra
   texto otimista gerado por LLM.
5. **Registra o que aprendeu:** o que funcionou, o que não funcionou, oportunidades a explorar
   e o porquê das decisões de caminho (ADR 012).
6. **Continua explorando** de forma iterativa até encontrar uma solução ou atingir um limite
   de uso definido pelo pesquisador responsável (ADR 012).
7. **Relata resultados** em relatório científico estruturado e rastreável (Spec G8).
8. **Busca na web apenas para suporte técnico** (documentação de bibliotecas, APIs, erros),
   como já definido no ADR 001.

### O que o sistema NÃO FAZ

- ❌ **Busca bibliográfica / revisão de literatura.** Continua fora do escopo. Os insumos
  bibliográficos são responsabilidade do pesquisador responsável ou de um agente externo
  especializado, que opera separadamente e alimenta o GeminiClaw via `input_context/`.
- ❌ **Inventar dados ou conclusões.** Toda conclusão precisa de evidência rastreável.
- ❌ **Agir sem limites.** A exploração é sempre limitada por orçamento definido pelo
  pesquisador responsável (tokens, tempo, retentativas, etc.).

### Autonomia governada pelo modo de sessão

A formulação e execução de hipóteses respeita o `SessionMode` (Spec G10):

- **`assisted`**: hipóteses geradas pelo sistema passam pela aprovação do pesquisador
  responsável antes de serem executadas.
- **`semi` / `auto`**: o sistema executa as hipóteses mais promissoras dentro do orçamento,
  documentando cada decisão.

### Visão de longo prazo

Nós do GeminiClaw em diferentes instituições poderão compartilhar descobertas e
oportunidades de pesquisa em uma rede pública (ADR 013). Essa capacidade é a **última** a ser
implementada, após todas as funcionalidades de pesquisa estarem completas e validadas.

### Sequência de implementação

```
V16  Fundações: provedores agnósticos (ADR 011), revisão de prompts ao novo propósito
V17  Camada de conhecimento experimental (ADR 009) + agente Curator (ADR 012)
V18  Ciclo de hipóteses: formulação, exploração iterativa, validação de suposições
V19  Controle de equipamentos físicos (Spec G7, antes prevista como V16)
V20  Federação entre nós (ADR 013)
```

---

## Alternativas Consideradas

### Alternativa A: Manter o ADR 001 (harness de execução)

**Descartado porque:** limita o sistema a executar o que lhe é pedido, desperdiçando a
experiência acumulada entre sessões e impedindo que ele contribua com a formulação de
hipóteses — exatamente o que o pesquisador responsável deseja.

### Alternativa B: Incluir busca bibliográfica autônoma

**Descartado porque:** os motivos do ADR 001 (dependências externas, credenciais de bases
pagas, requisitos próprios como PRISMA) continuam válidos. A busca bibliográfica deve ser uma
tarefa de outro agente que opera separadamente.

---

## Consequências

### Positivas

- O sistema passa a contribuir com a investigação, não apenas com a execução.
- A experiência acumulada torna cada nova pesquisa mais eficiente.
- O escopo permanece claro: a entrada de literatura continua sendo responsabilidade externa.

### Negativas / Trade-offs

- **Prompts de todos os agentes precisam ser revisados** — hoje eles refletem o ADR 001
  (ex.: proibição de gerar hipóteses). Isso é trabalho da V16.
- **Maior risco de gasto de recursos:** exploração iterativa exige limites de uso bem
  definidos e respeitados (ADR 012).
- **Hipóteses de baixa qualidade** podem consumir orçamento; a pontuação e priorização de
  hipóteses serão definidas na spec da V18.
- **A Spec G7** (`roadmaps/specs/G7_equipment_control_mhs.md`) deve ser renumerada de V16
  para V19 ao criar os roadmaps.

---

## Revisão

Este ADR deve ser revisado quando:
- A busca bibliográfica for reconsiderada como parte do sistema.
- A federação entre nós (ADR 013) for implementada.
- O caso de uso principal for novamente redefinido pelo pesquisador responsável.
