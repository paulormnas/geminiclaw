# Pré-registro do E2 (transferência: sem memória, memória plana, recorte do grafo, problema diferente)

**Data:** 2026-10-24 · **Mudança:** `v18.9-cross-project-context` e `v18.9-memory-evaluation` · **ADR:** 026 §6 e §7.
**Código avaliado:** `dev` com o PR dos modos do E2 mergeado (o commit entra no `manifesto` do relatório).
**Pré-condição:** o E1 terminou e o Pi foi atualizado para esse commit.

## Pergunta
Apresentar ao plano a experiência de Problemas semelhantes, selecionada e qualificada pelo grafo, melhora a pesquisa em
relação a não apresentar nada, a apresentar todos os registros sem seleção (memória plana) e a apresentar registros de
Problemas pouco semelhantes?

## Braços (matriz `scripts/benchmark/matrix_e2_transferencia.json`, `RELATED_RECORDS_MODE`)
| Braço | Modo | Bloco `experiencia_de_problemas_semelhantes` |
|---|---|---|
| `e2-glass-sem` | `sem` | ausente |
| `e2-glass-grafo` | `grafo` | até 5 Problemas com semelhança ≥ 0,60; melhor registro que atingiu o alvo e restrição mais recente; sem `retido`; com fatos, qualificação e limite |
| `e2-glass-plana` | `plana` | os mesmos Problemas, **todos** os registros (inclusive `retido`), só abordagem e valor |
| `e2-glass-distante` | `distante` | os 5 Problemas mais próximos **abaixo** de 0,60, com a seleção do `grafo` |

Idênticos no resto: tarefa Glass, todos os papéis `openai/gpt-6-luna` (`OPENAI_REASONING_EFFORT=medium`), Validator
`anthropic/claude-haiku-5-5`, `FAILURE_MEMORY_MAX_CHARS=1500`, teto por sessão US$ 1,5, 180 min, 3 M tokens, bancos
sem reset. **Corpus congelado:** `RELATED_RECORDS_CUTOFF` é o instante UTC de início da bateria (gravado em
`results.corte.txt`); Problemas criados depois (as próprias sessões do E2) não entram no bloco de nenhuma sessão.
O corpus visível é o do banco de benchmark do Pi (21 sessões do corpus, 4 problemas, mais as sessões do E1).

## Execuções e ordem
n = 5 por braço (20 sessões), por rodada, com a ordem dos braços rotacionada a cada rodada
(`scripts/memory_eval/run_battery.py`). Sessões que terminam por cota ou erro de infraestrutura do provedor são
reexecutadas uma vez e contadas à parte. Parada antecipada: gasto acumulado do E2 de US$ 5,00 na OpenAI ou US$ 3,00 na
Anthropic (o teto total do pesquisador é US$ 10 por provedor, E1 incluído); o corte é igual em todos os braços.

## Métricas (`scripts/memory_eval/metrics.py`, IC 95% por bootstrap das explorações)
- **Principal:** `taxa_sucesso` (objetivo atingido; alvo 0,80 do Glass).
- **Secundárias:** `ganho_base`, `taxa_validas`, `falhas_repetidas`; custo (US$) e tempo por sessão até o alvo.

## Regra de decisão
O bloco do grafo é **mantido ligado** se, em `taxa_sucesso`, o braço `grafo` superar o `sem` e não ficar abaixo de
`plana` nem de `distante`, com IC 95% que não se sobreponham ao de `sem`. Se os intervalos se sobrepuserem, o
resultado é "inconclusivo". **Extensão pré-registrada:** com resultado inconclusivo, a bateria é ampliada uma única vez
para n = 8 por braço, com a mesma matriz, o mesmo corte do corpus e a mesma regra; o relatório declara a ampliação e
reporta n = 5 e n = 8. Nenhuma outra mudança de configuração depois de ver os dados.

## Limitações já conhecidas
- Um problema alvo (Glass) cujo corpus tem 6 sessões do mesmo conjunto de dados: o braço `grafo` e o `plana` verão
  principalmente a experiência do próprio Glass, não transferência entre problemas distintos.
- O Developer e o Validator são os mesmos do E1; n pequeno; alta variância entre execuções.
- O falso positivo de validação no regime N do gerador (ADR 026 §7) não é medido aqui (exige o gerador controlado).
- Quatro braços de 5 execuções dão poder baixo; a extensão para 8 existe por isso.
