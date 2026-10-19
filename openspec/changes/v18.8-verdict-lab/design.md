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
├── sensitivity.py   # variação isolada e em pares dos parâmetros
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
| `variacao_util` | `nenhuma` (padrão), `melhora_o_melhor` | Com `melhora_o_melhor`, uma variação só recebe `d_variacao` se o valor superar o melhor valor anterior da hipótese, no sentido da métrica, em mais que `variacao_util_epsilon`; senão, recebe `d_semente` (é volume, não exploração). Padrão `variacao_util_epsilon = 0`: qualquer melhora conta (decisão do pesquisador, 2026-10-18) |
| `m_sem_baseline` | `fixo` (atual, 0,5), `folga` | Com `folga`, sem baseline e com alvo e `δ`, `m = min(1, folga / (2δ))` na positiva e `m = min(1, falta / δ)` na negativa, com `folga` e `falta` = distância ao alvo no sentido favorável e no desfavorável (ficar logo abaixo do alvo vale perto de 0, como o quase empate do ADR 015 §9.4) |
| `b_por` | `configuracao` (atual), `variacao_sem_ganho`, `variacao_sem_ganho_acumulada` | Com `variacao_sem_ganho`, `n_config` conta só as variações que não melhoraram o melhor valor anterior (mais 1), sobre todas as tentativas. Com `variacao_sem_ganho_acumulada`, a contagem vai só até a própria evidência, em ordem cronológica: uma evidência posterior não reduz o peso das anteriores (a primeira forma perde monotonicidade, achado da etapa 2) |
| `criterio_com_alvo` | `baseline_primeiro` (atual), `exige_alvo` | Hoje, com baseline, a direção vem só de `Δ ≥ δ` e o alvo é ignorado (`_direction_and_magnitude`, `src/knowledge/verdict.py:292-321`), enquanto o objetivo `limiar` exige alcançar o alvo **e** superar a referência (`src/knowledge/objective.py:228-236`). Com `exige_alvo`, quando o critério tem alvo e baseline, a evidência só é positiva se as duas condições valerem; `m` continua pela conta do baseline, e a evidência que supera o baseline mas não alcança o alvo é negativa com `m = min(1, falta / δ)` |
| `m_folga_piso` | número (padrão 0) | Com `m_sem_baseline = folga`, piso do `m` das evidências positivas (0,5 reproduz o valor fixo atual para melhoras pequenas e deixa `m` crescer com a folga). Sem piso, uma melhora pequena sobre o alvo pesa quase zero |
| `d_replica_contraria` | número ou ausente | Com `independencia = por_tipo`, peso `d` de uma evidência **negativa** em configuração já vista (réplica que não confirma). Ausente: o mesmo peso de uma réplica positiva. 1,0: a falha de confirmação pesa cheio |
| `d_variacao_sem_ganho` | número ou ausente | Com `variacao_util = melhora_o_melhor`, peso `d` de uma evidência **positiva** de variação que não superou o melhor valor anterior. Ausente: `d_semente`. 0,0: variação sem evolução não soma (o volume não produz conclusão) |

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

Depois da etapa 2 (2026-10-18), `variantes.json` ganhou `base_alvo` (por tipo, variação útil e alvo exigido) e `completa2` (`completa` corrigida: penalidade acumulada, piso 0,5 na folga, réplica contrária com peso cheio e positiva sem ganho com peso zero), mais `completa2` com `prior` 0,75, 0,5 e 0,25. As variantes antigas continuam, para reproduzir o relatório da etapa 2.


`variantes.json` traz `atual`, cada alternativa de estrutura isolada, as combinações `por_tipo + sem_falhas_em_nconfig`, `por_tipo + melhora_o_melhor`, `por_tipo + melhora_o_melhor + variacao_sem_ganho + folga`, e `prior` 0,5 e 0,25 sobre `atual` e sobre a combinação mais completa. O pesquisador pode passar outro arquivo com `--variantes`.

