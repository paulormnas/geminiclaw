# Bateria com LLMs locais no servidor LLAMA: resultados parciais (2026-10-24)

Corpus de memória da V18.9 (Iris, Wine, Glass, Cancer), modo `auto`, `dev` em `40b1854`. Servidor `ssh LLAMA` (2x RTX 6000 Ada
48 GB, **compartilhado**), modelos open weights servidos por vLLM 0.32.0 com FP8: **Qwen3.8-27B** (GPU 0) e **Gemma 4 31B**
(GPU 1), atrás de um roteador por `model` (`OPENAI_COMPATIBLE_BASE_URL`). Matriz `scripts/benchmark/matrix_llms_locais.json`
(8 combinações, cada modelo como Developer com o outro como Validator), **uma repetição por combinação**, reset isolado do
banco `geminiclaw_bench_local` e do Qdrant a cada combinação. Custo US$ 0 (modelos locais). A bateria foi **interrompida a
pedido do pesquisador** para liberar o servidor; Cancer não rodou. Dados brutos em
`/mnt/hd4/prnascimento/bench/results-llms-locais.json` no servidor (932 KB, não versionado).

| Combinação | Resultado | Tempo | Chamadas | Tokens totais | Subtarefas aprovadas |
|---|---|---|---|---|---|
| `qwen-dev-gemma-juiz-iris` | `solucao_encontrada` (exit 0), texto 6/6, acurácia declarada 1,0 | 98 min | 118 | 1,70 M | 5 de 6 |
| `gemma-dev-qwen-juiz-iris` | `solucao_encontrada` (exit 0), texto 6/6, acurácia declarada 1,0 | 51 min | 77 | 0,92 M | 9 de 10 |
| `qwen-dev-gemma-juiz-wine` | `solucao_encontrada` (exit 0), texto 5/6, acurácia declarada 1,0 | 31 min | 61 | 0,76 M | 4 de 7 |
| `gemma-dev-qwen-juiz-wine` | `solucao_encontrada` (exit 0), texto 6/6, acurácia declarada 1,0 | 21 min | 41 | 0,44 M | 6 de 7 |
| `qwen-dev-gemma-juiz-glass` | `erro` (exit 1): disjuntor de zero progresso | 87 min | 153 | 2,53 M | 3 de 5 |
| `gemma-dev-qwen-juiz-glass` | **interrompida** após ~6 h, sem registro nos resultados | ~6 h | 158 | 2,04 M | 13 concluídas e 2 abandonadas de 15 (checkpoint `em_execucao`) |
| `qwen-dev-gemma-juiz-cancer`, `gemma-dev-qwen-juiz-cancer` | não rodaram | | | | |

"Texto" é a conferência por texto do relatório final (EDA, pré-processamento, dois algoritmos, comparação, recomendação,
artefatos); a acurácia declarada é a que o relatório afirma, não a validada pelo Validator.

## Leituras

1. **Os dois modelos fecham Iris e Wine** de ponta a ponta (plano, experimentos, relatório, proveniência) sem nuvem.
2. **Glass é o problema difícil**: com Qwen como Developer, o plano exigia baseline majoritário entre 0,75 e 0,90 e o
   valor real é 0,3488 (a classe majoritária do Glass tem ~35 %); a subtarefa de revisão reprovou, quatro subtarefas
   falharam e o disjuntor encerrou. Com Gemma como Developer a sessão seguiu por 6 h, replanejando 6 vezes, sem fechar.
   Não é possível dizer, com uma repetição, se a causa é o modelo, o plano ou o enunciado.
3. **Velocidade** (medida com um pedido por vez no smoke test): Qwen ~29 tok/s e Gemma ~25 tok/s; com 8 pedidos em
   paralelo, ~186 e ~154 tok/s agregados. Taxas efetivas nos nossos testes com provedores em nuvem: Haiku ~285, Sonnet
   ~196, Luna ~107, Argon ~88 e Sol ~45 tok/s. O tempo por sessão local (21 a 98 min no Iris/Wine) é dominado pelas
   chamadas longas do Researcher (média de 170 s com Gemma).

## Defeitos encontrados

1. **`arguments` como dict no histórico de ferramentas** (corrigido, PR #252): o `openai_compatible` enviava
   `tool_calls[].function.arguments` como objeto; o vLLM respondia 400 na segunda volta de todo laço de ferramentas, o
   Researcher terminava em `error` e a sessão fechava com `planos_rejeitados`. Era a causa raiz das tentativas 1 a 5.
2. **Timeout fixo de 120 s e `max_tokens` de 4096** (corrigidos, PRs #250 e #251): variáveis
   `OPENAI_COMPATIBLE_TIMEOUT_SECONDS` e `OPENAI_COMPATIBLE_MAX_TOKENS`.
3. **Raciocínio do Qwen**: com ele ligado o modelo consumiu os 16384 tokens só pensando (`finish_reason=length`,
   conteúdo vazio). Todas as combinações acima rodaram com `enable_thinking: false`. Comparar com raciocínio ligado
   continua em aberto agora que o defeito 1 foi corrigido.
4. **Compressão de contexto pode descartar o primeiro turno de usuário** (**aberto**):
   `context_compression._truncate_by_priority`, com o orçamento de `OLLAMA_NUM_CTX=40000`, deixou duas requisições do
   Researcher sem mensagem `user`; o template do Qwen recusa ("No user query found in messages", 400). Duas ocorrências no
   Glass, a sessão se recuperou. Um provedor tolerante não acusaria o problema.

## Pendências

- Glass com Gemma como Developer (retomar o checkpoint ou refazer) e as duas combinações do Cancer.
- Smoke test e fase B com **Qwen3-Coder-Next 4 bits** (AWQ, TP=2) como Developer e Gemma w4a16 como Validator.
- Corrigir o defeito 4 e repetir o Glass; decidir sobre o raciocínio do Qwen.

## Limites da evidência

Uma repetição por combinação não ordena modelos nem separa efeito do modelo, do plano e do problema. Os tempos incluem
um servidor compartilhado (outro usuário ocupou ~40 GB de uma GPU durante a preparação).
