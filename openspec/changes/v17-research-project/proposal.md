# Proposta: Projeto de Pesquisa e Problema Confirmado

**ID:** `v17-research-project` · **Versão:** V17 · **Capacidade:** `research-project`
**ADRs de origem:** [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §2, §4;
discussão, questão 1

## Por quê

Hoje o sistema só conhece **sessões**; não existe o conceito de **projeto** — uma linha de
pesquisa que atravessa várias sessões. O grafo precisa dele (`Projeto`), e precisa do
**`Problema`** em alto nível, escrito como o resumo de um artigo ainda sem resultados, que é a
unidade de transferência de conhecimento entre áreas. O pesquisador decidiu: o Researcher
redige o problema, e **o pesquisador confirma**, em qualquer modo de sessão. O `Problema`
também carrega o `criterio_sucesso` com `delta_min` — a única escolha humana na fórmula de
confiança, feita **antes** dos experimentos.

## O que muda

- **Novo:** comandos `geminiclaw project new|list|show|use` e a opção `--project` na execução
  de prompts; o projeto ativo é gravado no payload da sessão.
- **Novo:** na primeira sessão de um projeto, o Researcher redige o `Problema` a partir do
  prompt e do `input_context/`, com domínios resolvidos no vocabulário controlado e critério de
  sucesso; o pesquisador **confirma ou edita** antes de qualquer experimento.
- **Novo:** nós `Projeto` e `Problema` e arestas `INVESTIGA` e `NO_DOMINIO` no grafo.
- **Fora do escopo:** ingestão de sessões e experimentos (`v17-structural-fact-ingestion`).

## Impacto

- **Código:** `src/cli.py`, `src/orchestrator.py` (sessão ligada ao projeto),
  `agents/researcher/agent.py` (função `draft_problem`), `src/knowledge/projects.py` (novo).
- **UX:** a primeira sessão de um projeto ganha um passo de confirmação obrigatório; as
  seguintes reutilizam o problema confirmado.
- **Compatibilidade:** sessões sem `--project` criam um projeto novo automaticamente (título
  derivado do prompt), mantendo o uso atual funcional.

## Aprovações necessárias

Nenhuma alteração de schema além do grafo já aprovado em `v17-graph-store`.
