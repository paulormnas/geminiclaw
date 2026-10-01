# Tarefas: v20-remote-knowledge-intake

## 0. Pré-requisitos
- [ ] 0.1 `v20-federated-records`, `v20-federation-transport` e `v17-knowledge-semantic-index` concluídas.
- [ ] 0.2 Aprovação do schema (`federation_trust`, `triagem`) e respostas às questões do design §10.

## 1. Entrada
- [ ] 1.1 `src/federation/intake.py`: validação completa, estados, revogação e rotação.
- [ ] 1.2 `src/federation/relevance.py`: texto canônico por tipo, embedding local, faixas, pontuação.
- [ ] 1.3 `src/federation/trust.py`: lista de confiança, silenciados, reputação.
- [ ] 1.4 Migração do schema.

## 2. Pesquisador
- [ ] 2.1 CLI `federation inbox|show|import|dismiss|trust|mute-author`.
- [ ] 2.2 `src/federation/importer.py`: oportunidade `documentada`, descoberta `externa`, problema como referência.
- [ ] 2.3 Correções e retratações com avisos.

## 3. Texto remoto
- [ ] 3.1 `ContentOrigin.REMOTO`, delimitadores, limpeza e limite; teste de política: nenhuma ferramenta de agente importa ou aprova.
- [ ] 3.2 Descobertas externas excluídas do cálculo de veredito.

## 4. Testes
- [ ] 4.1 Assinatura forjada; registro válido fora do grafo; chave revogada.
- [ ] 4.2 Sem chamada de LLM; entre domínios; pouco relevante.
- [ ] 4.3 Limite do resumo.
- [ ] 4.4 Importação de oportunidade; agente sem acesso; veredito inalterado.
- [ ] 4.5 Reputação com desconhecidos e com confiável.
- [ ] 4.6 Injeção no enunciado; nada em prompt antes da importação.
- [ ] 4.7 Retratação de importado.

## 5. Fechamento
- [ ] 5.1 `.env.example`; `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 5.2 Revisão do Analista de Segurança e testes do Pentester (registros maliciosos); revisão nos 7 eixos; PR para `dev`.
