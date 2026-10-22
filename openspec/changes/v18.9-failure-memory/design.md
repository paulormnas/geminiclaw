# Design: v18.9-failure-memory

## 1. Estado atual
- `classify_failure` grava `causa_falha` e `assinatura_falha` em `Experimento` (`ingestion.py:891`).
- As assinaturas conhecidas são `oom`, `timeout_execucao`, `sem_metricas`, `validacao_indeterminada`, `criterio_nao_atendido`, `falha_execucao_sem_excecao` e `instalacao_pacotes`, além do nome da exceção quando o sandbox o informa.
- O Developer recebe o manifesto do workspace e a subtarefa, mas nenhuma falha anterior.

## 2. Itens

Cada item tem:

| Campo | Conteúdo |
|---|---|
| `escopo` | `ambiente` ou o nome canônico da abordagem |
| `assinatura` | A assinatura da falha |
| `ocorrencias` | Número de vezes que a falha ocorreu |
| `ultima_correcao` | Opcional |

`ultima_correcao` vem do experimento seguinte, do mesmo escopo, que terminou com métrica válida. Dele se registra apenas o identificador e a diferença de `config_normalizada` e dos pacotes declarados. Não entra texto de LLM.

O escopo `ambiente` reúne `instalacao_pacotes`, `oom`, `timeout_execucao` e `sem_metricas` (a primeira e a última têm causa `ambigua` no grafo, e as duas entram mesmo assim). O escopo da abordagem reúne as falhas de causa `abordagem` com assinatura própria (o tipo da exceção). Falhas de infraestrutura, `validacao_indeterminada` e `falha_execucao_sem_excecao` não entram: não dão ao Developer o que corrigir.

`criterio_nao_atendido` não entra: não é erro, é resultado. Ele já está no `RegistroResultado`.

## 3. Texto

Modelo fixo, uma linha por item, ordenado por ocorrências:

```
NÃO: <assinatura> em <escopo> (<n> vezes). USE: <diferença da correção> | sem correção conhecida
```

Os itens são truncados para caber em `FAILURE_MEMORY_MAX_CHARS`, e o que sobra é contado no evento.

| Variável | Padrão | Restrição |
|---|---|---|
| `FAILURE_MEMORY_MAX_CHARS` | 1500 | Inteiro ≥ 0; 0 desliga, para os braços de controle do E1 |

## 4. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Domínio | Nenhum conceito novo no grafo |
| Camadas | `knowledge` só lê; o agente recebe um bloco |
| Dados | Nenhuma mudança |
| Segurança | Ver §5 |
| Desempenho | Uma consulta por subtarefa, limitada ao projeto |
| Testes | Unitários com grafo em memória |

## 5. Segurança

O texto vem de assinaturas validadas por `_SIGNATURE_RE` e de diferenças de configuração, nunca de saída livre do sandbox. O bloco entra por `wrap_data`, como dado não confiável.
