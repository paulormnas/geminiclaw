# Proposta: Ingestão de Dados de Pesquisa sem Valores Brutos

**ID:** `v18.5-research-data-ingestion` · **Versão:** V18.5 · **Capacidade:** `research-data`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md)
§3.1, §3.2, §3.3 (e a parte de visão do §3.5); revisa a Spec G9 (`input_context/`)
**Depende de:** `v18.5-egress-gate` (`PromptFragment`, `ContentOrigin`, `EgressGate`,
`classify_path`, `LOCALITY_MIN_GROUP_SIZE`)

## Por quê

`ContextBundle.to_prompt_context()` injeta no prompt do planejador as 5 primeiras linhas de
cada dataset e, por coluna, mínimo, máximo e média (`src/context_loader.py:119-122`,
`:413-440`), que são valores de registros, qualquer que seja o destino. JSON não tabular leva
até 5 registros (`:394-409`). Imagens são descritas pelo Gemini Vision por chamada direta, com
modelo fixo e fora da camada de provedores (`:472-497`), e o texto de OCR local de imagens e
PDFs escaneados vai ao prompt sem distinção de origem (`:335-354`, `:454-470`). O pesquisador
não tem como dizer que um dataset é público nem que um PDF contém medições.

## O que muda

- **Novo:** manifesto `input_context/dados.yaml` com marcações por arquivo:
  `compartilhavel` (ex.: dataset público) e `dado_de_pesquisa` (ex.: caderno de laboratório em
  PDF). As marcações ficam no payload da sessão, no `input_snapshot/` e no relatório final.
- **Modificado:** a ingestão produz, para cada arquivo, trechos rotulados em vez de um bloco
  único: um trecho `esquema_agregado` (esquema, metadados, descritores de formato e
  estatísticas pela regra de k, extremos só como faixa) e, quando houver, um trecho
  `dado_de_pesquisa` (amostras e estatísticas exatas), que o `EgressGate` só entrega a
  destinos com `aceita_dados_brutos` ou quando o arquivo é compartilhável.
- **Modificado:** visão passa pela camada de provedores e pelo `EgressGate`, com modelo do
  catálogo configurável (`VISION_MODEL`); `OCR_PROVIDER=gemini` vira alias obsoleto.
- **Modificado:** texto de OCR de imagens e de PDFs escaneados que são dados de pesquisa é
  `dado_de_pesquisa`.
- **Fora do escopo:** filtro de saída do sandbox e restrição de leitura no host
  (`v18.5-egress-gate`); dados produzidos pelas execuções (classificação padrão da
  `v18.5-egress-gate`).

## Impacto

- **Código:** `src/context_loader.py`, `src/research_data/manifest.py` (novo),
  `src/egress/classification.py` (extensão), `src/llm/vision.py` (novo),
  `src/llm/providers/{google,ollama}.py` (imagem), `src/orchestrator.py` (snapshot, payload,
  seção do relatório), `src/cli.py` (banner, README de `input_context/`), `src/config.py`,
  `.env.example`.
- **Comportamento:** com modelos sem `aceita_dados_brutos`, o planejador deixa de ver amostras
  e extremos exatos; passa a ver descritores de formato. A primeira leitura de dados pelo
  Developer pode exigir mais tentativas (ADR 019, Consequências).
- **Compatibilidade:** `input_context/` sem `dados.yaml` funciona com a classificação padrão.
  `ContextBundle.to_prompt_context()` é mantido, mas passa a devolver só a versão segura (sem
  trechos `dado_de_pesquisa`).

## Aprovações necessárias

Nenhuma alteração de schema de banco, Dockerfile ou compose; nenhum arquivo apagado. As
marcações ficam no payload JSONB da sessão.
