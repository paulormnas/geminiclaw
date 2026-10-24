# Design: v18.10-web-artifacts

## 1. Contrato

| Rota | Resposta |
|---|---|
| `GET /api/projects/{id}/sessions` | `[{session_id, alias, inicio, fim, status, tem_pasta}]` (sessões do projeto pelo grafo, mais recentes primeiro) |
| `GET /api/projects/{id}/sessions/{sid}/files` | `{raiz: "<slug>", arquivos: [{caminho, tamanho, modificado_em, tipo}], truncado: bool, total}` |
| `GET /api/projects/{id}/sessions/{sid}/files/preview?caminho=...` | `{tipo, conteudo?, linhas?, colunas?, truncado}` para `texto`, `json`, `markdown`, `csv`; 415 para os demais |
| `GET /api/projects/{id}/sessions/{sid}/files/raw?caminho=...` | o arquivo, com os cabeçalhos do §3 |

`caminho` é relativo à pasta da sessão, com `/` como separador.

## 2. Resolução do caminho (ponto crítico)

1. A sessão `sid` precisa pertencer ao projeto `id` pelo grafo; senão 404 (não revela que existe em outro projeto).
2. A pasta vem de `resolve_session_dir(OUTPUT_BASE_DIR, sid)`; ausente → `tem_pasta=false` e 404 nos arquivos.
3. O caminho é decodificado **uma vez** (a decodificação de URL do servidor) e só então validado; é rejeitado (400) se for absoluto, tiver `..`, `\`, `\0`, componente começando com `~`, ou mais de 512 caracteres.
4. A abertura percorre o caminho componente a componente com `os.open(..., O_NOFOLLOW)` relativo ao descritor do diretório anterior (`dir_fd`), a partir do descritor da pasta da sessão; um link simbólico em qualquer componente é recusado (403); depois de abrir, `os.fstat` confirma arquivo regular. Isso fecha a janela entre verificar e abrir enquanto o sandbox escreve na pasta. Na listagem, links aparecem com `tipo: "link"` e sem conteúdo.
5. Arquivos acima de `WEB_ARTIFACT_MAX_BYTES` (padrão 50 MB) não são servidos (413); a pré-visualização lê no máximo `WEB_ARTIFACT_PREVIEW_BYTES` (padrão 512 KB) e `WEB_ARTIFACT_PREVIEW_ROWS` (padrão 200) linhas de CSV **por página**: `preview?caminho=...&inicio=N` pagina o CSV e o texto, então todo o arquivo é visível na web, página a página.
6. A listagem é paginada (`WEB_ARTIFACT_MAX_FILES`, padrão 5 000, por página; `pagina=N`), com `total`; ignora `__pycache__` e `.git`.

## 3. Tipos e cabeçalhos

| Extensão | Pré-visualização | `raw` |
|---|---|---|
| `.txt .log .py .r .tex .yaml .yml .toml` | texto | `text/plain; charset=utf-8` |
| `.json .jsonl` | JSON formatado (inválido → texto) | `text/plain` |
| `.md` | Markdown renderizado sem HTML | `text/plain` |
| `.csv .tsv` | tabela das primeiras linhas | `text/plain` |
| `.png .jpg .jpeg .gif .webp` | `<img src=raw>` | tipo da imagem |
| `.svg` `.html .htm` | `<iframe sandbox src=raw>` (sem `allow-scripts`, sem `allow-same-origin`) | tipo real com `Content-Security-Policy: sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'` (sem `'self'`: o HTML gerado não alcança a API) |
| `.pdf` | link para abrir em aba nova | `application/pdf` com `Content-Security-Policy: sandbox` |
| demais | só download | `application/octet-stream` com `Content-Disposition: attachment` |

Toda resposta `raw` leva `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` e `Content-Disposition` com nome saneado. O tipo vem da extensão por tabela fechada, nunca do conteúdo.

## 4. Frontend

- `/p/:projetoId/artefatos`: lista de sessões (apelido, data, estado) → árvore de arquivos à esquerda (teclado: setas, Enter) → visualizador à direita, com nome, tamanho, botão Baixar.
- Markdown com `react-markdown` sem plugins de HTML; links externos com `rel="noopener noreferrer"` e `target="_blank"`; imagens relativas do Markdown resolvidas para a rota `raw` da mesma sessão.
- CSV em tabela com cabeçalho e aviso "mostrando 200 de N linhas".
- Estados: sem sessões, sessão sem pasta, carregando, arquivo grande demais, tipo sem pré-visualização.

## 5. Impacto nos 6 eixos

Orquestrador, agentes, sandbox: nenhum. Persistência: só leitura. Segurança: ponto principal (§6). Testes: unidade com pasta temporária e `InMemoryGraphStore`.

## 6. Segurança

| Ameaça | Mitigação |
|---|---|
| Travessia de caminho / link simbólico apontando para `~/.ssh` ou `.env` | §2, itens 3 e 4; testes com `..`, codificação `%2e%2e`, link simbólico e caminho absoluto |
| XSS armazenado: HTML ou SVG escrito por código gerado | `iframe sandbox` sem scripts nem mesma origem e CSP `sandbox` na própria resposta (vale mesmo aberto direto na aba) |
| Markdown com HTML ou `javascript:` | `react-markdown` sem HTML; URLs `javascript:` removidas pelo filtro padrão (teste) |
| Farejamento de tipo | `nosniff` e tipo por tabela fechada |
| Exaustão de memória | limites de tamanho, linhas e arquivos; leitura em fluxo no `raw` |
| Localidade (ADR 019) | os arquivos só vão ao navegador do pesquisador por loopback ou tailnet; nada vai a provedor LLM |

## 7. Questões em aberto

1. Mostrar também `checkpoint.json`, `curator_*.jsonl` e `egress/` (registros internos), ou só `artifacts/` e as pastas de subtarefa? Proposta: mostrar tudo da pasta da sessão, com `artifacts/` aberta por padrão.
