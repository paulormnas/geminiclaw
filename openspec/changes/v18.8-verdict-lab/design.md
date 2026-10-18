# Design: v18.8-verdict-lab

## 1. Confronto com o código (2026-10-18)

| Ponto | Onde está hoje | O que esta mudança faz |
|---|---|---|
| Equação | `compute_verdict`, `VerdictParams` (`src/knowledge/verdict.py:99-170`, `:490`), módulo puro | Usada sem alteração pela variante `atual` |
| Coleta das tentativas | `KnowledgeService.collect_attempts` e `_attempt_from` (`src/knowledge/service.py:281-338`) | Usada pelo `replay` sobre um `InMemoryGraphStore` carregado do arquivo |
| Grafo em memória | `InMemoryGraphStore` (`src/knowledge/graph_store.py:326`) | Recebe os nós e arestas do `grafo_projeto.json` |
| Arquivamento | `project_graph_full` (`scripts/benchmark/footprint.py:110-126`) usa `project_subgraph`, que não traz `Metrica` (nó de vocabulário, fora do projeto) | Acrescenta `Metrica` e `MEDE` |
| Scripts da etapa 1 | Fora do repositório (provisórios) | Substituídos pelo comando `replay` |

## 2. Organização

```
scripts/verdict_lab/
├── __init__.py
├── __main__.py      # argparse: replay | grade | simulacao | sensibilidade
├── variants.py      # Variant, carga do JSON, lab_verdict()
├── scenarios.py     # catálogo determinístico (famílias E, V, R, S, N, F, M, B)
├── simulation.py    # gerador estocástico com semente fixa
├── properties.py    # medidas de propriedade por variante
├── replay.py        # grafo_projeto.json -> InMemoryGraphStore -> KnowledgeService
├── output.py        # resultados.csv, relatorio.md, manifesto.json
└── variantes.json   # variantes padrão (design §3.3)
```

O pacote fica em `scripts/` (como `scripts/benchmark/`) porque é ferramenta de pesquisa, não comportamento do sistema. Importa de `src/` só `src.knowledge.verdict`, `src.knowledge.service`, `src.knowledge.graph_store` e `src.knowledge.ingestion.hash_params`. Nenhum módulo de `src/` importa o laboratório.

## 3. Variantes da fórmula

### 3.1 Formato

```json
{
  "versao": 1,
  "variantes": [
    {"nome": "atual", "descricao": "ADR 015 §9.8 (VerdictParams.from_config())"},
    {"nome": "sem_falhas_em_nconfig", "estrutura": {"n_config_conta_falhas": false}},
    {"nome": "independencia_por_tipo",
     "estrutura": {"independencia": "por_tipo", "d_variacao": 1.0, "d_replica_no": 0.5, "d_sessao": 0.3, "d_semente": 0.2}},
    {"nome": "prior_0_5", "parametros": {"prior": 0.5}}
  ]
}
```

- `parametros`: sobrescreve campos de `VerdictParams` (nomes do dataclass). Campo desconhecido é erro, com o nome do campo.
- `estrutura`: escolhe alternativas que não existem em `compute_verdict` (§3.2). Ausente, vale o comportamento atual.
- A base de toda variante é `VerdictParams.from_config()`, então as variáveis `VERDICT_*` do ambiente valem também no laboratório (ADR 025 §1: valores por variável de ambiente, sem alterar código). O manifesto registra os valores efetivos.

### 3.2 Alternativas de estrutura

`lab_verdict(attempts, criterion, variant)` reimplementa a equação com as alternativas abaixo. Com `estrutura` vazia, delega a `compute_verdict` (não reimplementa), e um teste confere que a reimplementação com todas as alternativas no valor atual dá o mesmo resultado que `compute_verdict` em todos os cenários do catálogo e da simulação (diferença ≤ 1e-12).

