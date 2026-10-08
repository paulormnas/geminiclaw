# Tarefas: v18.5-numeric-references

**Estado (2026-10-08):** Implementada na branch `feat/v185-numeric-references` (PR aberto, empilhado sobre `feat/v185-execution-provenance`); sessões de referência e medições no Pi ficam para a bateria final.

Pré-requisito: `v18.5-execution-provenance` implementada (registros e consulta por `exec_id`).

## 1. Sintaxe e resolução
- [x] 1.1 `src/numeric_refs/syntax.py`: `find_references`, `find_malformed`, expressões regulares do design §1.
- [x] 1.2 `save_experiment_artifacts`: parâmetro `unidades` e validação dos nomes de métrica.
- [x] 1.3 `src/numeric_refs/resolver.py`: `res` pelo registro de término com conferência de sha256; `param.<nome>`.
- [x] 1.4 `src/numeric_refs/units.py`: lista fechada de unidades.
- [x] 1.5 `src/numeric_refs/calc.py`: avaliador com lista de permissão, funções, limites e regras de unidade.
- [x] 1.6 `agents/researcher/tools.py`: registro em `fontes_busca.jsonl`. *(Em `src/numeric_refs/sources.py`; `agents/researcher/tools.py::search` registra cada resultado devolvido.)*
- [x] 1.7 Resolução de `src` (insumo com `hash_conteudo`; URL pelo registro; trecho com um único número).

## 2. Renderização e verificação
- [x] 2.1 `src/numeric_refs/render.py`: formato pt-BR, códigos R/C/S, apêndice delimitado.
- [x] 2.2 `src/numeric_refs/verifier.py`: algarismos, extenso, multiplicadores; exclusões X1–X9; marca `[não verificado]` sem alterar o texto.
- [x] 2.3 Contagens do orquestrador para X8 (subtarefas, hipóteses, execuções etc.).
- [x] 2.4 `src/numeric_refs/literal_metrics.py` (P1–P3) chamado em `CodeSkill.run`; `metricas_literais.json`.

## 3. Relatório e agentes
- [x] 3.1 `src/report/pipeline.py` com `register_stage`/`register_section`; seção `execution-metadata`. *(O relatório atual já separa narrativa (LLM, JSON) e tabelas (orquestrador); o pipeline renderiza o texto fonte `relatorio_final.fonte.md`, e as seções medidas ficam entre marcadores X2 (`report-results`, `researcher-decisions`, `execution-metadata`, `provenance-chain`).)*
- [x] 3.2 `src/numeric_refs/catalog.py`; substituir o bloco de métricas em `_synthesize_results` (via `EgressGate`).
- [x] 3.3 Instrução do Summarizer (design §7.1) e gravação de `relatorio_final.fonte.md`; renomear o arquivo antigo quando presente. *(Como o Summarizer devolve narrativa em JSON, o texto fonte é a montagem do orquestrador; o arquivo `relatorio_final.fonte.md` é gravado antes do pipeline.)*
- [x] 3.4 Instrução e ferramentas do Curator (design §7.2), quando `v17-curator-agent` existir.
- [x] 3.5 Instrução do Developer (unidades, sem literais).

## 4. Conversores
- [x] 4.1 Registro de marcas em `base_converter.py`.
- [x] 4.2 HTML, DOCX (inclusive células) e LaTeX (`xcolor`, `hyperref`).

## 5. Métricas
- [x] 5.1 `proveniencia_numerica.json` e `NumericProvenanceReader` registrado em `src/operation_metrics.py`. *(`proveniencia_numerica.json` e `NumericProvenanceReader` prontos; o registro em `src/operation_metrics.py` entra com `v18.5-operation-metrics`, que ainda não existe.)*

## 6. Testes (um por cenário da spec, no mínimo)
- [x] 6.1 Parser: válidas, malformadas, nome inválido.
- [x] 6.2 `res`: unidade, artefato alterado, execução órfã, `param.`.
- [x] 6.3 `calc`: divergência percentual (valor ouro), nós proibidos (`__import__`, atributo, subscrição, lambda, comprehension), sem referência, unidades, divisão por zero, limites de tamanho e expoente. Teste que falha se `eval`/`exec` aparecer no módulo.
- [x] 6.4 `src`: insumo, insumo alterado, URL não consultada, trecho ambíguo.
- [x] 6.5 Verificador: tabela de casos pt-BR (algarismos, extenso, frações, multiplicadores, faixas, percentuais) e cada exclusão X1–X9, inclusive ano fora de contexto e contagem divergente.
- [x] 6.6 Estática: P1, P2, P3, métrica calculada, execução não bloqueada.
- [x] 6.7 Pipeline ponta a ponta com Summarizer simulado (mock de LLM) e conversores (HTML, DOCX, LaTeX).
- [x] 6.8 Leitor de métricas.

## 7. Fechamento
- [x] 7.1 `.env.example` com as variáveis `NUMREF_*`.
- [ ] 7.2 Sessões de referência com o prompt novo; registrar taxa de números não verificados no PR.
- [ ] 7.3 Ruff, `uv run pytest -m "unit or integration"`; revisão nos 7 eixos; PR para `dev`. *(Parcial: unitários verdes e `ruff` limpo nos arquivos novos.)*