## 4. Catálogo de cenários (`grade`)

Cada cenário é uma lista de tentativas (`Attempt`), um `Criterion` e um `esperado` ∈ {`funciona`, `nao_funciona`, `indeciso`}. O critério padrão é `maior_melhor`, `alvo = 0,95` e `δ = 0,01`, com e sem baseline. Os valores ficam no próprio catálogo (não são do caso de pesquisa da dissertação). As famílias são:

| Família | O que varia | Exemplo |
|---|---|---|
| E, exploração em um nó | 1 a 5 e 8 variações, todas acima do alvo, com valores crescentes | E5: cinco configurações, 0,955 a 0,971 |
| V, volume sem ganho | 3, 8 e 20 variações com o mesmo valor, ou só uma acima do alvo | V8: oito configurações, todas 0,951 |
| R, réplica entre nós | A mesma configuração em 2, 3 e 5 nós | R3 |
| S, sementes e sessões | A mesma configuração com 3 e 10 sementes; 3 sessões | S10 |
| N, refutação em um nó | 1, 3 e 5 configurações abaixo do alvo; falha de abordagem reproduzida | N3 |
| F, falhas | Positivas com 1, 3 e 7 falhas ambíguas; falhas de infraestrutura | F7: o caso `…459203` da etapa 1 |
| M, mistos | 2 positivas e 1 negativa; 1 e 1; 3 e 3 | M21 |
| B, sem baseline | Folga de 0,001, 0,02 e 0,05 sobre o alvo | B-folga-0,001 |
| C, critério com baseline e alvo | Resultados acima do baseline + `δ` e abaixo do alvo; acima dos dois | C3-abaixo-do-alvo: três variações em 0,80, 0,85 e 0,90 com baseline 0,333 e alvo 0,95 |
| D, sentido `menor_melhor` | Os cenários E5, N3 e M21 espelhados para uma métrica de erro | D-E5 |
| P, exploração seguida de estagnação | E5 seguido de 5 e 15 variações sem ganho | P-E5-V15 |
| Q, réplica que não confirma | E5 e, depois, a melhor configuração em um ou três outros nós, abaixo do alvo | Q-E5-R1-neg, Q-E5-R3-neg |
| A, recordes por acaso | Resultados em torno do alvo, alternando acima e abaixo, com recordes crescentes pequenos; e só melhoras pequenas acima do alvo | A8-ruido |
| G, métrica discreta | Melhoras do tamanho de um acerto num conjunto de teste pequeno (1/30 ≈ 0,033), com valores repetidos | G-E2-passo |

O `esperado` segue as regras do pesquisador (2026-10-18; **revisado em 2026-10-19 de três para cinco variações**, porque o teto de 2 % de falsa validação não comporta três): **cinco variações com resultado positivo, cada uma melhor que a anterior, bastam para `funciona`** (E5, E8, E5-b, D-E5, P-E5-V*); com menos de cinco, `indeciso`, e concluir `funciona` com três ou quatro é *aceitável* quando a evidência é forte (campo `aceitaveis`), mas nunca exigido; **variações que não indicam evolução ficam `indeciso`** (família V). Os demais seguem a mesma leitura: N3 e N5 `nao_funciona`; R e S, a mesma configuração repetida sem variação ou em outros nós, `indeciso` (a réplica pesa menos que a variação, decisão de 2026-10-19); C com todos os resultados abaixo do alvo, `nao_funciona` para um objetivo `limiar`; Q `indeciso`; M21 `indeciso`. Cada `esperado` tem uma justificativa curta no catálogo, e o relatório lista os cenários em que nenhuma variante acerta. Para cada par (cenário, variante), a saída registra o veredito, a leitura, o detalhamento por tentativa e o acerto contra o `esperado`, considerando "conclui" quando `|veredito| ≥ DECISION_EVAL_MIN_VERDICT` (ou o limiar passado em `--limiar`, que pode ser uma lista para comparar limiares).

