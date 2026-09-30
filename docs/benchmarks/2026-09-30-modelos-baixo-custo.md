# Benchmark de modelos de baixo custo — relatório de 2026-09-30

**Status: ferramental pronto e validado; comparação de modelos não executada.** As três APIs disponíveis bloquearam a matriz (ver "Bloqueios"). Este relatório registra o que foi medido, o que foi corrigido e o que falta para rodar a matriz.

## Ambiente

Raspberry Pi 5 (8 GB, kernel 16K), agentes em processo (ADR 014), Qdrant v1.19.1 e PostgreSQL 16 em contêiner. Tarefa: pipeline de classificação Iris do `run.sh` (`~/bench/task.txt`). Modelos grandes (Claude Opus, GPT Astra/Sol, Gemini Pro) ficaram fora da matriz por decisão do pesquisador.

## Achados

| Item | Resultado |
|---|---|
| ID Gemini válido | `gemini-3.8-flash` (não `gemini-flash-3.8`). Fallback `gemini-3.7-flash`. `gemini-2.5-flash-lite` retorna 404 para contas novas |
| Modelos Google na API real | `3.8-flash`, `3.7-flash`, `3.5-flash-lite`, `3.1-flash-lite` completam chamada simples e ciclo de ferramenta (PR #82) |
| Bugs do provedor Google | papel `function` rejeitado (400); `thought_signature` ausente (400); `generate_content` síncrono travava o loop de eventos; tokens de pensamento subcontados; sem fallback em 429 |
| Bug herdado | tarefas de promoção de memória e extração de padrões usavam `agent_id="planner"`, papel inexistente no runtime; falhavam em silêncio (agora `base`) |
| Código morto | `agents/planner` e `agents/validator` removidos |
| Anthropic | a chave é válida, mas a conta responde `credit balance is too low`; a correção de capacidades por modelo (sem `effort`/fallback no Haiku 4.5) não pôde ser exercitada de verdade |
| OpenAI | `401 invalid_api_key` (provedor registrado como `openai_compatible`) |

## Execução exploratória (Google, plano gratuito)

`gemini-3.8-flash` com fallback `gemini-3.7-flash`, tarefa Iris completa, cerca de 40 min: **falhou**. Só 6 chamadas ao LLM tiveram sucesso (28.129 tokens de entrada, 6.733 de saída); as demais foram 429/503. A subtarefa `eda_iris` foi reprovada por artefatos ausentes. A cota gratuita é de 5 requisições/min e 20/dia por modelo, o que inviabiliza qualquer comparação de tempo ou acurácia.

## Recursos do Pi: validação do amostrador

A telemetria `hardware_snapshots` do projeto grava uma amostra por subtarefa e reporta CPU 0,0; não serve para picos. `scripts/benchmark/resources.py` amostra a cada 1 s (CPU do sistema, RAM, temperatura, `vcgencmd get_throttled`, CPU e RSS da árvore de processos). Teste com carga sintética no Pi (4 processos, 300 MB cada, 12 s):

| Grandeza | Medido | Esperado |
|---|---|---|
| CPU do sistema (máx) | 100 % | 100 % (4 núcleos saturados) |
| CPU da árvore | 402,5 % de um núcleo | ~400 % |
| RSS da árvore (máx) | 1234 MB | ~1200 MB |
| Temperatura (máx) | 67,2 °C | sobe com a carga |
| Throttling | nenhum | nenhum |

## Como rodar a matriz

```bash
cd ~/Documentos/Workspace/geminiclaw
uv run python -m scripts.benchmark.run_benchmark scripts/benchmark/matrix_baixo_custo.json --results ~/bench/results.json
uv run python -m scripts.benchmark.report ~/bench/results.json
```

A matriz (`matrix_baixo_custo.json`) cobre: Gemini 3.8 em todos os papéis; 3.7 em todos; Desenvolvedor 3.8 com 3.5-flash-lite ou 3.1-flash-lite nos demais; 3.5-flash-lite em todos; e, quando `ANTHROPIC_API_KEY` tiver crédito, Claude Haiku 4.5 em todos e misto Gemini 3.8 (Desenvolvedor) com Haiku. Métricas por combinação: tempo de parede, tokens de entrada e saída, custo estimado, subtarefas concluídas, checklist da tarefa (6 itens: EDA, pré-processamento, dois algoritmos, comparação com acurácia plausível 0,85–1,0, recomendação justificada, artefatos), acurácia relatada, picos de CPU/RAM/temperatura e throttling.

## Bloqueios para executar a matriz

1. Google: habilitar plano pago (ou outro projeto com cota) — a cota gratuita esgota em poucas chamadas.
2. Anthropic: adicionar crédito na conta da chave.
3. OpenAI: substituir a chave (`401`) e escolher um modelo barato.

Limitações do checklist: pontua artefatos e texto por padrões, não reexecuta o código gerado; a acurácia é a citada pelo pipeline.
