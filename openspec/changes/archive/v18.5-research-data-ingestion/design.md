# Design: Ingestão de Dados de Pesquisa sem Valores Brutos

## 0. Estado atual (verificado no código em 2026-09-29)

| Ponto | Onde | Situação |
|---|---|---|
| Renderização do bundle | `src/context_loader.py:97-135` | Um bloco de texto único; `:121` injeta "Amostra (5 primeiras linhas)" e `:122` as estatísticas. |
| Resumo tabular | `src/context_loader.py:413-440` | `describe()` com `min`, `max`, `mean` (`:417-426`); `head(5)` (`:428`). |
| JSON não tabular | `src/context_loader.py:394-409` | `sample_rows=records[:5]`. |
| Serialização | `src/context_loader.py:137-179` | `to_dict()` inclui `sample_rows` e `stats`. |
| Imagens | `src/context_loader.py:442-452` | `OCR_PROVIDER` (`src/config.py:214`) escolhe OCR local ou Gemini. |
| Gemini Vision | `src/context_loader.py:472-497` | `genai.Client` direto, modelo fixo `gemini-2.0-flash`, fora de `src/llm/`. |
| OCR local | `src/context_loader.py:335-354` (PDF escaneado), `:454-470` (imagem) | Texto vai ao prompt como documento. |
| Varredura | `src/context_loader.py:247` | Ignora só `README.md`. |
| Uso no plano | `src/orchestrator.py:322-327`, `:1200` | `to_prompt_context()` no prompt do planejador. |
| Snapshot | `src/orchestrator.py:474-500` | Copia os arquivos usados para `input_snapshot/`. |
| Carregamento na CLI e banner | `src/cli.py:517`, `:729-760` | Lista arquivos; sem marcações. |

## 1. Manifesto `input_context/dados.yaml`

```yaml
versao: 1
arquivos:
  - caminho: publicos/uci_air_quality.csv   # relativo a input_context/; aceita glob (fnmatch)
    marcacao: compartilhavel
    motivo: "Dataset público, DOI 10.24432/C59K5F"   # obrigatório para compartilhavel
  - caminho: cadernos/*.pdf
    marcacao: dado_de_pesquisa
```

Validação (`src/research_data/manifest.py`, `yaml.safe_load` e esquema estrito):

- chaves desconhecidas, `versao` diferente de 1, `marcacao` fora de
  `compartilhavel | dado_de_pesquisa`, `compartilhavel` sem `motivo`, caminho absoluto ou que
  resolva fora de `input_context/` (inclusive por symlink) → **erro** que impede a sessão, com
  a linha do problema;
- um arquivo coberto por padrões com marcações diferentes → erro;
- padrão que não casa com nenhum arquivo → `WARNING`;
- `dados.yaml` não é processado como contexto (como `README.md`).

O nome `dados.yaml` é o do contrato compartilhado da V18.5 e foi mantido.

## 2. Classificação efetiva por arquivo

`classify_path` da `v18.5-egress-gate` é estendida com o manifesto. Ordem de decisão:

1. marcação explícita no manifesto;
2. regra padrão:

| Tipo | Classe padrão |
|---|---|
| `.csv .tsv .xlsx .xls .ods .json .jsonl` | `dado_de_pesquisa` |
| `.png .jpg .jpeg .tif .tiff .bmp` | `dado_de_pesquisa` |
| `.txt .md .rst .pdf .docx .pptx` | `documento` (segue a `LLM_DATA_POLICY`, ADR 017) |
| outros (não processados) | `dado_de_pesquisa` (só o nome vai ao prompt, como hoje) |

`compartilhavel` só muda o tratamento de `dado_de_pesquisa`; num documento, não tem efeito além
do registro. `dado_de_pesquisa` num documento textual faz o texto inteiro virar trecho
`dado_de_pesquisa`.

## 3. Trechos produzidos pela ingestão

`ContextBundle.to_fragments() -> list[PromptFragment]` substitui o bloco único no plano
inicial. Para cada arquivo:

| Arquivo | Trecho `esquema_agregado` (vai a qualquer destino permitido) | Trecho `dado_de_pesquisa` (só destino com `aceita_dados_brutos` ou `compartilhavel`) |
|---|---|---|
| Tabular / planilha / JSON tabular | §4 | 5 primeiras linhas e estatísticas exatas (conteúdo atual) |
| JSON não tabular | tipo de nível superior, chaves, número de registros | até 5 registros |
| Documento `documento` | — (vai como trecho `documento`, texto integral ou 1º bloco, como hoje) | — |
| Documento marcado `dado_de_pesquisa` | título, formato, páginas, tamanho | texto |
| Imagem | nome, formato, dimensões em pixels, tamanho | texto de OCR local ou descrição de visão (§5) |
| Não processado | nome e tamanho | — |

Trechos de arquivo `compartilhavel` levam `compartilhavel=True`. O `source` de cada trecho é o
caminho relativo a `input_context/`. `to_prompt_context()` continua existindo e renderiza só os
trechos seguros (para chamadores antigos e testes).

`to_dict()` (uso local) mantém `sample_rows` e `stats` exatos: fica no nó.

