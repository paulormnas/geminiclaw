# Calibração do veredito: relatórios

Este diretório guarda os relatórios das etapas de calibração do veredito e de validação de parâmetros ([ADR 025](../decisions/adr_025_calibracao_do_veredito.md)). Os resultados de benchmark (baterias de sessões reais por combinação de modelos) ficam em [`docs/benchmarks/`](../benchmarks/).

Cada relatório registra a pergunta, os dados de entrada, o método, os resultados, a leitura e as limitações, com os comandos e o commit para reproduzir. Os textos servem de base para a descrição do método na dissertação.

| Data | Etapa (ADR 025 §3) | Relatório |
|---|---|---|
| 2026-10-18 | 1. Repetição offline sobre os grafos arquivados | [2026-10-18-etapa-1-repeticao-offline.md](2026-10-18-etapa-1-repeticao-offline.md) |
| 2026-10-18 | 2. Grade sintética, simulação e sensibilidade | [2026-10-18-etapa-2-grade-sintetica.md](2026-10-18-etapa-2-grade-sintetica.md) |
| 2026-10-18 | 2. Segunda rodada: variantes corrigidas e critério de 2 % de falsa validação | [2026-10-18-etapa-2b-criterio-de-2-por-cento.md](2026-10-18-etapa-2b-criterio-de-2-por-cento.md) |
| 2026-10-19 | Modelo v2 implementado no sistema | [2026-10-19-modelo-v2-implementado.md](2026-10-19-modelo-v2-implementado.md) |
| 2026-10-20 | 3. Falha de abordagem reproduzida: avaliação offline de `q` (seção 4 de `v18.8-verdict-controlled-sessions`) | [2026-10-20-etapa-3-falha-de-abordagem.md](2026-10-20-etapa-3-falha-de-abordagem.md) |
| 2026-10-21 | 3. Veredito perto de zero nas sessões controladas: decomposição, variantes e prior só na refutação | [2026-10-21-veredito-perto-de-zero.md](2026-10-21-veredito-perto-de-zero.md) |
