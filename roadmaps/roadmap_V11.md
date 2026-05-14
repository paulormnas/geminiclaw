# Roadmap V11 — Refatoração e Integridade de Observabilidade

**Contexto:** Durante análises do banco de dados pós-execução do pipeline de validação, identificou-se que a infraestrutura de telemetria (evoluída nos Roadmaps V5/V9) apresenta lacunas críticas de integridade. O sistema sofre perda de registros devido ao mecanismo de *buffering* em processos efêmeros (containers dos agentes). Além disso, há imprecisões na captura de consumo de tokens (falha na leitura da estrutura de resposta) e um claro cenário de *over-engineering* na tabela de métricas de subtarefas, resultando em múltiplas colunas com 100% de valores nulos. Este roadmap foca na estabilização e precisão da camada de observabilidade.

---

## Objetivos Principais

1. **Persistência Garantida (Zero Data Loss)**: Assegurar que todos os eventos de telemetria, independentemente da duração da execução do agente, sejam persistidos no PostgreSQL.
2. **Precisão em LLM Metrics**: Corrigir a extração de dados de tokens e latência, extraindo as métricas reais informadas pelos provedores (Ollama/Google).
3. **Schema Lean e Eficiente**: Simplificar a tabela `subtask_metrics`, removendo agregações redundantes e movendo dados volumosos ou detalhados para os locais apropriados.
4. **Armazenamento Inteligente de Payloads**: Implementar um sistema híbrido para payloads extensos, garantindo a rastreabilidade sem inflar o banco de dados relacional.

---

## Detalhamento das Etapas

### V11.1 — Gerenciamento Estrito do Ciclo de Vida da Telemetria (Flush)
Atualmente, o `TelemetryCollector` utiliza um buffer de 50 itens para minimizar o I/O no banco. No entanto, agentes em containers (`agents/runner.py`) frequentemente terminam suas tarefas gerando menos de 50 eventos e encerram o processo sem realizar o flush.
* **Ação 1.1.1**: Adicionar uma chamada explícita para `telemetry.flush()` no bloco `finally` do loop principal em `agents/runner.py`. Isso garante que todo o uso de ferramentas e tokens seja gravado antes do encerramento do container.
* **Ação 1.1.2**: Aplicar a mesma lógica de flush explícito no script de entrada principal (`src/cli.py`), especificamente nas funções que finalizam a sessão do orquestrador ou que tratam sinais de interrupção (Ctrl+C).
* **Ação 1.1.3**: Avaliar a conversão do `TelemetryCollector` para um `AsyncContextManager` para uso mais limpo em blocos `async with`.

### V11.2 — Precisão e Granularidade em Métricas LLM
O arquivo `src/llm/agent_loop.py` possui bugs na forma como extrai os tokens e mede o tempo das ferramentas.
* **Ação 1.2.1**: Em `agent_loop.py`, corrigir o acesso de `getattr(response, "prompt_tokens", 0)` para extrair os dados do dicionário padronizado: `response.usage.get("prompt_tokens", 0)`.
* **Ação 1.2.2**: Corrigir a medição de tempo das ferramentas em `agent_loop.py`. Atualmente, `_start_iso` e `_now_iso` são definidos de forma quase simultânea *após* a execução. O timestamp de início deve ser registrado antes da invocação corrotina/função.
* **Ação 1.2.3**: Expandir o objeto `LLMResponse` nos provedores (`OllamaProvider` e `GoogleProvider`) para capturar e repassar métricas granulares como o *Time to First Token (TTFT)*, fundamental para avaliação de performance em hardwares limitados como o Pi 5.

### V11.3 — Refatoração do Schema de Subtarefas (`subtask_metrics`)
A tabela `subtask_metrics` tenta consolidar dados como média de CPU, picos de memória e total de tokens. Na prática, a injeção desses dados está fragmentada ou ausente no `Orchestrator`, resultando em colunas permanentemente nulas.
* **Ação 1.3.1**: Executar um comando SQL `ALTER TABLE` para remover as colunas `cpu_usage_avg`, `mem_usage_peak_mb`, `temp_delta_c` e `waiting_time_ms`. A saúde do hardware já é monitorada perfeitamente na tabela temporal `hardware_snapshots`.
* **Ação 1.3.2**: Remover a necessidade de atualizar contagens como `total_tokens` e `tools_used_count` diretamente na tabela `subtask_metrics`. 
* **Ação 1.3.3**: Criar uma `VIEW` no PostgreSQL chamada `vw_subtask_performance` que realiza um `LEFT JOIN` ou agregação em tempo real unindo as chaves da tabela `subtask_metrics` com contagens sumárias extraídas de `token_usage` e `tool_usage`.

### V11.4 — Rastreabilidade, Erros Estruturados e Payloads Grandes
Argumentos e respostas de ferramentas estão sendo truncados abruptamente. Precisamos manter o banco de dados leve, mas reter os logs completos para depuração.
* **Ação 1.4.1**: Implementar um sistema de "Payload Offloading". Para argumentos ou resultados de ferramentas superiores a 1000 caracteres, o `TelemetryCollector` deve salvar o payload em um arquivo de texto compactado (`.json.gz`) dentro do diretório `logs/<session_id>/payloads/` e inserir na tabela do banco apenas um caminho relativo (`file://logs/session/payloads/xyz.gz`).
* **Ação 1.4.2**: Refinar o campo `error_type` para utilizar códigos padronizados (ex: `AUTH_FAILURE`, `TIMEOUT`, `INVALID_FORMAT`, `OOM_KILLED`) em vez de aceitar apenas strings livres, facilitando futuras queries de agrupamento e estatística.

---

## Tarefas de Execução

### Fase 1: Correção Crítica de Persistência (Flush & Tokens)
- [x] Inserir `await telemetry.flush()` no encerramento de `agents/runner.py`.
- [x] Inserir chamadas de fechamento seguras em `src/cli.py`.
- [x] Refatorar a captura de `response.usage` no `agent_loop.py`.
- [x] Corrigir o timestamp de início nas chamadas de ferramentas no agente.

### Fase 2: Limpeza do Banco de Dados
- [x] Escrever script de migração para remover colunas nulas (`cpu_usage_avg`, `temp_delta_c`, etc) da tabela `subtask_metrics`.
- [x] Escrever e aplicar a definição da View SQL `vw_subtask_performance`.
- [x] Atualizar o comando de terminal `geminiclaw --metrics` para consultar a nova View em vez de tentar ler colunas obsoletas.

### Fase 3: Rastreabilidade Profunda
- [x] Adicionar funcionalidade de Payload Offloading no registro de `tool_usage`.
- [x] Definir o enumerador de categorias de erro em `src/telemetry.py` e adotá-lo no orquestrador.

---

## Critérios de Aceite

1. **Volume de Dados**: Ao executar tarefas simples (ex: classificar um pequeno input via modo interativo), a tabela `token_usage` deve imediatamente exibir ao menos um registro após a conclusão.
2. **Exatidão de Tokens**: Uma consulta SQL em `token_usage` deve revelar valores exatos, não aproximações baseadas no fallback do tamanho da string.
3. **Database Saudável**: `SELECT * FROM subtask_metrics LIMIT 10` não deve retornar colunas que possuam exclusivamente campos preenchidos com `NULL` após execuções ricas.
4. **Visão Analítica**: O comando `geminiclaw --metrics <session_id>` continuará exibindo as agregações de tokens e ferramentas por subtarefa sem quebrar, operando suavemente através da nova View.
