# Benchmark de modelos de baixo custo: resultados de 2026-10-01

Tarefa: pipeline de classificação supervisionada do dataset Iris (`run.sh`), modo autônomo, uma execução por combinação, no Raspberry Pi 5 (8 GB). Substitui o relatório de 2026-09-30, que registrava só o ferramental e os bloqueios.

## Resultado em uma frase

Só duas combinações concluíram o pipeline inteiro (todas as subtarefas aprovadas e relatório final): **Gemini 3.1-flash-lite nos papéis de apoio com Gemini 3.8 no desenvolvedor** (a mais barata e rápida) e **Gemini 3.7-flash em todos os papéis** (a mais cara das completas). Nenhuma combinação com GPT-6 Luna ou Claude Sonnet 5.5 concluiu a tarefa.

## Tabela

| Combinação | Status | Tempo (s) | Tokens in | Tokens out | Subtarefas ok | Checklist | Acurácia | CPU sis. máx (%) | RAM máx (MB) | Temp máx (°C) | Throttling | Custo (USD) | Retentativas |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| google-3.8-todos | exit 0 | 469.2 | 460344 | 55041 | 3/4 | 6/6 | 0.967 | 30.8 | 1421.7 | 61.7 | não | 0.4859 | 0 |
| google-3.7-todos | exit 0 | 374.2 | 670660 | 47001 | 6/6 | 6/6 | 0.958 | 31.8 | 1422.8 | 60.6 | não | 0.5384 | 0 |
| google-3.8-dev-3.5lite-demais | exit 0 | 189.9 | 108177 | 21109 | 0/1 | 6/6 | 0.933 | 32.2 | 1442.7 | 60.6 | não | 0.1315 | 0 |
| google-3.8-dev-3.1lite-demais | exit 0 | 248.9 | 180649 | 23742 | 4/4 | 6/6 | 0.953 | 31.2 | 1432.9 | 61.15 | não | 0.1575 | 0 |
| openai-luna-todos | exit 0 | 486.8 | 445706 | 52210 | 0/0 | 3/6 | - | 33.7 | 1236.1 | 59.5 | não | 0.0707 | 0 |
| misto-3.8dev-luna-pesquisa | exit 0 | 1201.2 | 182071 | 27052 | 0/2 | 4/6 | - | 31.0 | 1281.4 | 60.05 | não | 0.0639 | 0 |
| misto-3.8dev-sonnet-pesquisa | exit 0 | 699.8 | 498387 | 71430 | 2/3 | 4/6 | - | 32.2 | 1413.3 | 61.7 | não | 1.0601 | 0 |
| sonnet-todos | exit 0 | 629.4 | 286422 | 82418 | 1/4 | 4/6 | - | 31.2 | 1322.4 | 60.6 | não | 1.3970 | 0 |

- Tokens e custo vêm do Postgres (`token_usage`) e incluem todas as chamadas: agentes, triagem, Validator, Reviewer e sumarização.
- Checklist (0 a 6) e acurácia vêm de `scripts/benchmark/scoring.py`: leem os artefatos da sessão, não reexecutam o código, e a acurácia é a de teste declarada pelo pipeline em `metrics.json` ou nos relatórios.
- CPU é a média de todos os núcleos do sistema; RAM é a usada no sistema inteiro (inclui Postgres e Qdrant).

## Recursos do Raspberry Pi 5 (avaliação do projeto)

| Grandeza | Pico em todas as execuções |
|---|---|
| CPU do sistema | 33,7 % |
| Memória usada (sistema) | 1443 MB de ~8 GB (~18 %) |
| Temperatura | 61,7 °C |
| Throttling / subtensão | nenhum |

O orquestrador e os agentes em processo mal pesam: o gargalo é a espera pela API, não o hardware. A amostragem é de 1 s, então picos mais curtos do sandbox Python podem passar despercebidos.

## Por que as combinações falharam

| Combinação | Causa observada |
|---|---|
| Gemini 3.8 (todos) | 3 de 4 subtarefas ok; a última foi reprovada pelo revisor por artefatos ausentes (`confusion_matrices.png`) |
| Desenvolvedor 3.8 + 3.5-lite | Circuit breaker de "zero progresso" depois de 1 subtarefa |
| GPT-6 Luna (todos) | O Validator nunca aprovou o plano; sessão interrompida pelo limite de 30 execuções de agente. O Luna chamou `ask_researcher` 10 vezes em modo autônomo, e todas falharam |
| Misto Luna / Sonnet, Sonnet (todos) | O revisor LLM reprovou subtarefas por critérios de forma (caminho citado diferente do caminho em disco, "log de execução não apresentado") e o circuit breaker encerrou a sessão |

As reprovações de Luna e Sonnet parecem vir mais da rigidez do revisor e do circuit breaker do que da qualidade dos modelos: ambos geraram artefatos. Com uma execução por combinação e variância alta (o Gemini 3.8 completo e o 3.5-lite abortado usam o mesmo modelo no desenvolvedor), **a diferença entre as combinações não é estatisticamente sustentável**. Para conclusões firmes, repita cada combinação (3 a 5 vezes) e reveja o critério do revisor.

## Gasto

| Provedor | Gasto no benchmark |
|---|---|
| Anthropic (Sonnet 5.5, esforço `low`) | US$ 2,08 de US$ 20 |
| OpenAI (GPT-6 Luna) | US$ 0,10 |
| Google (Gemini, plano pago) | US$ 1,73 |

## Defeitos encontrados e corrigidos pelo benchmark

1. Provedor Google: papel `function`, `thought_signature`, chamada síncrona no event loop, tokens de pensamento (PR #82).
2. Custo nunca calculado; chamadas de triagem, sumarização, Validator e Reviewer fora de `token_usage`; buffer de telemetria defasado (PR #84).
3. `max_tokens` baixo consumido pelo raciocínio do Gemini (PR #86).
4. Revisor não achava artefatos gravados em `<subtarefa>/`; `gpt-6-luna` recusava ferramentas com raciocínio ativo; erro HTTP sem corpo (PR #87).
5. Runner perdia tokens quando a sessão abortava sem `session_metadata.json` e lia como acurácia um exemplo do `scientific_helpers.py` (este PR).

## Próximos passos sugeridos

- Repetir a matriz com 3 a 5 execuções por combinação e reportar médias e desvios.
- Revisar o rigor do revisor LLM e o circuit breaker de "zero progresso" (o critério de caminho exato de artefato reprova resultados válidos).
- Impedir `ask_researcher` em modo autônomo (a ferramenta nem deveria ser oferecida ao modelo).
- Variar `OLLAMA_NUM_CTX` (4096 por padrão, também aplicado a modelos de nuvem) para medir o efeito da compressão de contexto na acurácia.