## 4. Resumo seguro de datasets

`_dataframe_to_summary` passa a devolver, além do resumo exato, um `SafeDatasetSummary`:

- **esquema:** colunas, `dtype`, unidade quando o cabeçalho a traz entre `()` ou `[]`
  (ex.: `temperatura (°C)` → unidade `°C`), número de linhas e colunas;
- **metadados:** tamanho em bytes, formato, aba (planilhas);
- **descritores de formato, sem valores:** codificação detectada (`utf-8` ou `latin-1`, pela
  mesma tentativa de leitura usada hoje), separador (`csv.Sniffer` sobre as primeiras linhas),
  separador decimal (`,` quando colunas de texto casam `^-?\d+,\d+$` em maioria), presença de
  cabeçalho, formato de data reconhecido (`%d/%m/%Y`, ISO etc.), contagem de nulos por coluna;
- **estatísticas por coluna**, com `n` = contagem de não nulos:
  - `n < k` (`LOCALITY_MIN_GROUP_SIZE`): só `n` e tipo;
  - `n ≥ k`, numérica: `n`, média, desvio e `faixa_aproximada` = `[floor_1sig(min),
    ceil_1sig(max)]` (arredondamento para um algarismo significativo, mesmo critério de faixa
    da `v18.5-egress-gate` §3.3);
  - `n ≥ k`, categórica: `n` e número de valores distintos (nunca os rótulos);
  - `n ≥ k`, data: ano inicial e ano final;
  - mínimo, máximo e quantis **nunca** exatos.

k vem da configuração da `v18.5-egress-gate` e é gravado no payload
(`payload["locality_min_group_size"]`).

Exemplo do trecho seguro:

```
Dataset: medicoes.csv (csv, 48 213 bytes)
Formato: codificação latin-1; separador ';'; decimal ','; cabeçalho presente
Linhas: 1 204 | Colunas: 3
- instante: datetime (%d/%m/%Y %H:%M), n=1 204, anos 2024–2025
- temperatura (°C) [unidade °C]: float64, n=1 198, média 21.7, desvio 3.2, faixa ≈ [10, 40]
- sensor: object, n=1 204, 6 valores distintos
```

## 5. Visão

- Nova configuração `VISION_MODEL=provedor/modelo`, que deve ser entrada do catálogo; vazio =
  sem visão (OCR local, como o padrão atual `OCR_PROVIDER=local`). `OCR_PROVIDER=gemini` vira
  alias de `VISION_MODEL=google/gemini-3.8-flash` com `WARNING` de obsolescência.
- `src/llm/vision.py`: `describe_image(path, prompt, destination) -> str`, com implementação
  para `google` (código atual movido de `context_loader.py:472-488`) e `ollama` (campo `images`
  de `/api/chat`, o que permite visão `no_no`). Outros provedores: erro "provedor sem suporte a
  visão".
- Antes do envio, `EgressGate.authorize_vision(path, compartilhavel, dest)`. Recusa (imagem de
  pesquisa e destino sem `aceita_dados_brutos`) → **não é erro da sessão**: cai para OCR local e
  registra no bundle `extraction_errors=["visão recusada pela camada de saída: ..."]`.
- A descrição produzida é trecho `dado_de_pesquisa` (derivada de dado de pesquisa), com
  `tainted = aceita_dados_brutos` do modelo de visão; para imagem compartilhável, trecho
  `documento`.

## 6. Registro e apresentação das marcações

- `payload["research_data_markings"]`: lista `{caminho, classe_efetiva, marcacao, motivo,
  sha256, origem: "manifesto" | "padrao"}` para cada arquivo de `input_context/`.
- `dados.yaml` é copiado para `input_snapshot/` junto dos demais arquivos.
- Banner: linha `Dados: N de pesquisa · M compartilháveis · P documentos` e, se houver, a lista
  dos compartilháveis com o motivo.
- Relatório final: seção determinística "Dados de entrada e marcações", gerada pelo
  orquestrador a partir do payload (não pelo LLM), anexada ao relatório.
- README criado em `input_context/` (`src/context_loader.py:182-199`) passa a explicar o
  manifesto e a regra padrão.

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Plano inicial recebe trechos rotulados; payload com marcações e k; seção no relatório. |
| Agentes & Prompts | Planejador sem `aceita_dados_brutos` vê esquema e descritores, não amostras. |
| Sandboxes & Containers | Nenhum (os dados continuam chegando ao sandbox pelos caminhos atuais; a política de rede é da `v18.5-sandbox-phases`). |
| Persistência | Payload JSONB; cópia do manifesto no snapshot. Sem schema. |
| Segurança | Fecha amostras e extremos no prompt e a visão fora da camada; manifesto validado contra escape de diretório. |
| Testes & Telemetria | Visões e recusas registradas no `egress_log` (via gate). |

## 8. Riscos e limites

- Descritores de formato são heurísticos; um formato não detectado vira mais tentativas do
  Developer.
- A marcação `compartilhavel` é declaração do pesquisador; o sistema a registra, não a verifica.
- Unidades só são reconhecidas quando estão no cabeçalho.
