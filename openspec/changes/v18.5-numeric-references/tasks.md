# Tarefas: v18.5-numeric-references

Pré-requisito: `v18.5-execution-provenance` implementada (registros e consulta por `exec_id`).

## 1. Sintaxe e resolução
- [ ] 1.1 `src/numeric_refs/syntax.py`: `find_references`, `find_malformed`, expressões regulares do design §1.
- [ ] 1.2 `save_experiment_artifacts`: parâmetro `unidades` e validação dos nomes de métrica.
- [ ] 1.3 `src/numeric_refs/resolver.py`: `res` pelo registro de término com conferência de sha256; `param.<nome>`.
- [ ] 1.4 `src/numeric_refs/units.py`: lista fechada de unidades.
- [ ] 1.5 `src/numeric_refs/calc.py`: avaliador com lista de permissão, funções, limites e regras de unidade.
- [ ] 1.6 `agents/researcher/tools.py`: registro em `fontes_busca.jsonl`.
- [ ] 1.7 Resolução de `src` (insumo com `hash_conteudo`; URL pelo registro; trecho com um único número).

## 2. Renderização e verificação
- [ ] 2.1 `src/numeric_refs/render.py`: formato pt-BR, códigos R/C/S, apêndice delimitado.
- [ ] 2.2 `src/numeric_refs/verifier.py`: algarismos, extenso, multiplicadores; exclusões X1–X9; marca `[não verificado]` sem alterar o texto.
- [ ] 2.3 Contagens do orquestrador para X8 (subtarefas, hipóteses, execuções etc.).
- [ ] 2.4 `src/numeric_refs/literal_metrics.py` (P1–P3) chamado em `CodeSkill.run`; `metricas_literais.json`.

## 3. Relatório e agentes
- [ ] 3.1 `src/report/pipeline.py` com `register_stage`/`register_section`; seção `execution-metadata`.
- [ ] 3.2 `src/numeric_refs/catalog.py`; substituir o bloco de métricas em `_synthesize_results` (via `EgressGate`).
- [ ] 3.3 Instrução do Summarizer (design §7.1) e gravação de `relatorio_final.fonte.md`; renomear o arquivo antigo quando presente.
- [ ] 3.4 Instrução e ferramentas do Curator (design §7.2), quando `v17-curator-agent` existir.
- [ ] 3.5 Instrução do Developer (unidades, sem literais).

## 4. Conversores
- [ ] 4.1 Registro de marcas em `base_converter.py`.
- [ ] 4.2 HTML, DOCX (inclusive células) e LaTeX (`xcolor`, `hyperref`).

## 5. Métricas
- [ ] 5.1 `proveniencia_numerica.json` e `NumericProvenanceReader` registrado em `src/operation_metrics.py`.

## 6. Testes (um por cenário da spec, no mínimo)
- [ ] 6.1 Parser: válidas, malformadas, nome inválido.
- [ ] 6.2 `res`: unidade, artefato alterado, execução órfã, `param.`.
- [ ] 6.3 `calc`: divergência percentual (valor ouro), nós proibidos (`__import__`, atributo, subscrição, lambda, comprehension), sem referência, unidades, divisão por zero, limites de tamanho e expoente. Teste que falha se `eval`/`exec` aparecer no módulo.
- [ ] 6.4 `src`: insumo, insumo alterado, URL não consultada, trecho ambíguo.
- [ ] 6.5 Verificador: tabela de casos pt-BR (algarismos, extenso, frações, multiplicadores, faixas, percentuais) e cada exclusão X1–X9, inclusive ano fora de contexto e contagem divergente.
- [ ] 6.6 Estática: P1, P2, P3, métrica calculada, execução não bloqueada.
- [ ] 6.7 Pipeline ponta a ponta com Summarizer simulado (mock de LLM) e conversores (HTML, DOCX, LaTeX).
- [ ] 6.8 Leitor de métricas.

## 7. Fechamento
- [ ] 7.1 `.env.example` com as variáveis `NUMREF_*`.
- [ ] 7.2 Sessões de referência com o prompt novo; registrar taxa de números não verificados no PR.
- [ ] 7.3 Ruff, `uv run pytest -m "unit or integration"`; revisão nos 7 eixos; PR para `dev`.
