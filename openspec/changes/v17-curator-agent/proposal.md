# Proposta: Agente Curator

**ID:** `v17-curator-agent` · **Versão:** V17 · **Capacidade:** `curator`
**ADRs de origem:** [ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §1, §2, §6,
[ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §5, §7, §8, §9, §10

## Por quê

O ADR 012 criou o papel **Curator**: explorar os resultados e registrar as descobertas como
memória experimental — o que funciona, o que não funciona, oportunidades e caminhos sem
conclusão. O ADR 015 §10 definiu diretrizes rígidas: **revisar minuciosamente antes de criar**,
evitar duplicação e criar apenas nós significativos. Esta mudança implementa o Curator como
**registrador de conhecimento**; o ciclo ativo Curator ↔ Researcher (sugestões de caminho e
exploração contínua) é da mudança `v18-hypothesis-loop`.

## O que muda

- **Novo:** papel `curator` no `ModelRouter` e em `AGENT_DEFINITIONS` (executa em processo,
  ADR 014).
- **Novo:** ferramentas tipadas do Curator, com as diretrizes do §10 **aplicadas pelas
  próprias ferramentas** (não só pelo prompt): criar descoberta verifica duplicatas antes.
- **Novo:** serviço determinístico `KnowledgeService` que recalcula vereditos
  (`v17-evidence-verdict`), mantém as arestas `SUSTENTA`/`REFUTA` e os atalhos
  `FUNCIONOU_PARA`/`FALHOU_PARA`, e detecta configurações para promoção.
- **Novo:** ferramenta `flag_for_curator` para Researcher, Developer e Validator sinalizarem
  pontos importantes (ADR 012 §2).
- **Novo:** revisão da fila de similaridade (`v17-knowledge-semantic-index`) dentro do
  orçamento do Curator.
- **Novo:** registro de caminhos sem conclusão ao fim da sessão.
- **Modificado (schema do grafo):** `Abordagem` ganha `status` (`ativa` | `fundida`) e a
  relação `Abordagem-FUNDIDA_EM->Abordagem`, para tratar duplicatas surgidas na ingestão sem
  apagar nós.

## Impacto

- **Código:** `agents/curator/` (novo), `src/knowledge/service.py` (novo),
  `src/knowledge/curator_tools.py` (novo), `src/knowledge/schema.py`, `src/model_config.py`,
  `src/autonomous_loop.py`, `agents/base/tools.py` (`flag_for_curator`), `src/config.py`.
- **Custo:** chamadas LLM do Curator por sessão, limitadas por orçamento próprio.

## Aprovações necessárias

- Ajuste do schema do grafo (`Abordagem.status`, relação `FUNDIDA_EM`,
  `Descoberta.filtro_condicoes`) — aprovação explícita. É uma extensão pequena do modelo do
  ADR 015 (§8 prevê reutilizar ou criar variante no momento da criação, mas não trata
  duplicatas já existentes).
