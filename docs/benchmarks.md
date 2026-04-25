# Benchmarks GeminiClaw — Raspberry Pi 5 (8GB)

Este documento registra a performance comparativa entre provedores Cloud (Google Gemini) e Local (Ollama + Qwen) executando o cenário complexo S8.

## Ambiente de Teste
- **Hardware**: Raspberry Pi 5, 8GB RAM, NVMe SSD.
- **OS**: Raspberry Pi OS 64-bit.
- **Versão Ollama**: 0.1.32+.
- **Modelos**:
  - Cloud: `gemini-2.0-flash`
  - Local: `qwen3.5:4b` (quantizado)

## Resultados Comparativos

| Métrica | Google (gemini-2.0-flash) | Ollama (qwen3.5:4b) |
|---|---|---|
| Latência primeira resposta | ~1.5 s | ? s |
| Tempo total tarefa complexa | ~15 s | ? s |
| Qualidade do plano (1–5) | 5 | ? |
| Sucesso do tool calling (%) | 100% | ? |
| Uso de RAM Pi 5 | N/A | ~4.5 GB |
| Tokens/s Pi 5 | N/A | ~12 t/s |

## Observações
1. **Confiabilidade**: O modelo local `qwen3.5:4b` exige `STRICT_VALIDATION=false` para evitar re-planejamentos desnecessários por pequenas falhas de formatação JSON.
2. **Temperatura**: Durante a inferência local prolongada, a temperatura do Pi 5 sobe cerca de 10-15°C. Recomenda-se uso de Active Cooler.
3. **Vantagem Local**: 100% offline, latência zero de rede, privacidade total dos dados.
