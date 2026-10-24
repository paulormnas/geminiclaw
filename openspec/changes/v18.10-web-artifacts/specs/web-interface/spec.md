# Delta: web-interface

## ADDED Requirements

### Requirement: Sessões e arquivos do projeto
A API SHALL listar as sessões de um projeto pelo grafo e os arquivos da pasta de cada sessão, e MUST responder 404 a uma sessão que não pertence ao projeto (ADR 027 §6.3).

#### Scenario: Listagem
- **GIVEN** a sessão S do projeto P com `artifacts/relatorio.md` e `eda_dados/fig.png`
- **WHEN** `GET /api/projects/P/sessions/S/files`
- **THEN** os dois caminhos aparecem, relativos à pasta, com tamanho e tipo

#### Scenario: Sessão de outro projeto
- **GIVEN** a sessão S do projeto Q
- **WHEN** `GET /api/projects/P/sessions/S/files`
- **THEN** a resposta é 404

#### Scenario: Muitos arquivos
- **GIVEN** `WEB_ARTIFACT_MAX_FILES=3` e 5 arquivos
- **THEN** a primeira página traz 3 com `total=5`, e `pagina=2` traz os outros 2

### Requirement: Caminho confinado à pasta da sessão
O backend MUST recusar caminho absoluto, com `..`, `\`, `\0` ou que passe por link simbólico, e MUST servir só arquivos cujo caminho real fica dentro da pasta real da sessão.

#### Scenario: Travessia
- **WHEN** `caminho` é `../../.env`, `%2e%2e/%2e%2e/.env` ou `/etc/passwd`
- **THEN** a resposta é 400 e nenhum arquivo fora da pasta é lido

#### Scenario: Link simbólico
- **GIVEN** `artifacts/x` é link para um arquivo fora da pasta
- **WHEN** o `raw` de `artifacts/x` é pedido
- **THEN** a resposta é 403, e a listagem mostra `x` com `tipo="link"`

### Requirement: Entrega segura por tipo
A rota `raw` SHALL definir o tipo pela tabela fechada do design §3, com `nosniff`; SVG, HTML e PDF MUST levar `Content-Security-Policy: sandbox`; tipos fora da tabela MUST ir como `attachment`.

#### Scenario: HTML gerado
- **GIVEN** `relatorio.html` com `<script>`
- **WHEN** o `raw` é pedido
- **THEN** a resposta tem `Content-Security-Policy` começando com `sandbox` e `X-Content-Type-Options: nosniff`

#### Scenario: Binário desconhecido
- **GIVEN** `modelo.pkl`
- **THEN** a resposta é `application/octet-stream` com `Content-Disposition: attachment`

#### Scenario: Arquivo grande
- **GIVEN** `WEB_ARTIFACT_MAX_BYTES=10` e um arquivo de 11 bytes
- **THEN** a resposta é 413

### Requirement: Pré-visualização limitada
A pré-visualização SHALL ler no máximo `WEB_ARTIFACT_PREVIEW_BYTES` e `WEB_ARTIFACT_PREVIEW_ROWS` linhas de CSV, informando `truncado`.

#### Scenario: CSV longo
- **GIVEN** um CSV de 1 000 linhas e `WEB_ARTIFACT_PREVIEW_ROWS=200`
- **THEN** a pré-visualização traz o cabeçalho, 200 linhas e `truncado=true`

#### Scenario: Próxima página do CSV
- **WHEN** `preview?caminho=dados.csv&inicio=200`
- **THEN** vêm o cabeçalho e as linhas 201 a 400

#### Scenario: Link criado entre verificar e abrir
- **GIVEN** um teste que troca `artifacts/a.txt` por link simbólico para fora da pasta logo antes da abertura (gancho injetado)
- **THEN** a resposta é 403 e nenhum byte de fora é lido

#### Scenario: JSON inválido
- **GIVEN** `metrics.json` malformado
- **THEN** a pré-visualização vem como `tipo="texto"`, sem erro

### Requirement: Visualizador no frontend
O frontend SHALL mostrar Markdown sem HTML bruto, HTML e SVG só em `iframe` com `sandbox` vazio, imagens raster em `img` e CSV em tabela.

#### Scenario: Markdown com HTML e javascript
- **GIVEN** Markdown com `<script>alert(1)</script>` e `[x](javascript:alert(1))`
- **WHEN** é renderizado
- **THEN** nenhum `script` existe no DOM e o link não tem `href` começando com `javascript:`

#### Scenario: HTML em iframe isolado
- **WHEN** um `.html` é aberto
- **THEN** o `iframe` tem o atributo `sandbox` sem `allow-scripts` e sem `allow-same-origin`

#### Scenario: Árvore por teclado
- **WHEN** o usuário navega a árvore com setas e Enter
- **THEN** o arquivo escolhido abre no visualizador e o foco fica visível