| Chave | Valores | Efeito |
|---|---|---|
| `n_config_conta_falhas` | `true` (atual), `false` | Com `false`, `n_config` da penalidade de busca conta só as configurações das tentativas que viraram evidência |
| `independencia` | `atual`, `por_tipo` | `por_tipo` classifica cada evidência pela ordem da tabela abaixo e usa os pesos `d_variacao`, `d_replica_no`, `d_dataset`, `d_sessao` e `d_semente` |
| `variacao_util` | `nenhuma` (padrão), `melhora_o_melhor` | Com `melhora_o_melhor`, uma variação só recebe `d_variacao` se o valor superar em pelo menos `variacao_util_epsilon` o melhor valor anterior da hipótese no sentido da métrica; senão, recebe `d_semente` (é volume, não exploração) |
| `m_sem_baseline` | `fixo` (atual, 0,5), `folga` | Com `folga`, sem baseline e com alvo, `m = min(1, folga / (2δ))` na positiva e `m = min(1, (δ − folga) / δ)` na negativa, com `folga` = distância ao alvo no sentido favorável |
| `b_por` | `configuracao` (atual), `variacao_sem_ganho` | Com `variacao_sem_ganho`, `n_config` conta só as variações que não melhoraram o melhor valor anterior (mais 1) |

Classificação de `independencia: por_tipo`, aplicada em ordem cronológica às tentativas que viram evidência, com os conjuntos de "já visto" da própria hipótese:

| Ordem | Caso | Definição | Peso |
|---|---|---|---|
| 1 | Variação | `config_hash` ainda não visto em nenhuma evidência da hipótese, em qualquer nó | `d_variacao` |
| 2 | Réplica em outro nó | `config_hash` já visto, em nó em que ele ainda não foi executado | `d_replica_no` |
| 3 | Dataset novo | Configuração e nó já vistos, com dataset ainda não usado | `d_dataset` |
| 4 | Sessão nova | Configuração, nó e datasets já vistos, sessão nova | `d_sessao` |
| 5 | Semente nova | Demais casos | `d_semente` |

A ordem segue as decisões do pesquisador de 2026-10-18: variação conta como exploração se a configuração ainda não foi executada (em nenhum nó), e réplica em outro nó conta como validação, com peso menor que a variação. Os pesos de `variantes.json` (§3.3) são pontos de partida para a grade, não recomendações.

### 3.3 Variantes padrão

`variantes.json` traz `atual`, cada alternativa de estrutura isolada, as combinações `por_tipo + sem_falhas_em_nconfig`, `por_tipo + melhora_o_melhor`, `por_tipo + melhora_o_melhor + variacao_sem_ganho + folga`, e `prior` 0,5 e 0,25 sobre `atual` e sobre a combinação mais completa. O pesquisador pode passar outro arquivo com `--variantes`.

## 4. Catálogo de cenários (`grade`)

Cada cenário é uma lista de tentativas (`Attempt`), um `Criterion` e um `esperado` ∈ {`funciona`, `nao_funciona`, `indeciso`}. O critério padrão é `maior_melhor`, `alvo = 0,95` e `δ = 0,01`, com e sem baseline. Os valores ficam no próprio catálogo (não são do caso de pesquisa da dissertação). As famílias são:

| Família | O que varia | Exemplo |
|---|---|---|
| E, exploração em um nó | 1, 2, 3, 5 e 8 variações, todas acima do alvo, com valores crescentes | E3: três configurações, 0,96, 0,97, 0,98 |
| V, volume sem ganho | 3, 8 e 20 variações com o mesmo valor, ou só uma acima do alvo | V8: oito configurações, todas 0,951 |
| R, réplica entre nós | A mesma configuração em 2, 3 e 5 nós | R3 |
| S, sementes e sessões | A mesma configuração com 3 e 10 sementes; 3 sessões | S10 |
| N, refutação em um nó | 1, 3 e 5 configurações abaixo do alvo; falha de abordagem reproduzida | N3 |
| F, falhas | Positivas com 1, 3 e 7 falhas ambíguas; falhas de infraestrutura | F7: o caso `…459203` da etapa 1 |
| M, mistos | 2 positivas e 1 negativa; 1 e 1; 3 e 3 | M21 |
| B, sem baseline | Folga de 0,001, 0,02 e 0,05 sobre o alvo | B-folga-0,001 |

