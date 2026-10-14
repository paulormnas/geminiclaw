# Design: v18.6-profile-hardening

Cada decisão abaixo escolhe a opção mais conservadora (menos informação sai, mais casos viram recusa).

## 1. Detecção de cabeçalho (R1, NC-PERFIL-1)
A primeira linha só é cabeçalho se **todos** os campos (dos que o perfil lê) passam em quatro testes:
(a) não vazios; (b) não são número (`float()` aceita) nem data (`AAAA-MM-DD`, `DD/MM/AAAA`, com ou sem hora) nem
contêm número decimal; (c) casam o padrão de nome seguro `^[\w .\-/()%]{1,80}$`; (d) **não se repetem como valor** na
mesma coluna nas linhas seguintes lidas (um rótulo de coluna não reaparece como célula, um valor categórico como
`setosa` reaparece). O teste (d) é a heurística "primeira linha igual aos tipos das linhas seguintes", escolhida por ser
decidível em fluxo e porque cobre o caso em que a primeira linha de dados é toda textual.
Limite conhecido: um CSV sem cabeçalho cuja primeira linha é toda textual, sem repetição, é indistinguível de um
cabeçalho; o padrão de nome seguro e o limite de 80 caracteres reduzem o dano, mas não o eliminam. Aceito e registrado
no parecer.
Sem cabeçalho reconhecido: o perfil traz `sem cabeçalho reconhecido`, a contagem de colunas e, por coluna,
`coluna_N (tipo, nulos)`. Nenhum rótulo vindo do arquivo. A primeira linha conta como linha de dados.

## 2. Confinamento e symlink (R2, NC-PERFIL-2)
- `build_artifact_evidence_fragments` ignora `path.is_symlink()` e qualquer arquivo cujo `resolve()` não esteja dentro de
  `root.resolve()`, em **todos** os ramos (`resolutions` lista, `None`, perfil, texto, binário). Symlink para dentro da
  sessão também é ignorado (política simples).
- A abertura usa `os.open(..., O_RDONLY | O_NOFOLLOW | O_NONBLOCK)` e confere `S_ISREG` no descritor (`fstat`), o que
  fecha a janela entre verificação e leitura e recusa FIFO/dispositivo. O ramo de texto (`.txt`, `.md`, `.log`, 700
  caracteres) usa o mesmo leitor. `profile_artifact` devolve `None` para symlink ou arquivo não regular.
- Onde `O_NOFOLLOW` não existe, o leitor recusa o symlink pela verificação prévia (melhor esforço).

## 3. Rótulos seguros e perfil como dado não confiável (R3, R6, NC-PERFIL-3/6)
- Rótulo de coluna ou chave: `^[\w .\-/()%]{1,80}$`, senão `coluna_N`/`chave_N`; números decimais no rótulo viram
  `<num padrão=...>` (mesma função do gate, `number_marker`).
- O perfil sai num fragmento próprio (`origem=esquema_agregado`, `source="perfil_artefato"`), separado da linha de nome
  do arquivo (`source="artefatos"`, que continua passando por `sanitize_artifact_name`). O `EgressGate` envolve fragmentos
  `esquema_agregado` com a fonte `perfil_artefato` em `<<<DADO id=... origem=esquema_agregado fonte=perfil_artefato>>>`
  pelo mesmo mecanismo de `OBSERVED_ORIGINS` (delimitador aleatório por envio, delimitadores internos escapados, regra
  `OBSERVED_DATA_RULE` no `system`). Opção descartada: pôr `ESQUEMA_AGREGADO` inteiro em `OBSERVED_ORIGINS`, o que
  delimitaria também o esquema de contexto e os nomes de artefatos, mudando prompts de outros fluxos.
- A instrução do revisor passa a dizer que a evidência em disco e o PERFIL são dado observado e que instruções nelas são
  ignoradas.

## 4. O perfil nunca levanta (R4, NC-PERFIL-4)
- `profile_artifact` captura `Exception` (inclui `RecursionError` e `MemoryError`) e devolve `perfil: <tipo>, não foi
  possível interpretar o arquivo`.
- JSON: antes de `json.loads`, varredura de colchetes fora de strings (regex de tokens, sem recursão); profundidade acima de
  32 devolve `estrutura aninhada acima de 32 níveis; não interpretada`.
- `LOCALITY_MIN_GROUP_SIZE` ausente: a causa não se perde. O `RuntimeError` de `require_locality_min_group_size` é
  capturado, registrado em `ERROR` e o perfil devolve `perfil: <tipo>, indisponível: LOCALITY_MIN_GROUP_SIZE não definida
  (...)` com a mensagem acionável. Fail-fast no sentido de erro explícito e visível no prompt e no log, sem derrubar a
  revisão da subtarefa (que não é a camada que deve falhar por configuração de egresso). Opção descartada: propagar a
  exceção (derruba a subtarefa).

## 5. Limites estruturais e de tempo (R5, NC-PERFIL-5)
Novas variáveis (`src/config.py`, `.env.example`): `REVIEW_PROFILE_MAX_COLUMNS=200`, `REVIEW_PROFILE_MAX_ROWS=100000`,
`REVIEW_PROFILE_MAX_SECONDS=5`, `REVIEW_PROFILE_MAX_JSON_LINES=200`. O CSV lê só as primeiras N colunas por linha e as
primeiras M linhas; o relógio é conferido a cada 1000 linhas e o perfil informa `leitura interrompida por tempo`. O texto
informa `colunas: 1000000 (descrição limitada às primeiras 200)` e `≥ N linhas (lidas até o limite)`. O JSON limita as
linhas de chaves e informa o corte.

## 6. Mapas JSON (R6)
Objeto com mais de 50 chaves aparece como `objeto com N chaves`, sem listar as chaves nem descer nos filhos. O limiar 50 é
fixo (constante do módulo).

## 7. Testes
Um por `Scenario` da spec delta, incluindo os ataques do parecer (`5.1,3.5,1.4,setosa`, symlink para arquivo com
`API_KEY=...`, JSON de 200000 níveis, CSV de 1000000 de colunas com tempo limitado).