## 5. Simulação (`simulacao`)

Mede erros de classificação com resposta conhecida, que nem os grafos arquivados nem a grade determinística dão.

- **Hipóteses:** `verdadeira` (média real acima do alvo por `efeito`), `falsa` (abaixo do alvo por `efeito`) e `sem_efeito` (média real igual ao alvo). Com `--granularidade 1/n`, os valores observados são arredondados ao múltiplo de `1/n` (métrica de acurácia num conjunto de teste de `n` amostras).
- **Tentativas:** a cada passo, o agente simulado escolhe uma nova configuração com probabilidade `p_variacao` ou repete uma existente com outra semente. Cada configuração tem efeito próprio `~ N(0, tau)` sobre a média da hipótese. O valor observado é `média + efeito_config + N(0, sigma)`. Uma fração `p_falha` das tentativas falha (ambígua ou de infraestrutura, na proporção `p_infra`). Com `nos > 1`, as réplicas podem ir para outros nós.
- **Medidas por variante e por número de tentativas (1 a `max_tentativas`):**
  - **taxa de falsa validação:** fração das hipóteses `falsa` ou `sem_efeito` que terminam com veredito ≥ limiar (validadas sem contribuir);
  - **taxa de falsa refutação:** fração das `verdadeira` com veredito ≤ −limiar;
  - **poder:** fração das `verdadeira` validadas (o que a fórmula consegue concluir quando há algo a concluir);
  - **indecisão:** fração que não cruza nenhum dos dois limiares;
  - **tentativas até cruzar** 0,1, 0,3 e 0,5 (mediana e percentis 10 e 90);
  - **custo por validação útil:** tentativas gastas em todas as hipóteses dividido pelo número de `verdadeira` validadas.
- **Curva de compromisso:** para cada variante, falsa validação contra poder variando o limiar (de 0,1 a 0,6). Uma variante domina outra quando tem mais poder com a mesma falsa validação. O relatório traz a curva em tabela.
- **Grade da simulação:** `sigma`, `tau`, `efeito`, `p_variacao`, `p_falha` e `nos` são listas na linha de comando ou num arquivo JSON. O produto cartesiano é executado com `repeticoes` sorteios por ponto. Os padrões são genéricos (por exemplo, `sigma` em {0,005; 0,01; 0,02}) e cobrem faixas, não um caso.
- **Determinismo:** um único `--semente` gera, por `random.Random`, a semente de cada ponto e repetição. A mesma semente dá a mesma saída byte a byte.

Os parâmetros da simulação também incluem `d_replica_no` em {0,3; 0,5; 0,7; 0,9} sobre as variantes `por_tipo`, para a questão 3 do §12.

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

## 12. Questões do pesquisador

1. **`esperado` dos cenários:** respondida em 2026-10-18 (§4): três variações positivas com evolução bastam para `funciona`; sem evolução, `indeciso`.
2. **Critério de "variação útil":** respondida em 2026-10-18: superar o melhor valor anterior por qualquer quantidade (`variacao_util_epsilon = 0`), porque, conforme o problema, 1 % a 3 % já é melhora significativa. A simulação também mede `epsilon` = `δ` e = `sigma` só para comparação (§13, achado 1).
3. **Peso relativo de réplica em outro nó:** em aberto; a simulação varia `d_replica_no` (§5).
4. **Critério de aceite de uma variante:** as medidas estão no §5 (falsa validação, poder, custo por validação útil e a curva de compromisso). A proposta de valores vem com os resultados; o objetivo do pesquisador é minimizar o registro e a validação de hipóteses que não contribuem para a pesquisa.

## 13. Revisão com perfil de pesquisador (2026-10-18)

Revisão metodológica do desenho, pedida pelo pesquisador antes da aprovação. Os achados entram no catálogo e na simulação; nenhum muda a decisão do pesquisador sem nova consulta.