O `esperado` de cada cenário é proposto pelo Arquiteto no catálogo e revisado pelo pesquisador antes de os resultados serem usados para escolher uma variante (questão em aberto 1). Para cada par (cenário, variante), a saída registra o veredito, a leitura, o detalhamento por tentativa e o acerto contra o `esperado`, considerando "conclui" quando `|veredito| ≥ DECISION_EVAL_MIN_VERDICT` (ou o limiar passado em `--limiar`, que pode ser uma lista para comparar limiares).

## 5. Simulação (`simulacao`)

Mede erros de classificação com resposta conhecida, que nem os grafos arquivados nem a grade determinística dão.

- **Hipóteses:** `verdadeira` (média real acima do alvo por `efeito`), `falsa` (abaixo do alvo por `efeito`) e `sem_efeito` (média real igual ao alvo).
- **Tentativas:** a cada passo, o agente simulado escolhe uma nova configuração com probabilidade `p_variacao` ou repete uma existente com outra semente. Cada configuração tem efeito próprio `~ N(0, tau)` sobre a média da hipótese. O valor observado é `média + efeito_config + N(0, sigma)`. Uma fração `p_falha` das tentativas falha (ambígua ou de infraestrutura, na proporção `p_infra`). Com `nos > 1`, as réplicas podem ir para outros nós.
- **Medidas por variante e por número de tentativas (1 a `max_tentativas`):** falsa validação (hipótese falsa ou sem efeito com veredito ≥ limiar), falsa refutação (verdadeira com veredito ≤ −limiar), indecisão (nem um nem outro), e tentativas até cruzar 0,1, 0,3 e 0,5 (mediana e percentis 10 e 90).
- **Grade da simulação:** `sigma`, `tau`, `efeito`, `p_variacao`, `p_falha` e `nos` são listas na linha de comando ou num arquivo JSON. O produto cartesiano é executado com `repeticoes` sorteios por ponto. Os padrões são genéricos (por exemplo, `sigma` em {0,005; 0,01; 0,02}) e cobrem faixas, não um caso.
- **Determinismo:** um único `--semente` gera, por `random.Random`, a semente de cada ponto e repetição. A mesma semente dá a mesma saída byte a byte.

A simulação é o instrumento para a cautela do pesquisador sobre variações sem ganho: com `sem_efeito`, `tau > 0` e muitas variações, alguma configuração passa do alvo por acaso. A taxa de falsa validação mostra quanto cada variante premia esse volume.

## 6. Propriedades (`grade --propriedades`)

Medidas por variante sobre o catálogo e sobre a amostra da simulação. São relatadas como contagem de violações com um exemplo mínimo de cada, sem reprovar a variante. Uma variante que viola uma propriedade pode ser a escolhida, e a escolha fica registrada.

| Propriedade | Verificação |
|---|---|
| Limites | `−1 ≤ veredito ≤ 1` e `0 ≤ certeza < 1` |
| Determinismo | duas execuções com a mesma entrada dão o mesmo resultado |
| Ordem de entrada | permutar a lista de tentativas (mantendo os `timestamp`) não muda o resultado |
| Monotonicidade | acrescentar uma evidência positiva independente (nó novo) nunca reduz o veredito; uma negativa nunca o aumenta |
| Simetria | trocar positivas por negativas de mesmo peso inverte o sinal; a diferença de módulo é relatada (a penalidade `b` só age nas positivas, então a variante `atual` não é simétrica) |
| Volume sem ganho | o veredito de V20 dividido pelo de V3, por variante |

## 7. Saída

`--saida <dir>` é obrigatório; o diretório é criado e não pode já conter `manifesto.json` (evita sobrescrever um resultado; `--sobrescrever` libera).

- `resultados.csv`: uma linha por (entrada, variante, limiar) com as colunas do comando.
- `relatorio.md`: tabelas em português com as mesmas convenções do relatório da etapa 1: resumo por variante, erros por família ou por tipo de hipótese, sensibilidade e propriedades. O relatório final de cada etapa em `docs/calibracao-veredito/` é escrito a partir delas, com leitura e limitações.
- `manifesto.json`: `commit` (`git rev-parse HEAD`, ou `desconhecido` fora de um repositório), data UTC, comando e argumentos, variantes com os parâmetros efetivos, sementes, e caminho e sha256 de cada entrada lida (`grafo_projeto.json`, arquivos de variantes e de grade).

