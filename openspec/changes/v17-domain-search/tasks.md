# Tarefas: v17-domain-search

## 0. Pré-requisitos
- [x] 0.1 `v17-controlled-vocabulary` (#96) e `v17-knowledge-semantic-index` mergeadas em `dev`.
- [x] 0.2 Worktree `.worktrees/feat-v17-domain-search`.

## 1. Texto canônico e payload hierárquicos
- [x] 1.1 `domain_canonical_text(node, ancestors)` puro (design §1) e a linha `Dominio` de `canonical_text`.
- [x] 1.2 Resolução dos ancestrais de um `Dominio` por `SUBAREA_DE`, com `caminho_completo` e aviso estruturado.
- [x] 1.3 Payload `nivel`, `caminho_ids`, `caminho_termos`, `caminho_completo`, `codigo_cnpq`; índice de payload
  `keyword` em `caminho_ids` e em `nivel`.
- [x] 1.4 Cálculo do `text_hash` com ancestrais e marcação dos descendentes como `pendente` em lotes
  (`DOMAIN_REINDEX_BATCH`) ao mudar termo ou sinônimo de um ancestral.
- [x] 1.5 Testes dos cenários de "Texto canônico e payload hierárquicos" e "Reconciliação por ancestral".

## 2. Busca
- [x] 2.1 `DomainHit` e `DomainSearch.search` (design §4), com filtros por subárvore, nível e status.
- [x] 2.2 Preferência pelo nível mais específico dentro da margem; limiar mínimo; limite máximo.
- [x] 2.3 Validação da entrada (tamanho, vazio) e `ValueError`/truncamento registrado.
- [x] 2.4 Testes dos cenários de "Busca hierárquica de domínios" com embeddings simulados determinísticos.

## 3. Integração com `resolve_domain`
- [x] 3.1 Passo semântico de `resolve_domain` usa `DomainSearch` (design §5), com `alternativas`.
- [x] 3.2 Preservar o `semantic_search` injetável; testes de regressão do #96.

## 4. Ferramenta `buscar_dominio`
- [x] 4.1 `src/skills/vocabulary/skill.py` somente leitura; saída curta e estável; limites do design §6.
- [x] 4.2 Registro para `researcher` e `curator` (o `curator` ainda não existe: tarefa 3.3 em `v17-curator-agent`); instrução curta no prompt do Researcher.
- [x] 4.3 Evento `domain_search` sem o texto da consulta.
- [x] 4.4 Testes dos cenários de "Ferramenta `buscar_dominio`".

## 5. Avaliação do modelo
- [x] 5.1 `tests/fixtures/domain_queries.jsonl` com 41 consultas (pt e en); versão inicial genérica, **pendente de revisão do pesquisador**.
- [x] 5.2 `scripts/eval_domain_search.py` (`hit@1`, `hit@3`, posição média, por idioma).
- [ ] 5.3 Rodar a avaliação no Pi 5 com o modelo padrão e com um multilíngue; anexar o relatório ao PR.

## 6. Fechamento
- [x] 6.1 Variáveis do design §7 em `src/config.py` e `.env.example`, com teste dos padrões.
- [x] 6.2 `uv run ruff check .`; suíte `-m "unit or integration"` (nenhum teste baixa modelo nem usa rede).
- [ ] 6.3 Reindexação dos 1335 domínios no Pi 5 e medição do tempo de indexação e de consulta.
- [ ] 6.4 Revisão do Analista de Segurança (entrada da ferramenta e telemetria); revisão nos 7 eixos; PR para
  `dev`; arquivar a mudança e consolidar `specs/domain-search/spec.md` depois do merge.