1. **Recordes por acaso.** Com ruído e variações sem efeito real, o melhor valor até agora é superado com frequência só por sorte: em `n` sorteios independentes, o número esperado de recordes é `1 + 1/2 + … + 1/n` (cerca de 3,6 em 20 tentativas). Com `variacao_util_epsilon = 0`, uma hipótese sem efeito e com 20 variações tende a acumular três "melhoras" e a ser validada. A simulação com `sem_efeito` mede essa taxa, e as comparações com `epsilon = δ` e `= sigma` mostram quanto ela cai. O pesquisador decide com os números.
2. **Alvo ignorado com baseline.** O veredito trata como positiva qualquer evidência acima do baseline + `δ`, mesmo abaixo do alvo do critério (no Iris, 0,80 > 0,333 + 0,01 conta a favor de "atinge 0,95"). O objetivo `limiar` exige os dois. Na etapa 1 isso não apareceu porque todos os resultados ficaram em 0,967. A família C e a alternativa `criterio_com_alvo` (§3.2) medem o efeito.
3. **Reúso do mesmo conjunto de teste.** Variações avaliadas sempre no mesmo conjunto de teste se ajustam a ele (análise adaptativa). A réplica em outro nó ou outro dataset é o que revela o otimismo da melhor variação. A família Q mede se a fórmula reduz o veredito quando a réplica não confirma.
4. **Métrica discreta.** Num conjunto de teste pequeno, uma melhora de 1 % a 3 % pode ser um único acerto, e valores repetidos são comuns. A família G e `--granularidade` da simulação medem esse caso.
5. **Exploração seguida de estagnação.** Depois de três melhoras, muitas variações sem ganho não deveriam desfazer o `funciona`, nem reforçá-lo. A família P mede os dois lados.
6. **Direção da métrica.** A família D confirma que a fórmula se comporta igual para métricas de erro (`menor_melhor`).
7. **Fora do escopo, registrado para depois:** dependência entre hipóteses do mesmo `Problema` (a mesma configuração testada sob duas hipóteses) e evidência vinda de outro projeto. Os dois casos ficam para `v18.8-verdict-calibration`.

Conclusão da revisão: o desenho responde às perguntas do ADR 025 para a etapa 2, com os seis acréscimos acima. Aprovação condicionada pelo pesquisador ("estando tudo certo pode considerar aprovado") e registrada com esta revisão em 2026-10-18.

## 14. Critério de aceite e saída da simulação (2026-10-18)

O pesquisador fixou **falsa validação de no máximo 2 %** (ADR 025 §4.2). A simulação passa a calcular, por variante e limiar, a falsa validação (maior entre `falsa` e `sem_efeito`), o pior ponto da grade, o poder e a falsa refutação, e imprime no `relatorio.md` a seção "Critério de aceite" (menor limiar da curva que respeita o teto, `--fv-max`, padrão 0,02). A tabela `aceite` também vai ao `resultados.csv`. A simulação não mede o volume sem ganho (a hipótese `sem_efeito` tem média no alvo, e metade dos resultados vira evidência negativa); por isso o critério de escolha da variante usa **os dois instrumentos**: teto de 2 % na simulação **e** acerto dos cenários de volume e de recordes por acaso na grade.

O comando `selecao --grade <resultados.csv> --simulacao <resultados.csv> [--fv-max 0.02]` combina os dois: para cada (variante, limiar) com linha `aceite` na simulação e linhas na grade com o mesmo limiar, aceita quando a falsa validação média é ≤ `--fv-max` **e** a variante não conclui `funciona` em nenhum cenário cujo esperado não é `funciona`. Escreve `resultados.csv` (linhas `selecao`), `relatorio.md` (aceitos por poder, e rejeitados pelo catálogo com os cenários) e `manifesto.json`. A grade e a simulação precisam ter os mesmos limiares.