O `replay` aceita arquivos ou diretórios (busca `grafo_projeto.json` recursivamente). Com `Metrica` e `MEDE` no arquivo, usa `KnowledgeService.collect_attempts` sem adaptação. Sem eles (arquivos anteriores a esta mudança), cria o nó `Metrica` a partir do `criterio_sucesso` do `Problema` e liga por `MEDE` os `Resultado` cujo `nome_original` é a métrica do critério. A hipótese ganha a marca `metrica_reconstruida = true` na saída, e o relatório conta as hipóteses cujo veredito recalculado diverge do gravado.

## 8. Custo e desempenho

Sem LLM, banco ou rede. A simulação padrão (cerca de 200 pontos de grade, 200 repetições, até 20 tentativas e 12 variantes) faz da ordem de 10⁷ chamadas a uma função pura de microssegundos. Meta: menos de 10 minutos no Raspberry Pi 5 em um processo. `--repeticoes` e a grade controlam o tamanho, e o comando imprime a estimativa de chamadas antes de começar.

## 9. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Arquitetura | Ferramenta fora de `src/`; dependência só de `src/knowledge` (puro e em memória). Nenhuma camada nova em `src/`. |
| Dados | Lê arquivos locais e escreve só em `--saida`. O arquivamento do benchmark ganha nós `Metrica` (sem dado de pesquisa novo). |
| Segurança | Ver §10. |
| Desempenho | Processo único, sem paralelismo nem memória proporcional ao total de sorteios (resultados agregados por ponto). |
| Custo | Zero tokens. |
| Manutenção | A equivalência da variante `atual` com `compute_verdict` é um teste: mudanças em `verdict.py` que não forem replicadas no laboratório quebram o teste. |

## 10. Segurança

- Arquivos de entrada são dados locais do pesquisador. O JSON é lido com `json.load`, sem `eval` nem pickle, e valores fora do formato esperado são erro com o caminho do arquivo e a chave.
- Não executa código dos arquivos de entrada nem lê `.env` além do que `src.config` já lê para `VerdictParams.from_config()`. Sem credenciais de provedor, a variante `atual` usa os padrões do dataclass, e o manifesto registra a origem (`config` ou `padrao`).
- `--saida` não segue links simbólicos para fora do diretório pedido e recusa diretórios do sistema (`/`, `$HOME` sem subdiretório).

Sem toque em sandbox, rede, permissões ou banco; a revisão do Analista de Segurança se limita a esta seção.

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| A reimplementação divergir de `compute_verdict` | Teste de equivalência em todo o catálogo e numa amostra da simulação |
| Escolher a variante pelo catálogo que o próprio Arquiteto escreveu | `esperado` revisado pelo pesquisador antes; simulação com resposta conhecida; critérios de aceite decididos pelo pesquisador (ADR 025 §4) |
| Ajustar a fórmula ao Iris | A grade e a simulação não usam os dados do benchmark; os parâmetros da simulação varrem faixas |
| Simulação simples demais (efeitos normais, independência entre tentativas) | Limitação declarada no relatório; a etapa 3 (sessões controladas) testa com agentes reais |

## 12. Questões em aberto (decisão do pesquisador)

1. **`esperado` dos cenários:** em especial, a partir de quantas variações que melhoram (família E) o sistema deve concluir `funciona` em um nó, e se o volume sem ganho (família V) deve ficar sempre `indeciso`.
2. **Critério de "variação útil":** superar o melhor valor anterior por qualquer quantidade, por `δ` ou por um `variacao_util_epsilon` próprio. O laboratório testa os três.
3. **Peso relativo de réplica em outro nó:** a decisão de 2026-10-18 fixa só a ordem (variação > réplica em outro nó). Os valores saem da grade.
4. **Critérios de aceite de uma variante** (por exemplo, taxa máxima de falsa validação em `sem_efeito`): propostos pelo Arquiteto com os resultados e decididos pelo pesquisador (ADR 025 §4).
