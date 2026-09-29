# Proposta: Referências Numéricas Rastreáveis

**ID:** `v18.5-numeric-references` · **Versão:** V18.5 · **Capacidade:** `numeric-provenance`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §2;
[ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) (Curator cita por referência);
[ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §7 (comparação só na mesma métrica)
**Depende de:** `v18.5-execution-provenance` (ids `exec_<uuid4>` e registros de término)

## Por quê

O ADR 019 §2 exige que todo número de um artefato entregue (relatório, nós do grafo e
conclusões) tenha origem rastreável: **execução registrada**, **cálculo determinístico** sobre
valores registrados ou **fonte citada**. Hoje nenhuma dessas origens aparece no texto:

- O Summarizer recebe os valores de `metrics.json` como texto e é instruído a **copiá-los** e a
  **calcular a divergência percentual** por conta própria (`agents/summarizer/agent.py:58-62`).
  Nada confirma que o número impresso é o número medido.
- O `ArtifactReader` injeta a tabela de métricas como JSON solto no prompt
  (`src/report/artifact_reader.py:69-84`, `src/autonomous_loop.py:1502-1521`); o relatório
  final é exatamente o que o LLM escreveu.
- Valores esperados de artigos de referência entram no texto sem citação verificável; os
  resultados da busca técnica ficam só num cache em memória (`agents/researcher/cache.py`).
- `metrics.json` é escrito por código gerado pelo modelo; um `metrics = {"acc": 0.95}` passa
  despercebido.

## O que muda

- **Novo:** sintaxe de referências `{{res:<exec_id>/<nome_metrica>}}`,
  `{{calc:<expressão sobre res:...>}}` e `{{src:<id_insumo_ou_url>#<trecho>}}`, com parser
  único em `src/numeric_refs/` (usado pelo relatório, pelas ferramentas do Curator e,
  por acordo, pelo `EgressGate` para reconhecer números com origem).
- **Novo:** resolução de `res` pelo registro de execução (com conferência do hash do
  `metrics.json`), avaliador **determinístico** de expressões `calc` (sem `eval`, com
  operadores e funções em lista fechada) e conferência de `src` contra o texto do `Insumo` ou
  o trecho devolvido pela busca técnica.
- **Novo:** renderização com **valor, unidade e origem** (código `[R1]`, `[C1]`, `[S1]`) e
  apêndice determinístico "Origem dos números" no relatório.
- **Novo:** verificador de números sobre o texto final, que reconhece algarismos, números por
  extenso e multiplicadores em pt-BR ("três vezes", "3x", "o dobro"), aplica uma lista
  explícita de exclusões estruturais e **marca** com `[não verificado]` os números sem origem,
  sem apagá-los nem corrigi-los.
- **Novo:** verificação estática (AST) do código executado, que sinaliza métricas gravadas como
  literais (`[literal no código]` no relatório).
- **Novo:** registro persistente das fontes da busca técnica por sessão
  (`outputs/<sessão>/fontes_busca.jsonl`), para que `{{src:<url>#...}}` seja conferível.
- **Modificado:** contrato de escrita do Summarizer (escreve referências e expressões, não
  números; deixa de calcular divergências e de escrever os metadados de execução) e do Curator
  (cita valores por referência; ferramentas validam a sintaxe).
- **Modificado:** o Summarizer passa a gravar `relatorio_final.fonte.md`; o orquestrador
  renderiza `relatorio_final.md` num pipeline com pontos de extensão para as seções de
  outras mudanças (afirmações, métricas de operação, perfil de alocação, ponta da cadeia).
- **Modificado:** conversores DOCX, HTML e LaTeX exibem os códigos de origem e as marcas.
- **Modificado:** `save_experiment_artifacts` aceita `unidades` e valida os nomes de métrica.

## Impacto

- **Código:** `src/numeric_refs/` (novo: `syntax.py`, `resolver.py`, `calc.py`, `render.py`,
  `verifier.py`, `literal_metrics.py`, `catalog.py`), `src/report/pipeline.py` (novo),
  `src/report/artifact_reader.py`, `src/report/base_converter.py`,
  `src/report/{html,docx,latex}_converter.py`, `src/autonomous_loop.py`
  (`_synthesize_results`), `agents/summarizer/agent.py`, `agents/curator/agent.py` e
  `src/knowledge/curator_tools.py` (quando existirem, V17), `agents/researcher/tools.py`,
  `src/skills/code/skill.py`, `src/skills/code/scientific_helpers.py`, `src/config.py`.
- **Comportamento:** números escritos pelo LLM sem referência continuam no relatório, mas
  marcados. Relatórios de sessões antigas não são reprocessados.
- **Custo:** nenhuma chamada LLM nova; tudo é determinístico.

## Dependências e acordos com outras mudanças

| Mudança | O que esta mudança usa ou oferece |
|---|---|
| `v18.5-execution-provenance` | **Usa** `exec_<uuid4>`, o registro de término (hashes de saída, código de saída) e a consulta por id. |
| `v18.5-egress-gate` | **Oferece** `numeric_refs.syntax.find_references()` para o §3.8 (números com origem não viram marcadores). O catálogo de referências injetado no Summarizer passa pelo `EgressGate`. |
| `v18.5-claim-verification` | **Oferece** valores resolvidos e o ponto de extensão do pipeline do relatório. |
| `v18.5-operation-metrics` | **Oferece** o leitor do grupo `proveniencia` (`numeros_por_origem`, `numeros_nao_verificados`, `metricas_literais`); **respeita** o bloco `<!-- operation-metrics:begin/end -->` como seção do orquestrador. |
| `v17-curator-agent`, `v16-research-assistant-prompts` | Ajuste de instruções e ferramentas (não altera essas specs; declara o delta aqui). |

## Aprovações necessárias

Nenhuma alteração de schema de banco (PostgreSQL ou grafo), Dockerfile ou compose, e nenhum
arquivo apagado. Os novos arquivos da sessão (`relatorio_final.fonte.md`,
`proveniencia_numerica.json`, `fontes_busca.jsonl`, `metricas_literais.json`) ficam em
`outputs/<sessão>/`. A decisão de guardar a referência ao trecho de origem em arquivo da
sessão, e não como propriedade nova do `Insumo` no grafo, está no design (§2.3) e em aberto
para o pesquisador.
