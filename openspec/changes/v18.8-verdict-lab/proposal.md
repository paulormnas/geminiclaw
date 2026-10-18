# Proposta: Laboratório do veredito (repetição offline, grade sintética e simulação)

**ID:** `v18.8-verdict-lab` · **Versão:** V18.8

**Capacidades:** `evidence-scoring`, `benchmark`

**ADRs de origem:** [ADR 025](../../../docs/decisions/adr_025_calibracao_do_veredito.md) §3, etapas 1 e 2 (repetição offline e grade sintética com propriedades), §4 (medidas e critérios de comparação), §5 (variantes candidatas) e "Decisões do pesquisador (2026-10-18)"; [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9 (equação de confiança, que o laboratório reproduz sem alterar).

**Depende de:** nada em aberto. Usa `compute_verdict` e `VerdictParams` (`src/knowledge/verdict.py`), `KnowledgeService.collect_attempts` (`src/knowledge/service.py`) e `InMemoryGraphStore` (`src/knowledge/graph_store.py`), todos existentes.

## Por quê

A etapa 1 do ADR 025 ([relatório](../../../docs/calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md)) mostrou que nenhuma das 30 hipóteses testadas nas baterias passou de 0,111. Variar os parâmetros atuais quase não muda o quadro. As causas são a pouca evidência por hipótese (no máximo duas positivas, um nó, uma sessão), a forma da equação, que exige pelo menos três evidências perfeitas e independentes para chegar a 0,3, e a forma como a independência é contada: uma configuração nova no mesmo nó vale o mesmo que uma semente nova.

O pesquisador decidiu ajustar a equação para que uma exploração em um único nó consiga chegar a um veredito de solução ou de falha, mantendo a contribuição das validações em outros nós. Também decidiu que variar a configuração conta como exploração e pesa mais que replicar em outro nó, sem premiar o volume de variações que não melhoram a pesquisa. Antes de mudar a fórmula, é preciso saber como cada parâmetro e cada alternativa de fórmula se comportam em situações cuja resposta é conhecida. Os grafos arquivados não dão isso: são uma só tarefa, quase só hipóteses verdadeiras e nenhuma evidência negativa.

O laboratório responde a essa pergunta sem chamada de LLM e sem alterar o comportamento do sistema. Os resultados vão para os relatórios de calibração, que também servem de base para a dissertação.

## O que muda

### Novo

- **Pacote `scripts/verdict_lab/`**, executado por `uv run python -m scripts.verdict_lab <comando>`, com quatro comandos:
  - `replay`: recalcula o veredito das hipóteses de arquivos `grafo_projeto.json` arquivados, com o mesmo coletor de tentativas do Curator, e confere com o valor gravado (refaz a etapa 1 com ferramenta versionada);
  - `grade`: aplica cada variante da fórmula a um catálogo de cenários sintéticos determinísticos, cada um com o desfecho esperado declarado;
  - `simulacao`: gera hipóteses verdadeiras, falsas e sem efeito com ruído controlado e semente fixa e mede, por variante, as taxas de falsa validação, falsa refutação e indecisão e o número de tentativas até cruzar cada faixa;
  - `sensibilidade`: varia cada parâmetro isoladamente e em pares e ordena os parâmetros pelo efeito no veredito.
- **Variantes da fórmula**, declaradas em arquivo JSON: valores de `VerdictParams` e alternativas de estrutura que só existem no laboratório. A variante `atual` reproduz `compute_verdict` exatamente.
- **Medida de propriedades por variante:** limites em [−1, +1], determinismo, invariância à ordem de entrada, monotonicidade com evidência concordante, simetria entre positivas e negativas e efeito do volume de variações sem ganho. São medidas e relatadas, não impostas.
- **Saída reprodutível:** `resultados.csv`, `relatorio.md` (tabelas prontas para os relatórios de calibração) e `manifesto.json` (commit, data, comando, variantes, sementes e sha256 das entradas).
- **Arquivamento da métrica no benchmark:** o `grafo_projeto.json` de cada repetição passa a incluir os nós `Metrica` ligados por `MEDE` aos `Resultado` do projeto e essas arestas. Sem isso, o `replay` precisa identificar a métrica pelo nome, como na etapa 1.

### Modificado

- `scripts/benchmark/footprint.py` (`project_graph_full`): inclui `Metrica` e `MEDE`.

### Fora do escopo

- Mudar a fórmula, os valores padrão ou o limiar usados pelo sistema: `v18.8-verdict-calibration`, depois dos resultados e com revisão do ADR 015 §9 aprovada pelo pesquisador.
- Direção da evidência pela predição da hipótese (ADR 015 §9): `v18.8-verdict-direction`.
- Sessões controladas com agentes e dados sintéticos (ADR 025 §3, etapa 3) e a bateria no Raspberry Pi (etapa 4).
- Corrigir o registro de `dataset_ids`, baseline e semente nos experimentos (achados da etapa 1, §6 item 5): entram em `v18.8-verdict-calibration` ou em mudança própria, conforme decisão do pesquisador.

## Impacto

- **Código:** pacote novo `scripts/verdict_lab/` e testes em `tests/unit/verdict_lab/`. `scripts/benchmark/footprint.py` ganha a métrica no arquivamento. Nenhum módulo de `src/` muda.
- **Contratos:** formato do arquivo de variantes, dos cenários e da saída (design §3 a §7). `grafo_projeto.json` ganha nós e arestas, sem mudar os existentes.
- **Schema:** nenhum.
- **Custo:** nenhuma chamada de LLM nem acesso a banco ou rede. A simulação padrão roda em poucos minutos no Raspberry Pi (design §8).

## Aprovações necessárias

Nenhuma além da aprovação desta mudança: sem schema, Dockerfile, `docker-compose.yml`, `AGENTS.md` ou exclusão de arquivo.
