# Pré-registro do E1 (memória de falhas, com e sem)

**Data:** 2026-10-24 · **Mudança:** `v18.9-failure-memory` e `v18.9-memory-evaluation` · **ADR:** 026 §5 e §7.
**Código avaliado:** `dev` no commit `09585a4` (sem `v18.9-cross-project-context`; o Pi roda exatamente este commit).

## Pergunta
Apresentar ao Developer a memória das falhas já vistas no projeto (`FAILURE_MEMORY_MAX_CHARS=1500`) reduz as falhas
repetidas e aumenta as execuções válidas, em relação à mesma configuração sem o bloco (`FAILURE_MEMORY_MAX_CHARS=0`)?

## Braços (matriz `scripts/benchmark/matrix_e1_memoria_falhas.json`)
| Braço | Configuração |
|---|---|
| `e1-glass-com-memoria` | `FAILURE_MEMORY_MAX_CHARS=1500` |
| `e1-glass-sem-memoria` | `FAILURE_MEMORY_MAX_CHARS=0` |

Idênticos no resto: tarefa Glass Identification (`task_glass.txt`), todos os papéis `openai/gpt-6-luna`
(`OPENAI_REASONING_EFFORT=medium`) e Validator `anthropic/claude-haiku-5-5` (família diferente da do Developer).
Teto por sessão `SESSION_MAX_COST_USD=1.5`, 180 min, 3 M tokens. Cada execução cria um projeto novo; **sem reset** dos
bancos (a memória de falhas é do projeto e nada entre projetos é lido neste commit).

## Execuções e ordem
n = 8 por braço, alternadas (com, sem, com, sem, …) para distribuir variações de horário e de provedor. Sessões que
terminam por cota ou erro de infraestrutura do provedor são reexecutadas uma vez e contadas à parte; não entram nas
métricas. Parada antecipada: gasto acumulado do E1 de US$ 5,00 na OpenAI ou US$ 3,00 na Anthropic (o restante do
teto de US$ 10 por provedor fica para o E2); se parar antes de n = 8, ambos os braços são cortados no mesmo n.

## Métricas (`scripts/memory_eval/metrics.py`, IC 95% por bootstrap das explorações)
- **Principal:** `falhas_repetidas` (fração das falhas cuja assinatura e escopo já ocorreram antes na exploração).
- **Secundárias:** `taxa_validas`, `taxa_sucesso` (alvo 0,80 do Glass), `ganho_base`; custo e tempo por sessão.

## Regra de decisão
A memória de falhas é **mantida ligada por padrão** se `falhas_repetidas` do braço com memória for menor que a do braço
sem memória **e** `taxa_validas` do braço com memória não for menor. Com n = 8 por braço os intervalos serão largos: se
os IC 95% de `falhas_repetidas` se sobrepuserem, o relatório diz "inconclusivo" (sem afirmar efeito) e registra a
direção e o tamanho observados. Nenhuma outra métrica muda a decisão.

## Limitações já conhecidas
- Um único problema (Glass), um modelo de Developer e n pequeno; o resultado não generaliza.
- Variância entre execuções do mesmo braço é alta (lição do benchmark de 2026-10-13).
- O número de falhas por sessão pode ser baixo; sessões sem falha não contribuem para `falhas_repetidas` (a fração é
  calculada sobre o total de falhas do braço) e o relatório informa o total de falhas de cada braço.
